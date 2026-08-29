//! Parameter plateau detection for overfitting screens.
//!
//! A robust strategy parameter sits on a plateau: moving the value around
//! the chosen point changes performance only slightly. A parameter tuned
//! into a sharp peak - performance collapses as soon as the value moves a
//! few percent away - is strong evidence of curve fitting to the specific
//! backtest sample. Sweep the parameter on a grid, evaluate the metric at
//! each grid point, then call [`detect_plateau`] with the chosen center.
//!
//! Pure Rust, no external dependencies.

/// Outcome of a plateau check around one parameter's chosen value.
#[derive(Debug, Clone)]
pub struct PlateauResult {
    /// True when the immediate neighbors of the center are both mutually
    /// consistent and perform nearly as well as the center itself: their
    /// coefficient of variation (`cv_coefficient`) and the relative gap
    /// |neighbor_mean - center_metric| / |center_metric| must both be at
    /// most `tolerance_cv`. The gap check is what separates a sharp peak
    /// (neighbors similar to each other but far below the optimum) from a
    /// genuine plateau.
    pub is_plateau: bool,
    /// Metric observed exactly at the center value.
    pub center_metric: f64,
    /// Mean metric across the immediate neighbors (up to two grid points:
    /// one below and/or one above the center).
    pub neighbor_mean: f64,
    /// Population standard deviation of the neighbor metrics.
    pub neighbor_std: f64,
    /// Coefficient of variation of the neighbors: neighbor_std divided by
    /// |neighbor_mean|. Defined as 0.0 when neighbors are identical and
    /// INFINITY when the mean is ~0 while the spread is not.
    pub cv_coefficient: f64,
}

impl Default for PlateauResult {
    fn default() -> Self {
        Self {
            is_plateau: false,
            center_metric: 0.0,
            neighbor_mean: 0.0,
            neighbor_std: 0.0,
            cv_coefficient: f64::INFINITY,
        }
    }
}

/// Detect whether performance forms a plateau or a sharp peak around
/// `center_value` in a parameter sweep.
///
/// `grid_values` and `grid_metrics` must be parallel slices produced by
/// sweeping one parameter; extra elements beyond the shorter length are
/// ignored. The center is located by exact value match first, falling
/// back to the nearest grid value (ties resolve to the lower index).
/// Neighbors are the grid points immediately adjacent to the center -
/// the local neighborhood that a plateau must survive.
///
/// The result `is_plateau` is true only when at least one neighbor exists
/// and both dispersion criteria hold at `cv <= tolerance_cv` and
/// `|neighbor_mean - center_metric| / |center_metric| <= tolerance_cv`
/// (e.g. tolerance_cv = 0.15 requires neighbors within roughly +/-15%
/// relative dispersion of each other AND of the center). Empty or
/// degenerate input yields the non-plateau default.
pub fn detect_plateau(
    center_value: f64,
    grid_values: &[f64],
    grid_metrics: &[f64],
    tolerance_cv: f64,
) -> PlateauResult {
    let n = grid_values.len().min(grid_metrics.len());
    if n == 0 {
        return PlateauResult::default();
    }

    // Locate the center: exact value match first, then the nearest
    // finite grid value (ties resolve toward the smaller index).
    let mut best_idx: Option<usize> = if center_value.is_finite() {
        (0..n).find(|&i| grid_values[i] == center_value)
    } else {
        None
    };
    if best_idx.is_none() && center_value.is_finite() {
        best_idx = (0..n)
            .filter(|&i| grid_values[i].is_finite())
            .min_by(|&a, &b| {
                let da = (grid_values[a] - center_value).abs();
                let db = (grid_values[b] - center_value).abs();
                da.partial_cmp(&db).unwrap_or(std::cmp::Ordering::Equal)
            });
    }
    let best_idx = match best_idx {
        Some(i) => i,
        None => return PlateauResult::default(),
    };

    let center_metric = grid_metrics[best_idx];
    let mut neighbors: Vec<f64> = Vec::with_capacity(2);
    if best_idx > 0 {
        neighbors.push(grid_metrics[best_idx - 1]);
    }
    if best_idx + 1 < n {
        neighbors.push(grid_metrics[best_idx + 1]);
    }
    if neighbors.is_empty() {
        return PlateauResult::default();
    }

    let k = neighbors.len() as f64;
    let mean = neighbors.iter().sum::<f64>() / k;
    let var = neighbors.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / k;
    let std_dev = var.sqrt();

    const EPS: f64 = 1e-12;
    let cv = if mean.abs() < EPS {
        if std_dev < EPS {
            0.0
        } else {
            f64::INFINITY
        }
    } else {
        std_dev / mean.abs()
    };

    // Relative offset of the neighborhood from the center metric: a sharp
    // peak has neighbors that agree with each other yet sit far below the
    // optimum, which this term exposes.
    let gap = if center_metric.abs() < EPS {
        (mean - center_metric).abs()
    } else {
        (mean - center_metric).abs() / center_metric.abs()
    };
    let tol = tolerance_cv.max(0.0);

    PlateauResult {
        is_plateau: cv.is_finite() && cv <= tol && gap <= tol,
        center_metric,
        neighbor_mean: mean,
        neighbor_std: std_dev,
        cv_coefficient: cv,
    }
}

/// Generate a symmetric sweep grid around `center`.
///
/// `offsets_pct` holds percentage offsets from the chosen value, e.g.
/// `[-20.0, -10.0, 0.0, 10.0, 20.0]` produces
/// `center * [0.80, 0.90, 1.00, 1.10, 1.20]`. Input order is preserved so
/// grid indices stay meaningful alongside caller-side labels. An empty
/// offset list yields an empty grid.
pub fn make_grid(center: f64, offsets_pct: &[f64]) -> Vec<f64> {
    offsets_pct
        .iter()
        .map(|&pct| center * (1.0 + pct / 100.0))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() <= tol
    }

    #[test]
    fn grid_generation_symmetric_percent_offsets() {
        let g = make_grid(100.0, &[-20.0, -10.0, 0.0, 10.0, 20.0]);
        let expected = [80.0, 90.0, 100.0, 110.0, 120.0];
        assert_eq!(g.len(), expected.len());
        for (got, want) in g.iter().zip(expected.iter()) {
            assert!(close(*got, *want, 1e-9), "{} vs {}", got, want);
        }

        // Fractional centers and single-sided sweeps work too.
        assert_eq!(make_grid(0.25, &[0.0]), vec![0.25]);
        // +10% of a negative center moves away from zero: -50 -> -55.
        assert!(close(make_grid(-50.0, &[10.0])[0], -55.0, 1e-9));
        assert!(make_grid(7.0, &[]).is_empty());
    }

    #[test]
    fn flat_neighborhood_is_plateau() {
        let grid = make_grid(100.0, &[-20.0, -10.0, 0.0, 10.0, 20.0]);
        let metrics = [0.95, 0.99, 1.00, 0.98, 0.96];
        let r = detect_plateau(100.0, &grid, &metrics, 0.15);
        assert!(r.is_plateau);
        assert!(close(r.center_metric, 1.00, 1e-12));
        assert!(close(r.neighbor_mean, (0.99 + 0.98) / 2.0, 1e-12));
        assert!(close(r.neighbor_std, 0.005, 1e-9));
        assert!(r.cv_coefficient <= 0.01);
    }

    #[test]
    fn sharp_peak_is_rejected() {
        let grid = make_grid(100.0, &[-20.0, -10.0, 0.0, 10.0, 20.0]);
        // Center spikes while everything around it collapses.
        let metrics = [0.20, 0.40, 1.00, 0.35, 0.15];
        let r = detect_plateau(100.0, &grid, &metrics, 0.15);
        assert!(!r.is_plateau);
        assert!(close(r.center_metric, 1.00, 1e-12));
        assert!(close(r.neighbor_mean, 0.375, 1e-12));
        // Neighbors agree with each other (low CV) but sit 62.5% below the
        // center - the gap term is what rejects the needle.
        assert!(r.cv_coefficient < 0.15);
        let gap = (r.neighbor_mean - r.center_metric).abs() / r.center_metric.abs();
        assert!(gap > 0.15);

        // A tolerance wide enough to cover a 62.5% gap accepts it: that is
        // what the caller asked for.
        assert!(!detect_plateau(100.0, &grid, &metrics, 0.30).is_plateau);
    }

    #[test]
    fn tolerance_controls_verdict() {
        let grid = make_grid(50.0, &[-10.0, 0.0, 10.0]);
        // Neighbors: mean 0.97, std 0.01 => CV ~1%; gap to center 3%.
        let metrics = [0.98, 1.00, 0.96];
        assert!(detect_plateau(50.0, &grid, &metrics, 0.05).is_plateau);
        assert!(!detect_plateau(50.0, &grid, &metrics, 0.02).is_plateau);
    }

    #[test]
    fn center_found_by_exact_match_then_nearest() {
        let grid = make_grid(100.0, &[-10.0, 0.0, 10.0]);
        let metrics = [0.9, 1.0, 0.9];
        let exact = detect_plateau(100.0, &grid, &metrics, 0.2);
        assert!(close(exact.center_metric, 1.0, 1e-12));

        // Off-grid center snaps to the closest value (tie goes downward).
        let snapped_up = detect_plateau(104.9, &grid, &metrics, 0.2);
        assert!(
            close(snapped_up.center_metric, 1.0, 1e-12),
            "{}",
            snapped_up.center_metric
        );
        let tie_low = detect_plateau(105.0, &grid, &metrics, 0.2);
        assert!(close(tie_low.center_metric, 1.0, 1e-12));
        let snapped_down = detect_plateau(92.0, &grid, &metrics, 0.2);
        assert!(close(snapped_down.center_metric, 0.9, 1e-12));
    }

    #[test]
    fn edge_center_uses_available_neighbor_only() {
        let grid = make_grid(100.0, &[0.0, 10.0]);
        let metrics = [1.0, 0.99];
        let r = detect_plateau(100.0, &grid, &metrics, 0.05);
        assert!(r.is_plateau);
        assert!(close(r.neighbor_mean, 0.99, 1e-12));
        assert!(close(r.neighbor_std, 0.0, 1e-12));
        assert!(close(r.cv_coefficient, 0.0, 1e-12));

        // Single-point grid has no neighbors: never a plateau.
        let lonely = detect_plateau(100.0, &[100.0], &[1.0], 1.0);
        assert!(!lonely.is_plateau);
    }

    #[test]
    fn negative_metrics_use_absolute_mean_for_cv() {
        let grid = make_grid(30.0, &[-5.0, 0.0, 5.0]);
        let metrics = [-1.00, -0.99, -1.01]; // drawdown-style metric
        let r = detect_plateau(30.0, &grid, &metrics, 0.05);
        // Neighbors -1.00 and -1.01: mean -1.005, std 0.005.
        assert!(close(r.neighbor_mean, -1.005, 1e-12));
        assert!(close(r.neighbor_std, 0.005, 1e-12));
        assert!(r.cv_coefficient < 0.05);
        assert!(r.is_plateau);
    }

    #[test]
    fn zero_mean_with_spread_is_not_a_plateau() {
        let grid = make_grid(10.0, &[-1.0, 0.0, 1.0]);
        let metrics = [-0.5, 0.0, 0.5]; // neighbors average to ~0
        let r = detect_plateau(10.0, &grid, &metrics, 0.15);
        assert!(!r.is_plateau);
        assert_eq!(r.cv_coefficient, f64::INFINITY);
    }

    #[test]
    fn degenerate_inputs_return_default() {
        let d = detect_plateau(1.0, &[], &[], 0.1);
        assert!(!d.is_plateau);
        let mismatch = detect_plateau(1.0, &[1.0, 2.0], &[0.5], 0.1); // trimmed to 1 pair
        assert!(!mismatch.is_plateau);
        let nan_grid = detect_plateau(f64::NAN, &[1.0], &[0.5], 0.1);
        assert!(!nan_grid.is_plateau);
    }
}
