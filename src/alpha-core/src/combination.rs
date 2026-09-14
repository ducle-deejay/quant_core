pub fn composite_score(scores: &[Vec<f64>], weights: &[f64]) -> Vec<f64> {
    let n_bars = scores.first().map(|s| s.len()).unwrap_or(0);
    let mut composite = vec![0.0; n_bars];
    for (alpha, score) in scores.iter().enumerate() {
        let w = weights.get(alpha).copied().unwrap_or(0.0);
        for t in 0..n_bars {
            composite[t] += w * score.get(t).copied().unwrap_or(0.0);
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

    #[test]
    fn test_ragged_score_missing_bars_contribute_zero() {
        let s1 = vec![1.0, 2.0, 3.0];
        let s2 = vec![10.0];
        let result = composite_score(&[s1, s2], &[1.0, 1.0]);
        assert_eq!(result, vec![11.0, 2.0, 3.0]);
    }

    #[test]
    fn test_empty_scores_with_weights_returns_empty() {
        assert!(composite_score(&[], &[1.0, 2.0]).is_empty());
    }
}
