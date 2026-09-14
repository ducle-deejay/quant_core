#[cfg(test)]
mod orthogonal_contract_tests {
    use super::orthogonalize;

    #[test]
    fn residual_is_orthogonal_to_every_pool_column() {
        let n = 300usize;
        let candidate: Vec<f64> = (0..n).map(|t| ((t as f64) * 0.31).sin() * 2.0).collect();
        let pool: Vec<Vec<f64>> = vec![
            (0..n).map(|t| ((t as f64) * 0.17).cos()).collect(),
            (0..n).map(|t| ((t as f64) * 0.05).sin()).collect(),
            (0..n).map(|t| if t % 7 == 0 { 1.0 } else { -0.5 }).collect(),
        ];

        let residual = orthogonalize(&candidate, &pool);

        for (k, column) in pool.iter().enumerate() {
            let dot: f64 = residual.iter().zip(column.iter()).map(|(r, x)| r * x).sum();
            assert!(
                dot.abs() < 1e-6,
                "residual correlates with pool column {}: dot = {:.2e}",
                k, dot
            );
        }
    }

    #[test]
    fn candidate_inside_pool_span_is_fully_absorbed() {

        let n = 200usize;
        let x1: Vec<f64> = (0..n).map(|t| ((t as f64) * 0.23).sin()).collect();
        let x2: Vec<f64> = (0..n).map(|t| ((t as f64) * 0.11).cos()).collect();
        let candidate: Vec<f64> = x1.iter().zip(x2.iter()).map(|(a, b)| a + 2.0 * b).collect();

        let residual = orthogonalize(&candidate, &[x1, x2]);

        let energy: f64 = residual.iter().map(|r| r * r).sum();
        assert!(energy < 1e-12, "in-span candidate must vanish, energy {:.2e}", energy);
    }

    #[test]
    fn exactly_anticorrelated_candidate_passes_through() {

        let n = 200usize;
        let regressor: Vec<f64> = (0..n)
            .map(|t| if t % 2 == 0 { 1.0 } else { -1.5 })
            .collect();
        let candidate: Vec<f64> = regressor.iter().map(|x| -1.7 * x).collect();

        let residual = orthogonalize(&candidate, &[regressor]);

        let energy: f64 = residual.iter().map(|r| r * r).sum();
        assert!(energy < 1e-18, "perfectly explained candidate must vanish");
    }

    #[test]
    fn empty_pool_returns_candidate_verbatim() {
        let candidate = vec![1.5, -2.0, 0.25];
        assert_eq!(orthogonalize(&candidate, &[]), candidate);
    }

    #[test]
    fn shorter_pool_column_uses_common_prefix_and_preserves_tail() {
        let candidate = vec![1.0, 2.0, 3.0, 4.0];
        let pool = vec![vec![0.5, 1.0, 1.5]];
        let residual = orthogonalize(&candidate, &pool);

        assert_eq!(residual.len(), candidate.len());
        assert!(residual[..3].iter().all(|value| value.is_finite()));
        assert_eq!(&residual[3..], &candidate[3..]);
    }
}

pub fn orthogonalize(candidate: &[f64], pool: &[Vec<f64>]) -> Vec<f64> {
    let k = pool.len();
    let n = candidate.len().min(pool.iter().map(Vec::len).min().unwrap_or(0));
    if k == 0 || n == 0 {
        return candidate.to_vec();
    }

    let mut xtx = vec![vec![0.0; k]; k];
    for i in 0..k {
        for j in 0..k {
            xtx[i][j] = (0..n).map(|t| pool[i][t] * pool[j][t]).sum();
        }
    }

    let mut xty = vec![0.0; k];
    for i in 0..k {
        xty[i] = (0..n).map(|t| pool[i][t] * candidate[t]).sum();
    }

    let beta = solve_linear(&xtx, &xty);

    let mut residual = candidate.to_vec();
    for t in 0..n {
        let predicted: f64 = (0..k).map(|i| beta[i] * pool[i][t]).sum();
        residual[t] = candidate[t] - predicted;
    }
    residual
}

fn solve_linear(a: &[Vec<f64>], b: &[f64]) -> Vec<f64> {
    let n = b.len();
    if n == 0 {
        return vec![];
    }

    let mut m = vec![vec![0.0; n + 1]; n];
    for i in 0..n {
        for j in 0..n {
            m[i][j] = a[i][j];
        }
        m[i][n] = b[i];
    }

    for col in 0..n {

        let mut max_row = col;
        for row in col + 1..n {
            if m[row][col].abs() > m[max_row][col].abs() {
                max_row = row;
            }
        }
        m.swap(col, max_row);
        if m[col][col].abs() < 1e-12 {
            continue;
        }

        for row in col + 1..n {
            let factor = m[row][col] / m[col][col];
            for c in col..=n {
                m[row][c] -= factor * m[col][c];
            }
        }
    }

    let mut x = vec![0.0; n];
    for i in (0..n).rev() {
        let mut sum = m[i][n];
        for j in i + 1..n {
            sum -= m[i][j] * x[j];
        }
        if m[i][i].abs() > 1e-12 {
            x[i] = sum / m[i][i];
        }
    }
    x
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_orthogonalize_removes_explained_part() {

        let pool_0 = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let pool_1 = vec![0.5, 1.0, 1.5, 2.0, 2.5];
        let noise = vec![0.01, -0.02, 0.03, -0.01, 0.02];
        let candidate: Vec<f64> = pool_0
            .iter()
            .zip(pool_1.iter())
            .zip(noise.iter())
            .map(|((&a, &b), &n)| 2.0 * a + 1.0 * b + n)
            .collect();

        let pool = vec![pool_0.clone(), pool_1.clone()];
        let resid = orthogonalize(&candidate, &pool);

        let max_abs: f64 = resid.iter().map(|x| x.abs()).fold(0.0, f64::max);
        assert!(max_abs < 0.15, "residual too large: {:?}", resid);
    }

    #[test]
    fn test_orthogonalize_uncorrelated_keeps_signal() {

        let pool_0 = vec![1.0, -1.0, 1.0, -1.0, 1.0];
        let candidate = vec![1.0, 2.0, -1.0, 3.0, -2.0];
        let pool = vec![pool_0];
        let resid = orthogonalize(&candidate, &pool);

        let diff: f64 = resid
            .iter()
            .zip(candidate.iter())
            .map(|(r, c)| (r - c).powi(2))
            .sum();

        assert!(
            diff < candidate.iter().map(|x| x.powi(2)).sum::<f64>(),
            "residual should not have MORE energy than original"
        );
    }
}
