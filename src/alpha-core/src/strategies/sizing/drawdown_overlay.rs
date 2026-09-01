//! Drawdown-based de-risking overlay (family-level exposure throttle).
//!
//! Financial logic: the overlay scales total family exposure down as the
//! strategy's own equity falls below its running peak. The rule table is a
//! ladder of drawdown bands, each mapping to a multiplier `m` applied to the
//! vol-targeted position:
//!
//! ```text
//! p_final = p_vol_targeted * m
//! ```
//!
//! Because the multiplier acts at family level on gross exposure, it never
//! changes which trades are taken or their relative sizes: alpha scores and
//! cross-sectional weights pass through untouched, and only the overall
//! leverage is throttled. A 0.50 multiplier means "run every position at half
//! size", not "drop the bottom half of the book".
//!
//! Pre-commitment: the table below is frozen before live deployment. Freezing
//! the ladder removes discretionary de-risking decisions made under stress,
//! which are notoriously badly timed; the response to any equity path is fully
//! determined in advance and can be backtested exactly.
//!
//! Kill line semantics: at a drawdown of 20% from peak the multiplier is
//! exactly 0.0 (flat). Mechanically, once equity makes a new high the drawdown
//! resets to zero and the ladder returns to full size; whether trading may
//! actually resume after a kill-line event is a formal human review decision
//! outside the scope of this struct -- this type computes the pre-committed
//! multiplier, it does not encode the restart approval workflow.
//!
//! Band convention: each band is stored as `(drawdown_threshold_fraction,
//! multiplier)` sorted ascending by threshold, and its multiplier applies while
//! the current drawdown is STRICTLY BELOW the threshold. The final band is the
//! kill line; its threshold is not used in comparisons because it catches every
//! drawdown at or above the previous band's threshold, so it is conventionally
//! written as `f64::INFINITY`.

/// Default pre-committed rule table, frozen before live deployment.
///
/// Drawdown from equity peak -> family-level exposure multiplier:
///
/// ```text
/// dd < 5%          -> m = 1.00   (full size)
/// 5% <= dd < 10%   -> m = 0.75
/// 10% <= dd < 15%  -> m = 0.50
/// 15% <= dd < 20%  -> m = 0.25
/// dd >= 20%        -> m = 0.00   (kill line: shut down, formal review)
/// ```
pub const DEFAULT_BANDS: [(f64, f64); 5] = [
    (0.05, 1.00),
    (0.10, 0.75),
    (0.15, 0.50),
    (0.20, 0.25),
    // Kill line: +INFINITY bound catches every drawdown >= 20%.
    (f64::INFINITY, 0.00),
];

/// Tracks the equity curve high-water mark and returns a pre-committed
/// exposure multiplier as a function of the current drawdown from that peak.
///
/// State model: the rule table (`bands`) is immutable after construction --
/// it is a pre-committed risk limit, not a tunable parameter. The only piece
/// of state that ever changes is `equity_peak`, which ratchets monotonically
/// upward (it never decreases).
pub struct DrawdownLadder {
    /// Pre-committed rule table: `(drawdown_threshold_fraction, multiplier)`.
    /// Sorted ascending by threshold. Each band's multiplier applies while
    /// drawdown is strictly below its threshold. Last entry is the kill line
    /// with multiplier exactly 0.0 (its threshold is conventionally
    /// `f64::INFINITY` and is never compared against).
    bands: Vec<(f64, f64)>,
    /// Highest equity value seen so far (running peak / high-water mark).
    /// Strictly positive and non-decreasing for the lifetime of the ladder.
    equity_peak: f64,
}

impl DrawdownLadder {
    /// Create a ladder with the default frozen rule table ([`DEFAULT_BANDS`]).
    ///
    /// `initial_capital` seeds the equity peak; before the first mark the
    /// drawdown is zero and the multiplier is full size.
    ///
    /// Panics if `initial_capital` is not finite and positive.
    pub fn new(initial_capital: f64) -> Self {
        Self::with_bands(DEFAULT_BANDS.to_vec(), initial_capital)
    }

    /// Create a ladder with custom bands (for testing or different risk
    /// appetites). Bands are sorted ascending by threshold before storage, so
    /// callers may pass them in any order.
    ///
    /// Contract enforced at construction (fail fast on a mis-typed risk table):
    /// - `bands` is non-empty;
    /// - every threshold is finite and non-negative, except that the catch-all
    ///   kill-line bound may be `f64::INFINITY`;
    /// - thresholds are strictly increasing after sorting (duplicates would
    ///   make band precedence ambiguous);
    /// - every multiplier is finite and within `[0.0, 1.0]` (a de-risking
    ///   ladder may only hold or cut exposure, never lever up);
    /// - the LAST band's multiplier is exactly `0.0` (the kill line).
    ///
    /// Panics if `initial_capital` is not finite and positive, or if any of
    /// the contract points above is violated.
    pub fn with_bands(bands: Vec<(f64, f64)>, initial_capital: f64) -> Self {
        assert!(
            initial_capital.is_finite() && initial_capital > 0.0,
            "initial_capital must be finite and positive, got {}",
            initial_capital
        );
        assert!(
            !bands.is_empty(),
            "bands must contain at least the kill line"
        );
        for &(threshold, multiplier) in &bands {
            assert!(
                threshold == f64::INFINITY || (threshold.is_finite() && threshold >= 0.0),
                "band threshold must be finite and non-negative \
                 (+INFINITY allowed only as the kill line's catch-all), got {}",
                threshold
            );
            assert!(
                multiplier.is_finite() && (0.0..=1.0).contains(&multiplier),
                "band multiplier must be finite and within [0, 1], got {}",
                multiplier
            );
        }

        let mut bands = bands;
        bands.sort_by(|a, b| a.0.total_cmp(&b.0));
        for pair in bands.windows(2) {
            assert!(
                pair[0].0 < pair[1].0,
                "band thresholds must be strictly increasing after sorting, \
                 found duplicate threshold {}",
                pair[0].0
            );
        }
        assert_eq!(
            bands.last().expect("non-empty checked above").1,
            0.0,
            "kill line: the last band must have multiplier exactly 0.0"
        );

        Self {
            bands,
            equity_peak: initial_capital,
        }
    }

    /// Update the equity peak if `current_equity` exceeds it, then return the
    /// current drawdown from the peak as a non-negative fraction.
    ///
    /// The peak is a ratchet: it moves only upward (a new equity high resets
    /// the drawdown to zero) and never decreases. Non-finite marks are treated
    /// as bad data: they never move the peak, and they are reported as an
    /// infinite drawdown so downstream sizing fails safe toward full de-risking.
    pub fn update_peak(&mut self, current_equity: f64) -> f64 {
        if current_equity.is_finite() && current_equity > self.equity_peak {
            self.equity_peak = current_equity;
        }
        self.current_drawdown(current_equity)
    }

    /// Compute the current family-level multiplier `m` from the drawdown of
    /// `current_equity` below the stored peak.
    ///
    /// Pure lookup: this never mutates state (the rule table is immutable and
    /// the peak only moves via [`Self::update_peak`]). Call `update_peak` first
    /// each bar so the high-water mark reflects the latest equity, then apply
    /// `p_final = p_vol_targeted * m`. A drawdown at or beyond the kill line
    /// yields exactly `0.0`.
    pub fn current_multiplier(&self, current_equity: f64) -> f64 {
        let drawdown = self.raw_drawdown(current_equity);
        for &(threshold, multiplier) in &self.bands {
            if drawdown < threshold {
                return multiplier;
            }
        }
        // Unreachable for finite drawdowns because the kill line's bound is
        // +INFINITY; an infinite drawdown (non-finite equity) lands here and
        // must fail safe to the kill-line multiplier.
        self.bands.last().expect("non-empty by construction").1
    }

    /// Current drawdown from the equity peak as a non-negative fraction
    /// (e.g. `0.073` = 7.3% below the high-water mark).
    ///
    /// The value is zero at or above the peak and can exceed `1.0` only if
    /// equity itself has gone negative. Non-finite equity is reported as
    /// infinity (fail-safe).
    pub fn current_drawdown(&self, current_equity: f64) -> f64 {
        let drawdown = self.raw_drawdown(current_equity);
        debug_assert!(drawdown >= 0.0, "drawdown is a distance below peak");
        drawdown
    }

    /// Running equity peak (high-water mark). Monotonically non-decreasing.
    pub fn equity_peak(&self) -> f64 {
        self.equity_peak
    }

    /// Raw drawdown fraction: non-negative, no debug assertion, shared by the
    /// public read paths.
    fn raw_drawdown(&self, current_equity: f64) -> f64 {
        if !current_equity.is_finite() {
            return f64::INFINITY;
        }
        if current_equity >= self.equity_peak {
            return 0.0;
        }
        // Peak is strictly positive by construction and equity is below it,
        // so numerator and denominator are positive: result is never negative.
        // Snap to 12 decimals so equity inputs derived from decimal drawdowns
        // (`1.0 - dd`) hit exact band boundaries instead of landing epsilon
        // below them (0.10 -> 0.0999... would miss the band-above roll and
        // the kill line would not fire at exactly 20%).
        ((self.equity_peak - current_equity) / self.equity_peak * 1e12).round() / 1e12
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const EPS: f64 = 1e-12;

    #[test]
    fn default_table_multipliers_at_band_interiors() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(100.0); // peak = 100

        // Comfortably inside each band.
        assert_eq!(ladder.current_multiplier(99.9), 1.00); // dd ~ 0.1%
        assert_eq!(ladder.current_multiplier(96.0), 1.00); // dd = 4%
        assert_eq!(ladder.current_multiplier(91.0), 0.75); // dd = 9%
        assert_eq!(ladder.current_multiplier(86.0), 0.50); // dd = 14%
        assert_eq!(ladder.current_multiplier(81.0), 0.25); // dd = 19%
    }

    #[test]
    fn default_table_exact_band_boundaries_roll_to_next_band() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(100.0);

        // Exactly at a threshold belongs to the band ABOVE it ("5% to <10%"
        // includes exactly 5%). 95/100 etc. are exact IEEE divisions, so these
        // boundary comparisons are deterministic.
        assert_eq!(ladder.current_multiplier(95.0), 0.75); // dd == 5%
        assert_eq!(ladder.current_multiplier(90.0), 0.50); // dd == 10%
        assert_eq!(ladder.current_multiplier(85.0), 0.25); // dd == 15%
        assert_eq!(ladder.current_multiplier(80.0), 0.00); // dd == 20% kill
    }

    #[test]
    fn initial_state_has_no_drawdown_and_full_size() {
        let ladder = DrawdownLadder::new(100.0);

        assert!((ladder.current_drawdown(100.0)).abs() < EPS);
        assert_eq!(ladder.current_multiplier(100.0), 1.00);
        assert!((ladder.equity_peak() - 100.0).abs() < EPS);
    }

    #[test]
    fn first_bar_above_initial_capital_sets_new_peak_at_zero_drawdown() {
        let mut ladder = DrawdownLadder::new(100.0);

        let dd = ladder.update_peak(107.5);

        assert!(dd.abs() < EPS);
        assert!((ladder.equity_peak() - 107.5).abs() < EPS);
        assert_eq!(ladder.current_multiplier(107.5), 1.00);
    }

    #[test]
    fn new_high_resets_drawdown_to_zero() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(110.0);

        // Fall into the second band, then recover to a fresh high.
        let dd_mid = ladder.update_peak(102.0);
        assert!(dd_mid > 0.05 && dd_mid < 0.10);
        assert_eq!(ladder.current_multiplier(102.0), 0.75);

        let dd_new_high = ladder.update_peak(120.0);
        assert!(dd_new_high.abs() < EPS);
        assert_eq!(ladder.current_multiplier(120.0), 1.00);
        assert!((ladder.equity_peak() - 120.0).abs() < EPS);
    }

    #[test]
    fn peak_updates_monotonically_and_never_decreases() {
        let mut ladder = DrawdownLadder::new(100.0);
        let path = [100.0, 112.0, 90.0, 105.0, 130.0, 60.0];

        // The peak must equal the running maximum of all marks seen so far,
        // which is non-decreasing by construction.
        let mut running_max = f64::NEG_INFINITY;
        for &equity in &path {
            if equity > running_max {
                running_max = equity;
            }
            ladder.update_peak(equity);
            assert!(
                (ladder.equity_peak() - running_max).abs() < EPS,
                "peak {} deviates from running max {}",
                ladder.equity_peak(),
                running_max
            );
        }

        assert!((ladder.equity_peak() - 130.0).abs() < EPS);
        // Deep below the untouched 130 peak: still measured against 130.
        assert!((ladder.current_drawdown(60.0) - (70.0 / 130.0)).abs() < EPS);
    }

    #[test]
    fn drawdown_is_never_negative_even_when_equity_exceeds_stored_peak() {
        let mut ladder = DrawdownLadder::new(100.0);

        // Equity above the peak WITHOUT calling update_peak first: distance
        // below the peak clamps at zero rather than going negative.
        assert_eq!(ladder.current_drawdown(150.0), 0.0);

        ladder.update_peak(150.0);
        assert!(ladder.update_peak(140.0) > 0.0);
        assert!(ladder.update_peak(160.0) >= 0.0);
        assert!(ladder.update_peak(155.0) >= 0.0);
    }

    #[test]
    fn kill_line_returns_exact_zero_multiplier() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(100.0);

        let m_deep = ladder.current_multiplier(70.0); // dd = 30%
        assert_eq!(m_deep, 0.0);

        // Even far beyond the table: total loss still maps to the kill line.
        let m_wiped = ladder.current_multiplier(0.0); // dd = 100%
        assert_eq!(m_wiped, 0.0);
    }

    #[test]
    fn non_finite_equity_fails_safe_to_kill_line_and_never_moves_peak() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(105.0);

        assert_eq!(ladder.current_multiplier(f64::NAN), 0.0);
        assert_eq!(ladder.current_multiplier(f64::INFINITY), 0.0);

        let dd = ladder.update_peak(f64::NAN);
        assert_eq!(dd, f64::INFINITY);
        assert!((ladder.equity_peak() - 105.0).abs() < EPS, "peak poisoned");

        // Ladder still usable once clean marks resume.
        assert_eq!(ladder.current_multiplier(104.0), 1.00);
    }

    #[test]
    fn multiplier_lookup_does_not_mutate_state() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(100.0);

        // Read-only lookups at a deep drawdown leave the peak untouched.
        // dd = 50% is past the kill line, so this returns exactly 0.0.
        for _ in 0..3 {
            assert_eq!(ladder.current_multiplier(50.0), 0.0);
        }
        assert!((ladder.equity_peak() - 100.0).abs() < EPS);

        // And the ladder keeps tracking correctly afterwards.
        assert!((ladder.update_peak(96.0) - 0.04).abs() < EPS);
        assert_eq!(ladder.current_multiplier(96.0), 1.00);
    }

    #[test]
    fn custom_bands_are_respected_and_sorted_defensively() {
        // Passed deliberately out of order; storage sorts by threshold.
        let ladder = DrawdownLadder::with_bands(vec![(f64::INFINITY, 0.0), (0.02, 0.5)], 100.0);

        assert_eq!(ladder.current_multiplier(99.5), 0.5); // dd = 0.5% < 2%
        assert_eq!(ladder.current_multiplier(98.5), 0.5); // dd = 1.5% < 2%
        assert_eq!(ladder.current_multiplier(98.0), 0.0); // dd == 2% -> kill line
        assert_eq!(ladder.current_multiplier(97.0), 0.0); // dd = 3% >= 2% kill
    }

    #[test]
    fn single_band_ladder_is_immediately_killed_above_zero_dd() {
        let mut ladder = DrawdownLadder::with_bands(vec![(f64::INFINITY, 0.0)], 100.0);
        ladder.update_peak(100.0);

        assert_eq!(ladder.current_multiplier(100.0), 0.0);
        assert_eq!(ladder.current_multiplier(99.999), 0.0);
    }

    #[test]
    #[should_panic(expected = "kill line")]
    fn with_bands_panics_when_last_band_is_not_the_kill_line() {
        let _ = DrawdownLadder::with_bands(vec![(0.10, 0.5), (f64::INFINITY, 0.25)], 100.0);
    }

    #[test]
    #[should_panic(expected = "strictly increasing")]
    fn with_bands_panics_on_duplicate_thresholds() {
        let _ = DrawdownLadder::with_bands(
            vec![(0.10, 0.75), (0.10, 0.25), (f64::INFINITY, 0.0)],
            100.0,
        );
    }

    #[test]
    #[should_panic(expected = "at least the kill line")]
    fn with_bands_panics_on_empty_table() {
        let _ = DrawdownLadder::with_bands(Vec::new(), 100.0);
    }

    #[test]
    #[should_panic(expected = "within [0, 1]")]
    fn with_bands_panics_on_levering_up_multiplier() {
        let _ = DrawdownLadder::with_bands(vec![(0.05, 1.5), (f64::INFINITY, 0.0)], 100.0);
    }

    #[test]
    #[should_panic(expected = "initial_capital")]
    fn constructors_reject_non_positive_initial_capital() {
        let _ = DrawdownLadder::new(0.0);
    }

    /// Integration test: one bar-by-bar pass over a full drawdown episode.
    ///
    /// Per bar: update the high-water mark, look up the pre-committed
    /// multiplier, and scale the vol-targeted position
    /// `p_final = p_vol_targeted * m`. The multiplier sequence walks every
    /// rung of the ladder down into the kill line and resets on the new high.
    #[test]
    fn integration_drawdown_scenario_over_multiple_bars() {
        let mut ladder = DrawdownLadder::new(100.0);

        // (equity_mark, p_vol_targeted)
        let bars: [(f64, f64); 8] = [
            (102.0, 1.20), // bar 0: new high out of the gate
            (110.0, 1.10), // bar 1: another new high, full size
            (104.0, 1.00), // bar 2: dd ~= 5.45%, first de-risk rung
            (98.0, 0.90),  // bar 3: dd ~= 10.91%
            (92.0, 0.80),  // bar 4
            (87.5, 0.70),  // bar 5: through the kill line
            (86.0, 0.60),  // bar 6: still killed, no new high
            (111.0, 1.30), // bar 7: recovery to a fresh high, full size
        ];

        // Expected multiplier per bar, derived by hand from the frozen table
        // against the running peak (110 from bar 1 onward until bar 7):
        //   bar 2: dd = 6/110  ~= 5.45%  -> 0.75
        //   bar 3: dd = 12/110 ~= 10.91% -> 0.50
        //   bar 4: dd = 18/110 ~= 16.36% -> 0.25
        //   bar 5: dd = 22.5/110 ~= 20.45% -> 0.00 (kill)
        //   bar 6: dd = 24/110 ~= 21.82% -> 0.00 (still killed)
        let expected_m = [1.00, 1.00, 0.75, 0.50, 0.25, 0.00, 0.00, 1.00];

        let mut gross_path = Vec::new();
        for (i, &(equity, p_vol)) in bars.iter().enumerate() {
            let _dd = ladder.update_peak(equity);
            let m = ladder.current_multiplier(equity);
            assert_eq!(
                m,
                expected_m[i],
                "bar {}: multiplier mismatch (equity {}, peak {})",
                i,
                equity,
                ladder.equity_peak()
            );
            gross_path.push(p_vol * m);
        }

        // Family gross exposure steps down monotonically through the drawdown
        // episode and is exactly flat once the kill line fires. The final
        // recovery bar (new high -> full size) is deliberately excluded:
        // re-risking after a fresh high is the whole point of the ratchet.
        for w in gross_path[1..7].windows(2) {
            assert!(w[1] <= w[0] + EPS);
        }
        assert!(gross_path[0] > 0.0);
        assert_eq!(gross_path[5], 0.0);
        assert_eq!(gross_path[6], 0.0);
        assert!(gross_path[7] > 0.0);

        // Alpha scores are untouched by the overlay: the multiplier applies at
        // family level, so relative bet sizes within the book are unchanged.
        let raw = [1.00, 0.90];
        let scaled: Vec<f64> = raw.iter().map(|&p| p * expected_m[3]).collect();
        assert!((scaled[0] - 0.50).abs() < EPS);
        assert!((scaled[1] - 0.45).abs() < EPS);
        assert!((scaled[0] / scaled[1] - raw[0] / raw[1]).abs() < EPS);

        // After the new high the ladder is back to full size at zero dd.
        assert!(ladder.current_drawdown(111.0).abs() < EPS);
        assert!((ladder.equity_peak() - 111.0).abs() < EPS);
    }
}
