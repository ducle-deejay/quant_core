//! Python bindings for the `alpha-core` quantitative-trading library.
//!
//! Compiled only when the `python-bindings` feature is enabled. Layout is
//! one file per component so binding authors work in isolation:
//!
//! ```text
//!     canonical.rs    Component 1 - canonical mapping and PnL      (active)
//!     metrics.rs      Component 1 - Sharpe / max drawdown          (slot P1)
//!     evaluation.rs   Component 2 - IC ladder, walk-forward,
//!                     gates, deflated Sharpe                       (slot P2)
//!     mining.rs       Component 0 - parser, DAG executor, GA       (slot P3)
//!     portfolio.rs    Components 3-5 - orthogonalization,
//!                     combination, sizing                          (slot P4)
//! ```
//!
//! Each submodule exposes a single `register(m: &Bound<'_, PyModule>)`
//! function; [`quantcore`] activates them. Shared input validation lives
//! in [`helpers`].

pub mod canonical;
pub mod evaluation;
pub mod helpers;
pub mod metrics;
pub mod mining;
pub mod portfolio;

use pyo3::prelude::*;
use pyo3::types::PyModule;

/// Register the `quantcore` Python extension module.
#[pymodule]
fn quantcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    canonical::register(m)?;
    portfolio::register(m)?;
    metrics::register(m)?;
    evaluation::register(m)?;
    mining::register(m)?;
    Ok(())
}
