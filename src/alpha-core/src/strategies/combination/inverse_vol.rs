use super::CombineMethod;

pub const DEFAULT_MIN_WEIGHT: f64 = 0.01;

pub const DEFAULT_MAX_WEIGHT: f64 = 0.50;

const FEASIBILITY_TOL: f64 = 1e-9;

const BISECT_STEPS: usize = 200;

#[derive(Debug, Clone, Copy)]
pub struct InverseVol {

    pub min_weight: f64,

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

    fn compute_weights(&self, scores: &[Vec<f64>]) -> Vec<f64> {
        let n_alphas = scores.len();
        if n_alphas == 0 {
            return Vec::new();
        }
        if n_alphas == 1 {

            return vec![1.0];
        }

        let vols: Vec<Option<f64>> = scores.iter().map(|s| sample_stddev(s)).collect();

        let raw: Vec<f64> = vols
            .iter()
            .map(|v| match v {
                Some(vol) if vol.is_finite() && *vol > 0.0 => 1.0 / *vol,
                _ => 0.0,
            })
            .collect();
        let eligible: Vec<usize> = (0..n_alphas).filter(|&i| raw[i] > 0.0).collect();

        if eligible.is_empty() {
            return vec![1.0 / n_alphas as f64; n_alphas];
        }

        let raw_total: f64 = eligible.iter().map(|&i| raw[i]).sum();
        let mut weights = vec![0.0; n_alphas];
        for &i in &eligible {
            weights[i] = raw[i] / raw_total;
        }

        self.apply_caps(&mut weights, &eligible);
        weights
    }

    fn apply_caps(&self, weights: &mut [f64], eligible: &[usize]) {
        let k = eligible.len();
        if k == 0 {
            return;
        }
        if k == 1 {

            weights[eligible[0]] = 1.0;
            return;
        }

        let lo = self.min_weight;
        let hi = self.max_weight;
        if !lo.is_finite() || !hi.is_finite() || lo > hi {

            return;
        }

        if k as f64 * lo > 1.0 + FEASIBILITY_TOL || k as f64 * hi < 1.0 - FEASIBILITY_TOL {

            return;
        }

        let scaled: Vec<f64> = eligible.iter().map(|&i| weights[i]).collect();

        let min_r = scaled
            .iter()
            .cloned()
            .fold(f64::INFINITY, f64::min)
            .max(f64::MIN_POSITIVE);

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

#[derive(Debug, Clone, Copy, Default)]
pub struct EqualWeight;

impl CombineMethod for EqualWeight {

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

    fn alternator(amplitude: f64, n: usize) -> Vec<f64> {
        (0..n)
            .map(|t| if t % 2 == 0 { amplitude } else { -amplitude })
            .collect()
    }

    #[test]
    fn weights_sum_to_one_and_rank_by_inverse_vol() {

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

        assert_close(w[0], 2.0 / 7.0, 1e-12);
        assert_close(w[1], 1.0 / 7.0, 1e-12);
        assert_close(w[2], 4.0 / 7.0, 1e-12);
    }

    #[test]
    fn max_weight_cap_is_respected() {

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

        assert_close(w[0], 1.0 / 3.0, 1e-9);
        assert_close(w[1], 1.0 / 6.0, 1e-9);
        assert_close(w[2], 0.5, 1e-9);
    }

    #[test]
    fn min_weight_cap_is_respected() {

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

        assert_close(w[0], 0.01, 1e-9);
        assert_close(w[1], 0.495, 1e-6);
        assert_close(w[2], 0.495, 1e-6);
    }

    #[test]
    fn zero_vol_alpha_is_excluded_without_nan() {
        let scores = vec![
            alternator(1.0, 64),
            alternator(2.0, 64),
            vec![3.0; 64],
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
            vec![f64::NAN; 32],
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
        let iv = InverseVol::new(0.9, 0.1);
        assert!(iv.min_weight <= iv.max_weight);
        let bad = InverseVol::new(f64::NAN, f64::INFINITY);
        assert!(bad.min_weight.is_finite() && bad.max_weight.is_finite());
    }
}
