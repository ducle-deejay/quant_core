/// Batch metrics computed from canonical PnL and score series.

/// Annualized Sharpe ratio from a DAILY PnL series.
///
/// The annualization always uses `sqrt(250)`. The trailing `_bars_per_day`
/// parameter is accepted for interface symmetry with other metrics and is
/// intentionally unused.
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
/// Returns the most negative equity-curve difference (e - peak) in the same
/// units as the input PnL series (e.g. -0.25 means a quarter of initial
/// capital lost peak-to-trough when inputs are simple-return PnLs).
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

#[cfg(test)]
mod tests {
    use super::*;

    // -------------------------------------------------------------------
    // Contract tests derived from the frozen canon (stage-1 formulas),
    // ledger governance DEC-001: tests encode INTENT, never behaviour.
    // -------------------------------------------------------------------

    #[test]
    fn sharpe_known_answer_hand_computed() {
        // daily pnl [3, 1, 3, 1]: sample std = sqrt(4/3), mean = 2
        // annualised = 2 / sqrt(4/3) * sqrt(250) = sqrt(3) * sqrt(250)
        let d = [3.0, 1.0, 3.0, 1.0];
        let got = sharpe(&d, 100);
        let want = (3.0f64).sqrt() * (250.0f64).sqrt();
        assert!((got - want).abs() < 1e-9, "got {}, want {}", got, want);
    }

    #[test]
    fn sharpe_zero_for_constant_series() {
        assert_eq!(sharpe(&[2.0; 50], 100), 0.0);
        assert_eq!(sharpe(&[], 100), 0.0);
    }

    #[test]
    fn sharpe_scale_invariant_and_sign_mirror() {
        // Metamorphic: scaling daily pnl carries no Sharpe information;
        // negating mirrors it. Annualisation constant cancels either way.
        let base: Vec<f64> = (0..300).map(|t| ((t as f64) * 0.37).sin()).collect();
        let scaled: Vec<f64> = base.iter().map(|v| v * 17.0).collect();
        let mirrored: Vec<f64> = base.iter().map(|v| -v).collect();

        let s0 = sharpe(&base, 100);
        assert!((sharpe(&scaled, 100) - s0).abs() < 1e-9);
        assert!((sharpe(&mirrored, 100) + s0).abs() < 1e-9);
    }

    #[test]
    fn max_drawdown_known_answer() {
        // equity curve of [1, 1, -2] is [1, 2, 0]; worst peak-to-trough -2
        assert!((max_drawdown(&[1.0, 1.0, -2.0]) - (-2.0)).abs() < 1e-12);
    }

    #[test]
    fn max_drawdown_never_positive_and_zero_when_monotone_rising() {
        assert_eq!(max_drawdown(&[1.0, 2.0, 3.0, 4.0]), 0.0);

        let series: Vec<f64> = (0..500).map(|t| ((t as f64) * 0.11).sin() * 3.0).collect();
        assert!(max_drawdown(&series) <= 0.0);
    }

    #[test]
    fn rank_ic_perfect_monotone_relation_scores_one() {
        // score strictly increasing and forward return strictly increasing:
        // Spearman must be exactly 1 up to floating point.
        let n = 200usize;
        let score: Vec<f64> = (0..n).map(|t| t as f64).collect();
        let ret: Vec<f64> = (0..n).map(|t| 0.001 * t as f64).collect();

        let (ic, pairs) = rank_ic_block(&score, &ret, 1, 10);
        assert!(ic > 0.999, "perfect lead-lag must give IC ~ 1, got {}", ic);
        assert_eq!(pairs, n - 2, "pair window excludes both ends at horizon 1");
    }

    #[test]
    fn rank_ic_anti_monotone_relation_scores_minus_one() {
        let n = 150usize;
        let score: Vec<f64> = (0..n).map(|t| -(t as f64)).collect();
        let ret: Vec<f64> = (0..n).map(|t| 0.002 * t as f64).collect();

        let (ic, _) = rank_ic_block(&score, &ret, 2, 10);
        assert!(ic < -0.999, "anti-monotone must give IC ~ -1, got {}", ic);
    }

    #[test]
    fn rank_ic_insufficient_data_reports_zero_pairs() {
        // shorter than horizon plus one: no information, zero pairs out
        let score = vec![1.0, 2.0];
        let ret = vec![0.0, 0.1];
        assert_eq!(rank_ic_block(&score, &ret, 5, 10), (0.0, 0));
    }
}
