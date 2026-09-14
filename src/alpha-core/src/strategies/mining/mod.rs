pub mod batch_executor;
pub mod dag_builder;
pub mod expression_parser;
pub mod operators;
pub mod seed_ga;

pub use batch_executor::execute_batch;
pub use dag_builder::{build_dag, ComputationDag, DagNode};
pub use expression_parser::{
    collect_fields, hash_ast, parse, AstNode, BinOp, ParseError, TsArg, TsFunc, UnaryOp,
};
pub use operators::*;
pub use seed_ga::{
    crossover, evolve_generation, initialize_population, mutate, run_ga, GaConfig, Individual, Rng,
    XorShift, UNEVALUATED_FITNESS,
};

pub mod alpha_generator;
pub use alpha_generator::{AlphaGenerator, GeneratorConfig};
