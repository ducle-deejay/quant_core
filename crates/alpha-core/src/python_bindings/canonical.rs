//! Python bindings for Component 1: canonical mapping and PnL identity.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{ensure_non_empty, ensure_non_negative_f64, ensure_positive_usize};
use crate::canonical::mapping::{canonical_map, CanonicalResult};
use crate::canonical::pnl::{compute_pnl, PnlConfig, PnlResult};
use crate::harness_config::HarnessConfig;

/// Result of the canonical score -> position mapping.
///
/// Attributes:
///     position (list[float]): Canonical position per bar, in z units.
///     turnover (list[float]): Absolute position change per bar.
///     trades_per_day (float): Average number of trades executed per day.
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

/// Gross/net PnL diagnostics for a canonical position series.
///
/// Attributes:
///     gross (list[float]): Per-bar PnL before transaction costs.
///     net (list[float]): Per-bar PnL after flat per-side costs.
///     turnover_annualized (float): Total absolute turnover annualized.
///     cost_drag_pct (float): Total cost as a percentage of gross PnL.
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

/// Map a raw alpha-score series onto canonical positions.
///
/// Runs the full canonical pipeline: EWMA smoothing (`span`), rolling
/// z-score normalization over a trailing window (`z_window`), a no-trade
/// dead-zone (`band`) and a leverage cap (`cap`). Positions are expressed
/// in z units on the same axis as the score.
///
/// Raises:
///     ValueError: On empty input or invalid parameter values.
#[pyfunction]
fn canonical_map_py(
    py: Python,
    score: Vec<f64>,
    span: usize,
    z_window: usize,
    band: f64,
    cap: f64,
    bars_per_day: usize,
) -> PyResult<PyCanonicalResult> {
    ensure_non_empty("score", &score)?;
    ensure_positive_usize("span", span)?;
    ensure_positive_usize("z_window", z_window)?;
    ensure_non_negative_f64("band", band)?;
    ensure_non_negative_f64("cap", cap)?;

    // `canonical_map` does not model costs; carry over the harness default
    // so the config remains a faithful `HarnessConfig`.
    let cfg = HarnessConfig {
        span,
        z_window,
        band,
        cap,
        cost_per_side: HarnessConfig::default().cost_per_side,
    };

    let result = py.detach(|| canonical_map(&score, &cfg, bars_per_day));
    Ok(PyCanonicalResult::from_core(result))
}

/// Compute gross and net PnL from a canonical position series.
///
/// Uses the exact identity ``pnl(t) = p(t-1) * r(t) - c * |p(t) - p(t-1)|``:
/// the position decided at end of bar `t-1` earns the return of bar `t`,
/// never `p(t) * r(t)`, so anti-lookahead holds by construction.
///
/// Raises:
///     ValueError: If either series is empty or their lengths differ.
#[pyfunction]
fn compute_pnl_py(
    py: Python,
    pos: Vec<f64>,
    ret: Vec<f64>,
    cost_per_side: f64,
    bars_per_day: usize,
) -> PyResult<PyPnlResult> {
    ensure_non_empty("pos", &pos)?;
    ensure_non_empty("ret", &ret)?;
    if pos.len() != ret.len() {
        return Err(PyValueError::new_err(format!(
            "`pos` and `ret` must have equal length (got {} and {})",
            pos.len(),
            ret.len()
        )));
    }
    ensure_positive_usize("bars_per_day", bars_per_day)?;

    let cfg = PnlConfig {
        cost_per_side,
        bars_per_day,
    };

    let result = py.detach(|| compute_pnl(&pos, &ret, &cfg));
    Ok(PyPnlResult::from_core(result))
}

/// Register Component 1 bindings onto the extension module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCanonicalResult>()?;
    m.add_class::<PyPnlResult>()?;
    m.add_function(wrap_pyfunction!(canonical_map_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute_pnl_py, m)?)?;
    Ok(())
}
