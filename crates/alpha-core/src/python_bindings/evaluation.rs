//! Python bindings for Component 2 evaluation metrics.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{ensure_all_finite, ensure_positive_usize};
use crate::evaluation::deflated_sharpe::{deflated_sharpe_probability, deflated_threshold};
use crate::evaluation::ic_ladder::ic_ladder;
use crate::evaluation::screening::{rank_survivors, screen_candidates, ScreeningThresholds};
use crate::evaluation::walk_forward::walk_forward;

/// One horizon's rank Information Coefficient result.
#[pyclass]
pub struct PyIcResult {
    #[pyo3(get)]
    pub horizon: usize,
    #[pyo3(get)]
    pub mean_ic: f64,
    #[pyo3(get)]
    pub t_stat: f64,
}

/// Walk-forward statistics for one block.
#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct PyBlockStats {
    #[pyo3(get)]
    pub sharpe: f64,
    #[pyo3(get)]
    pub total_pnl: f64,
}

/// Aggregate walk-forward validation result.
#[pyclass]
pub struct PyWalkForwardResult {
    #[pyo3(get)]
    pub positive_pct: f64,
    #[pyo3(get)]
    pub worst_block_sharpe: f64,
    #[pyo3(get)]
    pub blocks: Vec<PyBlockStats>,
}

/// Screening funnel counts and the indices passing both gates.
#[pyclass]
pub struct PyScreeningOutcome {
    #[pyo3(get)]
    pub total_candidates: usize,
    #[pyo3(get)]
    pub ic_pass_count: usize,
    #[pyo3(get)]
    pub drag_pass_count: usize,
    #[pyo3(get)]
    pub survivor_count: usize,
    #[pyo3(get)]
    pub survivor_indices: Vec<usize>,
}

/// Compute rank Information Coefficient at each requested horizon.
#[pyfunction]
fn ic_ladder_py(
    py: Python<'_>,
    score: Vec<f64>,
    ret: Vec<f64>,
    horizons: Vec<usize>,
    window: usize,
    bars_per_day: usize,
) -> PyResult<Vec<PyIcResult>> {
    ensure_all_finite("score", &score)?;
    ensure_all_finite("ret", &ret)?;
    if score.len() != ret.len() {
        return Err(PyValueError::new_err(format!(
            "`score` and `ret` must have equal length (got {} and {})",
            score.len(),
            ret.len()
        )));
    }
    ensure_positive_usize("bars_per_day", bars_per_day)?;
    let results = py.detach(|| ic_ladder(&score, &ret, &horizons, window, bars_per_day));
    Ok(results
        .into_iter()
        .map(|result| PyIcResult {
            horizon: result.horizon,
            mean_ic: result.mean_ic,
            t_stat: result.t_stat,
        })
        .collect())
}

/// Validate daily PnL in consecutive blocks and report stability statistics.
#[pyfunction]
fn walk_forward_py(
    py: Python<'_>,
    daily_pnl: Vec<f64>,
    block_days: usize,
    ann_factor: f64,
) -> PyResult<PyWalkForwardResult> {
    ensure_all_finite("daily_pnl", &daily_pnl)?;
    let result = py.detach(|| walk_forward(&daily_pnl, block_days, ann_factor));
    Ok(PyWalkForwardResult {
        positive_pct: result.positive_pct,
        worst_block_sharpe: result.worst_block_sharpe,
        blocks: result
            .blocks
            .into_iter()
            .map(|block| PyBlockStats {
                sharpe: block.sharpe,
                total_pnl: block.total_pnl,
            })
            .collect(),
    })
}

/// Apply Information Coefficient and cost-drag screening gates.
#[pyfunction]
#[pyo3(signature = (ic_values, cost_drag_pcts, min_abs_ic=0.02, max_cost_drag_pct=40.0))]
fn screen_candidates_py(
    py: Python<'_>,
    ic_values: Vec<f64>,
    cost_drag_pcts: Vec<f64>,
    min_abs_ic: f64,
    max_cost_drag_pct: f64,
) -> PyResult<PyScreeningOutcome> {
    if ic_values.len() != cost_drag_pcts.len() {
        return Err(PyValueError::new_err(format!(
            "`ic_values` and `cost_drag_pcts` must have equal length (got {} and {})",
            ic_values.len(),
            cost_drag_pcts.len()
        )));
    }
    let thresholds = ScreeningThresholds {
        min_abs_ic,
        max_cost_drag_pct,
    };
    let (funnel, survivors) = py.detach(|| screen_candidates(&ic_values, &cost_drag_pcts, &thresholds));
    Ok(PyScreeningOutcome {
        total_candidates: funnel.total_candidates,
        ic_pass_count: funnel.ic_pass_count,
        drag_pass_count: funnel.drag_pass_count,
        survivor_count: funnel.survivor_count,
        survivor_indices: survivors,
    })
}

/// Rank survivor indices by descending ranking score.
#[pyfunction]
fn rank_survivors_py(
    py: Python<'_>,
    survivor_indices: Vec<usize>,
    ranking_scores: Vec<f64>,
) -> PyResult<Vec<usize>> {
    if survivor_indices.iter().any(|&index| index >= ranking_scores.len()) {
        return Err(PyValueError::new_err(
            "`survivor_indices` contains an index outside `ranking_scores`",
        ));
    }
    Ok(py.detach(|| rank_survivors(&survivor_indices, &ranking_scores)))
}

/// Compute the expected maximum Sharpe threshold under trial selection.
#[pyfunction]
fn deflated_threshold_py(n_trials: usize, variance_of_sharpes: f64) -> f64 {
    deflated_threshold(n_trials, variance_of_sharpes)
}

/// Compute the probability that an observed Sharpe is spurious.
#[pyfunction]
fn deflated_sharpe_probability_py(
    observed_sharpe: f64,
    n_trials: usize,
    skewness: f64,
    kurtosis: f64,
    sample_length: usize,
) -> f64 {
    deflated_sharpe_probability(observed_sharpe, n_trials, skewness, kurtosis, sample_length)
}

/// Register Component 2 evaluation bindings onto the extension module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyIcResult>()?;
    m.add_class::<PyBlockStats>()?;
    m.add_class::<PyWalkForwardResult>()?;
    m.add_class::<PyScreeningOutcome>()?;
    m.add_function(wrap_pyfunction!(ic_ladder_py, m)?)?;
    m.add_function(wrap_pyfunction!(walk_forward_py, m)?)?;
    m.add_function(wrap_pyfunction!(screen_candidates_py, m)?)?;
    m.add_function(wrap_pyfunction!(rank_survivors_py, m)?)?;
    m.add_function(wrap_pyfunction!(deflated_threshold_py, m)?)?;
    m.add_function(wrap_pyfunction!(deflated_sharpe_probability_py, m)?)?;
    Ok(())
}
