pub fn sanitize_scores(score: &[f64]) -> Vec<f64> {
    let Some(&first_finite) = score.iter().find(|v| v.is_finite()) else {
        return vec![0.0; score.len()];
    };
    let mut last = first_finite;
    score.iter()
        .map(|v| {
            if v.is_finite() { last = *v; }
            last
        })
        .collect()
}

pub fn ewma_smooth(score: &[f64], span: usize) -> Vec<f64> {
    let lambda = 2.0 / (span as f64 + 1.0);
    let mut out = vec![score[0]];
    for t in 1..score.len() {
        out.push(lambda * score[t] + (1.0 - lambda) * out[t - 1]);
    }
    out
}

pub fn rolling_zscore(smoothed: &[f64], window: usize) -> Vec<f64> {
    let n = smoothed.len();
    if n == 0 || window == 0 { return vec![0.0; n]; }
    if n < window { return vec![0.0; n]; }

    let mut z = vec![0.0; n];
    let wf = window as f64;
    let anchor = smoothed[0];

    let centred = |v: f64| v - anchor;

    let mut run_sum: f64 = smoothed[..window].iter().map(|&v| centred(v)).sum();
    let mut run_sq_sum: f64 = smoothed[..window].iter()
        .map(|&v| { let y = centred(v); y * y })
        .sum();

    for t in window..n {

        let mean = run_sum / wf;
        let var = (run_sq_sum / wf - mean * mean).max(0.0);
        let std = var.sqrt();

        if std > f64::EPSILON && std.is_finite() && smoothed[t].is_finite() {
            z[t] = (centred(smoothed[t]) - mean) / std;
        }

        let old_val = centred(smoothed[t - window]);
        let new_val = centred(smoothed[t]);
        if old_val.is_finite() && new_val.is_finite() {
            run_sum += new_val - old_val;
            run_sq_sum += new_val * new_val - old_val * old_val;

            if run_sq_sum < 0.0 {
                run_sq_sum = 0.0;
            }
        }
    }
    z
}

pub fn apply_step_cd(z_t: f64, prev_pos: f64, band: f64, cap: f64) -> (f64, bool) {
    let target = z_t.clamp(-cap, cap);
    if (target - prev_pos).abs() > band {
        (target, true)
    } else {
        (prev_pos, false)
    }
}

#[derive(Debug, Clone)]
pub struct CanonicalResult {
    pub position: Vec<f64>,
    pub turnover: Vec<f64>,
    pub trades_per_day: f64,
}

pub fn canonical_map(
    score: &[f64],
    cfg: &crate::harness_config::HarnessConfig,
    bars_per_day: usize,
) -> CanonicalResult {
    if score.is_empty() {
        return CanonicalResult {
            position: vec![],
            turnover: vec![],
            trades_per_day: 0.0,
        };
    }

    let score = sanitize_scores(score);
    let smoothed = ewma_smooth(&score, cfg.span);
    let z = rolling_zscore(&smoothed, cfg.z_window);
    let mut pos = vec![0.0; z.len()];
    let mut turn = vec![0.0; z.len()];
    let mut trade_count = 0usize;

    for t in 1..z.len() {

        let target = if (z[t - 1] - pos[t - 1]).abs() > cfg.band {
            z[t - 1].clamp(-cfg.cap, cfg.cap)
        } else {
            pos[t - 1]
        };
        let delta = (target - pos[t - 1]).abs();
        turn[t] = delta;
        pos[t] = target;

        if delta > f64::EPSILON {
            trade_count += 1;
        }
    }

    CanonicalResult {
        position: pos,
        turnover: turn,
        trades_per_day: trade_count as f64 / bars_per_day.max(1) as f64,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::harness_config::HarnessConfig;

    #[test]
    fn sanitize_leading_nan_seeded_from_first_finite() {
        let got = sanitize_scores(&[f64::NAN, f64::NAN, 3.0, 4.0]);
        assert_eq!(got, vec![3.0, 3.0, 3.0, 4.0]);
    }

    #[test]
    fn sanitize_interior_nan_carries_forward() {
        let got = sanitize_scores(&[1.0, f64::NAN, f64::INFINITY, 2.0]);
        assert_eq!(got, vec![1.0, 1.0, 1.0, 2.0]);
    }

    #[test]
    fn sanitize_all_nan_maps_to_zeros() {
        let got = sanitize_scores(&[f64::NAN, f64::NAN]);
        assert_eq!(got, vec![0.0, 0.0]);
    }

    #[test]
    fn sanitize_clean_input_unchanged() {
        let got = sanitize_scores(&[1.5, -2.0, 0.0]);
        assert_eq!(got, vec![1.5, -2.0, 0.0]);
    }

    #[test]
    fn zscore_never_emits_nan_from_poisoned_accumulators() {

        let mut x = vec![1.0; 600];
        for t in 0..600 { x[t] = (t as f64 * 0.37).sin(); }
        x[10] = f64::NAN;
        let z = rolling_zscore(&x, 480);
        assert!(z.iter().all(|v| v.is_finite()));
    }

    fn oscillating_with_warmup(n: usize, warmup: usize) -> Vec<f64> {

        (0..n)
            .map(|t| {
                if t < warmup {
                    f64::NAN
                } else {
                    ((t as f64) * 0.2).sin() * 5.0
                }
            })
            .collect()
    }

    #[test]
    fn canonical_map_survives_warmup_nan_and_trades() {

        let n = 3000;
        let score = oscillating_with_warmup(n, 100);
        let cfg = HarnessConfig::default();
        let res = canonical_map(&score, &cfg, 240);

        assert!(res.position.iter().all(|p| p.is_finite()));
        let active = res.position.iter().filter(|p| p.abs() > 0.0).count();
        assert!(active > 100, "position should leave the flat state, got {} active bars", active);
        assert!(res.trades_per_day > 0.0);
    }

    #[test]
    fn trades_per_day_counts_actual_trades_not_bars() {

        let cfg = HarnessConfig::default();
        let score = oscillating_with_warmup(3000, 100);
        let res = canonical_map(&score, &cfg, 500);

        let position_changes = res.position.windows(2)
            .filter(|w| (w[1] - w[0]).abs() > f64::EPSILON)
            .count();
        assert!(position_changes > 0);
        assert!(position_changes < res.position.len() - 1,
            "oscillating score must not trade on every bar");
        assert_eq!(res.trades_per_day, position_changes as f64 / 500.0);
    }

    #[test]
    fn empty_score_yields_empty_result_without_crash() {
        let cfg = HarnessConfig::default();
        let res = canonical_map(&[], &cfg, 250);
        assert!(res.position.is_empty());
        assert!(res.turnover.is_empty());
        assert_eq!(res.trades_per_day, 0.0);
    }

    #[test]
    fn all_nan_score_yields_flat_position_without_crash() {
        let score = vec![f64::NAN; 500];
        let cfg = HarnessConfig::default();
        let res = canonical_map(&score, &cfg, 250);
        assert!(res.position.iter().all(|p| *p == 0.0));
    }

    #[test]
    fn constant_score_yields_zero_trades() {

        let score = vec![7.3; 2000];
        let cfg = HarnessConfig::default();
        let res = canonical_map(&score, &cfg, 480);
        assert!(res.position.iter().all(|p| *p == 0.0));
        assert_eq!(res.trades_per_day, 0.0);
    }

    fn reference_score(n: usize) -> Vec<f64> {
        (0..n)
            .map(|t| ((t as f64) * 0.11).sin() * 5.0 + ((t as f64) * 0.031).cos() * 3.0)
            .collect()
    }

    #[test]
    fn metamorphic_scale_invariance() {

        let cfg = HarnessConfig::default();
        let score = reference_score(3000);
        let scaled: Vec<f64> = score.iter().map(|v| v * 1000.0).collect();

        let base = canonical_map(&score, &cfg, 480);
        let scaled_res = canonical_map(&scaled, &cfg, 480);

        for (t, (a, b)) in base.position.iter().zip(scaled_res.position.iter()).enumerate() {
            assert!(
                (a - b).abs() < 1e-9,
                "position diverged at {} under positive scaling: {} vs {}",
                t, a, b
            );
        }
    }

    #[test]
    fn metamorphic_shift_invariance() {

        let cfg = HarnessConfig::default();
        let score = reference_score(3000);
        let shifted: Vec<f64> = score.iter().map(|v| v - 12345.0).collect();

        let base = canonical_map(&score, &cfg, 480);
        let shifted_res = canonical_map(&shifted, &cfg, 480);

        for (t, (a, b)) in base.position.iter().zip(shifted_res.position.iter()).enumerate() {
            assert!((a - b).abs() < 1e-9, "position diverged at {} under shift", t);
        }
    }

    #[test]
    fn metamorphic_sign_mirror() {

        let cfg = HarnessConfig::default();
        let score = reference_score(3000);
        let mirrored: Vec<f64> = score.iter().map(|v| -v).collect();

        let base = canonical_map(&score, &cfg, 480);
        let mirrored_res = canonical_map(&mirrored, &cfg, 480);

        for (t, (a, b)) in base.position.iter().zip(mirrored_res.position.iter()).enumerate() {
            assert!((a + b).abs() < 1e-9, "position not mirrored at {}", t);
        }
    }

    #[test]
    fn metamorphic_warmup_nan_prefix_is_behaviorally_neutral() {

        let cfg = HarnessConfig::default();
        let prefix_len = 150;
        let clean = reference_score(4000);
        let mut prefixed = vec![f64::NAN; prefix_len];
        prefixed.extend_from_slice(&clean);

        let base = canonical_map(&clean, &cfg, 480);
        let prefixed_res = canonical_map(&prefixed, &cfg, 480);

        let margin = 128usize;
        let start = cfg.z_window + margin;
        let end = clean.len() - margin;
        let mut mismatches = 0usize;
        for t in start..end {
            let a = base.position[t];
            let b = prefixed_res.position[t + prefix_len];
            if (a - b).abs() > 1e-6 {
                mismatches += 1;
            }
        }
        let checked = end - start;
        assert!(
            mismatches <= checked / 100,
            "warmup NaN prefix changed behaviour at {}/{} aligned bars",
            mismatches,
            checked
        );

        assert!(base.trades_per_day > 0.0);
        assert!(prefixed_res.trades_per_day > 0.0);
    }
}
