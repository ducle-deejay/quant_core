use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{
    ensure_all_finite, ensure_non_empty, ensure_non_negative_f64, ensure_positive_usize,
};
use crate::canonical::mapping::{canonical_map, CanonicalResult};
use crate::canonical::pnl::{compute_pnl, PnlConfig, PnlResult};
use crate::harness_config::HarnessConfig;

#[pyclass]
pub struct PyCanonicalResult {
    #[pyo3(get)]
    pub position: Vec<f64>,
    #[pyo3(get)]
    pub turnover: Vec<f64>,
    #[pyo3(get)]
    pub trades_per_day: f64,
}

impl PyCanonicalResult {
    fn from_core(result: CanonicalResult) -> Self {
        Self {
            position: result.position,
            turnover: result.turnover,
            trades_per_day: result.trades_per_day,
        }
    }
}

#[pyclass]
pub struct PyPnlResult {
    #[pyo3(get)]
    pub gross: Vec<f64>,
    #[pyo3(get)]
    pub net: Vec<f64>,
    #[pyo3(get)]
    pub turnover_annualized: f64,
    #[pyo3(get)]
    pub cost_drag_pct: f64,
}

impl PyPnlResult {
    fn from_core(result: PnlResult) -> Self {
        Self {
            gross: result.gross,
            net: result.net,
            turnover_annualized: result.turnover_annualized,
            cost_drag_pct: result.cost_drag_pct,
        }
    }
}

#[pyfunction]
fn canonical_map_py(
    py: Python,
    score: Vec<f64>,
    span: usize,
    z_window: usize,
    band: f64,
    cap: f64,
    bars_per_day: i64,
) -> PyResult<PyCanonicalResult> {
    ensure_non_empty("score", &score)?;
    ensure_all_finite("score", &score)?;
    ensure_positive_usize("span", span)?;
    ensure_positive_usize("z_window", z_window)?;
    ensure_non_negative_f64("band", band)?;
    ensure_non_negative_f64("cap", cap)?;
    if bars_per_day <= 0 {
        return Err(PyValueError::new_err(
            "`bars_per_day` must be greater than zero",
        ));
    }

    let cfg = HarnessConfig {
        span,
        z_window,
        band,
        cap,
        cost_per_side: HarnessConfig::default().cost_per_side,
    };

    let result = py.detach(|| canonical_map(&score, &cfg, bars_per_day as usize));
    Ok(PyCanonicalResult::from_core(result))
}

#[pyfunction]
fn compute_pnl_py(
    py: Python,
    pos: Vec<f64>,
    ret: Vec<f64>,
    cost_per_side: f64,
    bars_per_day: i64,
) -> PyResult<PyPnlResult> {
    ensure_non_empty("pos", &pos)?;
    ensure_all_finite("pos", &pos)?;
    ensure_non_empty("ret", &ret)?;
    ensure_all_finite("ret", &ret)?;
    if pos.len() != ret.len() {
        return Err(PyValueError::new_err(format!(
            "`pos` and `ret` must have equal length (got {} and {})",
            pos.len(),
            ret.len()
        )));
    }
    if bars_per_day <= 0 {
        return Err(PyValueError::new_err(
            "`bars_per_day` must be greater than zero",
        ));
    }

    let cfg = PnlConfig {
        cost_per_side,
        bars_per_day: bars_per_day as usize,
    };

    let result = py.detach(|| compute_pnl(&pos, &ret, &cfg));
    Ok(PyPnlResult::from_core(result))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCanonicalResult>()?;
    m.add_class::<PyPnlResult>()?;
    m.add_function(wrap_pyfunction!(canonical_map_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute_pnl_py, m)?)?;
    Ok(())
}
