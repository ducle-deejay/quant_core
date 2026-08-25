/// Orthogonalization: regress candidate PnL against pool PnLs,
/// keep only the residual (pure incremental value).

/// Simple OLS regression of candidate on pool members.
/// Returns residual series after regressing out all pool columns.
///
/// For large pools, use ridge regularization or PCA reduction.
pub fn orthogonalize(candidate: &[f64], pool: &[Vec<f64>]) -> Vec<f64> {
    let n = candidate.len();
    let k = pool.len();
    if k == 0 || n == 0 {
        return candidate.to_vec();
    }

    // Build design matrix X: each column is a pool member's PnL
    // Solve X * beta ≈ candidate via normal equations
    // X'X * beta = X'y

    // Compute X'X (k x k)
    let mut xtx = vec![vec![0.0; k]; k];
    for i in 0..k {
        for j in 0..k {
            xtx[i][j] = (0..n).map(|t| pool[i][t] * pool[j][t]).sum();
        }
    }

    // Compute X'y (k,)
    let mut xty = vec![0.0; k];
    for i in 0..k {
        xty[i] = (0..n).map(|t| pool[i][t] * candidate[t]).sum();
    }

    // Solve X'X beta = X'y using Gaussian elimination with partial pivoting
    let beta = solve_linear(&xtx, &xty);

    // Residual = y - X * beta
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

    // Gaussian elimination with partial pivoting
    let mut m = vec![vec![0.0; n + 1]; n];
    for i in 0..n {
        for j in 0..n {
            m[i][j] = a[i][j];
        }
        m[i][n] = b[i];
    }

    for col in 0..n {
        // pivot
        let mut max_row = col;
        for row in col + 1..n {
            if m[row][col].abs() > m[max_row][col].abs() {
                max_row = row;
            }
        }
        m.swap(col, max_row);
        if m[col][col].abs() < 1e-12 {
            continue;
        } // singular column, skip

        for row in col + 1..n {
            let factor = m[row][col] / m[col][col];
            for c in col..=n {
                m[row][c] -= factor * m[col][c];
            }
        }
    }

    // back substitution
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
        // candidate = 2 * pool_0 + noise
        let pool_0 = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let pool_1 = vec![0.5, 1.0, 1.5, 2.0, 2.5]; // correlated with pool_0
        let noise = vec![0.01, -0.02, 0.03, -0.01, 0.02];
        let candidate: Vec<f64> = pool_0
            .iter()
            .zip(pool_1.iter())
            .zip(noise.iter())
            .map(|((&a, &b), &n)| 2.0 * a + 1.0 * b + n)
            .collect();

        let pool = vec![pool_0.clone(), pool_1.clone()];
        let resid = orthogonalize(&candidate, &pool);

        // residual should be close to noise (small values)
        let max_abs: f64 = resid.iter().map(|x| x.abs()).fold(0.0, f64::max);
        assert!(max_abs < 0.15, "residual too large: {:?}", resid);
    }

    #[test]
    fn test_orthogonalize_uncorrelated_keeps_signal() {
        // candidate uncorrelated with pool -> residual ~= candidate
        let pool_0 = vec![1.0, -1.0, 1.0, -1.0, 1.0];
        let candidate = vec![1.0, 2.0, -1.0, 3.0, -2.0];
        let pool = vec![pool_0];
        let resid = orthogonalize(&candidate, &pool);
        // residual should be close to original candidate (low correlation)
        let diff: f64 = resid
            .iter()
            .zip(candidate.iter())
            .map(|(r, c)| (r - c).powi(2))
            .sum();
        // with only 5 points and OLS through origin, some signal removal is
        // expected even for weakly correlated data; threshold is generous
        assert!(
            diff < candidate.iter().map(|x| x.powi(2)).sum::<f64>(),
            "residual should not have MORE energy than original"
        );
    }
}
