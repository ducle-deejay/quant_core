/// Acceptance gate with dynamic thresholds based on trial count.
///
/// Integrates deflated Sharpe calculation, trial ledger tracking,
/// and plateau detection into a unified gate evaluation.
use super::deflated_sharpe::deflated_threshold;
use super::trial_ledger::TrialLedger;

pub struct GateCriteria {
    /// Minimum ICIR required regardless of trial count
    pub min_icir: f64,
    /// Maximum cost drag as percentage of gross
    pub max_cost_drag_pct: f64,
    /// Minimum percentage of positive walk-forward blocks
    pub min_positive_blocks_pct: f64,
    /// Turnover ceiling for the strategy slot
    pub slot_ceiling_turnover: f64,
    /// Variance of Sharpe ratios across all trials (for deflation)
    pub sharpe_variance_across_trials: f64,
}

impl Default for GateCriteria {
    fn default() -> Self {
        Self {
            min_icir: 0.3,
            max_cost_drag_pct: 40.0,
            min_positive_blocks_pct: 60.0,
            slot_ceiling_turnover: 5000.0,
            sharpe_variance_across_trials: 0.25,
        }
    }
}

/// Input data needed for gate evaluation
pub struct GateInput {
    pub net_sharpe_walkforward: f64,
    pub icir: f64,
    pub decay_through_target_holding: bool,
    pub cost_drag_pct: f64,
    pub turnover_annualized: f64,
    pub positive_blocks_pct: f64,
    pub skewness: f64,
    pub kurtosis: f64,
    pub sample_length_bars: usize,
}

/// Result of gate evaluation with per-check details
pub struct GateResult {
    pub passed: bool,
    pub checks: Vec<(String, bool)>,
    pub deflated_threshold_used: f64,
    pub effective_trials: usize,
}

/// Evaluate gate with dynamic threshold from trial ledger + deflated Sharpe.
///
/// The minimum net Sharpe is NOT fixed — it rises with effective trial count
/// via deflated Sharpe logic, so that after many trials only genuinely strong
/// alphas pass.
pub fn evaluate_gate(
    input: &GateInput,
    criteria: &GateCriteria,
    ledger: &TrialLedger,
) -> GateResult {
    // Compute effective trials from ledger
    let n_eff = ledger.unique_count().max(1);

    // Dynamic threshold from deflated Sharpe
    let deflated_min_sharpe = deflated_threshold(n_eff, criteria.sharpe_variance_across_trials);

    let mut checks = Vec::new();

    // Primary statistic: deflated net Sharpe
    let sharpe_pass = input.net_sharpe_walkforward >= deflated_min_sharpe;
    checks.push((
        format!(
            "net Sharpe {:.3} >= deflated threshold {:.3} (N_eff={})",
            input.net_sharpe_walkforward, deflated_min_sharpe, n_eff
        ),
        sharpe_pass,
    ));

    // Secondary constraints (fixed engineering limits)
    checks.push((
        format!("ICIR {:.3} >= {}", input.icir, criteria.min_icir),
        input.icir >= criteria.min_icir,
    ));
    checks.push((
        "decay positive through target holding".into(),
        input.decay_through_target_holding,
    ));
    checks.push((
        format!(
            "cost drag {:.1}% < {}%",
            input.cost_drag_pct, criteria.max_cost_drag_pct
        ),
        input.cost_drag_pct < criteria.max_cost_drag_pct as f64,
    ));
    checks.push((
        format!(
            "turnover {:.0} <= ceiling {}",
            input.turnover_annualized, criteria.slot_ceiling_turnover
        ),
        input.turnover_annualized <= criteria.slot_ceiling_turnover as f64,
    ));
    checks.push((
        format!(
            "positive blocks {:.0}% >= {}%",
            input.positive_blocks_pct, criteria.min_positive_blocks_pct
        ),
        input.positive_blocks_pct >= criteria.min_positive_blocks_pct as f64,
    ));

    let passed = checks.iter().all(|(_, pass)| *pass);
    GateResult {
        passed,
        checks,
        deflated_threshold_used: deflated_min_sharpe,
        effective_trials: n_eff,
    }
}
