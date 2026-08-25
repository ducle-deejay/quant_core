/// Walk-forward validation: slice PnL into rolling blocks and compute
/// stability metrics per block.
pub struct WalkForwardResult {
    pub positive_pct: f64,
    pub worst_block_sharpe: f64,
    pub blocks: Vec<BlockStats>,
}

pub struct BlockStats {
    pub sharpe: f64,
    pub total_pnl: f64,
}

pub fn walk_forward(daily_pnl: &[f64], block_days: usize, ann_factor: f64) -> WalkForwardResult {
    let n_blocks = daily_pnl.len() / block_days.max(1);
    if n_blocks == 0 {
        return WalkForwardResult {
            positive_pct: 0.0,
            worst_block_sharpe: 0.0,
            blocks: vec![],
        };
    }

    let mut stats = Vec::with_capacity(n_blocks);
    for b in 0..n_blocks {
        let chunk = &daily_pnl[b * block_days..((b + 1) * block_days).min(daily_pnl.len())];
        let total: f64 = chunk.iter().sum();
        let mean = total / chunk.len() as f64;
        let var = chunk.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / chunk.len().max(2) as f64;
        let std = var.sqrt();
        let sharpe = if std > 1e-12 {
            mean / std * ann_factor.sqrt()
        } else {
            0.0
        };
        stats.push(BlockStats {
            sharpe,
            total_pnl: total,
        });
    }

    let positive = stats.iter().filter(|s| s.total_pnl > 0.0).count();
    let pct = positive as f64 / stats.len() as f64 * 100.0;
    let worst = stats.iter().map(|s| s.sharpe).fold(f64::INFINITY, f64::min);

    WalkForwardResult {
        positive_pct: pct,
        worst_block_sharpe: worst,
        blocks: stats,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Contract tests derived from the frozen canon intent for walk-forward
    // validation: slice into consecutive blocks, report stability as the
    // share of profitable blocks plus the worst block Sharpe. Ledger M4.

    const ANN: f64 = 4.0;

    #[test]
    fn hand_computed_two_block_known_answer() {
        // blocks [2, 0] and [-2, 0]: means +-1, std 1, sharpe +-sqrt(ANN)
        let res = walk_forward(&[2.0, 0.0, -2.0, 0.0], 2, ANN);

        assert_eq!(res.blocks.len(), 2);
        assert_eq!(res.blocks[0].total_pnl, 2.0);
        assert_eq!(res.blocks[1].total_pnl, -2.0);
        assert!((res.blocks[0].sharpe - ANN.sqrt()).abs() < 1e-12);
        assert!((res.blocks[1].sharpe + ANN.sqrt()).abs() < 1e-12);
        assert!((res.positive_pct - 50.0).abs() < 1e-9);
        assert!((res.worst_block_sharpe + ANN.sqrt()).abs() < 1e-12);
    }

    #[test]
    fn stationary_positive_edge_reports_all_blocks_profitable() {
        // drift 1.0 dominates the bounded sinusoid, so every block earns
        let pnl: Vec<f64> = (0..400)
            .map(|t| 1.0 + 0.5 * ((t as f64) * 0.13).sin())
            .collect();
        let res = walk_forward(&pnl, 20, ANN);

        assert_eq!(res.blocks.len(), 20);
        assert!((res.positive_pct - 100.0).abs() < 1e-9);
        assert!(res.worst_block_sharpe > 0.0);
    }

    #[test]
    fn regime_shift_is_detected_as_collapsing_stability() {
        // The whole point of walk-forward: a strategy that worked and then
        // broke must NOT look stable overall. Alternating day shapes give
        // each block real variance so its Sharpe carries a true sign.
        let mut pnl: Vec<f64> = (0..200)
            .map(|t| if t % 2 == 0 { 1.0 } else { 0.6 })
            .collect(); // profitable regime
        pnl.extend((0..200).map(|t| if t % 2 == 0 { -0.6 } else { -1.0 })); // broken

        let res = walk_forward(&pnl, 25, ANN);

        assert_eq!(res.blocks.len(), 16);
        assert!((res.positive_pct - 50.0).abs() < 1e-9);
        assert!(res.worst_block_sharpe < 0.0, "dead regime must poison worst block");
    }

    #[test]
    fn trailing_remainder_days_are_excluded_not_partial_blocks() {
        // 10 days at block size 3 => three full blocks only; day 10 dropped
        let pnl = vec![1.0; 10];
        let res = walk_forward(&pnl, 3, ANN);
        assert_eq!(res.blocks.len(), 3);
        assert!((res.positive_pct - 100.0).abs() < 1e-9);
    }

    #[test]
    fn insufficient_input_returns_neutral_empty_result() {
        let res = walk_forward(&[1.0, -1.0], 5, ANN);
        assert_eq!(res.blocks.len(), 0);
        assert_eq!(res.positive_pct, 0.0);
        assert_eq!(res.worst_block_sharpe, 0.0);
    }

    #[test]
    fn zero_variance_block_scores_zero_not_infinity() {
        // perfectly constant losing days: undefined Sharpe reported as 0,
        // profitability still drives the verdict
        let res = walk_forward(&[-1.0; 8], 4, ANN);
        assert_eq!(res.blocks[0].sharpe, 0.0);
        assert_eq!(res.positive_pct, 0.0);
        assert_eq!(res.worst_block_sharpe, 0.0);
    }
}
