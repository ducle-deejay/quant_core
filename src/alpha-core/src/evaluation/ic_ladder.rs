#[derive(Debug, Clone)]
pub struct IcResult {
    pub horizon: usize,
    pub mean_ic: f64,
    pub t_stat: f64,
}

fn rank_transform(v: &[f64]) -> Vec<f64> {
    let mut indexed: Vec<usize> = (0..v.len()).collect();
    indexed.sort_by(|&a, &b| v[a].partial_cmp(&v[b]).unwrap_or(std::cmp::Ordering::Equal));
    let mut ranks = vec![0.0; v.len()];
    for (position, &original_index) in indexed.iter().enumerate() {
        ranks[original_index] = position as f64 + 1.0;
    }
    ranks
}

fn has_dispersion(v: &[f64]) -> bool {
    let first = match v.first() {
        Some(&x) => x,
        None => return false,
    };
    v.iter().any(|&x| (x - first).abs() > 1e-12)
}

pub fn rank_ic_block(
    score: &[f64],
    ret: &[f64],
    horizon: usize,
    window: usize,
    bars_per_day: usize,
) -> (f64, f64, usize) {
    let n = score.len().min(ret.len());
    if n <= horizon + 1 {
        return (0.0, 0.0, 0);
    }

    let mut fwd = vec![f64::NAN; n];
    for t in 0..n.saturating_sub(horizon) {
        fwd[t] = (1..=horizon)
            .filter(|&k| t + k < ret.len())
            .map(|k| if k + 1 < ret.len() { ret[t + k] } else { 0.0 })
            .sum::<f64>();
    }

    let mut block_ics = Vec::new();
    let mut start = window;
    while start < n - horizon {
        let end = (start + bars_per_day).min(n - horizon);
        if end <= start {
            break;
        }
        let sc: Vec<f64> = score[start..end].to_vec();
        let fw: Vec<f64> = fwd[start..end].to_vec();

        let pairs: Vec<(f64, f64)> = sc
            .iter()
            .zip(fw.iter())
            .filter(|(a, b)| a.is_finite() && b.is_finite())
            .map(|(a, b)| (*a, *b))
            .collect();

        if pairs.len() > 5 && has_dispersion(&pairs.iter().map(|p| p.0).collect::<Vec<_>>()) {
            let score_ranks = rank_transform(&pairs.iter().map(|p| p.0).collect::<Vec<_>>());
            let return_ranks = rank_transform(&pairs.iter().map(|p| p.1).collect::<Vec<_>>());

            let np = pairs.len() as f64;
            let ms: f64 = score_ranks.iter().sum::<f64>() / np;
            let mf: f64 = return_ranks.iter().sum::<f64>() / np;
            let cov: f64 = score_ranks
                .iter()
                .zip(return_ranks.iter())
                .map(|(a, b)| (a - ms) * (b - mf))
                .sum();
            let ss: f64 = score_ranks
                .iter()
                .map(|a| (a - ms).powi(2))
                .sum::<f64>()
                .sqrt();
            let sf: f64 = return_ranks
                .iter()
                .map(|b| (b - mf).powi(2))
                .sum::<f64>()
                .sqrt();
            if ss > 1e-12 && sf > 1e-12 {
                block_ics.push(cov / (ss * sf));
            }
        }
        start += bars_per_day;
    }

    if block_ics.is_empty() {
        return (0.0, 0.0, 0);
    }
    let nb = block_ics.len() as f64;
    let mean = block_ics.iter().sum::<f64>() / nb;
    let std = (block_ics.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / nb).sqrt();
    let t_stat = if std > 1e-12 {
        mean / (std / nb.sqrt())
    } else {
        0.0
    };
    (mean, t_stat, block_ics.len())
}

pub fn ic_ladder(
    score: &[f64],
    ret: &[f64],
    horizons: &[usize],
    window: usize,
    bars_per_day: usize,
) -> Vec<IcResult> {
    horizons
        .iter()
        .map(|&h| {
            let (mean_ic, t_stat, _) = rank_ic_block(score, ret, h, window, bars_per_day);
            IcResult {
                horizon: h,
                mean_ic,
                t_stat,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const WINDOW: usize = 20;
    const BARS_PER_DAY: usize = 10;

    fn lead_lag_world(n: usize) -> (Vec<f64>, Vec<f64>) {
        let score: Vec<f64> = (0..n)
            .map(|t| ((t as f64) * 0.21).sin() + 0.3 * ((t as f64) * 0.53).cos())
            .collect();
        let mut ret = vec![0.0; n];
        for t in 1..n {
            let wobble = 0.001 * ((t as f64) * 0.077).sin();
            ret[t] = 0.01 * score[t - 1] + wobble;
        }
        (score, ret)
    }

    #[test]
    fn perfect_lead_lag_scores_near_one_with_strong_tstat() {
        let (score, ret) = lead_lag_world(600);
        let (mean_ic, t_stat, blocks) =
            rank_ic_block(&score, &ret, 1, WINDOW, BARS_PER_DAY);

        assert!(blocks >= 10, "expected many daily blocks, got {}", blocks);
        assert!(mean_ic > 0.9, "lead-lag world must give mean IC ~ 1, got {}", mean_ic);
        assert!(t_stat > 10.0, "consistent edge must give large t-stat, got {}", t_stat);
    }

    #[test]
    fn mirrored_score_mirrors_mean_ic_and_tstat_sign() {
        let (score, ret) = lead_lag_world(600);
        let mirrored: Vec<f64> = score.iter().map(|v| -v).collect();

        let (pos_ic, pos_t, _) = rank_ic_block(&score, &ret, 1, WINDOW, BARS_PER_DAY);
        let (neg_ic, neg_t, _) = rank_ic_block(&mirrored, &ret, 1, WINDOW, BARS_PER_DAY);

        assert!((pos_ic + neg_ic).abs() < 1e-9);
        assert!(neg_t < 0.0 && pos_t > 0.0);
    }

    #[test]
    fn horizon_ladder_reports_each_requested_horizon_in_order() {
        let (score, ret) = lead_lag_world(800);
        let rungs = ic_ladder(&score, &ret, &[1, 3, 8], WINDOW, BARS_PER_DAY);

        assert_eq!(rungs.len(), 3);
        assert_eq!(rungs[0].horizon, 1);
        assert_eq!(rungs[1].horizon, 3);
        assert_eq!(rungs[2].horizon, 8);
        for rung in &rungs {
            assert!(rung.mean_ic.is_finite() && rung.t_stat.is_finite());
            assert!(rung.mean_ic.abs() <= 1.0 + 1e-9);
        }
    }

    #[test]
    fn short_series_yields_zero_blocks_and_neutral_output() {

        let score = vec![1.0, -1.0, 1.0];
        let ret = vec![0.0, 0.1, -0.1];
        let (mean_ic, t_stat, blocks) = rank_ic_block(&score, &ret, 1, WINDOW, BARS_PER_DAY);
        assert_eq!((mean_ic, t_stat, blocks), (0.0, 0.0, 0));
    }

    #[test]
    fn constant_score_within_every_block_is_reported_neutral() {

        let score = vec![2.5; 400];
        let (_, ret) = lead_lag_world(400);
        let (mean_ic, _, blocks) = rank_ic_block(&score, &ret, 1, WINDOW, BARS_PER_DAY);
        assert_eq!(blocks, 0);
        assert_eq!(mean_ic, 0.0);
    }
}
