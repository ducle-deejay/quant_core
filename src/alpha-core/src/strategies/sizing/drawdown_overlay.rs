pub const DEFAULT_BANDS: [(f64, f64); 5] = [
    (0.05, 1.00),
    (0.10, 0.75),
    (0.15, 0.50),
    (0.20, 0.25),

    (f64::INFINITY, 0.00),
];

pub struct DrawdownLadder {

    bands: Vec<(f64, f64)>,

    equity_peak: f64,
}

impl DrawdownLadder {

    pub fn new(initial_capital: f64) -> Self {
        Self::with_bands(DEFAULT_BANDS.to_vec(), initial_capital)
    }

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

    pub fn update_peak(&mut self, current_equity: f64) -> f64 {
        if current_equity.is_finite() && current_equity > self.equity_peak {
            self.equity_peak = current_equity;
        }
        self.current_drawdown(current_equity)
    }

    pub fn current_multiplier(&self, current_equity: f64) -> f64 {
        let drawdown = self.raw_drawdown(current_equity);
        for &(threshold, multiplier) in &self.bands {
            if drawdown < threshold {
                return multiplier;
            }
        }

        self.bands.last().expect("non-empty by construction").1
    }

    pub fn current_drawdown(&self, current_equity: f64) -> f64 {
        let drawdown = self.raw_drawdown(current_equity);
        debug_assert!(drawdown >= 0.0, "drawdown is a distance below peak");
        drawdown
    }

    pub fn equity_peak(&self) -> f64 {
        self.equity_peak
    }

    fn raw_drawdown(&self, current_equity: f64) -> f64 {
        if !current_equity.is_finite() {
            return f64::INFINITY;
        }
        if current_equity >= self.equity_peak {
            return 0.0;
        }

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
        ladder.update_peak(100.0);

        assert_eq!(ladder.current_multiplier(99.9), 1.00);
        assert_eq!(ladder.current_multiplier(96.0), 1.00);
        assert_eq!(ladder.current_multiplier(91.0), 0.75);
        assert_eq!(ladder.current_multiplier(86.0), 0.50);
        assert_eq!(ladder.current_multiplier(81.0), 0.25);
    }

    #[test]
    fn default_table_exact_band_boundaries_roll_to_next_band() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(100.0);

        assert_eq!(ladder.current_multiplier(95.0), 0.75);
        assert_eq!(ladder.current_multiplier(90.0), 0.50);
        assert_eq!(ladder.current_multiplier(85.0), 0.25);
        assert_eq!(ladder.current_multiplier(80.0), 0.00);
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

        assert!((ladder.current_drawdown(60.0) - (70.0 / 130.0)).abs() < EPS);
    }

    #[test]
    fn drawdown_is_never_negative_even_when_equity_exceeds_stored_peak() {
        let mut ladder = DrawdownLadder::new(100.0);

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

        let m_deep = ladder.current_multiplier(70.0);
        assert_eq!(m_deep, 0.0);

        let m_wiped = ladder.current_multiplier(0.0);
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

        assert_eq!(ladder.current_multiplier(104.0), 1.00);
    }

    #[test]
    fn multiplier_lookup_does_not_mutate_state() {
        let mut ladder = DrawdownLadder::new(100.0);
        ladder.update_peak(100.0);

        for _ in 0..3 {
            assert_eq!(ladder.current_multiplier(50.0), 0.0);
        }
        assert!((ladder.equity_peak() - 100.0).abs() < EPS);

        assert!((ladder.update_peak(96.0) - 0.04).abs() < EPS);
        assert_eq!(ladder.current_multiplier(96.0), 1.00);
    }

    #[test]
    fn custom_bands_are_respected_and_sorted_defensively() {

        let ladder = DrawdownLadder::with_bands(vec![(f64::INFINITY, 0.0), (0.02, 0.5)], 100.0);

        assert_eq!(ladder.current_multiplier(99.5), 0.5);
        assert_eq!(ladder.current_multiplier(98.5), 0.5);
        assert_eq!(ladder.current_multiplier(98.0), 0.0);
        assert_eq!(ladder.current_multiplier(97.0), 0.0);
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

    #[test]
    fn integration_drawdown_scenario_over_multiple_bars() {
        let mut ladder = DrawdownLadder::new(100.0);

        let bars: [(f64, f64); 8] = [
            (102.0, 1.20),
            (110.0, 1.10),
            (104.0, 1.00),
            (98.0, 0.90),
            (92.0, 0.80),
            (87.5, 0.70),
            (86.0, 0.60),
            (111.0, 1.30),
        ];

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

        for w in gross_path[1..7].windows(2) {
            assert!(w[1] <= w[0] + EPS);
        }
        assert!(gross_path[0] > 0.0);
        assert_eq!(gross_path[5], 0.0);
        assert_eq!(gross_path[6], 0.0);
        assert!(gross_path[7] > 0.0);

        let raw = [1.00, 0.90];
        let scaled: Vec<f64> = raw.iter().map(|&p| p * expected_m[3]).collect();
        assert!((scaled[0] - 0.50).abs() < EPS);
        assert!((scaled[1] - 0.45).abs() < EPS);
        assert!((scaled[0] / scaled[1] - raw[0] / raw[1]).abs() < EPS);

        assert!(ladder.current_drawdown(111.0).abs() < EPS);
        assert!((ladder.equity_peak() - 111.0).abs() < EPS);
    }
}
