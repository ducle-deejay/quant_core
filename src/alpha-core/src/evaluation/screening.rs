#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ScreeningThresholds {

    pub min_abs_ic: f64,

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

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ScreeningFunnel {
    pub total_candidates: usize,
    pub ic_pass_count: usize,
    pub drag_pass_count: usize,

    pub survivor_count: usize,
}

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

        let ics = [0.05, -0.03, 0.01, 0.005, -0.10];
        let drags = [10.0, 50.0, 5.0, 60.0, 20.0];
        let (funnel, survivors) =
            screen_candidates(&ics, &drags, &ScreeningThresholds::default());

        assert_eq!(funnel.total_candidates, 5);
        assert_eq!(funnel.ic_pass_count, 3);
        assert_eq!(funnel.drag_pass_count, 3);
        assert_eq!(funnel.survivor_count, 2);
        assert_eq!(survivors, vec![0, 4]);
    }

    #[test]
    fn ranking_pool_is_subset_of_survivors_and_ordered() {
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
