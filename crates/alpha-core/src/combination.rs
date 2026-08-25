/// Composite score computation: weighted sum of standardized scores.

/// Compute composite score from multiple alpha scores with weights.
///
/// All scores must already be standardized (z-scored) by the canonical
/// mapping in Component 1. Weights come from Stage 3 residual dossiers.
pub fn composite_score(scores: &[Vec<f64>], weights: &[f64]) -> Vec<f64> {
    let n_alphas = scores.len();
    let n_bars = scores.first().map(|s| s.len()).unwrap_or(0);
    assert_eq!(
        n_alphas,
        weights.len(),
        "scores and weights must have same length"
    );

    let mut composite = vec![0.0; n_bars];
    for (score, &w) in scores.iter().zip(weights.iter()) {
        for t in 0..n_bars {
            composite[t] += w * score[t];
        }
    }
    composite
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_composite_basic() {
        let s1 = vec![1.0, 2.0, 3.0];
        let s2 = vec![2.0, 4.0, 6.0];
        let w = [0.5, 0.5];
        let result = composite_score(&[s1, s2], &w);
        assert_eq!(result, vec![1.5, 3.0, 4.5]);
    }

    #[test]
    fn test_zero_weight_excludes_alpha() {
        let s1 = vec![1.0, 2.0];
        let s2 = vec![100.0, 200.0];
        let w = [1.0, 0.0];
        let result = composite_score(&[s1, s2], &w);
        assert_eq!(result, vec![1.0, 2.0]);
    }
}
