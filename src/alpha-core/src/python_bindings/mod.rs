pub mod canonical;
pub mod evaluation;
pub mod helpers;
pub mod metrics;
pub mod mining;
pub mod portfolio;

use pyo3::prelude::*;
use pyo3::types::PyModule;

#[pymodule]
fn alpha_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    canonical::register(m)?;
    portfolio::register(m)?;
    metrics::register(m)?;
    evaluation::register(m)?;
    mining::register(m)?;
    Ok(())
}
