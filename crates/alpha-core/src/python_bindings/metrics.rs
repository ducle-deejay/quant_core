//! Slot P1: Component 1 metrics bindings (Sharpe, max drawdown).
//! Owner-approved workstream DEC-005. Registers nothing yet.

use pyo3::prelude::*;
use pyo3::types::PyModule;

/// Register Component 1 metric bindings onto the extension module.
pub fn register(_m: &Bound<'_, PyModule>) -> PyResult<()> {
    Ok(())
}
