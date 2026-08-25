/// Grammar-guided alpha generation.
///
/// Generates valid expression trees directly from the DSL grammar rules.
/// Every generated tree is valid by construction — no post-hoc validation
/// needed, zero parse failures guaranteed.

use super::expression_parser::{AstNode, BinOp, TsFunc, TsArg, UnaryOp};

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct GeneratorConfig {
    /// Available data field names in the dataset
    pub fields: Vec<String>,
    /// Maximum tree depth to prevent unbounded recursion
    pub max_depth: usize,
    /// Minimum window size for time-series operators
    pub min_window: usize,
    /// Maximum window size for time-series operators
    pub max_window: usize,
}

impl Default for GeneratorConfig {
    fn default() -> Self {
        Self {
            fields: vec![
                "close".into(), "open".into(), "high".into(),
                "low".into(), "volume".into(),
            ],
            max_depth: 6,
            min_window: 5,
            max_window: 60,
        }
    }
}

// ---------------------------------------------------------------------------
// Generator
// ---------------------------------------------------------------------------

pub struct AlphaGenerator<'a> {
    cfg: &'a GeneratorConfig,
    rng_state: u64,
}

impl<'a> AlphaGenerator<'a> {
    pub fn new(cfg: &'a GeneratorConfig, seed: u64) -> Self {
        Self { cfg, rng_state: seed }
    }

    /// Generate one valid expression tree.
    pub fn generate(&mut self) -> AstNode {
        self.generate_expr(0)
    }

    /// Generate `n` valid expression trees.
    pub fn generate_batch(&mut self, n: usize) -> Vec<AstNode> {
        (0..n).map(|_| self.generate()).collect()
    }

    // -- internal: grammar rule expansions --

    /// Grammar rule: expr := term (('+'|'-') term)*
    fn generate_expr(&mut self, depth: usize) -> AstNode {
        if depth >= self.cfg.max_depth || self.flip(0.35) {
            return self.generate_term(depth + 1);
        }
        let left = Box::new(self.generate_term(depth + 1));
        let right = Box::new(self.generate_term(depth + 1));
        let op = if self.flip(0.5) { BinOp::Add } else { BinOp::Sub };
        AstNode::BinaryOp { op, left, right }
    }

    /// Grammar rule: term := factor (('*'|'/') factor)*
    fn generate_term(&mut self, depth: usize) -> AstNode {
        if depth >= self.cfg.max_depth || self.flip(0.40) {
            return self.generate_factor(depth + 1);
        }
        let left = Box::new(self.generate_factor(depth + 1));
        let right = Box::new(self.generate_factor(depth + 1));
        let op = if self.flip(0.6) { BinOp::Mul } else { BinOp::Div };
        AstNode::BinaryOp { op, left, right }
    }

    /// Grammar rule: factor := number | field | ts_func | '(' expr ')' | '-' factor
    fn generate_factor(&mut self, depth: usize) -> AstNode {
        let choice = if depth >= self.cfg.max_depth {
            self.below(2)
        } else {
            self.below(5)
        };
        match choice {
            0 => AstNode::Number(self.random_coefficient()),
            1 => AstNode::Field(self.pick_field()),
            2 => self.generate_ts_func(),
            3 => {
                let inner = Box::new(self.generate_expr(depth + 1));
                AstNode::UnaryOp { op: UnaryOp::Neg, operand: inner }
            }
            _ => {
                let inner = Box::new(self.generate_expr(depth + 1));
                AstNode::BinaryOp {
                    op: BinOp::Sub,
                    left: Box::new(AstNode::Number(0.0)),
                    right: inner,
                }
            }
        }
    }

    /// Generate a time-series function call node.
    fn generate_ts_func(&mut self) -> AstNode {
        let func = self.pick_ts_func();
        let range = (self.cfg.max_window - self.cfg.min_window + 1) as u64;
        let window = self.cfg.min_window + (self.next_u64() % range as u64) as usize;

        let args = if matches!(func, TsFunc::Corr | TsFunc::Covariance | TsFunc::RegressionResid | TsFunc::RegressionBeta) {
            // Dual-input operators require two series arguments
            vec![
                TsArg::Field(self.pick_field()),
                TsArg::Field(self.pick_field()),
            ]
        } else {
            // Single-input operators
            vec![TsArg::Field(self.pick_field())]
        };

        let param = match func {
            TsFunc::Quantile => 0.75,
            _ => 0.0,
        };

        AstNode::TsFunc { func, args, window, param }
    }

    // -- RNG helpers (xorshift64*) --

    fn next_u64(&mut self) -> u64 {
        let mut x = self.rng_state;
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        self.rng_state = x;
        x
    }

    fn flip(&mut self, prob_true: f64) -> bool {
        (self.next_u64() % 10000) as f64 / 10000.0 < prob_true
    }

    fn below(&mut self, n: usize) -> usize {
        if n == 0 { return 0; }
        (self.next_u64() % n as u64) as usize
    }

    fn random_coefficient(&mut self) -> f64 {
        // Always positive: negative coefficients are produced by wrapping
        // in UnaryOp::Neg or BinOp::Sub at the grammar level, which ensures
        // parse(ast.to_string()) == ast round-trip consistency.
        (self.next_u64() % 1000) as f64 / 1000.0
    }

    fn pick_field(&mut self) -> String {
        let idx = self.below(self.cfg.fields.len());
        self.cfg.fields[idx].clone()
    }

    fn pick_ts_func(&mut self) -> TsFunc {
        let funcs = [
            TsFunc::Mean, TsFunc::Std, TsFunc::Delta, TsFunc::Delay,
            TsFunc::Sum, TsFunc::Rank, TsFunc::Corr, TsFunc::Zscore,
            TsFunc::Ewma, TsFunc::Min, TsFunc::Max, TsFunc::Median,
            TsFunc::Skewness, TsFunc::Kurtosis, TsFunc::Ir,
            TsFunc::Product, TsFunc::ArgMax, TsFunc::ArgMin,
            TsFunc::MaxDiff, TsFunc::MinDiff, TsFunc::Scale,
            TsFunc::QuantilePos, TsFunc::DecayLinear,
            TsFunc::RegressionResid, TsFunc::RegressionBeta,
        ];
        let idx = self.below(funcs.len());
        funcs[idx].clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::strategies::mining::expression_parser::parse;

    #[test]
    fn test_all_generated_trees_are_parseable() {
        let cfg = GeneratorConfig::default();
        let mut gen = AlphaGenerator::new(&cfg, 42);
        for i in 0..100 {
            let ast = gen.generate();
            let dsl = ast.to_string();
            let reparsed = parse(&dsl)
                .unwrap_or_else(|e| panic!("tree {} DSL '{}' failed to parse: {}", i, dsl, e));
            assert_eq!(reparsed, ast, "round-trip mismatch at tree {}", i);
        }
    }

    #[test]
    fn test_trees_respect_max_depth() {
        let cfg = GeneratorConfig { max_depth: 3, ..Default::default() };
        let mut gen = AlphaGenerator::new(&cfg, 99);

        fn max_depth_of(ast: &AstNode) -> usize {
            match ast {
                AstNode::Number(_) | AstNode::Field(_) => 1,
                AstNode::BinaryOp { left, right, .. } => 1 + max_depth_of(left).max(max_depth_of(right)),
                AstNode::UnaryOp { operand, .. } => 1 + max_depth_of(operand),
                AstNode::TsFunc { args, .. } => 1 + args.iter()
                    .map(|arg| match arg {
                        crate::strategies::mining::expression_parser::TsArg::Field(_) => 1,
                        crate::strategies::mining::expression_parser::TsArg::Expr(e) => max_depth_of(e),
                    }).max().unwrap_or(1),
            }
        }

        for _ in 0..50 {
            let ast = gen.generate();
            assert!(max_depth_of(&ast) <= cfg.max_depth * 2 + 2, "tree too deep");
        }
    }

    #[test]
    fn test_batch_generation_produces_diverse_trees() {
        let cfg = GeneratorConfig::default();
        let mut gen = AlphaGenerator::new(&cfg, 12345);
        let trees = gen.generate_batch(20);
        let unique: std::collections::HashSet<String> =
            trees.iter().map(|t| t.to_string()).collect();
        assert!(unique.len() >= 10, "too few unique trees: {}", unique.len());
    }
}
