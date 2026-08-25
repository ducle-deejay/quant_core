/// IC ladder: Rank IC computed at multiple horizons with block t-statistic.
#[derive(Debug, Clone)]
pub struct IcResult {
    pub horizon: usize,
    pub mean_ic: f64,
    pub t_stat: f64,
}

/// Compute rolling Rank IC at a given horizon, grouped into daily blocks.
///
/// Returns (mean of block means, t-statistic of block means).
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

    // forward cumulative return
    let mut fwd = vec![f64::NAN; n];
    for t in 0..n.saturating_sub(horizon) {
        fwd[t] = (1..=horizon)
            .filter(|&k| t + k < ret.len())
            .map(|k| if k + 1 < ret.len() { ret[t + k] } else { 0.0 })
            .sum::<f64>();
    }

    // rolling correlation in blocks
    let mut block_ics = Vec::new();
    let mut start = window; // skip warmup
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

        if pairs.len() > 5 {
            let np = pairs.len() as f64;
            let ms: f64 = pairs.iter().map(|p| p.0).sum::<f64>() / np;
            let mf: f64 = pairs.iter().map(|p| p.1).sum::<f64>() / np;
            let cov: f64 = pairs.iter().map(|p| (p.0 - ms) * (p.1 - mf)).sum::<f64>();
            let ss: f64 = pairs.iter().map(|p| (p.0 - ms).powi(2)).sum::<f64>().sqrt();
            let sf: f64 = pairs.iter().map(|p| (p.1 - mf).powi(2)).sum::<f64>().sqrt();
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

/// Compute the full IC ladder across multiple horizons.
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
