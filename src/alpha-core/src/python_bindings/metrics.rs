//! Slot P1: Component 1 metrics bindings (Sharpe, max drawdown).
//! Owner-approved workstream DEC-005.

use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{ensure_all_finite, ensure_non_empty, ensure_positive_usize};
use crate::canonical::metrics::{max_drawdown, sharpe};

/// Compute the annualized Sharpe ratio of a daily PnL series.
///
/// The ratio is the series mean divided by its sample standard deviation,
/// annualized with a square-root-of-250 factor. `bars_per_day` is validated
/// for consistency with the canonical metrics interface; the underlying
/// annualized daily metric does not otherwise use it.
///
/// Args:
///     daily_pnl (list[float]): Non-empty daily profit-and-loss observations.
///     bars_per_day (int): Positive number of bars in each trading day.
///
/// Returns:
///     float: Annualized Sharpe ratio, or zero for a constant series.
///
/// Raises:
///     ValueError: If `daily_pnl` is empty or `bars_per_day` is zero.
#[pyfunction]
fn sharpe_py(py: Python<'_>, daily_pnl: Vec<f64>, bars_per_day: usize) -> PyResult<f64> {
    ensure_non_empty("daily_pnl", &daily_pnl)?;
    ensure_all_finite("daily_pnl", &daily_pnl)?;
    ensure_positive_usize("bars_per_day", bars_per_day)?;

    Ok(py.detach(|| sharpe(&daily_pnl, bars_per_day)))
}

/// Compute the maximum drawdown of a cumulative equity curve.
///
/// The input is interpreted as a PnL series whose cumulative sum forms the
/// equity curve. The result is the most negative peak-to-trough difference.
///
/// Args:
///     pnl_series (list[float]): Non-empty sequential PnL observations.
///
/// Returns:
///     float: Most negative peak-to-trough drawdown, never positive.
///
/// Raises:
///     ValueError: If `pnl_series` is empty.
#[pyfunction]
fn max_drawdown_py(py: Python<'_>, pnl_series: Vec<f64>) -> PyResult<f64> {
    ensure_non_empty("pnl_series", &pnl_series)?;
    ensure_all_finite("pnl_series", &pnl_series)?;

    Ok(py.detach(|| max_drawdown(&pnl_series)))
}

/// Register Component 1 metric bindings onto the extension module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sharpe_py, m)?)?;
    m.add_function(wrap_pyfunction!(max_drawdown_py, m)?)?;
    Ok(())
}
