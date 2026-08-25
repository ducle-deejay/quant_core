//! Vectorised execution of a [`ComputationDag`] over full time-series columns.
//!
//! [`execute_batch`] evaluates every unique DAG node once, in topological
//! order, over entire arrays: each rolling operator is a single-pass,
//! whole-series transform with O(1) amortised sliding accumulators (the
//! rolling rank keeps a sorted window and advances it by binary search +
//! insert). Results are memoised per node id so shared sub-expressions are
//! computed exactly once per batch, and the returned matrix holds one score
//! series (row) per requested alpha root.
//!
//! # Contracts
//!
//! * Columns are aligned: index `t` refers to the same bar in every series.
//! * Binary/unary operators produce `max(len)` outputs; positions beyond the
//!   shorter operand are NaN. Division follows IEEE-754 (`x/0 = +/-inf`,
//!   `0/0 = NaN`).
//! * Rolling functions output one value per input bar. The first
//!   `window - 1` bars are NaN warmup. A window containing any NaN yields NaN
//!   (except delay/delta, which simply shift their inputs).
//! * Degenerate statistics are NaN: sample std with `window < 2`, z-scores
//!   against zero-variance windows, correlations with an undefined
//!   denominator.
//! * Missing data fields evaluate to all-NaN columns of the longest column's
//!   length (length 0 when `data` is empty); numeric constants broadcast to
//!   that same default length.
//! * `alpha_roots` entries must be valid DAG node ids (panics otherwise).

use std::collections::HashMap;
use std::collections::VecDeque;

use super::dag_builder::ComputationDag;
use super::expression_parser::{AstNode, BinOp, TsFunc, UnaryOp};
use super::operators;

/// Execute all DAG nodes on data columns, producing scores for each alpha.
///
/// `data` maps field names to their time-series arrays.
/// `alpha_roots` are the DAG node IDs corresponding to each alpha's final
/// output. Returns a matrix where row i = score series for alpha i.
pub fn execute_batch(
    dag: &ComputationDag,
    data: &HashMap<String, Vec<f64>>,
    alpha_roots: &[usize],
) -> Vec<Vec<f64>> {
    for (i, &root) in alpha_roots.iter().enumerate() {
        assert!(
            root < dag.nodes.len(),
            "alpha_roots[{}] = {} is not a valid DAG node id",
            i,
            root
        );
    }

    let default_len = data.values().map(|v| v.len()).max().unwrap_or(0);
    let mut cache: Vec<Option<Vec<f64>>> = vec![None; dag.nodes.len()];
    for &id in &dag.execution_order {
        let node = &dag.nodes[id];
        let value = eval_node(node, data, &cache, default_len);
        cache[id] = Some(value);
    }

    alpha_roots
        .iter()
        .map(|&root| {
            cache[root]
                .as_ref()
                .expect("root evaluated during forward pass")
                .clone()
        })
        .collect()
}

fn cached<'a>(cache: &'a [Option<Vec<f64>>], id: usize) -> &'a Vec<f64> {
    cache[id]
        .as_ref()
        .expect("dependency must be evaluated before its parent")
}

fn eval_node(
    node: &super::dag_builder::DagNode,
    data: &HashMap<String, Vec<f64>>,
    cache: &[Option<Vec<f64>>],
    default_len: usize,
) -> Vec<f64> {
    match &node.ast {
        AstNode::Number(v) => vec![*v; default_len],
        AstNode::Field(name) => match data.get(name) {
            Some(column) => column.clone(),
            None => vec![f64::NAN; default_len],
        },
        AstNode::UnaryOp {
            op: UnaryOp::Neg,
            operand: _,
        } => {
            let xs = cached(cache, node.dependencies[0]);
            xs.iter().map(|x| -x).collect()
        }
        AstNode::BinaryOp { op, .. } => {
            let lhs = cached(cache, node.dependencies[0]);
            let rhs = cached(cache, node.dependencies[1]);
            zip_align(lhs, rhs, arith_fn(*op))
        }
        AstNode::TsFunc {
            func,
            args: _,
            window,
            param,
        } => {
            let inputs: Vec<&[f64]> = node
                .dependencies
                .iter()
                .map(|&dep| cached(cache, dep).as_slice())
                .collect();
            apply_ts(*func, &inputs, *window, *param)
        }
    }
}

fn arith_fn(op: BinOp) -> fn(f64, f64) -> f64 {
    match op {
        BinOp::Add => |a: f64, b: f64| a + b,
        BinOp::Sub => |a: f64, b: f64| a - b,
        BinOp::Mul => |a: f64, b: f64| a * b,
        BinOp::Div => |a: f64, b: f64| a / b,
    }
}

/// Element-wise binary op over possibly unequal-length operands; positions
/// missing one operand become NaN.
fn zip_align(a: &[f64], b: &[f64], f: fn(f64, f64) -> f64) -> Vec<f64> {
    let n = a.len().max(b.len());
    (0..n)
        .map(|i| match (a.get(i), b.get(i)) {
            (Some(&x), Some(&y)) => f(x, y),
            _ => f64::NAN,
        })
        .collect()
}

/// Dispatch a parsed time-series / cross-sectional function over evaluated
/// dependency columns. `window` is meaningful only for windowed functions;
/// `param` only for those with a scalar parameter (quantile level, scale
/// target). Cross-sectional and element-wise operators receive columns
/// padded to a common length with NaN.
fn apply_ts(func: TsFunc, inputs: &[&[f64]], window: usize, param: f64) -> Vec<f64> {
    match func {
        // ----- original rolling operators ---------------------------------
        TsFunc::Delay => rolling_delay(inputs[0], window),
        TsFunc::Delta => rolling_delta(inputs[0], window),
        TsFunc::Sum => rolling_sum(inputs[0], window),
        TsFunc::Mean => rolling_mean(inputs[0], window),
        TsFunc::Std => rolling_std(inputs[0], window),
        TsFunc::Zscore => rolling_zscore(inputs[0], window),
        TsFunc::Rank => rolling_rank(inputs[0], window),
        TsFunc::Corr => {
            assert!(
                inputs.len() >= 2,
                "ts_corr node requires exactly 2 input dependencies"
            );
            rolling_corr(inputs[0], inputs[1], window)
        }
        TsFunc::Ewma => ewma_span(inputs[0], window),
        // ----- rolling statistics ------------------------------------------
        TsFunc::Min => operators::ts_min(inputs[0], window),
        TsFunc::Max => operators::ts_max(inputs[0], window),
        TsFunc::Median => operators::ts_median(inputs[0], window),
        TsFunc::Quantile => operators::ts_quantile(inputs[0], param, window),
        TsFunc::Skewness => operators::ts_skewness(inputs[0], window),
        TsFunc::Kurtosis => operators::ts_kurtosis(inputs[0], window),
        TsFunc::Ir => operators::ts_ir(inputs[0], window),
        TsFunc::Product => operators::ts_product(inputs[0], window),
        // ----- positioning and distance --------------------------------------
        TsFunc::ArgMax => operators::ts_argmax(inputs[0], window),
        TsFunc::ArgMin => operators::ts_argmin(inputs[0], window),
        TsFunc::MaxDiff => operators::ts_max_diff(inputs[0], window),
        TsFunc::MinDiff => operators::ts_min_diff(inputs[0], window),
        TsFunc::Scale => operators::ts_scale(inputs[0], window),
        TsFunc::QuantilePos => operators::ts_quantile_pos(inputs[0], window),
        // ----- decay -----------------------------------------------------------
        TsFunc::DecayLinear => operators::ts_decay_linear(inputs[0], window),
        // ----- regression and relationship -------------------------------------
        TsFunc::RegressionResid | TsFunc::RegressionBeta | TsFunc::Covariance => {
            assert!(
                inputs.len() >= 2,
                "{} node requires exactly 2 input dependencies",
                func.name()
            );
            match func {
                TsFunc::RegressionResid => {
                    operators::ts_regression_resid(inputs[0], inputs[1], window)
                }
                TsFunc::RegressionBeta => {
                    operators::ts_regression_beta(inputs[0], inputs[1], window)
                }
                _ => operators::ts_covariance(inputs[0], inputs[1], window),
            }
        }
        // ----- momentum and returns ---------------------------------------------
        TsFunc::Returns => operators::ts_returns(inputs[0], window),
        TsFunc::SignDelta => operators::ts_sign_delta(inputs[0], window),
        TsFunc::TrendSlope => operators::ts_trend_slope(inputs[0], window),
        // ----- utility ------------------------------------------------------------
        TsFunc::Backfill => operators::ts_backfill(inputs[0], window),
        TsFunc::CountValid => operators::ts_count_valid(inputs[0], window),
        // ----- cross-sectional / element-wise --------------------------------
        TsFunc::CsRank
        | TsFunc::CsZscore
        | TsFunc::CsDemean
        | TsFunc::Abs
        | TsFunc::Log
        | TsFunc::Sign => {
            assert!(
                !inputs.is_empty(),
                "{} node requires exactly 1 input dependency",
                func.name()
            );
            let cols = aligned_columns(inputs);
            match func {
                TsFunc::CsRank => operators::cs_rank(&cols[0]),
                TsFunc::CsZscore => operators::cs_zscore(&cols[0]),
                TsFunc::CsDemean => operators::cs_demean(&cols[0]),
                TsFunc::Abs => operators::abs_val(&cols[0]),
                TsFunc::Log => operators::log_nat(&cols[0]),
                _ => operators::sign_of(&cols[0]),
            }
        }
        TsFunc::CsScale => {
            assert!(
                !inputs.is_empty(),
                "cs_scale node requires exactly 1 input dependency"
            );
            let cols = aligned_columns(inputs);
            operators::cs_scale(&cols[0], param)
        }
        TsFunc::ElemMax | TsFunc::ElemMin => {
            assert!(
                inputs.len() >= 2,
                "{} node requires exactly 2 input dependencies",
                func.name()
            );
            let cols = aligned_columns(inputs);
            if func == TsFunc::ElemMax {
                operators::elem_max(&cols[0], &cols[1])
            } else {
                operators::elem_min(&cols[0], &cols[1])
            }
        }
        TsFunc::IfElse => {
            assert!(
                inputs.len() >= 3,
                "if_else node requires exactly 3 input dependencies"
            );
            let cols = aligned_columns(inputs);
            // DSL conditions are numeric columns: finite and non-zero means
            // take the 'then' branch; NaN conditions count as false.
            let cond: Vec<bool> = cols[0].iter().map(|&v| v.is_finite() && v != 0.0).collect();
            operators::if_else(&cond, &cols[1], &cols[2])
        }
    }
}

/// Own copies of the dependency columns padded to a common length so the
/// whole-array cross-sectional operators see aligned inputs (shorter columns
/// are NaN-filled, matching the binary-op alignment contract).
fn aligned_columns(inputs: &[&[f64]]) -> Vec<Vec<f64>> {
    let n = inputs.iter().map(|c| c.len()).max().unwrap_or(0);
    inputs
        .iter()
        .map(|c| {
            let mut owned = c.to_vec();
            owned.resize(n, f64::NAN);
            owned
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Rolling primitives
//
// All functions return one output bar per input bar; the first `window - 1`
// bars are warmup NaN. A `window` of 0 (unreachable through the parser)
// defensively yields all NaN.
// ---------------------------------------------------------------------------

/// Sliding-window moment accumulator: tracks count, sum and sum of squares of
/// the values currently inside the window plus its NaN count, in O(1)
/// amortised per bar. Powers ts_sum / ts_mean / ts_std / ts_zscore.
struct MomentWindow {
    buf: VecDeque<f64>,
    cap: usize,
    sum: f64,
    sum_sq: f64,
    nan_count: usize,
}

impl MomentWindow {
    fn new(cap: usize) -> Self {
        MomentWindow {
            buf: VecDeque::with_capacity(cap.max(1)),
            cap,
            sum: 0.0,
            sum_sq: 0.0,
            nan_count: 0,
        }
    }

    fn push(&mut self, v: f64) {
        if self.buf.len() == self.cap {
            self.evict_front();
        }
        self.buf.push_back(v);
        if v.is_nan() {
            self.nan_count += 1;
        } else {
            self.sum += v;
            self.sum_sq += v * v;
        }
    }

    fn evict_front(&mut self) {
        if let Some(old) = self.buf.pop_front() {
            if old.is_nan() {
                self.nan_count -= 1;
            } else {
                self.sum -= old;
                self.sum_sq -= old * old;
            }
        }
    }

    /// True once the window is full and free of NaN values.
    fn valid(&self) -> bool {
        self.nan_count == 0 && self.buf.len() == self.cap
    }

    fn mean(&self) -> f64 {
        self.sum / self.cap as f64
    }

    /// Sample variance (ddof = 1). Returns None when undefined (window < 2,
    /// NaN contamination) or numerically negative; exact zero is preserved so
    /// flat windows yield a defined 0.0 std.
    fn sample_variance(&self) -> Option<f64> {
        if self.cap < 2 || !self.valid() {
            return None;
        }
        let w = self.cap as f64;
        let var = (self.sum_sq - self.sum * self.sum / w) / (w - 1.0);
        if var.is_finite() && var >= 0.0 {
            Some(var)
        } else {
            None
        }
    }
}

/// Rolling sum over trailing windows.
pub fn rolling_sum(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window > x.len() {
        return out;
    }
    let mut win = MomentWindow::new(window);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if t + 1 >= window && win.valid() {
            out[t] = win.sum;
        }
    }
    out
}

/// Rolling arithmetic mean over trailing windows.
pub fn rolling_mean(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window > x.len() {
        return out;
    }
    let mut win = MomentWindow::new(window);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if t + 1 >= window && win.valid() {
            out[t] = win.mean();
        }
    }
    out
}

/// Rolling sample standard deviation (ddof = 1) over trailing windows.
/// Windows shorter than 2 bars yield NaN; a constant window yields 0.0.
pub fn rolling_std(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window > x.len() {
        return out;
    }
    let mut win = MomentWindow::new(window);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if t + 1 >= window {
            if let Some(var) = win.sample_variance() {
                out[t] = var.sqrt();
            }
        }
    }
    out
}

/// Rolling z-score `(x[t] - mean_w(x)) / std_w(x)` with sample std.
/// Zero-variance windows yield NaN.
pub fn rolling_zscore(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window > x.len() {
        return out;
    }
    let mut win = MomentWindow::new(window);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if t + 1 >= window {
            if let Some(var) = win.sample_variance() {
                if var > 0.0 {
                    out[t] = (v - win.mean()) / var.sqrt();
                }
            }
        }
    }
    out
}

/// Shift a series forward by `window` bars: `out[t] = x[t - window]`.
pub fn rolling_delay(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window >= x.len() {
        return out;
    }
    // Single memcpy for the shifted region.
    out[window..].copy_from_slice(&x[..x.len() - window]);
    out
}

/// Difference against `window` bars ago: `out[t] = x[t] - x[t - window]`.
pub fn rolling_delta(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window >= x.len() {
        return out;
    }
    for t in window..x.len() {
        out[t] = x[t] - x[t - window];
    }
    out
}

/// Sliding Pearson correlation between two series over trailing windows.
/// Windows where either series has zero variance or contains NaN yield NaN.
pub fn rolling_corr(x: &[f64], y: &[f64], window: usize) -> Vec<f64> {
    let n = x.len().min(y.len());
    let mut out = vec![f64::NAN; n.max(x.len()).max(y.len())];
    if window == 0 || window > n {
        return out;
    }
    let mut buf: VecDeque<(f64, f64)> = VecDeque::with_capacity(window);
    let (mut sx, mut sy, mut sxx, mut syy, mut sxy) = (0.0, 0.0, 0.0, 0.0, 0.0);
    let mut bad = 0usize;
    for t in 0..n {
        let pair = (x[t], y[t]);
        if buf.len() == window {
            let (ox, oy) = buf.pop_front().expect("non-empty buffer");
            if ox.is_nan() || oy.is_nan() {
                bad -= 1;
            } else {
                sx -= ox;
                sy -= oy;
                sxx -= ox * ox;
                syy -= oy * oy;
                sxy -= ox * oy;
            }
        }
        buf.push_back(pair);
        let (vx, vy) = pair;
        if vx.is_nan() || vy.is_nan() {
            bad += 1;
        } else {
            sx += vx;
            sy += vy;
            sxx += vx * vx;
            syy += vy * vy;
            sxy += vx * vy;
        }
        if t + 1 >= window && bad == 0 {
            let w = window as f64;
            let mx = sx / w;
            let my = sy / w;
            let cov = sxy / w - mx * my;
            let var_x = sxx / w - mx * mx;
            let var_y = syy / w - my * my;
            let denom = (var_x * var_y).sqrt();
            if cov.is_finite() && denom.is_finite() && denom > 0.0 {
                out[t] = cov / denom;
            }
        }
    }
    out
}

/// Percentile rank of `x[t]` within its trailing `window` bars, ties averaged,
/// scaled to (0, 1]. Windows containing NaN yield NaN.
///
/// Maintains a chronology deque (for eviction) alongside a sorted copy of the
/// live window; each bar costs one binary search plus one insert/remove.
pub fn rolling_rank(x: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if window == 0 || window > x.len() {
        return out;
    }
    let mut chrono: VecDeque<f64> = VecDeque::with_capacity(window);
    let mut sorted: Vec<f64> = Vec::with_capacity(window);
    let mut nan_count = 0usize;
    for (t, &v) in x.iter().enumerate() {
        if chrono.len() == window {
            let old = chrono.pop_front().expect("non-empty chronology");
            if old.is_nan() {
                nan_count -= 1;
            } else {
                // `old` is bit-identical to a stored value (+/-0 interchangeable).
                let pos = sorted.partition_point(|&s| s < old);
                sorted.remove(pos);
            }
        }
        chrono.push_back(v);
        if v.is_nan() {
            nan_count += 1;
        } else {
            let pos = sorted.partition_point(|&s| s < v);
            sorted.insert(pos, v);
        }
        if t + 1 >= window && nan_count == 0 && !v.is_nan() {
            let lt = sorted.partition_point(|&s| s < v) as f64;
            let le = sorted.partition_point(|&s| s <= v) as f64;
            let eq = le - lt;
            // Average rank among ties (1-based), normalised by window length.
            let avg_rank = lt + (eq - 1.0) / 2.0 + 1.0;
            out[t] = avg_rank / window as f64;
        }
    }
    out
}

/// Exponentially weighted moving average with smoothing span (`window`),
/// alpha = 2 / (span + 1). Seeded at the first finite observation; NaN bars
/// carry the previous smoothed value forward unchanged (and emit it).
pub fn ewma_span(x: &[f64], span: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if span == 0 || x.is_empty() {
        return out;
    }
    let alpha = 2.0 / (span as f64 + 1.0);
    let mut prev = f64::NAN;
    for (t, &v) in x.iter().enumerate() {
        if v.is_nan() {
            out[t] = prev;
        } else if prev.is_nan() {
            prev = v;
            out[t] = v;
        } else {
            prev = alpha * v + (1.0 - alpha) * prev;
            out[t] = prev;
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::super::expression_parser::TsArg;
    use super::*;

    // ----- deterministic pseudo-random series ------------------------------

    fn gen_series(seed: u64, n: usize) -> Vec<f64> {
        let mut state = seed
            .wrapping_mul(0x9E37_79B9_7F4A_7C15)
            .wrapping_add(0xD1B5_4A32_D192_ED03);
        (0..n)
            .map(|_| {
                state = state
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                (((state >> 33) % 20000) as f64) / 100.0 - 100.0
            })
            .collect()
    }

    // ----- naive reference implementations (test oracle) -------------------

    fn na_shift(x: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| if t >= w { x[t - w] } else { f64::NAN })
            .collect()
    }

    fn na_delta(x: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| if t >= w { x[t] - x[t - w] } else { f64::NAN })
            .collect()
    }

    /// Apply `f` to every full, NaN-free trailing window of size `w`.
    fn na_stat(x: &[f64], w: usize, f: impl Fn(&[f64]) -> f64) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if t + 1 >= w {
                    let win = &x[t + 1 - w..=t];
                    if win.iter().any(|v| v.is_nan()) {
                        f64::NAN
                    } else {
                        f(win)
                    }
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    fn na_mean(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| win.iter().sum::<f64>() / win.len() as f64)
    }

    fn na_sum(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| win.iter().sum::<f64>())
    }

    fn na_std(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let n = win.len();
            if n < 2 {
                return f64::NAN;
            }
            let m = win.iter().sum::<f64>() / n as f64;
            let var = win.iter().map(|v| (v - m) * (v - m)).sum::<f64>() / (n - 1) as f64;
            var.sqrt()
        })
    }

    fn na_zscore(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let n = win.len();
            if n < 2 {
                return f64::NAN;
            }
            let m = win.iter().sum::<f64>() / n as f64;
            let var = win.iter().map(|v| (v - m) * (v - m)).sum::<f64>() / (n - 1) as f64;
            if var > 0.0 {
                (win[win.len() - 1] - m) / var.sqrt()
            } else {
                f64::NAN
            }
        })
    }

    fn na_rank(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let v = win[win.len() - 1];
            let lt = win.iter().filter(|&&s| s < v).count() as f64;
            let eq = win.iter().filter(|&&s| s == v).count() as f64;
            (lt + (eq - 1.0) / 2.0 + 1.0) / win.len() as f64
        })
    }

    fn na_corr(x: &[f64], y: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if t + 1 >= w {
                    let wx = &x[t + 1 - w..=t];
                    let wy = &y[t + 1 - w..=t];
                    if wx.iter().chain(wy).any(|v| v.is_nan()) {
                        return f64::NAN;
                    }
                    let n = w as f64;
                    let mx = wx.iter().sum::<f64>() / n;
                    let my = wy.iter().sum::<f64>() / n;
                    let cov: f64 = wx
                        .iter()
                        .zip(wy)
                        .map(|(a, b)| (a - mx) * (b - my))
                        .sum::<f64>()
                        / n;
                    let vx: f64 = wx.iter().map(|a| (a - mx) * (a - mx)).sum::<f64>() / n;
                    let vy: f64 = wy.iter().map(|b| (b - my) * (b - my)).sum::<f64>() / n;
                    let den = (vx * vy).sqrt();
                    if den > 0.0 && den.is_finite() && cov.is_finite() {
                        return cov / den;
                    }
                }
                f64::NAN
            })
            .collect()
    }

    fn na_ewma(x: &[f64], span: usize) -> Vec<f64> {
        let alpha = 2.0 / (span as f64 + 1.0);
        let mut prev = f64::NAN;
        (0..x.len())
            .map(|t| {
                let v = x[t];
                if v.is_nan() {
                    prev
                } else if prev.is_nan() {
                    prev = v;
                    v
                } else {
                    prev = alpha * v + (1.0 - alpha) * prev;
                    prev
                }
            })
            .collect()
    }

    fn na_zip(a: &[f64], b: &[f64], f: fn(f64, f64) -> f64) -> Vec<f64> {
        (0..a.len().max(b.len()))
            .map(|i| match (a.get(i), b.get(i)) {
                (Some(&u), Some(&v)) => f(u, v),
                _ => f64::NAN,
            })
            .collect()
    }

    /// Independent recursive reference evaluator over raw ASTs.
    fn naive_eval(ast: &AstNode, data: &HashMap<String, Vec<f64>>) -> Vec<f64> {
        let default_len = data.values().map(|v| v.len()).max().unwrap_or(0);
        match ast {
            AstNode::Number(v) => vec![*v; default_len],
            AstNode::Field(name) => data
                .get(name)
                .cloned()
                .unwrap_or_else(|| vec![f64::NAN; default_len]),
            AstNode::UnaryOp { operand, .. } => {
                naive_eval(operand, data).into_iter().map(|v| -v).collect()
            }
            AstNode::BinaryOp { op, left, right } => {
                let l = naive_eval(left, data);
                let r = naive_eval(right, data);
                let f = match op {
                    BinOp::Add => |a: f64, b: f64| a + b,
                    BinOp::Sub => |a: f64, b: f64| a - b,
                    BinOp::Mul => |a: f64, b: f64| a * b,
                    BinOp::Div => |a: f64, b: f64| a / b,
                };
                na_zip(&l, &r, f)
            }
            AstNode::TsFunc {
                func, args, window, ..
            } => {
                let series: Vec<Vec<f64>> = args
                    .iter()
                    .map(|arg| match arg {
                        TsArg::Field(name) => data
                            .get(name)
                            .cloned()
                            .unwrap_or_else(|| vec![f64::NAN; default_len]),
                        TsArg::Expr(inner) => naive_eval(inner, data),
                    })
                    .collect();
                match func {
                    TsFunc::Delay => na_shift(&series[0], *window),
                    TsFunc::Delta => na_delta(&series[0], *window),
                    TsFunc::Sum => na_sum(&series[0], *window),
                    TsFunc::Mean => na_mean(&series[0], *window),
                    TsFunc::Std => na_std(&series[0], *window),
                    TsFunc::Zscore => na_zscore(&series[0], *window),
                    TsFunc::Rank => na_rank(&series[0], *window),
                    TsFunc::Corr => na_corr(&series[0], &series[1], *window),
                    TsFunc::Ewma => na_ewma(&series[0], *window),
                    // Newer operators are covered by the dedicated wiring
                    // test against the operator library directly.
                    _ => vec![f64::NAN; default_len],
                }
            }
        }
    }

    fn assert_series_eq(got: &[f64], want: &[f64], what: &str) {
        assert_eq!(got.len(), want.len(), "{}: length mismatch", what);
        for (i, (g, w)) in got.iter().zip(want.iter()).enumerate() {
            if g.is_nan() && w.is_nan() {
                continue;
            }
            if g.is_infinite() && w.is_infinite() {
                assert!(
                    g.is_sign_positive() == w.is_sign_positive(),
                    "{}[{}]: got {} want {}",
                    what,
                    i,
                    g,
                    w
                );
                continue;
            }
            let scale = g.abs().max(w.abs()).max(1.0);
            assert!(
                (g - w).abs() <= 1e-9 * scale,
                "{}[{}]: got {} want {}",
                what,
                i,
                g,
                w
            );
        }
    }

    // ----- rolling primitive accuracy --------------------------------------

    #[test]
    fn rolling_delay_and_delta_match_naive() {
        let x = gen_series(7, 40);
        for w in [1usize, 4, 9, 39, 40, 60] {
            assert_series_eq(&rolling_delay(&x, w), &na_shift(&x, w), "delay");
            assert_series_eq(&rolling_delta(&x, w), &na_delta(&x, w), "delta");
        }
    }

    #[test]
    fn rolling_sum_mean_std_match_naive() {
        let x = gen_series(11, 48);
        for w in [1usize, 3, 7, 16, 48, 49] {
            assert_series_eq(&rolling_sum(&x, w), &na_sum(&x, w), "sum");
            assert_series_eq(&rolling_mean(&x, w), &na_mean(&x, w), "mean");
            assert_series_eq(&rolling_std(&x, w), &na_std(&x, w), "std");
        }
        // Constant window: std is a defined 0.0, not NaN.
        let flat = vec![3.25f64; 10];
        let got = rolling_std(&flat, 5);
        assert!(got.iter().skip(4).all(|v| *v == 0.0));
        assert!(got.iter().take(4).all(|v| v.is_nan()));
    }

    #[test]
    fn rolling_zscore_matches_naive_and_nans_on_flat_windows() {
        let x = gen_series(13, 48);
        for w in [2usize, 5, 12, 48] {
            assert_series_eq(&rolling_zscore(&x, w), &na_zscore(&x, w), "zscore");
        }
        let flat = vec![7.0f64; 12];
        let got = rolling_zscore(&flat, 6);
        assert!(got.iter().skip(5).all(|v| v.is_nan()));
    }

    #[test]
    fn rolling_corr_matches_naive_and_handles_degenerate_windows() {
        let x = gen_series(21, 40);
        let y = gen_series(22, 40);
        for w in [2usize, 5, 13, 40, 41] {
            assert_series_eq(&rolling_corr(&x, &y, w), &na_corr(&x, &y, w), "corr");
        }
        // Zero variance on one side -> NaN.
        let flat = vec![5.0f64; 20];
        let got = rolling_corr(&flat, &y[..20], 5);
        assert!(got.iter().skip(4).all(|v| v.is_nan()));
    }

    #[test]
    fn rolling_rank_matches_naive_including_ties_and_nan_windows() {
        // Quantised values force frequent ties.
        let x: Vec<f64> = gen_series(31, 60).iter().map(|v| v.trunc()).collect();
        for w in [3usize, 8, 20] {
            assert_series_eq(&rolling_rank(&x, w), &na_rank(&x, w), "rank");
        }
        // A NaN contaminates every window covering it, and only those.
        let mut xn = x.clone();
        xn[10] = f64::NAN;
        let got = rolling_rank(&xn, 5);
        for t in 10..=14 {
            assert!(got[t].is_nan(), "rank[{}] should be NaN", t);
        }
        assert!(!got[16].is_nan());
        assert!(!got[9].is_nan());
    }

    #[test]
    fn ewma_matches_hand_computed_values_and_carries_across_gaps() {
        let out = ewma_span(&[1.0, 2.0, 3.0, 4.0], 3); // alpha = 0.5
        assert_series_eq(&out, &[1.0, 1.5, 2.25, 3.125], "ewma");

        let gapped = ewma_span(&[1.0, f64::NAN, 2.0], 3);
        assert_series_eq(&gapped, &[1.0, 1.0, 1.5], "ewma-gap");

        assert!(ewma_span(&[], 3).is_empty());
        assert!(ewma_span(&[1.0, 2.0], 0).iter().all(|v| v.is_nan()));
        assert!(ewma_span(&[f64::NAN, f64::NAN], 3)
            .iter()
            .all(|v| v.is_nan()));
    }

    // ----- batch execution --------------------------------------------------

    #[test]
    fn binary_ops_division_and_negation_follow_ieee754() {
        let mut close = gen_series(41, 16);
        close[3] = 0.0;
        let mut data = HashMap::new();
        data.insert("close".to_string(), close.clone());

        let asts = vec![
            super::super::expression_parser::parse("1/close").expect("valid"),
            super::super::expression_parser::parse("-close").expect("valid"),
        ];
        let dag = super::super::dag_builder::build_dag(&asts);
        let rows = execute_batch(&dag, &data, &dag.roots);

        let want_div = na_zip(&vec![1.0; 16], &close, |_, c| 1.0 / c);
        assert_series_eq(&rows[0], &want_div, "1/close");
        assert!(rows[0][3].is_infinite() && rows[0][3] > 0.0);

        let want_neg: Vec<f64> = close.iter().map(|c| -c).collect();
        assert_series_eq(&rows[1], &want_neg, "-close");
    }

    #[test]
    fn unequal_column_lengths_pad_with_nan() {
        let close: Vec<f64> = (0..10).map(|i| i as f64 + 1.0).collect();
        let open: Vec<f64> = (0..6).map(|i| i as f64 + 2.0).collect();
        let mut data = HashMap::new();
        data.insert("close".to_string(), close.clone());
        data.insert("open".to_string(), open.clone());

        let asts = vec![super::super::expression_parser::parse("close+open").expect("valid")];
        let dag = super::super::dag_builder::build_dag(&asts);
        let rows = execute_batch(&dag, &data, &dag.roots);

        assert_eq!(rows[0].len(), 10);
        for t in 0..6 {
            assert_eq!(rows[0][t], close[t] + open[t]);
        }
        assert!(rows[0][6..].iter().all(|v| v.is_nan()));
    }

    #[test]
    fn missing_field_becomes_nan_column_of_default_length() {
        let close = gen_series(51, 12);
        let mut data = HashMap::new();
        data.insert("close".to_string(), close);

        let asts = vec![super::super::expression_parser::parse("close+ghost").expect("valid")];
        let dag = super::super::dag_builder::build_dag(&asts);
        let rows = execute_batch(&dag, &data, &dag.roots);

        assert_eq!(rows[0].len(), 12);
        assert!(rows[0].iter().all(|v| v.is_nan()));
    }

    #[test]
    fn window_larger_than_series_yields_all_nan() {
        let close = gen_series(61, 10);
        let mut data = HashMap::new();
        data.insert("close".to_string(), close);

        for expr in [
            "ts_mean(close, 11)",
            "ts_rank(close, 11)",
            "ts_corr(close, close, 11)",
        ] {
            let asts = vec![super::super::expression_parser::parse(expr).expect("valid")];
            let dag = super::super::dag_builder::build_dag(&asts);
            let rows = execute_batch(&dag, &data, &dag.roots);
            assert!(rows[0].iter().all(|v| v.is_nan()), "{}", expr);
        }
    }

    #[test]
    fn execute_batch_matches_reference_evaluator_end_to_end() {
        let n = 48;
        let close: Vec<f64> = gen_series(71, n).iter().map(|v| v + 100.0).collect();
        let volume: Vec<f64> = gen_series(72, n)
            .iter()
            .map(|v| (v + 100.0).abs() + 1.0)
            .collect();
        let ret: Vec<f64> = gen_series(73, n);
        let mut data = HashMap::new();
        data.insert("close".to_string(), close.clone());
        data.insert("volume".to_string(), volume.clone());
        data.insert("ret".to_string(), ret.clone());

        let exprs = [
            "ts_zscore(ts_mean(close, 5), 12)",
            "ts_corr(close, volume, 8)",
            "(close - ts_delay(close, 1)) / ts_delay(close, 1)",
            "ts_rank(close / volume, 10) - 0.5",
            "ewma(close, 6) / close - 1",
            "ts_delta(ts_delay(ret, 2), 3) * volume",
        ];
        let asts: Vec<AstNode> = exprs
            .iter()
            .map(|e| super::super::expression_parser::parse(e).expect(e))
            .collect();

        let dag = super::super::dag_builder::build_dag(&asts);
        assert_eq!(dag.roots.len(), exprs.len());
        let rows = execute_batch(&dag, &data, &dag.roots);

        for ((row, ast), expr) in rows.iter().zip(asts.iter()).zip(exprs.iter()) {
            assert_eq!(row.len(), n, "{}", expr);
            let want = naive_eval(ast, &data);
            assert_series_eq(row, &want, expr);
        }
    }

    #[test]
    fn shared_subexpressions_produce_consistent_rows() {
        let n = 24;
        let close = gen_series(81, n);
        let mut data = HashMap::new();
        data.insert("close".to_string(), close.clone());

        let asts: Vec<AstNode> = ["ts_mean(close, 4)+1", "ts_mean(close, 4)*2"]
            .iter()
            .map(|e| super::super::expression_parser::parse(e).expect(e))
            .collect();
        let dag = super::super::dag_builder::build_dag(&asts);
        // Both alphas share the ts_mean node but keep distinct roots.
        assert_ne!(dag.roots[0], dag.roots[1]);

        let rows = execute_batch(&dag, &data, &dag.roots);
        for (row, ast) in rows.iter().zip(asts.iter()) {
            assert_series_eq(row, &naive_eval(ast, &data), "shared");
        }
    }

    #[test]
    fn invalid_root_panics_with_clear_message() {
        let asts = vec![super::super::expression_parser::parse("close").expect("valid")];
        let dag = super::super::dag_builder::build_dag(&asts);
        let result = std::panic::catch_unwind(|| {
            let empty: HashMap<String, Vec<f64>> = HashMap::new();
            execute_batch(&dag, &empty, &[999]);
        });
        assert!(result.is_err());
    }

    /// End-to-end wiring check for the expanded operator vocabulary: parsed
    /// expressions executed through the DAG must equal direct calls into the
    /// operator library on the same columns.
    #[test]
    #[allow(clippy::type_complexity)]
    fn new_operator_expressions_match_direct_operator_calls() {
        let n = 40;
        let close: Vec<f64> = gen_series(91, n).iter().map(|v| v + 100.0).collect();
        let volume: Vec<f64> = gen_series(92, n).iter().map(|v| v.abs() + 1.0).collect();
        let ret = gen_series(93, n);
        // A gap exercises NaN handling through the whole pipeline.
        let mut gapped = close.clone();
        gapped[7] = f64::NAN;
        let mut data = HashMap::new();
        data.insert("close".to_string(), gapped.clone());
        data.insert("clean".to_string(), close.clone());
        data.insert("volume".to_string(), volume.clone());
        data.insert("ret".to_string(), ret.clone());

        // The boxed closures borrow the local columns, so the element type
        // stays inline rather than in a `'static` type alias.
        let cases: Vec<(&str, Box<dyn Fn(usize) -> f64>)> = vec![
            (
                "ts_min(clean, 6)",
                Box::new(|t: usize| super::super::operators::ts_min(&close, 6)[t]),
            ),
            (
                "ts_max(close, 6)",
                Box::new(|t: usize| super::super::operators::ts_max(&gapped, 6)[t]),
            ),
            (
                "ts_median(close, 5)",
                Box::new(|t: usize| super::super::operators::ts_median(&gapped, 5)[t]),
            ),
            (
                "ts_quantile(close, 0.25, 9)",
                Box::new(|t: usize| super::super::operators::ts_quantile(&gapped, 0.25, 9)[t]),
            ),
            (
                "ts_skewness(ret, 12) + ts_kurtosis(ret, 12)*0.0",
                Box::new(|t: usize| {
                    super::super::operators::ts_skewness(&ret, 12)[t]
                        + super::super::operators::ts_kurtosis(&ret, 12)[t] * 0.0
                }),
            ),
            (
                "ts_ir(ret, 10)",
                Box::new(|t: usize| super::super::operators::ts_ir(&ret, 10)[t]),
            ),
            (
                "ts_argmax(close, 8) - ts_argmin(close, 8)",
                Box::new(|t: usize| {
                    super::super::operators::ts_argmax(&gapped, 8)[t]
                        - super::super::operators::ts_argmin(&gapped, 8)[t]
                }),
            ),
            (
                "ts_scale(close, 7)",
                Box::new(|t: usize| super::super::operators::ts_scale(&gapped, 7)[t]),
            ),
            (
                "ts_quantile_pos(volume, 5)",
                Box::new(|t: usize| super::super::operators::ts_quantile_pos(&volume, 5)[t]),
            ),
            (
                "ts_decay_linear(close, 4)",
                Box::new(|t: usize| super::super::operators::ts_decay_linear(&gapped, 4)[t]),
            ),
            (
                "ts_regression_beta(close, volume, 10)",
                Box::new(|t: usize| {
                    super::super::operators::ts_regression_beta(&gapped, &volume, 10)[t]
                }),
            ),
            (
                "ts_regression_resid(ret, volume, 10)",
                Box::new(|t: usize| {
                    super::super::operators::ts_regression_resid(&ret, &volume, 10)[t]
                }),
            ),
            (
                "ts_covariance(close, volume, 10)",
                Box::new(|t: usize| {
                    super::super::operators::ts_covariance(&gapped, &volume, 10)[t]
                }),
            ),
            (
                "ts_returns(close, 3)",
                Box::new(|t: usize| super::super::operators::ts_returns(&gapped, 3)[t]),
            ),
            (
                "ts_sign_delta(ret, 2)",
                Box::new(|t: usize| super::super::operators::ts_sign_delta(&ret, 2)[t]),
            ),
            (
                "ts_trend_slope(close, 6)",
                Box::new(|t: usize| super::super::operators::ts_trend_slope(&gapped, 6)[t]),
            ),
            (
                "ts_backfill(close, 3)",
                Box::new(|t: usize| super::super::operators::ts_backfill(&gapped, 3)[t]),
            ),
            (
                "ts_count_valid(close, 5)",
                Box::new(|t: usize| super::super::operators::ts_count_valid(&gapped, 5)[t]),
            ),
            (
                "cs_rank(ts_mean(close, 3))",
                Box::new(|t: usize| super::super::operators::cs_rank(&rolling_mean(&gapped, 3))[t]),
            ),
            (
                "cs_zscore(ret)",
                Box::new(|t: usize| super::super::operators::cs_zscore(&ret)[t]),
            ),
            (
                "cs_scale(volume, 2.0)",
                Box::new(|t: usize| super::super::operators::cs_scale(&volume, 2.0)[t]),
            ),
            (
                "cs_demean(ret)",
                Box::new(|t: usize| super::super::operators::cs_demean(&ret)[t]),
            ),
            (
                "abs(ret) * sign(ret)",
                Box::new(|t: usize| {
                    super::super::operators::abs_val(&ret)[t]
                        * super::super::operators::sign_of(&ret)[t]
                }),
            ),
            (
                "log(volume)",
                Box::new(|t: usize| super::super::operators::log_nat(&volume)[t]),
            ),
            (
                "elem_max(close, clean) + elem_min(close, clean)*0.0",
                Box::new(|t: usize| {
                    super::super::operators::elem_max(&gapped, &close)[t]
                        + super::super::operators::elem_min(&gapped, &close)[t] * 0.0
                }),
            ),
            (
                "if_else(ret, close, volume)",
                Box::new(|t: usize| {
                    let cond: Vec<bool> = ret.iter().map(|&v| v.is_finite() && v != 0.0).collect();
                    super::super::operators::if_else(&cond, &gapped, &volume)[t]
                }),
            ),
        ];

        let exprs: Vec<&str> = cases.iter().map(|(e, _)| *e).collect();
        let asts: Vec<AstNode> = exprs
            .iter()
            .map(|e| {
                super::super::expression_parser::parse(e)
                    .unwrap_or_else(|err| panic!("'{}': {}", e, err))
            })
            .collect();
        let dag = super::super::dag_builder::build_dag(&asts);
        let rows = execute_batch(&dag, &data, &dag.roots);

        for ((expr, want_fn), row) in cases.iter().zip(rows.iter()) {
            assert_eq!(row.len(), n, "{}", expr);
            for (t, &got) in row.iter().enumerate() {
                let want = want_fn(t);
                if got.is_nan() && want.is_nan() {
                    continue;
                }
                let scale = got.abs().max(want.abs()).max(1.0);
                assert!(
                    (got - want).abs() <= 1e-9 * scale,
                    "{}[{}]: got {} want {}",
                    expr,
                    t,
                    got,
                    want
                );
            }
        }
    }
}
