//! Python bindings for Components 3-5: portfolio construction and sizing.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{ensure_all_finite, ensure_non_empty};
use crate::combination::composite_score;
use crate::orthogonalization::orthogonalize;
use crate::strategies::combination::inverse_vol::InverseVol;
use crate::strategies::combination::CombineMethod;
use crate::strategies::sizing::drawdown_overlay::DrawdownLadder;
use crate::strategies::sizing::vol_target::{VolTarget, VolTargetWithFloor};
use crate::strategies::sizing::SizingMethod;

fn ensure_matrix_non_empty(name: &str, matrix: &[Vec<f64>]) -> PyResult<()> {
    if matrix.is_empty() {
        return Err(PyValueError::new_err(format!(
            "`{name}` must contain at least one series"
        )));
    }
    for (i, series) in matrix.iter().enumerate() {
        ensure_non_empty(&format!("{name}[{i}]"), series)?;
    }
    Ok(())
}

fn ensure_equal_series_lengths(name: &str, series: &[Vec<f64>], expected: usize) -> PyResult<()> {
    for (i, values) in series.iter().enumerate() {
        if values.len() != expected {
            return Err(PyValueError::new_err(format!(
                "`{name}[{i}]` must have length {expected} (got {})",
                values.len()
            )));
        }
    }
    Ok(())
}

/// Regress a candidate series on a pool of series and return its residual.
///
/// Raises `ValueError` when the candidate or a pool member is empty, or when
/// any pool member has a different number of bars than the candidate.
#[pyfunction]
fn orthogonalize_py(py: Python, candidate: Vec<f64>, pool: Vec<Vec<f64>>) -> PyResult<Vec<f64>> {
    ensure_non_empty("candidate", &candidate)?;
    ensure_all_finite("candidate", &candidate)?;
    for (i, series) in pool.iter().enumerate() {
        ensure_non_empty(&format!("pool[{i}]"), series)?;
        ensure_all_finite(&format!("pool[{i}]"), series)?;
        if series.len() != candidate.len() {
            return Err(PyValueError::new_err(format!(
                "`pool[{i}]` and `candidate` must have equal length (got {} and {})",
                series.len(),
                candidate.len()
            )));
        }
    }
    Ok(py.detach(|| orthogonalize(&candidate, &pool)))
}

/// Compute a weighted composite from multiple score series.
///
/// All score series must be non-empty and have equal bar counts, and there
/// must be one weight per series.
#[pyfunction]
fn composite_score_py(py: Python, scores: Vec<Vec<f64>>, weights: Vec<f64>) -> PyResult<Vec<f64>> {
    ensure_matrix_non_empty("scores", &scores)?;
    for (i, series) in scores.iter().enumerate() {
        ensure_all_finite(&format!("scores[{i}]"), series)?;
    }
    ensure_all_finite("weights", &weights)?;
    if scores.len() != weights.len() {
        return Err(PyValueError::new_err(format!(
            "`scores` and `weights` must have equal length (got {} and {})",
            scores.len(),
            weights.len()
        )));
    }
    let n_bars = scores[0].len();
    ensure_equal_series_lengths("scores", &scores, n_bars)?;
    Ok(py.detach(|| composite_score(&scores, &weights)))
}

/// Combine score series using the default inverse-volatility weighting rule.
#[pyfunction]
fn inverse_vol_combine_py(py: Python, scores: Vec<Vec<f64>>) -> PyResult<Vec<f64>> {
    ensure_matrix_non_empty("scores", &scores)?;
    for (i, series) in scores.iter().enumerate() {
        ensure_all_finite(&format!("scores[{i}]"), series)?;
    }
    let n_bars = scores[0].len();
    ensure_equal_series_lengths("scores", &scores, n_bars)?;
    Ok(py.detach(|| InverseVol::default().combine(&scores)))
}

/// Size scores toward a target volatility, optionally applying a volatility floor.
///
/// `floor=None` selects plain targeting; `Some(floor)` selects floored targeting.
#[pyfunction]
fn vol_target_py(
    py: Python,
    z_scores: Vec<f64>,
    vol_est: Vec<f64>,
    target_vol: f64,
    floor: Option<f64>,
) -> PyResult<Vec<f64>> {
    ensure_non_empty("z_scores", &z_scores)?;
    ensure_all_finite("z_scores", &z_scores)?;
    ensure_non_empty("vol_est", &vol_est)?;
    ensure_all_finite("vol_est", &vol_est)?;
    if z_scores.len() != vol_est.len() {
        return Err(PyValueError::new_err(format!(
            "`z_scores` and `vol_est` must have equal length (got {} and {})",
            z_scores.len(),
            vol_est.len()
        )));
    }
    if let Some(value) = floor {
        if !value.is_finite() || value <= 0.0 {
            return Err(PyValueError::new_err(format!(
                "`floor` must be finite and positive (got {value})"
            )));
        }
        Ok(py.detach(|| VolTargetWithFloor::new(target_vol, value).compute(&z_scores, &vol_est)))
    } else {
        Ok(py.detach(|| VolTarget::new(target_vol).compute(&z_scores, &vol_est)))
    }
}

/// Return default-ladder exposure multipliers for drawdown fractions.
///
/// The input is interpreted as drawdown from a fixed initial equity of 1.0;
/// each value is converted to equity and evaluated against the default ladder.
#[pyfunction]
fn drawdown_multiplier_py(py: Python, drawdowns: Vec<f64>) -> PyResult<Vec<f64>> {
    ensure_non_empty("drawdowns", &drawdowns)?;
    for (i, &drawdown) in drawdowns.iter().enumerate() {
        if !drawdown.is_finite() || drawdown < 0.0 {
            return Err(PyValueError::new_err(format!(
                "`drawdowns[{i}]` must be finite and non-negative (got {drawdown})"
            )));
        }
    }
    Ok(py.detach(|| {
        let mut ladder = DrawdownLadder::new(1.0);
        drawdowns
            .into_iter()
            .map(|drawdown| {
                let equity = 1.0 - drawdown;
                ladder.update_peak(equity);
                ladder.current_multiplier(equity)
            })
            .collect()
    }))
}

/// Register Components 3-5 bindings onto the extension module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(orthogonalize_py, m)?)?;
    m.add_function(wrap_pyfunction!(composite_score_py, m)?)?;
    m.add_function(wrap_pyfunction!(inverse_vol_combine_py, m)?)?;
    m.add_function(wrap_pyfunction!(vol_target_py, m)?)?;
    m.add_function(wrap_pyfunction!(drawdown_multiplier_py, m)?)?;
    Ok(())
}
