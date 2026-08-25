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
