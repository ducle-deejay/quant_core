//! Python bindings for Component 0 mining (parser, DAG executor, GA loop).

use std::collections::HashMap;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use super::helpers::{ensure_all_finite, ensure_non_empty, ensure_positive_usize};
use crate::strategies::mining::{
    build_dag, execute_batch, parse, AlphaGenerator, GaConfig, GeneratorConfig, Individual,
    XorShift,
};

/// Parse an expression and return its canonical DSL serialization.
///
/// Raises:
///     ValueError: If `dsl` is not a valid mining expression.
#[pyfunction]
fn validate_expression_py(py: Python<'_>, dsl: &str) -> PyResult<String> {
    py.detach(|| {
        parse(dsl)
            .map(|ast| ast.to_string())
            .map_err(|err| PyValueError::new_err(err.to_string()))
    })
}

/// Execute several mining expressions over close and volume columns.
///
/// Returns one score series per expression. Expressions are parsed and then
/// evaluated through one shared computation DAG.
///
/// Raises:
///     ValueError: If an input column is empty or an expression is invalid.
#[pyfunction]
fn execute_batch_py(
    py: Python<'_>,
    expressions: Vec<String>,
    close: Vec<f64>,
    volume: Vec<f64>,
) -> PyResult<Vec<Vec<f64>>> {
    ensure_non_empty("close", &close)?;
    ensure_all_finite("close", &close)?;
    ensure_non_empty("volume", &volume)?;
    ensure_all_finite("volume", &volume)?;
    py.detach(|| {
        let asts = expressions
            .iter()
            .enumerate()
            .map(|(index, expression)| {
                parse(expression).map_err(|err| {
                    PyValueError::new_err(format!("expression at index {index}: {err}"))
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        let mut data = HashMap::new();
        data.insert("close".to_string(), close);
        data.insert("volume".to_string(), volume);
        let dag = build_dag(&asts);
        Ok(execute_batch(&dag, &data, &dag.roots))
    })
}

/// Run the mining genetic algorithm and return its best DSL expression.
///
/// The generator is restricted to `close` and `volume`; fitness is the mean
/// product of each finite score and the next-bar close return, evaluated via
/// the batch executor. Tournament selection, crossover, mutation, and elitism
/// use the shared seed-GA implementation.
///
/// Raises:
///     ValueError: If either input column is empty or `population_size` is 0.
#[pyfunction]
fn ga_best_expression_py(
    py: Python<'_>,
    close: Vec<f64>,
    volume: Vec<f64>,
    population_size: usize,
    generations: usize,
    seed: u64,
) -> PyResult<String> {
    ensure_non_empty("close", &close)?;
    ensure_non_empty("volume", &volume)?;
    super::helpers::ensure_all_finite("close", &close)?;
    super::helpers::ensure_all_finite("volume", &volume)?;
    ensure_positive_usize("population_size", population_size)?;

    py.detach(|| {
        let generator_config = GeneratorConfig {
            fields: vec!["close".into(), "volume".into()],
            ..Default::default()
        };
        let mut generator = AlphaGenerator::new(&generator_config, seed);
        let seeds = generator.generate_batch(population_size.min(4));
        let mut returns = vec![0.0; close.len()];
        for t in 1..close.len() {
            returns[t] = close[t] / close[t - 1] - 1.0;
        }
        let forward_returns = returns[1..].to_vec();
        let data = {
            let mut map = HashMap::new();
            map.insert("close".to_string(), close);
            map.insert("volume".to_string(), volume);
            map
        };
        let config = GaConfig {
            population_size,
            elite_count: 4.min(population_size),
            tournament_size: 3,
            crossover_rate: 0.75,
            mutation_rate: 0.3,
            max_generations: generations,
            max_tree_depth: 6,
        };
        let evaluate = |population: &[Individual]| {
            population
                .iter()
                .map(|individual| {
                    let ast = match parse(&individual.dsl_string) {
                        Ok(ast) => ast,
                        Err(_) => return f64::NEG_INFINITY,
                    };
                    let dag = build_dag(std::slice::from_ref(&ast));
                    let rows = execute_batch(&dag, &data, &dag.roots);
                    let n = rows[0].len().min(forward_returns.len());
                    // Scale-free fitness: z-score the score row before the
                    // mean score x next-bar-return product, so the GA breeds
                    // INFORMATION, not magnitude monsters (practitioner
                    // review: raw fitness made ts_sum^2*close^3 products win).
                    let mut xs: Vec<f64> = Vec::new();
                    let mut ys: Vec<f64> = Vec::new();
                    for t in 0..n {
                        if rows[0][t].is_finite() && forward_returns[t].is_finite() {
                            xs.push(rows[0][t]);
                            ys.push(forward_returns[t]);
                        }
                    }
                    if xs.len() < 2 {
                        return -1.0;
                    }
                    let mean = xs.iter().sum::<f64>() / xs.len() as f64;
                    let var = xs
                        .iter()
                        .map(|x| (x - mean) * (x - mean))
                        .sum::<f64>()
                        / xs.len() as f64;
                    if var == 0.0 {
                        return 0.0;
                    }
                    let std = var.sqrt();
                    xs.iter()
                        .zip(ys.iter())
                        .map(|(x, y)| (x - mean) / std * y)
                        .sum::<f64>()
                        / xs.len() as f64
                })
                .collect::<Vec<f64>>()
        };
        let final_population =
            crate::strategies::mining::run_ga(&seeds, &config, evaluate, &mut XorShift::new(seed));
        final_population
            .first()
            .map(|individual| individual.dsl_string.clone())
            .ok_or_else(|| PyValueError::new_err("genetic algorithm produced no individuals"))
    })
}

/// Breed the genetic algorithm from researcher-provided seed expressions and
/// return the final population's DSL strings ranked by fitness (best first).
///
/// Unlike [`ga_best_expression_py`], the initial population is bred from the
/// given seeds (WorldQuant-style: only evaluation-passing seeds enter
/// mining, decision note DEC-017). Fitness is the same mean score x
/// next-bar-return statistic; a custom fitness remains a Python-side GA
/// loop (research module).
///
/// Raises:
///     ValueError: If ``seeds`` is empty, an input column is empty or
///     non-finite, ``population_size`` is 0, or a rate lies outside [0, 1].
#[pyfunction]
#[pyo3(signature = (seeds, close, volume, population_size, generations, seed, elite_count=None, tournament_size=None, crossover_rate=None, mutation_rate=None, max_tree_depth=None))]
fn ga_breed_py(
    py: Python<'_>,
    seeds: Vec<String>,
    close: Vec<f64>,
    volume: Vec<f64>,
    population_size: usize,
    generations: usize,
    seed: u64,
    elite_count: Option<usize>,
    tournament_size: Option<usize>,
    crossover_rate: Option<f64>,
    mutation_rate: Option<f64>,
    max_tree_depth: Option<usize>,
) -> PyResult<Vec<String>> {
    if seeds.is_empty() {
        return Err(PyValueError::new_err("`seeds` must contain at least one expression"));
    }
    ensure_non_empty("close", &close)?;
    ensure_all_finite("close", &close)?;
    ensure_non_empty("volume", &volume)?;
    ensure_all_finite("volume", &volume)?;
    ensure_positive_usize("population_size", population_size)?;
    if let Some(rate) = crossover_rate {
        if !(0.0..=1.0).contains(&rate) {
            return Err(PyValueError::new_err("crossover_rate must be in [0, 1]"));
        }
    }
    if let Some(rate) = mutation_rate {
        if !(0.0..=1.0).contains(&rate) {
            return Err(PyValueError::new_err("mutation_rate must be in [0, 1]"));
        }
    }

    py.detach(|| {
        let seed_asts = seeds
            .iter()
            .enumerate()
            .map(|(index, dsl)| {
                parse(dsl)
                    .map_err(|err| PyValueError::new_err(format!("seed at index {index}: {err}")))
            })
            .collect::<PyResult<Vec<_>>>()?;
        let mut returns = vec![0.0; close.len()];
        for t in 1..close.len() {
            returns[t] = close[t] / close[t - 1] - 1.0;
        }
        let forward_returns = returns[1..].to_vec();
        let data = {
            let mut map = HashMap::new();
            map.insert("close".to_string(), close);
            map.insert("volume".to_string(), volume);
            map
        };
        let config = GaConfig {
            population_size,
            elite_count: elite_count.unwrap_or(4).min(population_size),
            tournament_size: tournament_size.unwrap_or(3),
            crossover_rate: crossover_rate.unwrap_or(0.75),
            mutation_rate: mutation_rate.unwrap_or(0.3),
            max_generations: generations,
            max_tree_depth: max_tree_depth.unwrap_or(6),
        };
        let evaluate = |population: &[Individual]| {
            population
                .iter()
                .map(|individual| {
                    let ast = match parse(&individual.dsl_string) {
                        Ok(ast) => ast,
                        Err(_) => return f64::NEG_INFINITY,
                    };
                    let dag = build_dag(std::slice::from_ref(&ast));
                    let rows = execute_batch(&dag, &data, &dag.roots);
                    let n = rows[0].len().min(forward_returns.len());
                    // Scale-free fitness: z-score the score row before the
                    // mean score x next-bar-return product, so the GA breeds
                    // INFORMATION, not magnitude monsters (practitioner
                    // review: raw fitness made ts_sum^2*close^3 products win).
                    let mut xs: Vec<f64> = Vec::new();
                    let mut ys: Vec<f64> = Vec::new();
                    for t in 0..n {
                        if rows[0][t].is_finite() && forward_returns[t].is_finite() {
                            xs.push(rows[0][t]);
                            ys.push(forward_returns[t]);
                        }
                    }
                    if xs.len() < 2 {
                        return -1.0;
                    }
                    let mean = xs.iter().sum::<f64>() / xs.len() as f64;
                    let var = xs
                        .iter()
                        .map(|x| (x - mean) * (x - mean))
                        .sum::<f64>()
                        / xs.len() as f64;
                    if var == 0.0 {
                        return 0.0;
                    }
                    let std = var.sqrt();
                    xs.iter()
                        .zip(ys.iter())
                        .map(|(x, y)| (x - mean) / std * y)
                        .sum::<f64>()
                        / xs.len() as f64
                })
                .collect::<Vec<f64>>()
        };
        let final_population =
            crate::strategies::mining::run_ga(&seed_asts, &config, evaluate, &mut XorShift::new(seed));
        Ok(final_population
            .into_iter()
            .map(|individual| individual.dsl_string)
            .collect())
    })
}

/// Register Component 0 bindings onto the extension module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(validate_expression_py, m)?)?;
    m.add_function(wrap_pyfunction!(execute_batch_py, m)?)?;
    m.add_function(wrap_pyfunction!(ga_best_expression_py, m)?)?;
    m.add_function(wrap_pyfunction!(ga_breed_py, m)?)?;
    Ok(())
}
