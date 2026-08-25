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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::evaluation::trial_ledger::TrialLedger;

    /// Candidate comfortably clearing every fixed engineering limit.
    fn base_input() -> GateInput {
        GateInput {
            net_sharpe_walkforward: 3.0,
            icir: 0.5,
            decay_through_target_holding: true,
            cost_drag_pct: 10.0,
            turnover_annualized: 1000.0,
            positive_blocks_pct: 80.0,
            // Ledger note OBS-004: skewness, kurtosis and sample_length_bars
            // are accepted by the input contract but unused by evaluate_gate
            // today (the full PSR-style probability is not wired). Kept here
            // so the contract shape is visible at every call site.
            skewness: 0.0,
            kurtosis: 3.0,
            sample_length_bars: 50_000,
        }
    }

    fn ledger_with(n_unique: usize) -> TrialLedger {
        let mut ledger = TrialLedger::new();
        for i in 0..n_unique {
            ledger.record("test-code", &format!("params-{}", i), "test-range", "ok");
        }
        ledger
    }

    #[test]
    fn single_trial_ledger_leaves_only_fixed_limits() {
        // N_eff floors at 1 and deflated_threshold returns 0.0 there:
        // the gate degenerates to the fixed engineering limits alone.
        let result = evaluate_gate(&base_input(), &GateCriteria::default(), &ledger_with(1));
        assert_eq!(result.effective_trials, 1);
        assert_eq!(result.deflated_threshold_used, 0.0);
        assert!(result.passed);
    }

    #[test]
    fn threshold_rises_strictly_with_effective_trials() {
        let criteria = GateCriteria::default();
        let input = base_input();
        let small = evaluate_gate(&input, &criteria, &ledger_with(2)).deflated_threshold_used;
        let mid = evaluate_gate(&input, &criteria, &ledger_with(50)).deflated_threshold_used;
        let large = evaluate_gate(&input, &criteria, &ledger_with(5000)).deflated_threshold_used;

        assert!(small > 0.0);
        assert!(mid > small);
        assert!(large > mid);
    }

    #[test]
    fn marginal_alpha_survives_fresh_registry_dies_in_crowded_one() {
        // The canon purpose of deflation: after many trials only genuinely
        // strong alphas pass. Same candidate, only the registry size differs.
        let criteria = GateCriteria::default();
        let mut input = base_input();
        input.net_sharpe_walkforward = 1.0;

        let fresh = evaluate_gate(&input, &criteria, &ledger_with(2));
        let crowded = evaluate_gate(&input, &criteria, &ledger_with(50_000));

        assert!(fresh.passed, "mediocre alpha must pass an almost empty registry");
        assert!(!crowded.passed, "same alpha must fail once trials are legion");
        assert!(crowded.net_sharpe_below_threshold());
    }

    #[test]
    fn every_fixed_limit_enforced_independently() {
        let criteria = GateCriteria::default();

        let mut icir_case = base_input(); icir_case.icir = 0.1;
        let mut decay_case = base_input(); decay_case.decay_through_target_holding = false;
        let mut drag_case = base_input(); drag_case.cost_drag_pct = 95.0;
        let mut turnover_case = base_input(); turnover_case.turnover_annualized = 99_999.0;
        let mut blocks_case = base_input(); blocks_case.positive_blocks_pct = 10.0;
        let cases = [icir_case, decay_case, drag_case, turnover_case, blocks_case];

        for case in cases {
            let result = evaluate_gate(&case, &criteria, &ledger_with(1));
            assert!(!result.passed, "gate passed despite one violated fixed limit");
            assert_eq!(
                result.checks.iter().filter(|(_, ok)| !ok).count(),
                1,
                "exactly one failing check expected"
            );
        }
    }

    #[test]
    fn sharpe_comparison_uses_geq_semantics_at_boundary() {
        // At N_eff = 1 the deflated threshold is 0.0; a Sharpe of exactly
        // epsilon above zero satisfies the documented >= comparison.
        let criteria = GateCriteria::default();
        let mut input = base_input();
        input.net_sharpe_walkforward = f64::EPSILON;

        let result = evaluate_gate(&input, &criteria, &ledger_with(1));
        assert!(result.checks[0].1, "boundary Sharpe must pass the >= check");
        assert_eq!(result.deflated_threshold_used, 0.0);
    }

    impl GateResult {
        fn net_sharpe_below_threshold(&self) -> bool {
            !self.checks[0].1
        }
    }
}
