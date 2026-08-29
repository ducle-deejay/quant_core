//! Deflated Sharpe Ratio (DSR), after Bailey and Lopez de Prado (2014).
//!
//! When many strategy configurations are tried, the best observed Sharpe
//! ratio is inflated by pure luck: taking the maximum of N noisy estimates
//! produces a positive value even when every trial has zero true skill.
//! The DSR compares the observed best Sharpe against the Sharpe level that
//! chance alone would be expected to produce given N trials, and corrects
//! the comparison for skewness, kurtosis, and finite sample length.
//!
//! Reference:
//! Bailey, D. H. and Lopez de Prado, M. (2014), "The Deflated Sharpe
//! Ratio: Correcting for Selection Bias, Backtest Overfitting and
//! Non-Normality", Journal of Portfolio Management 40(5), 94-107.
//!
//! Expected maximum Sharpe under the null (all true Sharpes equal zero):
//!
//!   SR0 = sqrt(V[{SR_n}]) * ((1 - gamma) * Z(1 - 1/N)
//!                             + gamma * Z(1 - 1/(N*e)))
//!
//! where gamma = 0.5772156... is the Euler-Mascheroni constant, e is
//! Euler's number, N is the number of independent trials, V[{SR_n}] is
//! the cross-trial variance of the Sharpe estimates, and Z(p) is the
//! inverse standard normal CDF at probability p.
//!
//! All code in this module is pure Rust with no external dependencies.

/// Euler-Mascheroni constant.
const EULER_GAMMA: f64 = 0.5772156649015329;

/// Compute the deflation threshold: the expected maximum Sharpe ratio
/// across `n_trials` independent trials under the null hypothesis of zero
/// skill, given a cross-trial Sharpe variance `variance_of_sharpes`.
///
/// Results above this level are unlikely to be produced by chance alone;
/// results below it are consistent with selection bias over N trials.
///
/// Assumes the trial Sharpes are independent draws with mean zero.
/// Returns 0.0 when `n_trials < 2` or `variance_of_sharpes` is not
/// positive (a single trial carries no selection bias to deflate).
pub fn deflated_threshold(n_trials: usize, variance_of_sharpes: f64) -> f64 {
    if n_trials < 2 || !(variance_of_sharpes > 0.0) {
        return 0.0;
    }
    let n = n_trials as f64;
    // Probability arguments for the two order-statistic terms. Both lie in
    // [0.5, 1) for n >= 2; clamped defensively against float rounding for
    // extremely large N so Z() never sees 0.0 or 1.0 exactly.
    let p_first = (1.0 - 1.0 / n).clamp(1e-15, 1.0 - 1e-15);
    let p_second = (1.0 - 1.0 / (n * std::f64::consts::E)).clamp(1e-15, 1.0 - 1e-15);
    let z_first = inv_norm_cdf(p_first);
    let z_second = inv_norm_cdf(p_second);
    variance_of_sharpes.sqrt() * ((1.0 - EULER_GAMMA) * z_first + EULER_GAMMA * z_second)
}

/// Deflated Sharpe Ratio probability: adjusts an observed (best-of-N)
/// Sharpe for the expected maximum of N random trials, accounting for
/// skewness, kurtosis, and sample length.
///
/// Returns the estimated probability that the observed best-of-N Sharpe is
/// spurious, i.e. that the underlying true Sharpe is not positive once the
/// multiple-testing inflation has been removed. Lower values mean the edge
/// is more likely real; values above roughly 0.05 fail a 95% significance
/// screen.
///
/// Arguments:
/// - `observed_sharpe`: the winning Sharpe estimate across all trials,
///   expressed in units where the cross-trial variance of Sharpes is 1.0
///   (if the measured variance is V, divide the observed Sharpe by
///   sqrt(V) before calling; see `deflated_threshold` for raw-scale use).
/// - `n_trials`: number of independent configurations tried.
/// - `skewness`: skewness of the per-period returns of the winning trial.
/// - `kurtosis`: non-excess kurtosis of those returns (normal = 3.0).
/// - `sample_length`: number of return observations T behind the estimate.
///
/// Uses the standard PSR-style correction
///
///   stat = ((SR - SR0) * sqrt(T - 1)) / sqrt(1 - skew*SR + ((kurt-1)/4)*SR^2)
///   P(spurious) = 1 - Phi(stat)
///
/// where SR0 is the null expected maximum from `deflated_threshold` with
/// unit cross-trial variance. If the moment-based denominator is not a
/// real number (possible only for extreme negative skew / high kurtosis),
/// the Gaussian floor 1 + SR^2/2 is substituted. Returns 1.0 (cannot rule
/// out spuriousness) for non-finite input or `sample_length < 2`.
pub fn deflated_sharpe_probability(
    observed_sharpe: f64,
    n_trials: usize,
    skewness: f64,
    kurtosis: f64,
    sample_length: usize,
) -> f64 {
    if !observed_sharpe.is_finite() || !skewness.is_finite() || !kurtosis.is_finite() {
        return 1.0;
    }
    if sample_length < 2 {
        return 1.0;
    }
    let sr = observed_sharpe;
    let sr0 = deflated_threshold(n_trials.max(1), 1.0);

    let t = (sample_length - 1) as f64;
    let mut denom_sq = 1.0 - skewness * sr + ((kurtosis - 1.0) / 4.0) * sr * sr;
    let gaussian_floor = 1.0 + sr * sr / 2.0;
    if !(denom_sq > 0.0) || !denom_sq.is_finite() {
        denom_sq = gaussian_floor;
    }
    let stat = (sr - sr0) * t.sqrt() / denom_sq.sqrt();
    let confidence = norm_cdf(stat);
    (1.0 - confidence).clamp(0.0, 1.0)
}

/// Standard normal CDF Phi(x).
///
/// Central range (|x| < 3) uses the Abramowitz and Stegun 26.2.17 rational
/// polynomial (absolute error below 7.5e-8). The tails use the Laplace
/// continued fraction for the Mills ratio, which preserves *relative*
/// accuracy where polynomial fits decay badly - important because the DSR
/// statistic lands deep in the tail for strong strategies. Phi(0) returns
/// exactly 0.5.
fn norm_cdf(x: f64) -> f64 {
    if x.is_nan() {
        return x;
    }
    if x == 0.0 {
        return 0.5;
    }
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let ax = x.abs();
    let upper_tail = if ax < 3.0 {
        let t = 1.0 / (1.0 + A_S_P * ax);
        let poly = t * (A_S_B[0] + t * (A_S_B[1] + t * (A_S_B[2] + t * (A_S_B[3] + t * A_S_B[4]))));
        normal_density(ax) * poly
    } else {
        normal_density(ax) * mills_ratio(ax)
    };
    if sign > 0.0 {
        1.0 - upper_tail
    } else {
        upper_tail
    }
}

/// Standard normal density phi(x).
fn normal_density(x: f64) -> f64 {
    (-x * x / 2.0).exp() / (std::f64::consts::SQRT_2 * std::f64::consts::PI.sqrt())
}

/// Mills ratio Q(x)/phi(x) for x > 0, evaluated as the Laplace continued
/// fraction 1/(x + 1/(x + 2/(x + 3/(x + ...)))) from the bottom up.
/// All intermediate values are positive, so there is no cancellation;
/// relative error is below ~1e-13 for x >= 3.
fn mills_ratio(x: f64) -> f64 {
    const DEPTH: usize = 220;
    let mut t = (DEPTH as f64) / x; // seed for the deepest level
    for k in (1..DEPTH).rev() {
        t = (k as f64) / (x + t);
    }
    1.0 / (x + t)
}

// Coefficients for Abramowitz & Stegun 26.2.17.
const A_S_P: f64 = 0.2316419;
const A_S_B: [f64; 5] = [
    0.319381530,
    -0.356563782,
    1.781477937,
    -1.821255978,
    1.330274429,
];

/// Inverse standard normal CDF Z(p) for p in (0, 1).
///
/// Peter Acklam's rational approximation (relative error < 1.15e-9) with a
/// Halley refinement step driven by `norm_cdf`, which tightens the result
/// toward the accuracy limit of the CDF itself.
fn inv_norm_cdf(p: f64) -> f64 {
    if !(p > 0.0 && p < 1.0) {
        if p == 0.0 {
            return f64::NEG_INFINITY;
        }
        if p == 1.0 {
            return f64::INFINITY;
        }
        return f64::NAN;
    }
    let p = p.clamp(1e-15, 1.0 - 1e-15);
    let p_low = 0.02425;
    let p_high = 1.0 - p_low;

    // Rational approximations (Acklam).
    let a: [f64; 6] = [
        -3.969683028665376e+01,
        2.209460984245205e+02,
        -2.759285104469687e+02,
        1.383577518672690e+02,
        -3.066479806614716e+01,
        2.506628277459239e+00,
    ];
    let b: [f64; 5] = [
        -5.447609879822406e+01,
        1.615858368580409e+02,
        -1.556989798598866e+02,
        6.680131188771972e+01,
        -1.328068155288572e+01,
    ];
    let c: [f64; 6] = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e+00,
        -2.549732539343734e+00,
        4.374664141464968e+00,
        2.938163982698783e+00,
    ];
    let d: [f64; 4] = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e+00,
        3.754408661907416e+00,
    ];

    let mut x;
    if p < p_low {
        let q = (-2.0 * p.ln()).sqrt();
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
    } else if p <= p_high {
        let q = p - 0.5;
        let r = q * q;
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0);
    } else {
        let q = (-2.0 * (1.0 - p).ln()).sqrt();
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
    }

    // One Halley refinement step: e = Phi(x) - p, then Newton-style update
    // scaled for faster convergence near the root.
    let e = norm_cdf(x) - p;
    let u = e * (std::f64::consts::SQRT_2 * std::f64::consts::PI.sqrt()) * (x * x / 2.0).exp();
    x -= u / (1.0 + x * u / 2.0);
    x
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() <= tol
    }

    #[test]
    fn inverse_cdf_known_quantiles() {
        assert!(close(inv_norm_cdf(0.5), 0.0, 1e-12));
        // Z(0.975) = 1.959963985...
        assert!(close(inv_norm_cdf(0.975), 1.959963985, 1e-5));
        // Symmetry: Z(p) = -Z(1-p).
        assert!(close(inv_norm_cdf(0.025), -1.959963985, 1e-5));
        // Z(0.841344746) ~ 1.0 (Phi(1)).
        assert!(close(inv_norm_cdf(0.841344746), 1.0, 1e-5));
        // Far tail stays finite and sane: Z(1 - 1e-9) ~ 5.9978.
        assert!(close(inv_norm_cdf(1.0 - 1e-9), 5.997807, 1e-3));
    }

    #[test]
    fn normal_cdf_round_trip() {
        for &p in &[0.001, 0.025, 0.3, 0.5, 0.7, 0.975, 0.999] {
            let x = inv_norm_cdf(p);
            assert!(
                close(norm_cdf(x), p, 1e-6),
                "round trip failed at p = {}: got {}",
                p,
                norm_cdf(x)
            );
        }
    }

    #[test]
    fn normal_cdf_symmetry_and_bounds() {
        assert!(close(norm_cdf(0.0), 0.5, 1e-12));
        assert!(norm_cdf(-40.0) < 1e-10);
        let z = 1.96;
        assert!((1.0 - norm_cdf(-z) - norm_cdf(z)).abs() < 1e-9);
    }

    #[test]
    fn threshold_grows_with_trials() {
        assert_eq!(deflated_threshold(1, 1.0), 0.0);
        assert_eq!(deflated_threshold(100, 0.0), 0.0);
        assert_eq!(deflated_threshold(100, -1.0), 0.0);

        // Known magnitudes for unit cross-trial variance:
        // N = 100 blends Z(0.99)=2.32635 and Z(1-1/(100e))=2.67993 into ~2.53.
        let t100 = deflated_threshold(100, 1.0);
        assert!(t100 > 2.52 && t100 < 2.54, "t100 = {}", t100);
        // N = 10000 lands near 3.83.
        let t10k = deflated_threshold(10_000, 1.0);
        assert!(t10k > 3.70 && t10k < 3.95, "t10k = {}", t10k);

        // Monotone increasing in N and in sqrt(variance).
        assert!(deflated_threshold(10, 1.0) < t100);
        assert!(t100 < t10k);
        assert!(close(deflated_threshold(100, 4.0), 2.0 * t100, 1e-9));
    }

    #[test]
    fn probability_at_threshold_is_coin_flip() {
        // Observed exactly at the null expected max => statistic 0 => 0.5.
        let sr0 = deflated_threshold(50, 1.0);
        let p = deflated_sharpe_probability(sr0, 50, 0.0, 3.0, 1000);
        assert!(close(p, 0.5, 1e-6), "p = {}", p);
    }

    #[test]
    fn probability_monotone_in_observed_sharpe() {
        let weak = deflated_sharpe_probability(1.0, 50, 0.0, 3.0, 1000);
        let mid = deflated_sharpe_probability(2.6, 50, 0.0, 3.0, 1000);
        let strong = deflated_sharpe_probability(4.0, 50, 0.0, 3.0, 1000);
        assert!(weak > mid);
        assert!(mid > strong);
        assert!(strong < 0.01, "strong sharpe should look real: {}", strong);
    }

    #[test]
    fn probability_grows_with_trial_count() {
        let few = deflated_sharpe_probability(2.0, 5, 0.0, 3.0, 1000);
        let many = deflated_sharpe_probability(2.0, 5000, 0.0, 3.0, 1000);
        assert!(few < many);
    }

    #[test]
    fn bad_distribution_raises_spurious_probability() {
        let clean = deflated_sharpe_probability(3.0, 100, 0.0, 3.0, 2000);
        let neg_skew = deflated_sharpe_probability(3.0, 100, -1.5, 3.0, 2000);
        let fat_tails = deflated_sharpe_probability(3.0, 100, -0.5, 8.0, 2000);
        assert!(neg_skew > clean);
        assert!(fat_tails > clean);
    }

    #[test]
    fn negative_or_degenerate_input_is_spurious() {
        assert!(deflated_sharpe_probability(-1.0, 10, 0.0, 3.0, 500) > 0.99);
        assert_eq!(deflated_sharpe_probability(2.0, 10, 0.0, 3.0, 1), 1.0);
        assert_eq!(
            deflated_sharpe_probability(f64::NAN, 10, 0.0, 3.0, 500),
            1.0
        );
        // Zero observed Sharpe sits below any positive threshold.
        assert!(deflated_sharpe_probability(0.0, 10, 0.0, 3.0, 500) > 0.9);
    }

    #[test]
    fn short_samples_are_penalized() {
        let long = deflated_sharpe_probability(3.0, 100, 0.0, 3.0, 2500);
        let short = deflated_sharpe_probability(3.0, 100, 0.0, 3.0, 30);
        assert!(short > long, "short sample must look less trustworthy");
    }
}
