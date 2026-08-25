/// Batch metrics computed from canonical PnL and score series.

/// Annualized Sharpe ratio from daily PnL series.
pub fn sharpe(daily_pnl: &[f64], _bars_per_day: usize) -> f64 {
    if daily_pnl.is_empty() {
        return 0.0;
    }
    let n = daily_pnl.len() as f64;
    let mean: f64 = daily_pnl.iter().sum::<f64>() / n;
    let var: f64 =
        daily_pnl.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1.0_f64).max(1.0);
    let std = var.sqrt();
    if std < 1e-12 {
        return 0.0;
    }
    mean / std * (250.0_f64).sqrt()
}

/// Maximum drawdown from equity curve (cumulative sum of PnL).
/// Returns the most negative drawdown as a fraction of peak.
pub fn max_drawdown(pnl_series: &[f64]) -> f64 {
    let _equity = 0.0;
    let mut peak = f64::NEG_INFINITY;
    let mut mdd = 0.0;

    // build equity curve
    let eq: Vec<f64> = {
        let mut cum = Vec::with_capacity(pnl_series.len());
        let mut acc = 0.0;
        for &p in pnl_series {
            acc += p;
            cum.push(acc);
        }
        cum
    };

    for &e in &eq {
        if e > peak {
            peak = e;
        }
        let dd = e - peak;
        if dd < mdd {
            mdd = dd;
        }
    }
    mdd
}

/// Rank Information Coefficient at a given horizon.
///
/// Computes Spearman rank correlation between score at t and
/// cumulative forward return over h bars, aggregated into blocks.
pub fn rank_ic_block(
    score: &[f64],
    ret: &[f64],
    horizon: usize,
    block_size: usize,
) -> (f64, usize) {
    let n = score.len().min(ret.len());
    if n <= horizon + 1 {
        return (0.0, 0);
    }

    // compute forward cumulative returns
    let mut fwd = vec![0.0; n];
    for t in 0..n.saturating_sub(horizon) {
        fwd[t] = (t + 1..=t + horizon)
            .map(|k| if k < ret.len() { ret[k] } else { 0.0 })
            .sum::<f64>();
    }

    // collect valid pairs (skip warmup NaN/zero regions)
    let pairs: Vec<(f64, f64)> = (horizon..n - horizon).map(|t| (score[t], fwd[t])).collect();

    if pairs.len() < block_size {
        return (0.0, 0);
    }

    // rank-transform both sides (Spearman)
    let sc_ranks = rank_vec(&pairs.iter().map(|p| p.0).collect::<Vec<_>>());
    let fw_ranks = rank_vec(&pairs.iter().map(|p| p.1).collect::<Vec<_>>());

    // Pearson correlation on ranks = Spearman
    let n_pairs = pairs.len() as f64;
    let mean_sc: f64 = sc_ranks.iter().sum::<f64>() / n_pairs;
    let mean_fw: f64 = fw_ranks.iter().sum::<f64>() / n_pairs;

    let cov: f64 = sc_ranks
        .iter()
        .zip(fw_ranks.iter())
        .map(|(a, b)| (a - mean_sc) * (b - mean_fw))
        .sum();
    let std_sc: f64 = sc_ranks
        .iter()
        .map(|a| (a - mean_sc).powi(2))
        .sum::<f64>()
        .sqrt();
    let std_fw: f64 = fw_ranks
        .iter()
        .map(|b| (b - mean_fw).powi(2))
        .sum::<f64>()
        .sqrt();

    if std_sc < 1e-12 || std_fw < 1e-12 {
        return (0.0, 0);
    }

    ((cov / (std_sc * std_fw)) as f64, pairs.len() as usize)
}

fn rank_vec(v: &[f64]) -> Vec<f64> {
    let mut indexed: Vec<(usize, &f64)> = v.iter().enumerate().collect();
    indexed.sort_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(std::cmp::Ordering::Equal));
    let mut ranks = vec![0.0; v.len()];
    for (i, (orig_idx, _)) in indexed.iter().enumerate() {
        ranks[*orig_idx] = i as f64 + 1.0;
    }
    ranks
}
