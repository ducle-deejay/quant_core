use std::cmp::Ordering;
use std::collections::HashSet;
use std::time::{SystemTime, UNIX_EPOCH};

use super::expression_parser::{collect_fields, AstNode, BinOp, TsArg, TsFunc};

#[derive(Debug, Clone)]
pub struct GaConfig {

    pub population_size: usize,

    pub elite_count: usize,

    pub tournament_size: usize,

    pub crossover_rate: f64,

    pub mutation_rate: f64,

    pub max_generations: usize,

    pub max_tree_depth: usize,
}

impl Default for GaConfig {
    fn default() -> Self {
        GaConfig {
            population_size: 100,
            elite_count: 5,
            tournament_size: 3,
            crossover_rate: 0.7,
            mutation_rate: 0.15,
            max_generations: 50,
            max_tree_depth: 8,
        }
    }
}

pub const UNEVALUATED_FITNESS: f64 = f64::NEG_INFINITY;

#[derive(Debug, Clone)]
pub struct Individual {

    pub ast: AstNode,

    pub dsl_string: String,

    pub fitness: f64,

    pub generation: usize,
}

fn make_individual(ast: AstNode, generation: usize) -> Individual {
    let ast = canonicalize(ast);
    let dsl_string = ast.to_string();
    Individual {
        ast,
        dsl_string,
        fitness: UNEVALUATED_FITNESS,
        generation,
    }
}

pub trait Rng {

    fn next_u64(&mut self) -> u64;

    fn next_f64(&mut self) -> f64 {
        ((self.next_u64() >> 11) as f64) / ((1u64 << 53) as f64)
    }

    fn below(&mut self, n: usize) -> usize {
        if n <= 1 {
            return 0;
        }
        let n64 = n as u64;
        let limit = (u64::MAX / n64) * n64;
        loop {
            let v = self.next_u64();
            if v < limit {
                return (v % n64) as usize;
            }
        }
    }

    fn range_usize(&mut self, lo: usize, hi: usize) -> usize {
        if hi <= lo {
            return lo;
        }
        lo + self.below(hi - lo)
    }

    fn chance(&mut self, p: f64) -> bool {
        if p >= 1.0 {
            return true;
        }
        if p <= 0.0 {
            return false;
        }
        self.next_f64() < p
    }

    fn choose<'a, T>(&mut self, items: &'a [T]) -> Option<&'a T> {
        if items.is_empty() {
            None
        } else {
            items.get(self.below(items.len()))
        }
    }

    fn shuffle<T>(&mut self, items: &mut [T]) {
        let n = items.len();
        if n < 2 {
            return;
        }
        let mut i = n - 1;
        while i > 0 {
            let j = self.below(i + 1);
            items.swap(i, j);
            i -= 1;
        }
    }
}

#[derive(Debug, Clone)]
pub struct XorShift {
    state: u64,
}

impl XorShift {

    pub fn new(seed: u64) -> Self {

        let mut z = seed ^ 0x9E37_79B9_7F4A_7C15;
        z = z.wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z ^= z >> 31;
        z = z.wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^= z >> 30;
        if z == 0 {
            z = 0x9E37_79B9_7F4A_7C15;
        }
        XorShift { state: z }
    }

    pub fn from_time() -> Self {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0x9E37_79B9_7F4A_7C15);
        XorShift::new(nanos)
    }
}

impl Default for XorShift {
    fn default() -> Self {
        XorShift::from_time()
    }
}

impl Rng for XorShift {
    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.state = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
}

const DEFAULT_FIELD_POOL: [&str; 4] = ["close", "open", "volume", "ret"];

const ARITY1_FUNCS: [TsFunc; 8] = [
    TsFunc::Mean,
    TsFunc::Std,
    TsFunc::Delta,
    TsFunc::Delay,
    TsFunc::Sum,
    TsFunc::Rank,
    TsFunc::Zscore,
    TsFunc::Ewma,
];

const BIN_OPS: [BinOp; 4] = [BinOp::Add, BinOp::Sub, BinOp::Mul, BinOp::Div];

const ATOMIC_NUMBERS: [f64; 4] = [0.25, 0.5, 1.0, 2.0];

const MIN_RANDOM_WINDOW: usize = 2;
const MAX_RANDOM_WINDOW: usize = 64;

const WINDOW_HARD_CAP: usize = 1024;

const CROSSOVER_RETRIES: usize = 12;

const OP_SUBSTITUTION: usize = 0;
const FIELD_SWAP: usize = 1;
const WINDOW_PERTURBATION: usize = 2;
const SUBTREE_REPLACEMENT: usize = 3;

pub fn ast_depth(ast: &AstNode) -> usize {
    match ast {
        AstNode::Number(_) | AstNode::Field(_) => 1,
        AstNode::UnaryOp { operand, .. } => 1 + ast_depth(operand),
        AstNode::BinaryOp { left, right, .. } => 1 + ast_depth(left).max(ast_depth(right)),
        AstNode::TsFunc { args, .. } => {
            1 + args
                .iter()
                .map(|arg| match arg {
                    TsArg::Field(_) => 1,
                    TsArg::Expr(inner) => ast_depth(inner),
                })
                .max()
                .unwrap_or(1)
        }
    }
}

pub fn ast_size(ast: &AstNode) -> usize {
    match ast {
        AstNode::Number(_) | AstNode::Field(_) => 1,
        AstNode::UnaryOp { operand, .. } => 1 + ast_size(operand),
        AstNode::BinaryOp { left, right, .. } => 1 + ast_size(left) + ast_size(right),
        AstNode::TsFunc { args, .. } => {
            1 + args
                .iter()
                .map(|arg| match arg {
                    TsArg::Field(_) => 1,
                    TsArg::Expr(inner) => ast_size(inner),
                })
                .sum::<usize>()
        }
    }
}

fn walk_slots<'a>(node: &'a AstNode, level: usize, out: &mut Vec<(&'a AstNode, usize)>) {
    out.push((node, level));
    match node {
        AstNode::Number(_) | AstNode::Field(_) => {}
        AstNode::UnaryOp { operand, .. } => walk_slots(operand, level + 1, out),
        AstNode::BinaryOp { left, right, .. } => {
            walk_slots(left, level + 1, out);
            walk_slots(right, level + 1, out);
        }
        AstNode::TsFunc { args, .. } => {
            for arg in args {
                if let TsArg::Expr(inner) = arg {
                    walk_slots(inner, level + 1, out);
                }
            }
        }
    }
}

fn slots_of(ast: &AstNode) -> Vec<(&AstNode, usize)> {
    let mut out = Vec::new();
    walk_slots(ast, 1, &mut out);
    out
}

fn set_slot_at(root: &mut AstNode, target: usize, replacement: AstNode) {
    let mut holder = Some(replacement);
    let mut counter = 0usize;
    let found = set_slot(root, target, &mut counter, &mut holder);
    debug_assert!(found, "slot index {} out of range", target);
}

fn set_slot(
    node: &mut AstNode,
    target: usize,
    counter: &mut usize,
    holder: &mut Option<AstNode>,
) -> bool {
    if *counter == target {
        *node = holder.take().expect("replacement consumed exactly once");
        return true;
    }
    *counter += 1;
    match node {
        AstNode::Number(_) | AstNode::Field(_) => false,
        AstNode::UnaryOp { operand, .. } => set_slot(operand, target, counter, holder),
        AstNode::BinaryOp { left, right, .. } => {
            set_slot(left, target, counter, holder) || set_slot(right, target, counter, holder)
        }
        AstNode::TsFunc { args, .. } => {
            for arg in args.iter_mut() {
                if let TsArg::Expr(inner) = arg {
                    if set_slot(inner.as_mut(), target, counter, holder) {
                        return true;
                    }
                }
            }
            false
        }
    }
}

fn canonicalize(ast: AstNode) -> AstNode {
    match ast {
        AstNode::Number(_) | AstNode::Field(_) => ast,
        AstNode::UnaryOp { op, operand } => AstNode::UnaryOp {
            op,
            operand: Box::new(canonicalize(*operand)),
        },
        AstNode::BinaryOp { op, left, right } => AstNode::BinaryOp {
            op,
            left: Box::new(canonicalize(*left)),
            right: Box::new(canonicalize(*right)),
        },
        AstNode::TsFunc {
            func,
            args,
            window,
            param,
        } => AstNode::TsFunc {
            func,
            args: args
                .into_iter()
                .map(|arg| match arg {
                    TsArg::Expr(inner) => match canonicalize(*inner) {
                        AstNode::Field(name) => TsArg::Field(name),
                        other => TsArg::Expr(Box::new(other)),
                    },
                    field @ TsArg::Field(_) => field,
                })
                .collect(),
            window,
            param,
        },
    }
}

fn walk_fields<'a>(node: &'a AstNode, out: &mut Vec<&'a str>) {
    match node {
        AstNode::Number(_) => {}
        AstNode::Field(name) => out.push(name),
        AstNode::UnaryOp { operand, .. } => walk_fields(operand, out),
        AstNode::BinaryOp { left, right, .. } => {
            walk_fields(left, out);
            walk_fields(right, out);
        }
        AstNode::TsFunc { args, .. } => {
            for arg in args {
                match arg {
                    TsArg::Field(name) => out.push(name),
                    TsArg::Expr(inner) => walk_fields(inner, out),
                }
            }
        }
    }
}

fn replace_nth_field(node: &mut AstNode, target: usize, counter: &mut usize, new_name: &str) {
    match node {
        AstNode::Field(name) => {
            if *counter == target {
                *name = new_name.to_string();
            }
            *counter += 1;
        }
        AstNode::Number(_) => {}
        AstNode::UnaryOp { operand, .. } => replace_nth_field(operand, target, counter, new_name),
        AstNode::BinaryOp { left, right, .. } => {
            replace_nth_field(left, target, counter, new_name);
            replace_nth_field(right, target, counter, new_name);
        }
        AstNode::TsFunc { args, .. } => {
            for arg in args.iter_mut() {
                match arg {
                    TsArg::Field(name) => {
                        if *counter == target {
                            *name = new_name.to_string();
                        }
                        *counter += 1;
                    }
                    TsArg::Expr(inner) => {
                        replace_nth_field(inner, target, counter, new_name);
                    }
                }
            }
        }
    }
}

fn field_pool(ast: &AstNode) -> Vec<String> {
    let mut pool = collect_fields(ast);
    for name in DEFAULT_FIELD_POOL {
        if !pool.iter().any(|p| p == name) {
            pool.push(name.to_string());
        }
    }
    pool
}

fn random_field(rng: &mut impl Rng, fields: &[String]) -> String {
    if fields.is_empty() {
        return DEFAULT_FIELD_POOL[rng.below(DEFAULT_FIELD_POOL.len())].to_string();
    }
    fields[rng.below(fields.len())].clone()
}

fn random_atom(rng: &mut impl Rng, fields: &[String]) -> AstNode {
    if rng.chance(0.82) {
        AstNode::Field(random_field(rng, fields))
    } else {
        AstNode::Number(ATOMIC_NUMBERS[rng.below(ATOMIC_NUMBERS.len())])
    }
}

fn random_ts_call(rng: &mut impl Rng, budget: usize, fields: &[String]) -> AstNode {
    let use_corr = budget >= 3 && rng.chance(0.18);
    let (func, arity) = if use_corr {
        (TsFunc::Corr, 2)
    } else {
        (ARITY1_FUNCS[rng.below(ARITY1_FUNCS.len())], 1)
    };
    let mut args = Vec::with_capacity(arity);
    for _ in 0..arity {
        if rng.chance(0.72) {
            args.push(TsArg::Field(random_field(rng, fields)));
        } else {
            args.push(TsArg::Expr(Box::new(random_expression(
                rng,
                budget - 1,
                fields,
            ))));
        }
    }
    let window = rng.range_usize(MIN_RANDOM_WINDOW, MAX_RANDOM_WINDOW + 1);
    AstNode::TsFunc {
        func,
        args,
        window,
        param: 0.0,
    }
}

fn random_expression(rng: &mut impl Rng, budget: usize, fields: &[String]) -> AstNode {
    if budget <= 1 {
        return random_atom(rng, fields);
    }
    let roll = rng.next_f64();
    if roll < 0.28 {
        random_atom(rng, fields)
    } else if roll < 0.58 {
        let op = BIN_OPS[rng.below(BIN_OPS.len())];
        let left = random_expression(rng, budget - 1, fields);
        let right = random_expression(rng, budget - 1, fields);
        AstNode::BinaryOp {
            op,
            left: Box::new(left),
            right: Box::new(right),
        }
    } else {
        random_ts_call(rng, budget, fields)
    }
}

pub fn crossover(a: &AstNode, b: &AstNode, rng: &mut impl Rng) -> (AstNode, AstNode) {
    let slots_a = slots_of(a);
    let slots_b = slots_of(b);
    let idx_a = rng.below(slots_a.len());
    let idx_b = rng.below(slots_b.len());

    let sub_a = slots_a[idx_a].0.clone();
    let sub_b = slots_b[idx_b].0.clone();

    let mut child_a = a.clone();
    let mut child_b = b.clone();
    set_slot_at(&mut child_a, idx_a, sub_b);
    set_slot_at(&mut child_b, idx_b, sub_a);
    (canonicalize(child_a), canonicalize(child_b))
}

pub fn mutate(ast: &AstNode, rng: &mut impl Rng, max_depth: usize) -> AstNode {
    if max_depth == 0 {
        return ast.clone();
    }
    let mut kinds = [
        OP_SUBSTITUTION,
        FIELD_SWAP,
        WINDOW_PERTURBATION,
        SUBTREE_REPLACEMENT,
    ];
    rng.shuffle(&mut kinds);
    for &kind in &kinds {
        if let Some(next) = try_mutate_kind(ast, kind, rng, max_depth) {
            return canonicalize(next);
        }
    }
    ast.clone()
}

fn try_mutate_kind(
    ast: &AstNode,
    kind: usize,
    rng: &mut impl Rng,
    max_depth: usize,
) -> Option<AstNode> {
    match kind {
        OP_SUBSTITUTION => mutate_operator(ast, rng),
        FIELD_SWAP => mutate_field(ast, rng),
        WINDOW_PERTURBATION => mutate_window(ast, rng),
        _ => mutate_subtree(ast, rng, max_depth),
    }
}

fn mutate_operator(ast: &AstNode, rng: &mut impl Rng) -> Option<AstNode> {
    let slots = slots_of(ast);
    let mut candidates = Vec::new();
    for (i, entry) in slots.iter().enumerate() {
        if matches!(entry.0, AstNode::TsFunc { .. })
            || matches!(entry.0, AstNode::BinaryOp { .. })
            || matches!(entry.0, AstNode::UnaryOp { .. })
        {
            candidates.push(i);
        }
    }
    let idx = *rng.choose(&candidates)?;
    let replacement = substituted_variant(slots[idx].0, rng)?;
    let mut out = ast.clone();
    set_slot_at(&mut out, idx, replacement);
    Some(out)
}

fn substituted_variant(slot: &AstNode, rng: &mut impl Rng) -> Option<AstNode> {
    match slot {
        AstNode::TsFunc {
            func,
            args,
            window,
            param,
        } => {
            if args.len() >= 2 {

                let mut swapped = args.clone();
                swapped.reverse();
                Some(AstNode::TsFunc {
                    func: *func,
                    args: swapped,
                    window: *window,
                    param: *param,
                })
            } else {
                let alternatives: Vec<TsFunc> = ARITY1_FUNCS
                    .iter()
                    .copied()
                    .filter(|f| *f != *func)
                    .collect();
                let pick = *rng.choose(&alternatives)?;
                Some(AstNode::TsFunc {
                    func: pick,
                    args: args.clone(),
                    window: *window,
                    param: 0.0,
                })
            }
        }
        AstNode::BinaryOp { op, left, right } => {
            let flipped = match op {
                BinOp::Add => BinOp::Sub,
                BinOp::Sub => BinOp::Add,
                BinOp::Mul => BinOp::Div,
                BinOp::Div => BinOp::Mul,
            };
            Some(AstNode::BinaryOp {
                op: flipped,
                left: left.clone(),
                right: right.clone(),
            })
        }
        AstNode::UnaryOp { operand, .. } => Some((**operand).clone()),
        _ => None,
    }
}

fn mutate_field(ast: &AstNode, rng: &mut impl Rng) -> Option<AstNode> {
    let mut occurrences: Vec<&str> = Vec::new();
    walk_fields(ast, &mut occurrences);
    if occurrences.is_empty() {
        return None;
    }
    let n = rng.below(occurrences.len());
    let current = occurrences[n].to_string();

    let mut pool = field_pool(ast);
    pool.retain(|p| *p != current);
    if pool.is_empty() {
        return None;
    }
    let pick = pool[rng.below(pool.len())].clone();

    let mut out = ast.clone();
    let mut counter = 0usize;
    replace_nth_field(&mut out, n, &mut counter, &pick);
    Some(out)
}

fn mutate_window(ast: &AstNode, rng: &mut impl Rng) -> Option<AstNode> {
    let slots = slots_of(ast);
    let mut candidates = Vec::new();
    for (i, entry) in slots.iter().enumerate() {
        if matches!(entry.0, AstNode::TsFunc { .. }) {
            candidates.push(i);
        }
    }
    let idx = *rng.choose(&candidates)?;
    if let AstNode::TsFunc {
        func,
        args,
        window,
        param,
    } = slots[idx].0
    {
        let factor = 0.5 + 1.5 * rng.next_f64();
        let scaled = (*window as f64 * factor).round() as i64;
        let new_window = scaled.clamp(1, WINDOW_HARD_CAP as i64) as usize;
        let replacement = AstNode::TsFunc {
            func: *func,
            args: args.clone(),
            window: new_window,
            param: *param,
        };
        let mut out = ast.clone();
        set_slot_at(&mut out, idx, replacement);
        return Some(out);
    }
    None
}

fn mutate_subtree(ast: &AstNode, rng: &mut impl Rng, max_depth: usize) -> Option<AstNode> {
    let slots = slots_of(ast);
    let idx = rng.below(slots.len());
    let (_, level) = slots[idx];

    let remaining = max_depth as i64 - level as i64 + 1;
    if remaining < 1 {
        return None;
    }
    let budget = remaining as usize;
    let pool = field_pool(ast);
    let fresh = random_expression(rng, budget, &pool);
    let mut out = ast.clone();
    set_slot_at(&mut out, idx, fresh);
    Some(out)
}

fn comparable_fitness(f: f64) -> f64 {
    if f.is_nan() {
        f64::NEG_INFINITY
    } else {
        f
    }
}

fn cmp_fitness_desc(a: &Individual, b: &Individual) -> Ordering {
    comparable_fitness(b.fitness)
        .partial_cmp(&comparable_fitness(a.fitness))
        .unwrap_or(Ordering::Equal)
}

fn tournament_select<'a>(
    population: &'a [Individual],
    k: usize,
    rng: &mut impl Rng,
) -> &'a Individual {
    assert!(
        !population.is_empty(),
        "tournament_select requires a non-empty population"
    );
    let k = k.max(1);
    let mut best = rng
        .choose(population)
        .expect("population checked non-empty");
    for _ in 1..k {
        let candidate = rng
            .choose(population)
            .expect("population checked non-empty");
        if comparable_fitness(candidate.fitness) > comparable_fitness(best.fitness) {
            best = candidate;
        }
    }
    best
}

pub fn initialize_population(
    seeds: &[AstNode],
    config: &GaConfig,
    rng: &mut impl Rng,
) -> Vec<Individual> {
    let capacity = config.population_size.max(1);
    let mut population: Vec<Individual> = Vec::with_capacity(capacity);
    let mut seen: HashSet<String> = HashSet::new();

    for seed in seeds {
        if population.len() == capacity {
            break;
        }
        let dsl = seed.to_string();
        if seen.insert(dsl) {
            population.push(make_individual(seed.clone(), 0));
        }
    }

    let mut seed_fields: Vec<String> = Vec::new();
    for seed in seeds {
        for field in collect_fields(seed) {
            if !seed_fields.contains(&field) {
                seed_fields.push(field);
            }
        }
    }

    let max_depth = config.max_tree_depth.max(1);
    let mut stale_attempts = 0usize;
    while population.len() < capacity {
        let candidate = if !seeds.is_empty() && rng.chance(0.6) {
            let source = seeds[rng.below(seeds.len())].clone();
            mutate(&source, rng, max_depth)
        } else {
            random_expression(rng, max_depth, &seed_fields)
        };
        let dsl = candidate.to_string();
        if seen.insert(dsl) || stale_attempts > 64 || population.is_empty() {
            stale_attempts = 0;
            population.push(make_individual(candidate, 0));
        } else {
            stale_attempts += 1;
        }
    }
    population
}

fn assign_fitness_and_sort(
    population: &mut Vec<Individual>,
    evaluate_fn: &dyn Fn(&[Individual]) -> Vec<f64>,
) {
    if population.is_empty() {
        return;
    }
    let scores = evaluate_fn(population);
    for (ind, score) in population.iter_mut().zip(scores) {
        ind.fitness = score;
    }
    population.sort_by(cmp_fitness_desc);
}

pub fn evolve_generation(
    population: &mut Vec<Individual>,
    config: &GaConfig,
    evaluate_fn: &dyn Fn(&[Individual]) -> Vec<f64>,
    rng: &mut impl Rng,
) {
    if population.is_empty() {
        return;
    }

    assign_fitness_and_sort(population, evaluate_fn);

    let target = config.population_size.max(1);
    let elite_count = config.elite_count.min(population.len()).min(target);
    let tournament_k = config.tournament_size.max(1);

    let mut next: Vec<Individual> = population[..elite_count].to_vec();

    let child_generation = population
        .iter()
        .map(|ind| ind.generation)
        .max()
        .unwrap_or(0)
        + 1;

    while next.len() < target {
        let parent_a = tournament_select(population, tournament_k, rng);
        let parent_b = tournament_select(population, tournament_k, rng);

        let (mut child_a, mut child_b) =
            if parent_a.dsl_string == parent_b.dsl_string || !rng.chance(config.crossover_rate) {
                (parent_a.ast.clone(), parent_b.ast.clone())
            } else {
                breed_within_depth(&parent_a.ast, &parent_b.ast, config.max_tree_depth, rng)
            };

        for child in [&mut child_a, &mut child_b] {
            if rng.chance(config.mutation_rate) {
                *child = mutate(child, rng, config.max_tree_depth);
            }
        }

        for child_ast in [child_a, child_b] {
            if next.len() >= target {
                break;
            }
            next.push(make_individual(child_ast, child_generation));
        }
    }

    *population = next;
}

fn breed_within_depth(
    a: &AstNode,
    b: &AstNode,
    max_depth: usize,
    rng: &mut impl Rng,
) -> (AstNode, AstNode) {
    for _ in 0..CROSSOVER_RETRIES {
        let (ca, cb) = crossover(a, b, rng);
        if ast_depth(&ca) <= max_depth && ast_depth(&cb) <= max_depth {
            return (ca, cb);
        }
    }
    (a.clone(), b.clone())
}

pub fn run_ga(
    seeds: &[AstNode],
    config: &GaConfig,
    evaluate_fn: impl Fn(&[Individual]) -> Vec<f64>,
    rng: &mut impl Rng,
) -> Vec<Individual> {
    let mut population = initialize_population(seeds, config, rng);
    if population.is_empty() {
        return population;
    }
    for _ in 0..config.max_generations {
        evolve_generation(&mut population, config, &evaluate_fn, rng);
        if population.is_empty() {
            return population;
        }
    }
    assign_fitness_and_sort(&mut population, &evaluate_fn);
    population
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::strategies::mining::{build_dag, execute_batch, parse};
    use std::collections::HashMap;

    const SEED_SOURCES: [&str; 4] = [
        "ts_zscore(ts_delta(close, 1), 20)",
        "ts_corr(close, volume, 20)",
        "ts_rank(close / open, 12) - 0.5",
        "-ts_delta(close, 5) / ts_delay(close, 5)",
    ];

    fn seed_asts() -> Vec<AstNode> {
        SEED_SOURCES
            .iter()
            .map(|s| parse(s).unwrap_or_else(|e| panic!("seed '{}' failed: {}", s, e)))
            .collect()
    }

    fn test_config() -> GaConfig {
        GaConfig {
            population_size: 24,
            elite_count: 3,
            tournament_size: 3,
            crossover_rate: 0.8,
            mutation_rate: 0.35,
            max_generations: 8,
            max_tree_depth: 6,
        }
    }

    fn assert_round_trip(ast: &AstNode) {
        let printed = ast.to_string();
        let reparsed =
            parse(&printed).unwrap_or_else(|e| panic!("re-parse '{}' failed: {}", printed, e));
        assert_eq!(reparsed, *ast, "round-trip mismatch for '{}'", printed);
    }

    fn string_fitness(s: &str) -> f64 {
        let mut h: u64 = 0xcbf2_9ce4_8422_2325;
        for b in s.bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x100_0000_01b3);
        }
        ((h % 2001) as f64 - 1000.0) / 1000.0
    }

    fn synthetic_data(n: usize, seed: u64) -> HashMap<String, Vec<f64>> {
        let mut rng = XorShift::new(seed);
        let mut close = Vec::with_capacity(n);
        let mut volume = Vec::with_capacity(n);
        let mut price = 100.0f64;
        let mut vol = 1_000_000.0f64;
        for _ in 0..n {
            price *= 1.0 + (rng.next_f64() - 0.5) * 0.02;
            vol *= 1.0 + (rng.next_f64() - 0.5) * 0.05;
            close.push(price);
            volume.push(vol);
        }
        let mut ret = vec![0.0f64; n];
        for t in 1..n {
            ret[t] = close[t] / close[t - 1] - 1.0;
        }
        let mut data = HashMap::new();
        data.insert("close".to_string(), close);
        data.insert("volume".to_string(), volume);
        data.insert("ret".to_string(), ret);
        data
    }

    fn ic_proxy(alpha: &[f64], forward_ret: &[f64]) -> f64 {
        let mut acc = 0.0;
        let mut count = 0usize;
        let n = alpha.len().min(forward_ret.len());
        for t in 0..n {
            let a = alpha[t];
            let f = forward_ret[t];
            if a.is_finite() && f.is_finite() {
                acc += a * f;
                count += 1;
            }
        }
        if count == 0 {
            -1.0
        } else {
            let score = acc / count as f64;
            if score.is_finite() {
                score
            } else {
                -1.0
            }
        }
    }

    #[test]
    fn xorshift_is_reproducible_and_seed_sensitive() {
        let mut a = XorShift::new(42);
        let mut b = XorShift::new(42);
        for _ in 0..128 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
        let mut c = XorShift::new(43);
        let seq_a: Vec<u64> = (0..16).map(|_| a.next_u64()).collect();
        let seq_c: Vec<u64> = (0..16).map(|_| c.next_u64()).collect();
        assert_ne!(seq_a, seq_c);
    }

    #[test]
    fn rng_helpers_respect_bounds_and_balance() {
        let mut rng = XorShift::new(9);
        for _ in 0..2000 {
            assert!(rng.below(7) < 7);
            let r = rng.range_usize(3, 5);
            assert!((3..5).contains(&r));
            let f = rng.next_f64();
            assert!((0.0..1.0).contains(&f));
        }
        assert_eq!(rng.below(0), 0);
        assert_eq!(rng.below(1), 0);
        let heads = (0..4000).filter(|_| rng.chance(0.5)).count();
        assert!(heads > 1700 && heads < 2300, "coin balance off: {}", heads);
    }

    #[test]
    fn seeds_parse_into_valid_asts() {
        let asts = seed_asts();
        assert_eq!(asts.len(), SEED_SOURCES.len());
        for (ast, src) in asts.iter().zip(SEED_SOURCES.iter()) {
            assert_round_trip(ast);
            assert!(!collect_fields(ast).is_empty(), "{}", src);
        }

        let nested = parse("-ts_zscore(ts_corr(ts_mean(close, 5), volume, 20), 60)").unwrap();
        assert_eq!(ast_depth(&nested), 5);
    }

    #[test]
    fn crossover_produces_valid_trees_with_conserved_total_size() {
        let a = parse("ts_corr(ts_mean(close, 5), volume, 20)").unwrap();
        let b = parse("-ts_delta(open, 3) * ts_rank(ret, 12)").unwrap();
        let total_before = ast_size(&a) + ast_size(&b);
        let mut rng = XorShift::new(77);
        let mut saw_change = false;
        for _ in 0..300 {
            let (ca, cb) = crossover(&a, &b, &mut rng);
            assert_round_trip(&ca);
            assert_round_trip(&cb);
            assert_eq!(ast_size(&ca) + ast_size(&cb), total_before);
            if ca != a || cb != b {
                saw_change = true;
            }
        }
        assert!(saw_change, "crossover never changed anything in 300 tries");
    }

    #[test]
    fn crossover_on_atoms_swaps_whole_trees() {
        let a = parse("close").unwrap();
        let b = parse("ts_rank(volume, 10)").unwrap();
        let mut rng = XorShift::new(11);
        for _ in 0..50 {
            let (ca, cb) = crossover(&a, &b, &mut rng);
            assert_round_trip(&ca);
            assert_round_trip(&cb);
        }
    }

    #[test]
    fn mutation_preserves_tree_validity_and_depth_budget() {
        let base = parse("ts_zscore(ts_corr(close, open, 20) / ts_delay(volume, 3), 40)").unwrap();
        assert!(ast_depth(&base) <= 6);
        let mut rng = XorShift::new(2024);
        for _ in 0..300 {
            let m = mutate(&base, &mut rng, 6);
            assert_round_trip(&m);
            assert!(ast_depth(&m) <= 6, "depth {} exceeds budget", ast_depth(&m));
        }
    }

    #[test]
    fn mutation_explores_operators_fields_windows_and_structure() {
        let base = parse("ts_mean(close, 20)").unwrap();
        let mut rng = XorShift::new(31337);
        let mut func_changed = false;
        let mut field_changed = false;
        let mut window_changed = false;
        for _ in 0..80 {
            let m = mutate(&base, &mut rng, 8);
            assert_round_trip(&m);
            if let AstNode::TsFunc { func, window, .. } = &m {
                if *func != TsFunc::Mean {
                    func_changed = true;
                }
                if *window != 20 {
                    window_changed = true;
                }
                assert!(*window >= 1 && *window <= WINDOW_HARD_CAP);
            }
            let fields = collect_fields(&m);
            if !fields.is_empty() && fields[0] != "close" {
                field_changed = true;
            }
        }
        assert!(func_changed, "operator substitution never fired");
        assert!(field_changed, "field swap never fired");
        assert!(window_changed, "window perturbation never fired");
    }

    #[test]
    fn mutation_respects_zero_and_tiny_depth_budgets() {

        let bases = [
            parse("-ts_delta(close, 3)").unwrap(),
            parse("volume - ts_mean(open, 5)").unwrap(),
        ];
        assert!(bases.iter().all(|b| ast_depth(b) <= 3));
        let mut rng = XorShift::new(5);
        let frozen = mutate(&bases[0], &mut rng, 0);
        assert_eq!(frozen, bases[0]);
        for base in &bases {
            for _ in 0..150 {
                let m = mutate(base, &mut rng, 3);
                assert_round_trip(&m);
                assert!(ast_depth(&m) <= 3, "depth {} exceeds budget", ast_depth(&m));
            }
        }
    }

    #[test]
    fn tournament_select_prefers_the_best_candidate() {
        let mut pop: Vec<Individual> = ["close", "open", "volume"]
            .iter()
            .map(|f| make_individual(parse(f).unwrap(), 0))
            .collect();
        pop[0].fitness = 0.1;
        pop[1].fitness = 0.9;
        pop[2].fitness = -0.5;
        let mut rng = XorShift::new(5);
        for _ in 0..200 {
            let picked = tournament_select(&pop, 64, &mut rng);
            assert_eq!(picked.fitness, 0.9);
        }
    }

    #[test]
    fn fitness_ordering_treats_nan_as_worst() {
        let mut a = make_individual(parse("close").unwrap(), 0);
        let mut b = make_individual(parse("open").unwrap(), 0);

        a.fitness = f64::NAN;
        b.fitness = -1.0;
        assert_eq!(cmp_fitness_desc(&a, &b), Ordering::Greater);
        assert_eq!(cmp_fitness_desc(&b, &a), Ordering::Less);

        b.fitness = UNEVALUATED_FITNESS;
        assert_eq!(cmp_fitness_desc(&a, &b), Ordering::Equal);
    }

    #[test]
    fn initialized_population_embeds_seeds_and_unique_dsl_strings() {
        let cfg = test_config();
        let seeds = seed_asts();
        let mut rng = XorShift::new(101);
        let pop = initialize_population(&seeds, &cfg, &mut rng);

        assert_eq!(pop.len(), cfg.population_size);
        let unique: HashSet<&String> = pop.iter().map(|i| &i.dsl_string).collect();
        assert_eq!(unique.len(), pop.len(), "duplicate individuals in init");
        for seed in &seeds {
            let expected = seed.to_string();
            assert!(
                pop.iter().any(|i| i.dsl_string == expected),
                "seed '{}' missing from population",
                expected
            );
        }
        for ind in &pop {
            assert_eq!(ind.generation, 0);
            assert_eq!(ind.fitness, UNEVALUATED_FITNESS);
            assert_round_trip(&ind.ast);
            assert!(ast_depth(&ind.ast) <= cfg.max_tree_depth);
        }
    }

    #[test]
    fn seed_overflow_truncates_to_population_size() {
        let cfg = GaConfig {
            population_size: 3,
            ..test_config()
        };
        let seeds = seed_asts();
        let mut rng = XorShift::new(7);
        let pop = initialize_population(&seeds, &cfg, &mut rng);
        assert_eq!(pop.len(), 3);
        assert!(pop.iter().all(|i| i.generation == 0));
    }

    #[test]
    fn empty_seeds_still_fill_the_population_randomly() {
        let cfg = test_config();
        let mut rng = XorShift::new(13);
        let pop = initialize_population(&[], &cfg, &mut rng);
        assert_eq!(pop.len(), cfg.population_size);
        for ind in &pop {
            assert_round_trip(&ind.ast);
            assert!(ast_depth(&ind.ast) <= cfg.max_tree_depth);
        }
    }

    #[test]
    fn population_size_maintained_across_generations() {
        let cfg = test_config();
        let seeds = seed_asts();
        let eval = |pop: &[Individual]| -> Vec<f64> {
            pop.iter()
                .map(|i| string_fitness(&i.dsl_string))
                .collect::<Vec<f64>>()
        };
        let mut rng = XorShift::new(2027);
        let mut pop = initialize_population(&seeds, &cfg, &mut rng);
        for gen in 1..=6 {
            evolve_generation(&mut pop, &cfg, &eval, &mut rng);
            assert_eq!(pop.len(), cfg.population_size, "generation {}", gen);
            assert!(
                pop.iter().any(|i| i.generation == gen),
                "no generation-{} offspring produced",
                gen
            );
        }
    }

    #[test]
    fn best_fitness_never_decreases_with_elitism_enabled() {
        let cfg = GaConfig {
            elite_count: 4,
            ..test_config()
        };
        let seeds = seed_asts();
        let eval = |pop: &[Individual]| -> Vec<f64> {
            pop.iter()
                .map(|i| string_fitness(&i.dsl_string))
                .collect::<Vec<f64>>()
        };
        let mut rng = XorShift::new(4242);
        let mut pop = initialize_population(&seeds, &cfg, &mut rng);
        let mut best_so_far = f64::NEG_INFINITY;
        for _ in 0..12 {
            evolve_generation(&mut pop, &cfg, &eval, &mut rng);
            let current_best = pop.iter().fold(f64::NEG_INFINITY, |m, i| {
                m.max(comparable_fitness(i.fitness))
            });
            assert!(
                current_best >= best_so_far,
                "best fitness regressed: {} < {}",
                current_best,
                best_so_far
            );
            best_so_far = best_so_far.max(current_best);
        }
        assert!(best_so_far > f64::NEG_INFINITY);
    }

    #[test]
    fn depth_limit_enforced_across_full_run() {
        let cfg = GaConfig {
            population_size: 30,
            elite_count: 4,
            tournament_size: 3,
            crossover_rate: 0.9,
            mutation_rate: 0.5,
            max_generations: 10,
            max_tree_depth: 4,
        };
        let seeds = seed_asts();
        let eval = |pop: &[Individual]| -> Vec<f64> {
            pop.iter()
                .map(|i| string_fitness(&i.dsl_string))
                .collect::<Vec<f64>>()
        };
        let mut rng = XorShift::new(999);
        let final_pop = run_ga(&seeds, &cfg, eval, &mut rng);
        assert_eq!(final_pop.len(), cfg.population_size);
        for ind in &final_pop {
            assert!(
                ast_depth(&ind.ast) <= cfg.max_tree_depth,
                "'{}' reached depth {}",
                ind.dsl_string,
                ast_depth(&ind.ast)
            );
        }
    }

    #[test]
    fn empty_population_is_a_noop() {
        let cfg = test_config();
        let eval = |pop: &[Individual]| -> Vec<f64> { vec![0.0; pop.len()] };
        let mut rng = XorShift::new(1);
        let mut pop: Vec<Individual> = Vec::new();
        evolve_generation(&mut pop, &cfg, &eval, &mut rng);
        assert!(pop.is_empty());
    }

    #[test]
    fn all_zero_fitness_evolution_remains_stable() {
        let cfg = GaConfig {
            population_size: 12,
            elite_count: 2,
            ..test_config()
        };
        let seeds = seed_asts();
        let eval = |pop: &[Individual]| -> Vec<f64> { vec![0.0; pop.len()] };
        let mut rng = XorShift::new(88);
        let final_pop = run_ga(&seeds, &cfg, eval, &mut rng);
        assert_eq!(final_pop.len(), cfg.population_size);
        for ind in &final_pop {
            assert_eq!(ind.fitness, 0.0);
            assert_round_trip(&ind.ast);
        }
    }

    #[test]
    fn single_individual_population_survives_evolution() {
        let cfg = GaConfig {
            population_size: 1,
            elite_count: 1,
            tournament_size: 1,
            crossover_rate: 0.0,
            mutation_rate: 0.0,
            max_generations: 5,
            max_tree_depth: 6,
        };
        let seeds = vec![parse("ts_mean(close, 10)").unwrap()];
        let eval = |pop: &[Individual]| -> Vec<f64> { vec![1.5; pop.len()] };
        let mut rng = XorShift::new(2);
        let final_pop = run_ga(&seeds, &cfg, eval, &mut rng);
        assert_eq!(final_pop.len(), 1);
        assert_eq!(final_pop[0].fitness, 1.5);
        assert_round_trip(&final_pop[0].ast);
    }

    #[test]
    fn run_ga_end_to_end_with_batch_executor_fitness() {
        let cfg = GaConfig {
            population_size: 20,
            elite_count: 4,
            tournament_size: 3,
            crossover_rate: 0.75,
            mutation_rate: 0.3,
            max_generations: 6,
            max_tree_depth: 6,
        };
        let n = 180;
        let data = synthetic_data(n, 7);
        let forward_ret: Vec<f64> = data["ret"][1..].to_vec();

        let eval = move |pop: &[Individual]| -> Vec<f64> {
            pop.iter()
                .map(|ind| {

                    let ast = match parse(&ind.dsl_string) {
                        Ok(ast) => ast,
                        Err(_) => return f64::NEG_INFINITY,
                    };
                    let dag = build_dag(std::slice::from_ref(&ast));
                    let rows = execute_batch(&dag, &data, &dag.roots);
                    ic_proxy(&rows[0], &forward_ret)
                })
                .collect::<Vec<f64>>()
        };

        let seeds = seed_asts();
        let mut rng = XorShift::new(555);
        let final_pop = run_ga(&seeds, &cfg, eval, &mut rng);

        assert_eq!(final_pop.len(), cfg.population_size);
        assert_eq!(
            final_pop.iter().map(|i| i.generation).max().unwrap(),
            cfg.max_generations,
            "offspring generations should advance to the last generation"
        );

        for pair in final_pop.windows(2) {
            assert!(
                comparable_fitness(pair[0].fitness) >= comparable_fitness(pair[1].fitness),
                "population not sorted: {} vs {}",
                pair[0].fitness,
                pair[1].fitness
            );
        }

        for ind in &final_pop {
            assert_round_trip(&ind.ast);
            assert_eq!(ind.dsl_string, ind.ast.to_string());
            assert!(ind.fitness.is_finite(), "unevaluated individual survived");
        }
        assert!(final_pop[0].fitness > final_pop[cfg.population_size - 1].fitness);
    }

    #[test]
    fn dsl_round_trip_holds_for_every_evolved_individual() {
        let cfg = test_config();
        let seeds = seed_asts();
        let eval = |pop: &[Individual]| -> Vec<f64> {
            pop.iter()
                .map(|i| string_fitness(&i.dsl_string))
                .collect::<Vec<f64>>()
        };
        let mut rng = XorShift::new(31415);
        let final_pop = run_ga(&seeds, &cfg, eval, &mut rng);
        assert!(!final_pop.is_empty());
        for ind in &final_pop {
            let reparsed = parse(&ind.dsl_string)
                .unwrap_or_else(|e| panic!("'{}' failed to re-parse: {}", ind.dsl_string, e));
            assert_eq!(reparsed, ind.ast);
        }
    }
}
