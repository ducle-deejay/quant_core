//! Python bindings for the `alpha-core` quantitative-trading library.
//!
//! This module is compiled **only** when the `python-bindings` feature is
//! enabled; without the feature neither this file nor its dependency on
//! `pyo3` is visible to the compiler. It deliberately contains no business
//! logic of its own: every exported function validates its inputs, releases
//! the GIL around the pure-Rust hot path, delegates to the corresponding
//! implementation in [`crate::canonical`], and converts the result into a
//! Python-visible wrapper object.
//!
//! # Exposed surface (extension module name: `quantcore`)
//!
//! | Python symbol       | Wraps                                             |
//! |---------------------|---------------------------------------------------|
//! | `PyCanonicalResult` | [`crate::canonical::mapping::CanonicalResult`]    |
//! | `PyPnlResult`       | [`crate::canonical::pnl::PnlResult`]              |
//! | `canonical_map_py`  | [`crate::canonical::mapping::canonical_map`]      |
//! | `compute_pnl_py`    | [`crate::canonical::pnl::compute_pnl`]            |
//!
//! # Type conversions
//!
//! All conversions between Python and Rust types are explicit at this
//! boundary: Python sequences of floats arrive as `Vec<f64>` through PyO3's
//! `FromPyObject` impls, scalars as `usize`/`f64`, and results are handed
//! back as Python lists of floats via the `#[pyo3(get)]` accessors on the
//! wrapper classes. Invalid arguments (empty series, zero windows,
//! mismatched lengths) raise Python `ValueError` instead of letting a Rust
//! panic cross the FFI boundary.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use crate::canonical::mapping::{canonical_map, CanonicalResult};
use crate::canonical::pnl::{compute_pnl, PnlConfig, PnlResult};
use crate::harness_config::HarnessConfig;

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

/// Reject an empty float series with a `ValueError`.
///
/// Several core routines index their first element or divide by the series
/// length; raising here keeps Rust panics from ever crossing the FFI
/// boundary.
fn ensure_non_empty(name: &str, series: &[f64]) -> PyResult<()> {
    if series.is_empty() {
        return Err(PyValueError::new_err(format!(
            "`{name}` must contain at least one element"
        )));
    }
    Ok(())
}

/// Reject zero-valued count-like parameters (spans, windows, bar counts).
fn ensure_positive_usize(name: &str, value: usize) -> PyResult<()> {
    if value == 0 {
        return Err(PyValueError::new_err(format!(
            "`{name}` must be greater than zero"
        )));
    }
    Ok(())
}

/// Reject non-finite or negative threshold parameters (`band`, `cap`).
fn ensure_non_negative_f64(name: &str, value: f64) -> PyResult<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(PyValueError::new_err(format!(
            "`{name}` must be a finite, non-negative number (got {value})"
        )));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Wrapper classes
// ---------------------------------------------------------------------------

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
    /// Wrap a core [`CanonicalResult`] for export to Python.
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
    /// Wrap a core [`PnlResult`] for export to Python.
    fn from_core(result: PnlResult) -> Self {
        Self {
            gross: result.gross,
            net: result.net,
            turnover_annualized: result.turnover_annualized,
            cost_drag_pct: result.cost_drag_pct,
        }
    }
}

// ---------------------------------------------------------------------------
// Exported functions
// ---------------------------------------------------------------------------

/// Map a raw alpha-score series onto canonical positions.
///
/// Runs the full canonical pipeline: EWMA smoothing (`span`), rolling
/// z-score normalization over a trailing window (`z_window`), a no-trade
/// dead-zone (`band`) and a leverage cap (`cap`). Positions are expressed
/// in z units on the same axis as the score, so band comparisons remain
/// dimensionally valid.
///
/// Args:
///     score: Raw alpha-score series, one float per bar (non-empty).
///     span: EWMA smoothing span in bars (> 0).
///     z_window: Rolling z-score window length in bars (> 0).
///     band: No-trade dead-zone threshold in z units (>= 0).
///     cap: Maximum absolute position, multiples of capital (>= 0).
///     bars_per_day: Number of bars per trading day (> 0), used only to
///         report trade frequency.
///
/// Raises:
///     ValueError: On empty input or invalid parameter values.
///
/// Returns:
///     A `PyCanonicalResult` exposing `position`, `turnover` and
///     `trades_per_day`.
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
    ensure_positive_usize("bars_per_day", bars_per_day)?;
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

    // Pure-Rust numeric work: run it with the GIL released so other Python
    // threads stay responsive during long backtests.
    let result = py.allow_threads(|| canonical_map(&score, &cfg, bars_per_day));
    Ok(PyCanonicalResult::from_core(result))
}

/// Compute gross and net PnL from a canonical position series.
///
/// Uses the exact identity ``pnl(t) = p(t-1) * r(t) - c * |p(t) - p(t-1)|``:
/// the position decided at end of bar `t-1` earns the return of bar `t`,
/// never `p(t) * r(t)`, so anti-lookahead holds by construction.
///
/// Args:
///     pos: Canonical position series (non-empty).
///     ret: Per-bar simple returns, same length as `pos` (non-empty).
///     cost_per_side: Flat cost per unit notional per side.
///     bars_per_day: Number of bars per trading day (> 0), used to
///         annualize turnover.
///
/// Raises:
///     ValueError: If either series is empty or their lengths differ.
///
/// Returns:
///     A `PyPnlResult` exposing `gross`, `net`, `turnover_annualized` and
///     `cost_drag_pct`.
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

    // GIL released for the pure-Rust computation, same rationale as above.
    let result = py.allow_threads(|| compute_pnl(&pos, &ret, &cfg));
    Ok(PyPnlResult::from_core(result))
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

/// Register the `quantcore` Python extension module.
///
/// Exposes the two wrapper classes and both entry-point functions under
/// their Python-facing names.
///
/// Note: this crate pins `pyo3 = "0.20"`, which predates the `Bound<'_,
/// PyModule>` API introduced in pyo3 0.21, so the module argument uses the
/// GIL-bound `&PyModule` form. Migrating to pyo3 >= 0.21 only requires
/// changing this signature back to `&Bound<'_, PyModule>`.
#[pymodule]
fn quantcore(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyCanonicalResult>()?;
    m.add_class::<PyPnlResult>()?;
    m.add_function(wrap_pyfunction!(canonical_map_py, m)?)?;
    m.add_function(wrap_pyfunction!(compute_pnl_py, m)?)?;
    Ok(())
}
