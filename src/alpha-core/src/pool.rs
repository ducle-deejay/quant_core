#[derive(Clone, Debug)]
pub struct PoolAlpha {
    pub name: String,
    pub score_series: Vec<f64>,
    pub daily_net_pnl: Vec<f64>,
    pub daily_gross_pnl: Vec<f64>,
    pub turnover_annualized: f64,
    pub cost_drag_pct: f64,
    pub icir: f64,
    pub net_sharpe: f64,
    pub spec_sheet: SpecSheet,
}

#[derive(Clone, Debug)]
pub struct SpecSheet {
    pub expected_holding_period_bars: usize,
    pub expected_net_sharpe: f64,

    pub kill_criteria_ic_threshold: f64,

    pub kill_criteria_consecutive_blocks: usize,
}

#[derive(Debug)]
pub struct AlphaPool {
    members: Vec<PoolAlpha>,
    max_size: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub enum AdmissionError {
    PoolFull(usize),
    DuplicateName(String),
    InsufficientIncrementalValue { residual_sharpe: f64 },
}

impl AlphaPool {

    pub fn new(max_size: usize) -> Self {
        Self {
            members: Vec::new(),
            max_size,
        }
    }

    pub fn try_admit(&mut self, candidate: &PoolAlpha) -> Result<(), AdmissionError> {
        if self
            .members
            .iter()
            .any(|member| member.name == candidate.name)
        {
            return Err(AdmissionError::DuplicateName(candidate.name.clone()));
        }
        if self.max_size == 0 {
            return Err(AdmissionError::PoolFull(self.max_size));
        }

        if self.members.is_empty() {
            self.members.push(candidate.clone());
            return Ok(());
        }

        let residual_sharpe = self.residual_sharpe(candidate);
        if residual_sharpe <= candidate.spec_sheet.expected_net_sharpe {
            return Err(AdmissionError::InsufficientIncrementalValue { residual_sharpe });
        }

        if self.members.len() < self.max_size {
            self.members.push(candidate.clone());
            return Ok(());
        }

        let worst_index = self
            .members
            .iter()
            .enumerate()
            .min_by(|(_, left), (_, right)| {
                left.net_sharpe
                    .partial_cmp(&right.net_sharpe)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|(index, _)| index)
            .expect("a full pool contains at least one member");

        if candidate.net_sharpe > self.members[worst_index].net_sharpe {
            self.members[worst_index] = candidate.clone();
            Ok(())
        } else {

            Err(AdmissionError::InsufficientIncrementalValue { residual_sharpe })
        }
    }

    pub fn retire(&mut self, name: &str) -> bool {
        let Some(index) = self.members.iter().position(|member| member.name == name) else {
            return false;
        };
        self.members.remove(index);
        true
    }

    pub fn composite_scores(&self) -> Option<Vec<f64>> {
        let n_bars = self
            .members
            .iter()
            .map(|member| member.score_series.len())
            .min()?;
        let weight = 1.0 / self.members.len() as f64;
        let mut composite = vec![0.0; n_bars];
        for member in &self.members {
            for (value, score) in composite.iter_mut().zip(member.score_series.iter()) {
                *value += score * weight;
            }
        }
        Some(composite)
    }

    pub fn member_names(&self) -> Vec<String> {
        self.members
            .iter()
            .map(|member| member.name.clone())
            .collect()
    }

    pub fn check_kill_criteria(&self, recent_returns: &[f64]) -> Vec<String> {
        self.members
            .iter()
            .filter(|member| should_retire(member, recent_returns))
            .map(|member| member.name.clone())
            .collect()
    }

    fn residual_sharpe(&self, candidate: &PoolAlpha) -> f64 {
        let n = self
            .members
            .iter()
            .map(|member| member.daily_net_pnl.len())
            .chain(std::iter::once(candidate.daily_net_pnl.len()))
            .min()
            .unwrap_or(0);
        if n == 0 {
            return 0.0;
        }

        let candidate_pnl = &candidate.daily_net_pnl[..n];
        let member_pnls: Vec<Vec<f64>> = self
            .members
            .iter()
            .map(|member| member.daily_net_pnl[..n].to_vec())
            .collect();
        let residual = crate::orthogonalization::orthogonalize(candidate_pnl, &member_pnls);
        crate::canonical::metrics::sharpe(&residual, 1)
    }
}

fn should_retire(member: &PoolAlpha, recent_returns: &[f64]) -> bool {
    let required_blocks = member.spec_sheet.kill_criteria_consecutive_blocks;
    if required_blocks == 0 {
        return false;
    }

    let n = member.score_series.len().min(recent_returns.len());
    let block_size = member.spec_sheet.expected_holding_period_bars;
    if block_size < 2 || n < block_size {
        return false;
    }

    let mut trailing_breaches = 0;
    let mut end = n / block_size * block_size;
    while end >= block_size {
        let start = end - block_size;
        let ic = rank_correlation(
            &member.score_series[start..end],
            &recent_returns[start..end],
        );
        if ic < member.spec_sheet.kill_criteria_ic_threshold {
            trailing_breaches += 1;
            if trailing_breaches >= required_blocks {
                return true;
            }
        } else {
            break;
        }
        end -= block_size;
    }
    false
}

fn rank_correlation(left: &[f64], right: &[f64]) -> f64 {
    let n = left.len().min(right.len());
    if n < 2 {
        return 0.0;
    }
    let left_ranks = ranks(&left[..n]);
    let right_ranks = ranks(&right[..n]);
    let mean = (n as f64 + 1.0) / 2.0;
    let numerator: f64 = left_ranks
        .iter()
        .zip(right_ranks.iter())
        .map(|(l, r)| (l - mean) * (r - mean))
        .sum();
    let left_energy: f64 = left_ranks.iter().map(|rank| (rank - mean).powi(2)).sum();
    let right_energy: f64 = right_ranks.iter().map(|rank| (rank - mean).powi(2)).sum();
    if left_energy < 1e-12 || right_energy < 1e-12 {
        0.0
    } else {
        numerator / (left_energy * right_energy).sqrt()
    }
}

fn ranks(values: &[f64]) -> Vec<f64> {
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|&left, &right| {
        values[left]
            .partial_cmp(&values[right])
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut result = vec![0.0; values.len()];
    for (rank, index) in order.into_iter().enumerate() {
        result[index] = rank as f64 + 1.0;
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn alpha(name: &str, scores: Vec<f64>, pnl: Vec<f64>, net_sharpe: f64) -> PoolAlpha {
        PoolAlpha {
            name: name.to_string(),
            score_series: scores,
            daily_net_pnl: pnl.clone(),
            daily_gross_pnl: pnl,
            turnover_annualized: 1.0,
            cost_drag_pct: 0.0,
            icir: 1.0,
            net_sharpe,
            spec_sheet: SpecSheet {
                expected_holding_period_bars: 3,
                expected_net_sharpe: 0.1,
                kill_criteria_ic_threshold: 0.0,
                kill_criteria_consecutive_blocks: 2,
            },
        }
    }

    #[test]
    fn admits_first_alpha_into_empty_pool() {
        let mut pool = AlphaPool::new(2);
        let first = alpha("first", vec![1.0, 2.0], vec![1.0, -1.0], 0.0);
        assert!(pool.try_admit(&first).is_ok());
        assert_eq!(pool.member_names(), vec!["first"]);
    }

    #[test]
    fn rejects_correlated_alpha_without_incremental_value() {
        let mut pool = AlphaPool::new(2);
        let first = alpha("first", vec![1.0; 5], vec![1.0, -1.0, 2.0, -2.0, 1.0], 1.0);
        let correlated = alpha("copy", vec![2.0; 5], first.daily_net_pnl.clone(), 2.0);
        pool.try_admit(&first).unwrap();
        assert!(matches!(
            pool.try_admit(&correlated),
            Err(AdmissionError::InsufficientIncrementalValue { .. })
        ));
    }

    #[test]
    fn admits_uncorrelated_alpha_with_members_present() {
        let mut pool = AlphaPool::new(2);
        let first = alpha("first", vec![1.0; 5], vec![1.0, -1.0, 1.0, -1.0, 1.0], 1.0);
        let independent = alpha(
            "independent",
            vec![2.0; 5],
            vec![1.0, 2.0, -1.0, 3.0, -2.0],
            2.0,
        );
        pool.try_admit(&first).unwrap();
        assert!(pool.try_admit(&independent).is_ok());
        assert_eq!(pool.member_names().len(), 2);
    }

    #[test]
    fn full_pool_replaces_worst_member_for_better_candidate() {
        let mut pool = AlphaPool::new(2);
        let first = alpha("worst", vec![1.0; 5], vec![1.0, -1.0, 1.0, -1.0, 1.0], 0.5);
        let second = alpha("best", vec![1.0; 5], vec![1.0, 2.0, -1.0, 3.0, -2.0], 2.0);
        let candidate = alpha(
            "replacement",
            vec![1.0; 5],
            vec![2.0, -1.0, 3.0, -2.0, 1.0],
            1.0,
        );
        pool.try_admit(&first).unwrap();
        pool.try_admit(&second).unwrap();
        pool.try_admit(&candidate).unwrap();
        assert_eq!(pool.member_names(), vec!["replacement", "best"]);
    }

    #[test]
    fn retires_member_by_name() {
        let mut pool = AlphaPool::new(2);
        let first = alpha("first", vec![1.0], vec![1.0], 1.0);
        pool.try_admit(&first).unwrap();
        assert!(pool.retire("first"));
        assert!(!pool.retire("first"));
        assert!(pool.member_names().is_empty());
    }

    #[test]
    fn flags_degrading_ic_for_retirement() {
        let mut pool = AlphaPool::new(1);
        let degrading = alpha(
            "degrading",
            vec![1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
            vec![1.0, -1.0, 1.0],
            1.0,
        );
        pool.try_admit(&degrading).unwrap();
        let returns = vec![3.0, 2.0, 1.0, 3.0, 2.0, 1.0];
        assert_eq!(pool.check_kill_criteria(&returns), vec!["degrading"]);
    }

    #[test]
    fn computes_equal_weight_composite_scores() {
        let mut pool = AlphaPool::new(2);
        let first = alpha("first", vec![1.0, 2.0, 3.0], vec![1.0, -1.0, 1.0], 1.0);
        let second = alpha("second", vec![3.0, 4.0, 5.0], vec![1.0, 2.0, -1.0], 2.0);
        pool.try_admit(&first).unwrap();
        pool.try_admit(&second).unwrap();
        assert_eq!(pool.composite_scores(), Some(vec![2.0, 3.0, 4.0]));
    }
}
