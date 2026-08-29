//! Screening funnel: gate candidates by Information Coefficient and cost
//! drag, then rank survivors.
//!
//! Kept as pure functions over plain metric slices so the report layer can
//! never silently diverge from the gate definitions: binaries render tables
//! from these results instead of re-implementing filtering inline. This
//! closes the bug class where a ranking table was built from all candidates
//! while the funnel counted only survivors.

/// Gate thresholds applied during screening.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ScreeningThresholds {
    /// A candidate passes the Information Coefficient gate when |IC| exceeds it.
    pub min_abs_ic: f64,
    /// A candidate passes the cost gate when its cost drag stays below this
    /// percentage of gross PnL.
    pub max_cost_drag_pct: f64,
}

impl Default for ScreeningThresholds {
    fn default() -> Self {
        Self {
            min_abs_ic: 0.02,
            max_cost_drag_pct: 40.0,
        }
    }
}

/// Counts reported in the screening funnel table.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ScreeningFunnel {
    pub total_candidates: usize,
    pub ic_pass_count: usize,
    pub drag_pass_count: usize,
    /// Candidates that passed BOTH gates.
    pub survivor_count: usize,
}

/// Apply both gates to parallel metric vectors.
///
/// Returns the funnel counts plus the unsorted survivor index set (the only
/// lawful input to [`rank_survivors`]). Panics when the input vectors differ
/// in length: a silent partial screen would corrupt the funnel counts.
pub fn screen_candidates(
    ic_values: &[f64],
    cost_drag_pcts: &[f64],
    thresholds: &ScreeningThresholds,
) -> (ScreeningFunnel, Vec<usize>) {
    assert_eq!(
        ic_values.len(),
        cost_drag_pcts.len(),
        "screening requires one cost-drag value per Information Coefficient"
    );

    let mut survivors = Vec::new();
    let mut ic_pass_count = 0usize;
    let mut drag_pass_count = 0usize;

    for (i, (&ic, &drag)) in ic_values.iter().zip(cost_drag_pcts.iter()).enumerate() {
        let ic_pass = ic.abs() > thresholds.min_abs_ic;
        let drag_pass = drag < thresholds.max_cost_drag_pct;
        if ic_pass { ic_pass_count += 1; }
        if drag_pass { drag_pass_count += 1; }
        if ic_pass && drag_pass {
            survivors.push(i);
        }
    }

    let funnel = ScreeningFunnel {
        total_candidates: ic_values.len(),
        ic_pass_count,
        drag_pass_count,
        survivor_count: survivors.len(),
    };
    (funnel, survivors)
}

/// Rank survivor indices by a score (Net Sharpe) in descending order.
///
/// Ties break by lower index for deterministic output. The caller must pass
/// indices produced by [`screen_candidates`]; ranking an arbitrary pool
/// would resurrect the divergent-report bug class this module exists to
/// prevent.
pub fn rank_survivors(
    survivor_indices: &[usize],
    ranking_scores: &[f64],
) -> Vec<usize> {
    let mut ranked = survivor_indices.to_vec();
    ranked.sort_by(|&a, &b| {
        ranking_scores[b]
            .partial_cmp(&ranking_scores[a])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(&b))
    });
    ranked
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn funnel_counts_each_gate_and_both_gates() {
        // ICs:      0.05, -0.03, 0.01, 0.005, -0.10
        // drags %:  10.0,  50.0,  5.0,  60.0,  20.0
        let ics = [0.05, -0.03, 0.01, 0.005, -0.10];
        let drags = [10.0, 50.0, 5.0, 60.0, 20.0];
        let (funnel, survivors) =
            screen_candidates(&ics, &drags, &ScreeningThresholds::default());

        assert_eq!(funnel.total_candidates, 5);
        assert_eq!(funnel.ic_pass_count, 3); // 0.05, -0.03, -0.10
        assert_eq!(funnel.drag_pass_count, 3); // 10.0, 5.0, 20.0
        assert_eq!(funnel.survivor_count, 2); // #0 and #4 pass both
        assert_eq!(survivors, vec![0, 4]);
    }

    #[test]
    fn ranking_pool_is_subset_of_survivors_and_ordered() {
        // The exact regression guard for the divergent-report bug: a
        // high-Sharpe candidate that failed a gate must never appear here.
        let ics = [0.05, 0.001, -0.06];
        let drags = [90.0, 10.0, 20.0];
        let sharpes = [9.99, 5.00, 1.00];
        let (_, survivors) =
            screen_candidates(&ics, &drags, &ScreeningThresholds::default());

        let ranked = rank_survivors(&survivors, &sharpes);
        assert_eq!(ranked, vec![2], "gate-failing candidate must be excluded");
    }

    #[test]
    fn ties_break_by_lower_index_deterministically() {
        let (_, survivors) =
            screen_candidates(&[0.05, 0.05], &[1.0, 1.0], &ScreeningThresholds::default());
        let ranked = rank_survivors(&survivors, &[1.5, 1.5]);
        assert_eq!(ranked, vec![0, 1]);
    }

    #[test]
    #[should_panic(expected = "one cost-drag value per")]
    fn mismatched_metric_vectors_are_rejected() {
        let _ = screen_candidates(&[0.05, 0.01], &[10.0], &ScreeningThresholds::default());
    }
}
