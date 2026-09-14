use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{ensure_all_finite, ensure_non_empty, ensure_positive_usize};
use crate::canonical::metrics::{max_drawdown, sharpe};

#[pyfunction]
fn sharpe_py(py: Python<'_>, daily_pnl: Vec<f64>, bars_per_day: usize) -> PyResult<f64> {
    ensure_non_empty("daily_pnl", &daily_pnl)?;
    ensure_all_finite("daily_pnl", &daily_pnl)?;
    ensure_positive_usize("bars_per_day", bars_per_day)?;

    Ok(py.detach(|| sharpe(&daily_pnl, bars_per_day)))
}

#[pyfunction]
fn max_drawdown_py(py: Python<'_>, pnl_series: Vec<f64>) -> PyResult<f64> {
    ensure_non_empty("pnl_series", &pnl_series)?;
    ensure_all_finite("pnl_series", &pnl_series)?;

    Ok(py.detach(|| max_drawdown(&pnl_series)))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sharpe_py, m)?)?;
    m.add_function(wrap_pyfunction!(max_drawdown_py, m)?)?;
    Ok(())
}
