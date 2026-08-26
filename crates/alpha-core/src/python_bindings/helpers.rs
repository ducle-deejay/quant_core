//! Input validation shared by every Python-facing wrapper.
//!
//! Kept tiny on purpose: raising here keeps Rust panics from crossing
//! the FFI boundary.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Reject an empty float series with a `ValueError`.
pub fn ensure_non_empty(name: &str, series: &[f64]) -> PyResult<()> {
    if series.is_empty() {
        return Err(PyValueError::new_err(format!(
            "`{name}` must contain at least one element"
        )));
    }
    Ok(())
}

/// Reject zero-valued count-like parameters (spans, windows, bar counts).
pub fn ensure_positive_usize(name: &str, value: usize) -> PyResult<()> {
    if value == 0 {
        return Err(PyValueError::new_err(format!(
            "`{name}` must be greater than zero"
        )));
    }
    Ok(())
}

/// Reject non-finite or negative threshold parameters (`band`, `cap`).
pub fn ensure_non_negative_f64(name: &str, value: f64) -> PyResult<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(PyValueError::new_err(format!(
            "`{name}` must be a finite, non-negative number (got {value})"
        )));
    }
    Ok(())
}
