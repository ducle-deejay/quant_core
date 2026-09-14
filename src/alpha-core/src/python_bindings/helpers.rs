use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub fn ensure_non_empty(name: &str, series: &[f64]) -> PyResult<()> {
    if series.is_empty() {
        return Err(PyValueError::new_err(format!(
            "`{name}` must contain at least one element"
        )));
    }
    Ok(())
}

pub fn ensure_all_finite(name: &str, series: &[f64]) -> PyResult<()> {
    if let Some((index, value)) = series
        .iter()
        .enumerate()
        .find(|(_, value)| !value.is_finite())
    {
        return Err(PyValueError::new_err(format!(
            "`{name}[{index}]` must be finite (non-finite value: {value})"
        )));
    }
    Ok(())
}

pub fn ensure_positive_usize(name: &str, value: usize) -> PyResult<()> {
    if value == 0 {
        return Err(PyValueError::new_err(format!(
            "`{name}` must be greater than zero"
        )));
    }
    Ok(())
}

pub fn ensure_non_negative_f64(name: &str, value: f64) -> PyResult<()> {
    if !value.is_finite() || value < 0.0 {
        return Err(PyValueError::new_err(format!(
            "`{name}` must be a finite, non-negative number (got {value})"
        )));
    }
    Ok(())
}
