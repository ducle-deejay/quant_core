//! Inverse-volatility weighting scheme for combining alpha scores.
//!
//! Financial logic
//! ---------------
//! Each alpha is treated as a standardized per-bar signal whose realized
//! volatility (the standard deviation of its score series) measures how
//! aggressively it swings the book. Assigning weight `1 / vol_i` to alpha `i`
//! equalizes the *risk contribution* of every sleeve instead of their dollar
//! allocation: noisy, high-variance alphas are down-weighted while stable
//! ones are up-weighted. This is the classic inverse-volatility (vol-weighted)
//! portfolio construction rule, a robust baseline before moving to fuller
//! risk-parity schemes.
//!
//! Raw inverse-vol weights are unbounded, so they are projected onto the
//! capped simplex `{w : min_weight <= w_i <= max_weight, sum(w) = 1}`. A naive
//! clip followed by a single renormalization can push weights back outside
//! the caps, so the projection instead solves for a global scale factor
//! (water-filling) such that the clipped weights sum to exactly one. This
//! enforces both the caps and the full-investment constraint simultaneously.

use super::CombineMethod;

/// Default floor applied to an individual strategy weight.
pub const DEFAULT_MIN_WEIGHT: f64 = 0.01;

/// Default cap applied to an individual strategy weight.
pub const DEFAULT_MAX_WEIGHT: f64 = 0.50;

/// Relative tolerance used when checking whether the cap band can jointly
/// hold together with the full-investment constraint `sum(w) = 1`.
const FEASIBILITY_TOL: f64 = 1e-9;

/// Bisection iterations for the capped-simplex projection. Each step halves
/// the search interval, so a couple hundred steps exhaust f64 precision.
const BISECT_STEPS: usize = 200;

/// Inverse-volatility combiner.
///
/// The weight of alpha `i` is proportional to `1 / std(scores_i)`, clipped to
/// the per-alpha `[min_weight, max_weight]` band and renormalized so the
/// weights always sum to one.
#[derive(Debug, Clone, Copy)]
pub struct InverseVol {
    /// Floor for an individual weight (default 0.01).
    pub min_weight: f64,
    /// Cap for an individual weight (default 0.50).
    pub max_weight: f64,
}

impl Default for InverseVol {
    fn default() -> Self {
        Self {
            min_weight: DEFAULT_MIN_WEIGHT,
            max_weight: DEFAULT_MAX_WEIGHT,
        }
    }
}

impl InverseVol {
    /// Creates a configuration with explicit bounds. Bounds are sanitized so
    /// that `0.0 <= min_weight <= max_weight <= 1.0` always holds.
    pub fn new(min_weight: f64, max_weight: f64) -> Self {
        let lo = if min_weight.is_finite() {
            min_weight.clamp(0.0, 1.0)
        } else {
            DEFAULT_MIN_WEIGHT
        };
        let hi = if max_weight.is_finite() {
            max_weight.clamp(0.0, 1.0)
        } else {
            DEFAULT_MAX_WEIGHT
        };
        Self {
            min_weight: lo,
            max_weight: hi.max(lo),
        }
    }

    /// Computes one portfolio weight per alpha from the score matrix.
    ///
    /// Row `i` of `scores` is the score series of alpha `i`; columns are time
    /// bars. The returned weights sum to 1. An empty input yields an empty
    /// vector. Alphas with zero or undefined volatility are excluded (weight
    /// exactly 0) because `1 / vol` is meaningless for them.
    fn compute_weights(&self, scores: &[Vec<f64>]) -> Vec<f64> {
        let n_alphas = scores.len();
        if n_alphas == 0 {
            return Vec::new();
        }
        if n_alphas == 1 {
            // A lone alpha carries the whole budget regardless of its vol.
            return vec![1.0];
        }

        // Step 1: realized per-alpha volatility of each score series.
        let vols: Vec<Option<f64>> = scores.iter().map(|s| sample_stddev(s)).collect();

        // Step 2: raw inverse-volatility weights. Series with zero or
        // undefined volatility (flat, too short, or non-finite data) provide
        // no usable risk signal and are excluded with zero raw weight.
        let raw: Vec<f64> = vols
            .iter()
            .map(|v| match v {
                Some(vol) if vol.is_finite() && *vol > 0.0 => 1.0 / *vol,
                _ => 0.0,
            })
            .collect();
        let eligible: Vec<usize> = (0..n_alphas).filter(|&i| raw[i] > 0.0).collect();

        // Zero-vol safety net: if no alpha is usable, fall back to equal
        // weights so the composite stays defined and finite.
        if eligible.is_empty() {
            return vec![1.0 / n_alphas as f64; n_alphas];
        }

        // Step 3: normalize the raw weights across the usable alphas.
        let raw_total: f64 = eligible.iter().map(|&i| raw[i]).sum();
        let mut weights = vec![0.0; n_alphas];
        for &i in &eligible {
            weights[i] = raw[i] / raw_total;
        }

        // Steps 4-5: apply the min/max caps and re-normalize, preserving the
        // budget constraint `sum(w) = 1`.
        self.apply_caps(&mut weights, &eligible);
        weights
    }

    /// Projects the eligible weights onto the capped simplex
    /// `{w : min_weight <= w_i <= max_weight, sum(w_i) = 1}`.
    ///
    /// Water-filling: find a scale `lambda` such that the eligible weights,
    /// scaled and then clipped to the cap band, sum to one. Because
    /// `g(lambda) = sum(clamp(lambda * r_i, lo, hi))` is monotone in `lambda`,
    /// bisection converges to the unique solution, and the resulting weights
    /// respect both caps and the budget exactly.
    fn apply_caps(&self, weights: &mut [f64], eligible: &[usize]) {
        let k = eligible.len();
        if k == 0 {
            return;
        }
        if k == 1 {
            // A single survivor must take the full budget even if that
            // breaches max_weight; sum-to-one always wins over the caps.
            weights[eligible[0]] = 1.0;
            return;
        }

        let lo = self.min_weight;
        let hi = self.max_weight;
        if !lo.is_finite() || !hi.is_finite() || lo > hi {
            // Degenerate configuration: keep the plain normalized weights.
            return;
        }

        // Feasibility: the cap band must be able to absorb the full budget.
        if k as f64 * lo > 1.0 + FEASIBILITY_TOL || k as f64 * hi < 1.0 - FEASIBILITY_TOL {
            // The caps cannot hold jointly with `sum(w) = 1` (far too many
            // names for the floor, or too few for the cap); keep the uncapped
            // normalized weights rather than emitting inconsistent ones.
            return;
        }

        let scaled: Vec<f64> = eligible.iter().map(|&i| weights[i]).collect();
        // Smallest normalized raw weight, guarding against underflow so the
        // bracket below stays finite.
        let min_r = scaled
            .iter()
            .cloned()
            .fold(f64::INFINITY, f64::min)
            .max(f64::MIN_POSITIVE);

        // Bracket: g(0) = k * lo <= 1 and, once the smallest raw weight is
        // pushed to `hi`, every weight clips to `hi`, giving g = k * hi >= 1.
        let mut low = 0.0f64;
        let mut high = hi / min_r;
        if !high.is_finite() {
            high = f64::MAX;
        }
        for _ in 0..BISECT_STEPS {
            let mid = 0.5 * (low + high);
            let g: f64 = scaled.iter().map(|&r| (r * mid).clamp(lo, hi)).sum();
            if g < 1.0 {
                low = mid;
            } else {
                high = mid;
            }
        }
        let lambda = 0.5 * (low + high);

        for (&i, &r) in eligible.iter().zip(scaled.iter()) {
            weights[i] = (lambda * r).clamp(lo, hi);
        }
    }
}

impl CombineMethod for InverseVol {
    /// Combines the score matrix into a single composite series using the
    /// inverse-volatility weights.
    fn combine(&self, scores: &[Vec<f64>]) -> Vec<f64> {
        let weights = self.compute_weights(scores);
        let n_bars = scores.first().map(|s| s.len()).unwrap_or(0);
        let mut composite = vec![0.0; n_bars];
        for (score, &w) in scores.iter().zip(weights.iter()) {
            for (t, &x) in score.iter().enumerate().take(n_bars) {
                composite[t] += w * x;
            }
        }
        composite
    }

    fn name(&self) -> &str {
        "inverse_vol"
    }
}

/// Benchmark combiner: uniform `1 / N` weights across all alphas.
///
/// Useful as a baseline when judging whether the inverse-volatility risk
/// model actually adds value over naive averaging of signals.
#[derive(Debug, Clone, Copy, Default)]
pub struct EqualWeight;

impl CombineMethod for EqualWeight {
    /// Averages the score series with equal `1 / N` weights.
    fn combine(&self, scores: &[Vec<f64>]) -> Vec<f64> {
        let n_bars = scores.first().map(|s| s.len()).unwrap_or(0);
        let mut composite = vec![0.0; n_bars];
        if scores.is_empty() || n_bars == 0 {
            return composite;
        }
        let w = 1.0 / scores.len() as f64;
        for score in scores {
            for (t, &x) in score.iter().enumerate().take(n_bars) {
                composite[t] += w * x;
            }
        }
        composite
    }

    fn name(&self) -> &str {
        "equal_weight"
    }
}

/// Sample standard deviation (n-1 denominator) of a series.
///
/// Returns `None` for series shorter than two observations or containing
/// non-finite values, signalling "no usable volatility estimate".
fn sample_stddev(series: &[f64]) -> Option<f64> {
    let n = series.len();
    if n < 2 {
        return None;
    }
    let mean = series.iter().sum::<f64>() / n as f64;
    if !mean.is_finite() {
        return None;
    }
    let variance = series
        .iter()
        .map(|&x| {
            let d = x - mean;
            d * d
        })
        .sum::<f64>()
        / (n - 1) as f64;
    if !variance.is_finite() {
        return None;
    }
    Some(variance.sqrt())
}

#[cfg(test)]
mod tests {
    use super::*;

    const EPS: f64 = 1e-9;

    fn assert_close(actual: f64, expected: f64, tol: f64) {
        assert!(
            (actual - expected).abs() <= tol,
            "actual {} differs from expected {} by more than {}",
            actual,
            expected,
            tol
        );
    }

    /// Alternating `+/-amplitude` series; for even length the sample standard
    /// deviation equals `amplitude` exactly.
    fn alternator(amplitude: f64, n: usize) -> Vec<f64> {
        (0..n)
            .map(|t| if t % 2 == 0 { amplitude } else { -amplitude })
            .collect()
    }

    #[test]
    fn weights_sum_to_one_and_rank_by_inverse_vol() {
        // Vols 1.0, 2.0, 0.5 -> raw 1.0, 0.5, 2.0 -> normalized 2/7, 1/7, 4/7.
        let scores = vec![
            alternator(1.0, 64),
            alternator(2.0, 64),
            alternator(0.5, 64),
        ];
        let iv = InverseVol {
            min_weight: 1e-6,
            max_weight: 1.0,
        };
        let w = iv.compute_weights(&scores);
        assert_eq!(w.len(), 3);
        assert_close(w.iter().sum(), 1.0, EPS);
        // Lower volatility -> higher weight.
        assert_close(w[0], 2.0 / 7.0, 1e-12);
        assert_close(w[1], 1.0 / 7.0, 1e-12);
        assert_close(w[2], 4.0 / 7.0, 1e-12);
    }

    #[test]
    fn max_weight_cap_is_respected() {
        // The calmest alpha earns a fair weight of 4/7 > 0.5, so the cap binds.
        let scores = vec![
            alternator(1.0, 64),
            alternator(2.0, 64),
            alternator(0.5, 64),
        ];
        let iv = InverseVol::new(0.01, 0.50);
        let w = iv.compute_weights(&scores);
        assert!(w.iter().all(|&x| x <= 0.5 + 1e-12), "cap violated: {:?}", w);
        assert!(
            w.iter().all(|&x| x >= 0.01 - 1e-12),
            "floor violated: {:?}",
            w
        );
        assert_close(w.iter().sum(), 1.0, EPS);
        // Closed form with only the third name clipped at 0.5:
        // (2/7 + 1/7) * lambda + 0.5 = 1  ->  lambda = 7/6.
        assert_close(w[0], 1.0 / 3.0, 1e-9);
        assert_close(w[1], 1.0 / 6.0, 1e-9);
        assert_close(w[2], 0.5, 1e-9);
    }

    #[test]
    fn min_weight_cap_is_respected() {
        // A wild alpha (vol 100) earns a fair weight far below the floor.
        let scores = vec![
            alternator(100.0, 64),
            alternator(1.0, 64),
            alternator(1.0, 64),
        ];
        let iv = InverseVol::new(0.01, 0.90);
        let w = iv.compute_weights(&scores);
        assert_close(w.iter().sum(), 1.0, EPS);
        assert!(
            w.iter().all(|&x| x >= 0.01 - 1e-12),
            "floor violated: {:?}",
            w
        );
        assert!(
            w.iter().all(|&x| x <= 0.90 + 1e-12),
            "cap violated: {:?}",
            w
        );
        // The floor binds exactly on the volatile name; the two calm names
        // split the remaining budget: 0.01 + lambda * (2 * 0.4975...) = 1.
        assert_close(w[0], 0.01, 1e-9);
        assert_close(w[1], 0.495, 1e-6);
        assert_close(w[2], 0.495, 1e-6);
    }

    #[test]
    fn zero_vol_alpha_is_excluded_without_nan() {
        let scores = vec![
            alternator(1.0, 64),
            alternator(2.0, 64),
            vec![3.0; 64], // perfectly flat series: zero volatility
        ];
        let iv = InverseVol::default();
        let w = iv.compute_weights(&scores);
        assert_eq!(w.len(), 3);
        assert!(
            w.iter().all(|&x| x.is_finite()),
            "non-finite weight: {:?}",
            w
        );
        assert_close(w.iter().sum(), 1.0, EPS);
        assert_eq!(w[2], 0.0);
        // Remaining budget splits across the two live alphas; with default
        // caps (max 0.5) the calmer alpha is clipped and both end at 0.5.
        assert_close(w[0], 0.5, EPS);
        assert_close(w[1], 0.5, EPS);
    }

    #[test]
    fn all_zero_vol_falls_back_to_equal_weights() {
        let scores = vec![vec![1.0; 32], vec![-2.0; 32], vec![7.0; 32]];
        let iv = InverseVol::default();
        let w = iv.compute_weights(&scores);
        assert_eq!(w.len(), 3);
        for &wi in &w {
            assert!(wi.is_finite());
            assert_close(wi, 1.0 / 3.0, EPS);
        }
        assert_close(w.iter().sum(), 1.0, EPS);
    }

    #[test]
    fn non_finite_series_is_excluded() {
        let scores = vec![
            alternator(1.0, 32),
            vec![f64::NAN; 32], // corrupted feed: no usable volatility
            alternator(0.5, 32),
        ];
        let iv = InverseVol {
            min_weight: 1e-6,
            max_weight: 1.0,
        };
        let w = iv.compute_weights(&scores);
        assert!(
            w.iter().all(|&x| x.is_finite()),
            "non-finite weight: {:?}",
            w
        );
        assert_eq!(w[1], 0.0);
        assert_close(w.iter().sum(), 1.0, EPS);
        // Raw inverse-vol weights 1/1 and 1/0.5 -> normalized 1/3 and 2/3:
        // the calmer surviving alpha takes the larger share.
        assert_close(w[0], 1.0 / 3.0, 1e-12);
        assert_close(w[2], 2.0 / 3.0, 1e-12);
    }

    #[test]
    fn lone_usable_alpha_takes_full_budget() {
        let scores = vec![alternator(1.0, 16), vec![5.0; 16]];
        let iv = InverseVol::default();
        let w = iv.compute_weights(&scores);
        assert_close(w[0], 1.0, EPS);
        assert_eq!(w[1], 0.0);
    }

    #[test]
    fn single_alpha_portfolio_gets_full_weight() {
        let iv = InverseVol::default();
        let scores = vec![alternator(2.0, 16)];
        let w = iv.compute_weights(&scores);
        assert_eq!(w.len(), 1);
        assert_close(w[0], 1.0, EPS);
        // Composite reproduces the sole input series.
        let composite = iv.combine(&scores);
        for (c, &s) in composite.iter().zip(scores[0].iter()) {
            assert_close(*c, s, 1e-12);
        }
    }

    #[test]
    fn combine_equals_manual_weighted_sum() {
        let scores = vec![alternator(1.0, 8), alternator(0.5, 8)];
        let iv = InverseVol {
            min_weight: 1e-6,
            max_weight: 1.0,
        };
        let w = iv.compute_weights(&scores);
        let composite = iv.combine(&scores);
        assert_eq!(composite.len(), 8);
        for t in 0..8 {
            let expected: f64 = w.iter().zip(scores.iter()).map(|(&wi, s)| wi * s[t]).sum();
            assert_close(composite[t], expected, 1e-12);
        }
    }

    #[test]
    fn combine_handles_empty_input() {
        let iv = InverseVol::default();
        assert!(iv.combine(&[]).is_empty());
        assert!(iv.compute_weights(&[]).is_empty());
        assert!(EqualWeight.combine(&[]).is_empty());
    }

    #[test]
    fn equal_weight_averages_all_series() {
        let scores = vec![vec![1.0, 2.0, 3.0], vec![3.0, 2.0, 1.0]];
        let ew = EqualWeight;
        assert_eq!(ew.name(), "equal_weight");
        let composite = ew.combine(&scores);
        assert_eq!(composite.len(), 3);
        for &c in &composite {
            assert_close(c, 2.0, 1e-12);
        }
    }

    #[test]
    fn names_are_stable() {
        assert_eq!(InverseVol::default().name(), "inverse_vol");
        assert_eq!(EqualWeight.name(), "equal_weight");
    }

    #[test]
    fn default_bounds_match_specification() {
        let iv = InverseVol::default();
        assert_close(iv.min_weight, 0.01, 1e-15);
        assert_close(iv.max_weight, 0.50, 1e-15);
    }

    #[test]
    fn constructor_sanitizes_inverted_or_non_finite_bounds() {
        let iv = InverseVol::new(0.9, 0.1); // inverted: swapped/clamped
        assert!(iv.min_weight <= iv.max_weight);
        let bad = InverseVol::new(f64::NAN, f64::INFINITY);
        assert!(bad.min_weight.is_finite() && bad.max_weight.is_finite());
    }
}
