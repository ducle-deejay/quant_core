use std::collections::VecDeque;

const DISPERSION_EPSILON: f64 = 1e-12;

const BASE_EPSILON: f64 = 1e-12;

struct SortedWindow {
    chrono: VecDeque<f64>,
    sorted: Vec<f64>,
    cap: usize,
    nan_count: usize,
}

impl SortedWindow {
    fn new(cap: usize) -> Self {
        SortedWindow {
            chrono: VecDeque::with_capacity(cap.max(1)),
            sorted: Vec::with_capacity(cap.max(1)),
            cap,
            nan_count: 0,
        }
    }

    fn push(&mut self, v: f64) {
        if self.chrono.len() == self.cap {
            let old = self.chrono.pop_front().expect("non-empty chronology");
            if old.is_nan() {
                self.nan_count -= 1;
            } else {

                let pos = self.sorted.partition_point(|&s| s < old);
                self.sorted.remove(pos);
            }
        }
        self.chrono.push_back(v);
        if v.is_nan() {
            self.nan_count += 1;
        } else {
            let pos = self.sorted.partition_point(|&s| s < v);
            self.sorted.insert(pos, v);
        }
    }

    fn full(&self) -> bool {
        self.chrono.len() == self.cap
    }

    fn clean(&self) -> bool {
        self.nan_count == 0
    }
}

struct PowerSumWindow {
    buf: VecDeque<f64>,
    cap: usize,
    s1: f64,
    s2: f64,
    s3: f64,
    s4: f64,
    nan_count: usize,
}

impl PowerSumWindow {
    fn new(cap: usize) -> Self {
        PowerSumWindow {
            buf: VecDeque::with_capacity(cap.max(1)),
            cap,
            s1: 0.0,
            s2: 0.0,
            s3: 0.0,
            s4: 0.0,
            nan_count: 0,
        }
    }

    fn push(&mut self, v: f64) {
        if self.buf.len() == self.cap {
            let old = self.buf.pop_front().expect("non-empty buffer");
            if old.is_nan() {
                self.nan_count -= 1;
            } else {
                let p2 = old * old;
                self.s1 -= old;
                self.s2 -= p2;
                self.s3 -= p2 * old;
                self.s4 -= p2 * p2;
            }
        }
        self.buf.push_back(v);
        if v.is_nan() {
            self.nan_count += 1;
        } else {
            let p2 = v * v;
            self.s1 += v;
            self.s2 += p2;
            self.s3 += p2 * v;
            self.s4 += p2 * p2;
        }
    }

    fn ready(&self) -> bool {
        self.buf.len() == self.cap && self.nan_count == 0
    }

    fn mean(&self) -> f64 {
        self.s1 / self.cap as f64
    }

    fn central_moments(&self) -> (f64, f64, f64) {
        let n = self.cap as f64;
        let mu = self.s1 / n;
        let e2 = self.s2 / n;
        let e3 = self.s3 / n;
        let e4 = self.s4 / n;
        let mu2 = mu * mu;
        let mu3 = mu2 * mu;
        let m2 = e2 - mu2;
        let m3 = e3 - 3.0 * mu * e2 + 2.0 * mu3;
        let m4 = e4 - 4.0 * mu * e3 + 6.0 * mu2 * e2 - 3.0 * mu3 * mu;
        (m2, m3, m4)
    }
}

fn monotonic_sweep(x: &[f64], d: usize, want_max: bool, mut emit: impl FnMut(usize, usize, f64)) {
    let mut deque: VecDeque<(usize, f64)> = VecDeque::with_capacity(d.max(1));
    let mut nan_count = 0usize;

    let dominated = |candidate: f64, incoming: f64| {
        if want_max {
            candidate < incoming
        } else {
            candidate > incoming
        }
    };
    for (t, &v) in x.iter().enumerate() {

        if t >= d && x[t - d].is_nan() {
            nan_count -= 1;
        }
        if v.is_nan() {
            nan_count += 1;
        } else {
            while let Some(&(_, back_val)) = deque.back() {
                if dominated(back_val, v) {
                    deque.pop_back();
                } else {
                    break;
                }
            }
            deque.push_back((t, v));
        }

        while let Some(&(front_idx, _)) = deque.front() {
            if front_idx + d <= t {
                deque.pop_front();
            } else {
                break;
            }
        }
        if t + 1 >= d && nan_count == 0 {
            let &(extreme_idx, extreme_val) = deque
                .front()
                .expect("clean full window keeps one candidate");
            emit(t, extreme_idx, extreme_val);
        }
    }
}

pub fn ts_min(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    monotonic_sweep(x, d, false, |t, _, v| out[t] = v);
    out
}

pub fn ts_max(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    monotonic_sweep(x, d, true, |t, _, v| out[t] = v);
    out
}

pub fn ts_median(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut win = SortedWindow::new(d);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if win.full() && win.clean() {
            let n = win.sorted.len();
            let mid = n / 2;
            out[t] = if n % 2 == 1 {
                win.sorted[mid]
            } else {
                (win.sorted[mid - 1] + win.sorted[mid]) / 2.0
            };
        }
    }
    out
}

pub fn ts_quantile(x: &[f64], q: f64, d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if !(q.is_finite() && (0.0..=1.0).contains(&q)) || d == 0 || d > x.len() {
        return out;
    }
    let mut win = SortedWindow::new(d);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if win.full() && win.clean() {
            let n = win.sorted.len();
            let pos = q * (n - 1) as f64;
            let lo = pos.floor() as usize;
            let hi = pos.ceil() as usize;
            let frac = pos - lo as f64;
            let a = win.sorted[lo];
            let b = win.sorted[hi];
            out[t] = a + (b - a) * frac;
        }
    }
    out
}

pub fn ts_skewness(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut win = PowerSumWindow::new(d);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if win.ready() {
            let (m2, m3, _) = win.central_moments();
            if m2 > 0.0 {
                let std = m2.sqrt();
                if std > DISPERSION_EPSILON {
                    let skew = m3 / (m2 * std);
                    if skew.is_finite() {
                        out[t] = skew;
                    }
                }
            }
        }
    }
    out
}

pub fn ts_kurtosis(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut win = PowerSumWindow::new(d);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if win.ready() {
            let (m2, _, m4) = win.central_moments();
            if m2 > 0.0 {
                let kurt = m4 / (m2 * m2) - 3.0;
                if kurt.is_finite() {
                    out[t] = kurt;
                }
            }
        }
    }
    out
}

pub fn ts_ir(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d < 2 || d > x.len() {
        return out;
    }
    let mut win = PowerSumWindow::new(d);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if win.ready() {
            let (m2, _, _) = win.central_moments();

            let var_sample = m2 * d as f64 / (d - 1) as f64;
            if var_sample > 0.0 {
                let std = var_sample.sqrt();
                if std > DISPERSION_EPSILON {
                    let ir = win.mean() / std;
                    if ir.is_finite() {
                        out[t] = ir;
                    }
                }
            }
        }
    }
    out
}

pub fn ts_product(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut chrono: VecDeque<f64> = VecDeque::with_capacity(d);
    let mut prod = 1.0f64;
    let mut zeros = 0usize;
    let mut nan_count = 0usize;
    for (t, &v) in x.iter().enumerate() {
        if chrono.len() == d {
            let old = chrono.pop_front().expect("non-empty chronology");
            if old.is_nan() {
                nan_count -= 1;
            } else if old == 0.0 {
                zeros -= 1;
            } else {
                prod /= old;
            }
        }
        chrono.push_back(v);
        if v.is_nan() {
            nan_count += 1;
        } else if v == 0.0 {
            zeros += 1;
        } else {
            prod *= v;
        }
        if t + 1 >= d && nan_count == 0 {
            out[t] = if zeros > 0 { 0.0 } else { prod };
        }
    }
    out
}

pub fn ts_argmax(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    monotonic_sweep(x, d, true, |t, idx, _| out[t] = (t - idx) as f64);
    out
}

pub fn ts_argmin(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    monotonic_sweep(x, d, false, |t, idx, _| out[t] = (t - idx) as f64);
    out
}

pub fn ts_max_diff(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    monotonic_sweep(x, d, true, |t, _, v| out[t] = x[t] - v);
    out
}

pub fn ts_min_diff(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    monotonic_sweep(x, d, false, |t, _, v| out[t] = x[t] - v);
    out
}

pub fn ts_scale(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut lows = vec![f64::NAN; x.len()];
    let mut highs = vec![f64::NAN; x.len()];
    monotonic_sweep(x, d, false, |t, _, v| lows[t] = v);
    monotonic_sweep(x, d, true, |t, _, v| highs[t] = v);
    for t in 0..x.len() {
        let range = highs[t] - lows[t];
        if range.is_finite() && range > DISPERSION_EPSILON {
            out[t] = (x[t] - lows[t]) / range;
        }
    }
    out
}

pub fn ts_quantile_pos(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut win = SortedWindow::new(d);
    for (t, &v) in x.iter().enumerate() {
        win.push(v);
        if win.full() && win.clean() {
            let below = win.sorted.partition_point(|&s| s < v) as f64;
            out[t] = below / d as f64;
        }
    }
    out
}

pub fn ts_decay_linear(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }

    let weight_sum = d as f64 * (d as f64 + 1.0) / 2.0;
    for t in (d - 1)..x.len() {
        let win = &x[t + 1 - d..=t];
        if win.iter().any(|v| v.is_nan()) {
            continue;
        }
        let mut acc = 0.0;

        for (i, &v) in win.iter().enumerate() {
            acc += (i + 1) as f64 * v;
        }
        let avg = acc / weight_sum;
        if avg.is_finite() {
            out[t] = avg;
        }
    }
    out
}

fn sliding_ols(y: &[f64], x: &[f64], d: usize) -> (Vec<f64>, Vec<f64>) {
    let pair_len = x.len().min(y.len());
    let out_len = x.len().max(y.len());
    let mut betas = vec![f64::NAN; out_len];
    let mut resids = vec![f64::NAN; out_len];
    if d == 0 || d > pair_len {
        return (betas, resids);
    }
    let mut ring: VecDeque<(f64, f64)> = VecDeque::with_capacity(d);
    let (mut sx, mut sy, mut sxx, mut sxy) = (0.0, 0.0, 0.0, 0.0);
    let mut bad = 0usize;
    for t in 0..pair_len {
        let pair = (x[t], y[t]);
        if ring.len() == d {
            let (ox, oy) = ring.pop_front().expect("non-empty ring");
            if ox.is_nan() || oy.is_nan() {
                bad -= 1;
            } else {
                sx -= ox;
                sy -= oy;
                sxx -= ox * ox;
                sxy -= ox * oy;
            }
        }
        ring.push_back(pair);
        let (vx, vy) = pair;
        if vx.is_nan() || vy.is_nan() {
            bad += 1;
        } else {
            sx += vx;
            sy += vy;
            sxx += vx * vx;
            sxy += vx * vy;
        }
        if t + 1 >= d && bad == 0 {
            let w = d as f64;

            let denom = w * sxx - sx * sx;
            let num = w * sxy - sx * sy;
            if denom > 0.0 && denom.is_finite() {
                let beta = num / denom;
                if beta.is_finite() {
                    betas[t] = beta;
                    let alpha = (sy - beta * sx) / w;
                    let resid = y[t] - alpha - beta * x[t];
                    if resid.is_finite() {
                        resids[t] = resid;
                    }
                }
            }
        }
    }
    (betas, resids)
}

pub fn ts_regression_resid(y: &[f64], x: &[f64], d: usize) -> Vec<f64> {
    sliding_ols(y, x, d).1
}

pub fn ts_regression_beta(y: &[f64], x: &[f64], d: usize) -> Vec<f64> {
    sliding_ols(y, x, d).0
}

pub fn ts_covariance(x: &[f64], y: &[f64], d: usize) -> Vec<f64> {
    let pair_len = x.len().min(y.len());
    let mut out = vec![f64::NAN; x.len().max(y.len())];
    if d < 2 || d > pair_len {
        return out;
    }
    let mut ring: VecDeque<(f64, f64)> = VecDeque::with_capacity(d);
    let (mut sx, mut sy, mut sxy) = (0.0, 0.0, 0.0);
    let mut bad = 0usize;
    for t in 0..pair_len {
        let pair = (x[t], y[t]);
        if ring.len() == d {
            let (ox, oy) = ring.pop_front().expect("non-empty ring");
            if ox.is_nan() || oy.is_nan() {
                bad -= 1;
            } else {
                sx -= ox;
                sy -= oy;
                sxy -= ox * oy;
            }
        }
        ring.push_back(pair);
        let (vx, vy) = pair;
        if vx.is_nan() || vy.is_nan() {
            bad += 1;
        } else {
            sx += vx;
            sy += vy;
            sxy += vx * vy;
        }
        if t + 1 >= d && bad == 0 {
            let w = d as f64;

            let cov = (w * sxy - sx * sy) / (w * (w - 1.0));
            if cov.is_finite() {
                out[t] = cov;
            }
        }
    }
    out
}

pub fn ts_returns(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d >= x.len() {
        return out;
    }
    for t in d..x.len() {
        let base = x[t - d];
        let cur = x[t];
        if base.is_nan() || cur.is_nan() || base.abs() <= BASE_EPSILON {
            continue;
        }
        let ret = cur / base - 1.0;
        if ret.is_finite() {
            out[t] = ret;
        }
    }
    out
}

pub fn ts_sign_delta(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d >= x.len() {
        return out;
    }
    for t in d..x.len() {
        let change = x[t] - x[t - d];
        if change.is_nan() {
            continue;
        }
        out[t] = match change {
            c if c > 0.0 => 1.0,
            c if c < 0.0 => -1.0,
            _ => 0.0,
        };
    }
    out
}

pub fn ts_trend_slope(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d < 2 || d > x.len() {
        return out;
    }
    let mut buf: VecDeque<f64> = VecDeque::with_capacity(d);
    let (mut sx, mut s_ix) = (0.0, 0.0);
    let mut nan_count = 0usize;
    for (t, &v) in x.iter().enumerate() {
        if buf.len() == d {
            let old = buf.pop_front().expect("non-empty buffer");
            if old.is_nan() {
                nan_count -= 1;
            }

            let rest_sum = if old.is_nan() { sx } else { sx - old };
            s_ix -= rest_sum;
            sx = rest_sum;
        }
        buf.push_back(v);
        if v.is_nan() {
            nan_count += 1;
        } else {

            let age = buf.len() - 1;
            sx += v;
            s_ix += age as f64 * v;
        }
        if t + 1 >= d && nan_count == 0 {
            let w = d as f64;

            let sxx = w * (w * w - 1.0) / 12.0;
            let sxy = s_ix - sx * (w - 1.0) / 2.0;
            let slope = sxy / sxx;
            if slope.is_finite() {
                out[t] = slope;
            }
        }
    }
    out
}

pub fn ts_backfill(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    let mut last_valid: Option<usize> = None;
    for (t, &v) in x.iter().enumerate() {
        if !v.is_nan() {
            last_valid = Some(t);
            out[t] = v;
        } else if let Some(p) = last_valid {
            if t - p <= d {
                out[t] = x[p];
            }
        }
    }
    out
}

pub fn ts_count_valid(x: &[f64], d: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    if d == 0 || d > x.len() {
        return out;
    }
    let mut count = 0usize;
    for (t, &v) in x.iter().enumerate() {
        if !v.is_nan() {
            count += 1;
        }
        if t >= d && !x[t - d].is_nan() {
            count -= 1;
        }
        if t + 1 >= d {
            out[t] = count as f64;
        }
    }
    out
}

pub fn cs_rank(x: &[f64]) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    let mut order: Vec<usize> = (0..x.len()).filter(|&i| !x[i].is_nan()).collect();
    order.sort_by(|&a, &b| x[a].partial_cmp(&x[b]).unwrap_or(std::cmp::Ordering::Equal));
    let m = order.len();
    let mut i = 0usize;
    while i < m {
        let mut j = i;
        while j + 1 < m && x[order[j + 1]] == x[order[i]] {
            j += 1;
        }

        let avg_rank = (i + j) as f64 / 2.0 + 1.0;
        let score = avg_rank / m as f64;
        for &k in &order[i..=j] {
            out[k] = score;
        }
        i = j + 1;
    }
    out
}

pub fn cs_zscore(x: &[f64]) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    let mut sum = 0.0;
    let mut m = 0usize;
    for &v in x {
        if !v.is_nan() {
            sum += v;
            m += 1;
        }
    }
    if m == 0 {
        return out;
    }
    let mean = sum / m as f64;
    let var = x
        .iter()
        .filter(|v| !v.is_nan())
        .map(|&v| (v - mean) * (v - mean))
        .sum::<f64>()
        / m as f64;
    if !var.is_finite() {
        return out;
    }
    let std = var.sqrt();
    if std > DISPERSION_EPSILON {
        for (o, &v) in out.iter_mut().zip(x.iter()) {
            if !v.is_nan() {
                let z = (v - mean) / std;
                if z.is_finite() {
                    *o = z;
                }
            }
        }
    }
    out
}

pub fn cs_scale(x: &[f64], target_abs_sum: f64) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    let total: f64 = x.iter().filter(|v| !v.is_nan()).map(|v| v.abs()).sum();
    if !total.is_finite() {
        return out;
    }
    let factor = target_abs_sum / total;
    if !factor.is_finite() {
        return out;
    }
    for (o, &v) in out.iter_mut().zip(x.iter()) {
        if !v.is_nan() {
            let scaled = v * factor;
            if scaled.is_finite() {
                *o = scaled;
            }
        }
    }
    out
}

pub fn cs_demean(x: &[f64]) -> Vec<f64> {
    let mut out = vec![f64::NAN; x.len()];
    let mut sum = 0.0;
    let mut m = 0usize;
    for &v in x {
        if !v.is_nan() {
            sum += v;
            m += 1;
        }
    }
    if m == 0 {
        return out;
    }
    let mean = sum / m as f64;
    for (o, &v) in out.iter_mut().zip(x.iter()) {
        if !v.is_nan() {
            let centered = v - mean;
            if centered.is_finite() {
                *o = centered;
            }
        }
    }
    out
}

pub fn abs_val(x: &[f64]) -> Vec<f64> {
    x.iter().map(|v| v.abs()).collect()
}

pub fn log_nat(x: &[f64]) -> Vec<f64> {
    x.iter()
        .map(|&v| {
            if v.is_nan() || v <= 0.0 {
                f64::NAN
            } else {
                v.ln()
            }
        })
        .collect()
}

pub fn sign_of(x: &[f64]) -> Vec<f64> {
    x.iter()
        .map(|&v| {
            if v.is_nan() {
                f64::NAN
            } else if v == 0.0 {
                0.0
            } else if v > 0.0 {
                1.0
            } else {
                -1.0
            }
        })
        .collect()
}

pub fn elem_max(a: &[f64], b: &[f64]) -> Vec<f64> {
    zip_propagating(a, b, |u, v| if u >= v { u } else { v })
}

pub fn elem_min(a: &[f64], b: &[f64]) -> Vec<f64> {
    zip_propagating(a, b, |u, v| if u <= v { u } else { v })
}

fn zip_propagating(a: &[f64], b: &[f64], f: impl Fn(f64, f64) -> f64) -> Vec<f64> {
    let n = a.len().max(b.len());
    (0..n)
        .map(|i| match (a.get(i), b.get(i)) {
            (Some(&u), Some(&v)) if !u.is_nan() && !v.is_nan() => f(u, v),
            _ => f64::NAN,
        })
        .collect()
}

pub fn if_else(cond: &[bool], then_x: &[f64], else_x: &[f64]) -> Vec<f64> {
    let n = cond.len().max(then_x.len()).max(else_x.len());
    (0..n)
        .map(|i| match cond.get(i) {
            Some(&c) => {
                let branch = if c { then_x.get(i) } else { else_x.get(i) };
                branch.copied().unwrap_or(f64::NAN)
            }
            None => f64::NAN,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

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

    fn assert_series_eq_tol(got: &[f64], want: &[f64], rtol: f64, atol: f64, what: &str) {
        assert_eq!(got.len(), want.len(), "{}: length mismatch", what);
        for (i, (g, w)) in got.iter().zip(want.iter()).enumerate() {
            if g.is_nan() && w.is_nan() {
                continue;
            }
            let tol = atol + rtol * g.abs().max(w.abs());
            assert!(
                (g - w).abs() <= tol,
                "{}[{}]: got {} want {}",
                what,
                i,
                g,
                w
            );
        }
    }

    fn assert_series_eq(got: &[f64], want: &[f64], what: &str) {
        assert_series_eq_tol(got, want, 1e-9, 1e-9, what);
    }

    fn na_stat(x: &[f64], w: usize, f: impl Fn(&[f64]) -> f64) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if w > 0 && t + 1 >= w {
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

    fn na_arg_extreme(win: &[f64], want_max: bool) -> usize {
        let mut best = 0usize;
        for (i, &v) in win.iter().enumerate() {
            let better = if want_max {
                v > win[best]
            } else {
                v < win[best]
            };
            if better {
                best = i;
            }
        }
        best
    }

    fn na_extreme(x: &[f64], w: usize, want_max: bool) -> Vec<f64> {
        na_stat(x, w, |win| win[na_arg_extreme(win, want_max)])
    }

    fn na_median(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let mut s = win.to_vec();
            s.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let n = s.len();
            if n % 2 == 1 {
                s[n / 2]
            } else {
                (s[n / 2 - 1] + s[n / 2]) / 2.0
            }
        })
    }

    fn na_quantile(x: &[f64], q: f64, w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let mut s = win.to_vec();
            s.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let n = s.len();
            let pos = q * (n - 1) as f64;
            let lo = pos.floor() as usize;
            let hi = pos.ceil() as usize;
            let frac = pos - lo as f64;
            s[lo] + (s[hi] - s[lo]) * frac
        })
    }

    fn na_central_moments(win: &[f64]) -> (f64, f64, f64) {
        let n = win.len() as f64;
        let mean = win.iter().sum::<f64>() / n;
        let mut m2 = 0.0;
        let mut m3 = 0.0;
        let mut m4 = 0.0;
        for &v in win {
            let d = v - mean;
            let d2 = d * d;
            m2 += d2;
            m3 += d2 * d;
            m4 += d2 * d2;
        }
        (m2 / n, m3 / n, m4 / n)
    }

    fn na_skewness(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let (m2, m3, _) = na_central_moments(win);
            if m2 <= 0.0 {
                return f64::NAN;
            }
            let std = m2.sqrt();
            if std <= DISPERSION_EPSILON {
                return f64::NAN;
            }
            m3 / (m2 * std)
        })
    }

    fn na_kurtosis(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let (m2, _, m4) = na_central_moments(win);
            if m2 <= 0.0 {
                return f64::NAN;
            }
            m4 / (m2 * m2) - 3.0
        })
    }

    fn na_ir(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            if win.len() < 2 {
                return f64::NAN;
            }
            let n = win.len() as f64;
            let mean = win.iter().sum::<f64>() / n;
            let var = win.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / (n - 1.0);
            let std = var.sqrt();
            if std <= DISPERSION_EPSILON {
                return f64::NAN;
            }
            mean / std
        })
    }

    fn na_product(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            if win.contains(&0.0) {
                0.0
            } else {
                win.iter().product()
            }
        })
    }

    fn na_scale(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let lo = win.iter().cloned().fold(f64::INFINITY, f64::min);
            let hi = win.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
            let range = hi - lo;
            if range <= DISPERSION_EPSILON {
                f64::NAN
            } else {
                (win[win.len() - 1] - lo) / range
            }
        })
    }

    fn na_quantile_pos(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let v = win[win.len() - 1];
            win.iter().filter(|&&s| s < v).count() as f64 / win.len() as f64
        })
    }

    fn na_decay_linear(x: &[f64], w: usize) -> Vec<f64> {
        na_stat(x, w, |win| {
            let weight_sum = w as f64 * (w as f64 + 1.0) / 2.0;
            win.iter()
                .enumerate()
                .map(|(i, &v)| (i + 1) as f64 * v)
                .sum::<f64>()
                / weight_sum
        })
    }

    fn na_ols(y: &[f64], x: &[f64], w: usize) -> (Vec<f64>, Vec<f64>) {
        let n = y.len().min(x.len());
        let mut betas = vec![f64::NAN; y.len().max(x.len())];
        let mut resids = vec![f64::NAN; y.len().max(x.len())];
        for t in 0..n {
            if w > 0 && t + 1 >= w {
                let wy = &y[t + 1 - w..=t];
                let wx = &x[t + 1 - w..=t];
                if wy.iter().chain(wx).any(|v| v.is_nan()) {
                    continue;
                }
                let k = wy.len() as f64;
                let mx = wx.iter().sum::<f64>() / k;
                let my = wy.iter().sum::<f64>() / k;
                let sxx: f64 = wx.iter().map(|v| (v - mx) * (v - mx)).sum();
                if sxx <= 0.0 {
                    continue;
                }
                let sxy: f64 = wx.iter().zip(wy).map(|(a, b)| (a - mx) * (b - my)).sum();
                let beta = sxy / sxx;
                let alpha = my - beta * mx;
                betas[t] = beta;
                resids[t] = wy[wy.len() - 1] - alpha - beta * wx[wx.len() - 1];
            }
        }
        (betas, resids)
    }

    fn na_covariance(x: &[f64], y: &[f64], w: usize) -> Vec<f64> {
        (0..x.len().min(y.len()))
            .map(|t| {
                if w >= 2 && t + 1 >= w {
                    let wx = &x[t + 1 - w..=t];
                    let wy = &y[t + 1 - w..=t];
                    if wx.iter().chain(wy).any(|v| v.is_nan()) {
                        return f64::NAN;
                    }
                    let k = w as f64;
                    let mx = wx.iter().sum::<f64>() / k;
                    let my = wy.iter().sum::<f64>() / k;
                    wx.iter()
                        .zip(wy)
                        .map(|(a, b)| (a - mx) * (b - my))
                        .sum::<f64>()
                        / (k - 1.0)
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    fn na_returns(x: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if w > 0 && t >= w {
                    let base = x[t - w];
                    let cur = x[t];
                    if base.is_nan() || cur.is_nan() || base.abs() <= BASE_EPSILON {
                        f64::NAN
                    } else {
                        cur / base - 1.0
                    }
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    fn na_sign_delta(x: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if w > 0 && t >= w && !x[t].is_nan() && !x[t - w].is_nan() {
                    let c = x[t] - x[t - w];
                    if c > 0.0 {
                        1.0
                    } else if c < 0.0 {
                        -1.0
                    } else {
                        0.0
                    }
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    fn na_trend_slope(x: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if w >= 2 && t + 1 >= w {
                    let win = &x[t + 1 - w..=t];
                    if win.iter().any(|v| v.is_nan()) {
                        return f64::NAN;
                    }
                    let k = win.len() as f64;
                    let mean_i = (k - 1.0) / 2.0;
                    let mean_x = win.iter().sum::<f64>() / k;
                    let sxx: f64 = (0..win.len())
                        .map(|i| {
                            let di = i as f64 - mean_i;
                            di * di
                        })
                        .sum();
                    let sxy: f64 = win
                        .iter()
                        .enumerate()
                        .map(|(i, &v)| (i as f64 - mean_i) * (v - mean_x))
                        .sum();
                    sxy / sxx
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    fn na_backfill(x: &[f64], d: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if !x[t].is_nan() {
                    return x[t];
                }
                for back in 1..=d {
                    if back <= t && !x[t - back].is_nan() {
                        return x[t - back];
                    }
                }
                f64::NAN
            })
            .collect()
    }

    fn na_count_valid(x: &[f64], w: usize) -> Vec<f64> {
        (0..x.len())
            .map(|t| {
                if w > 0 && t + 1 >= w {
                    x[t + 1 - w..=t].iter().filter(|v| !v.is_nan()).count() as f64
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    #[test]
    fn ts_min_and_ts_max_match_naive() {
        let x = gen_series(101, 60);
        let tied: Vec<f64> = gen_series(102, 60).iter().map(|v| v.trunc()).collect();
        for series in [&x, &tied] {
            for w in [1usize, 2, 7, 30, 60, 61, 0] {
                assert_series_eq(&ts_min(series, w), &na_extreme(series, w, false), "ts_min");
                assert_series_eq(&ts_max(series, w), &na_extreme(series, w, true), "ts_max");
            }
        }
    }

    #[test]
    fn ts_argmax_and_ts_argmin_match_naive_with_earliest_ties() {
        let x = gen_series(111, 55);
        let tied: Vec<f64> = gen_series(112, 55).iter().map(|v| v.trunc()).collect();
        for series in [&x, &tied] {
            for w in [1usize, 3, 10, 40, 55, 56] {
                assert_series_eq(
                    &ts_argmax(series, w),
                    &bars_since_extreme(series, w, true),
                    "ts_argmax",
                );
                assert_series_eq(
                    &ts_argmin(series, w),
                    &bars_since_extreme(series, w, false),
                    "ts_argmin",
                );
            }
        }

        let flat = vec![4.2f64; 10];
        let got = ts_argmax(&flat, 4);
        assert!(got.iter().skip(3).all(|v| *v == 3.0));
        let got_min = ts_argmin(&flat, 4);
        assert!(got_min.iter().skip(3).all(|v| *v == 3.0));
    }

    fn bars_since_extreme(s: &[f64], w: usize, want_max: bool) -> Vec<f64> {
        (0..s.len())
            .map(|t| {
                if w > 0 && t + 1 >= w {
                    let win = &s[t + 1 - w..=t];
                    if win.iter().any(|v| v.is_nan()) {
                        f64::NAN
                    } else {
                        let pos = na_arg_extreme(win, want_max);
                        (win.len() - 1 - pos) as f64
                    }
                } else {
                    f64::NAN
                }
            })
            .collect()
    }

    #[test]
    fn argmax_offset_semantics_on_handcrafted_series() {

        let x = [1.0, 9.0, 2.0, 3.0, 4.0];
        let got = ts_argmax(&x, 4);
        assert!(got[..3].iter().all(|v| v.is_nan()));
        assert_eq!(got[3], 2.0);
        assert_eq!(got[4], 3.0);
    }

    #[test]
    fn ts_max_diff_and_ts_min_diff_match_naive_and_signed() {
        let x = gen_series(121, 50);
        for w in [1usize, 4, 15, 50, 51, 0] {
            assert_series_eq(
                &ts_max_diff(&x, w),
                &na_zip_sub_last(&x, &na_extreme(&x, w, true)),
                "ts_max_diff",
            );
            assert_series_eq(
                &ts_min_diff(&x, w),
                &na_zip_sub_last(&x, &na_extreme(&x, w, false)),
                "ts_min_diff",
            );
        }

        for t in 14..50 {
            assert!(ts_max_diff(&x, 15)[t] <= 0.0);
            assert!(ts_min_diff(&x, 15)[t] >= 0.0);
        }
    }

    fn na_zip_sub_last(x: &[f64], extreme: &[f64]) -> Vec<f64> {
        extreme
            .iter()
            .enumerate()
            .map(|(t, &e)| if e.is_nan() { f64::NAN } else { x[t] - e })
            .collect()
    }

    #[test]
    fn ts_median_matches_naive_for_odd_and_even_windows() {
        let x = gen_series(131, 48);
        for w in [1usize, 2, 5, 8, 48, 49, 0] {
            assert_series_eq(&ts_median(&x, w), &na_median(&x, w), "ts_median");
        }
        let hand = ts_median(&[5.0, 1.0, 3.0], 3);
        assert_eq!(hand[2], 3.0);
        let even = ts_median(&[1.0, 2.0, 3.0, 10.0], 4);
        assert_eq!(even[3], 2.5);
    }

    #[test]
    fn ts_quantile_matches_naive_and_interpolates() {
        let x = gen_series(141, 48);
        for q in [0.0f64, 0.1, 0.25, 0.5, 0.75, 0.99, 1.0] {
            for w in [2usize, 5, 17, 48] {
                assert_series_eq(
                    &ts_quantile(&x, q, w),
                    &na_quantile(&x, q, w),
                    "ts_quantile",
                );
            }
        }

        assert_series_eq(&ts_quantile(&x, 0.5, 9), &ts_median(&x, 9), "q50==median");
        assert_series_eq(&ts_quantile(&x, 0.0, 9), &ts_min(&x, 9), "q0==min");
        assert_series_eq(&ts_quantile(&x, 1.0, 9), &ts_max(&x, 9), "q1==max");

        let interp = ts_quantile(&[0.0, 10.0], 0.25, 2);
        assert_eq!(interp[1], 2.5);

        for bad_q in [f64::NAN, -0.1, 1.5, f64::INFINITY] {
            assert!(ts_quantile(&x, bad_q, 5).iter().all(|v| v.is_nan()));
        }
    }

    #[test]
    fn ts_skewness_and_kurtosis_match_naive_two_pass() {

        let skewed: Vec<f64> = gen_series(151, 70).iter().map(|v| v.abs()).collect();
        for w in [3usize, 6, 20, 70] {
            assert_series_eq_tol(
                &ts_skewness(&skewed, w),
                &na_skewness(&skewed, w),
                1e-8,
                1e-10,
                "ts_skewness",
            );
            assert_series_eq_tol(
                &ts_kurtosis(&skewed, w),
                &na_kurtosis(&skewed, w),
                1e-8,
                1e-10,
                "ts_kurtosis",
            );
        }

        let symmetric = [-3.0, -1.0, 1.0, 3.0];
        let sk = ts_skewness(&symmetric, 4);
        assert!(sk[3].abs() < 1e-12);

        let flat = vec![7.0f64; 10];
        assert!(ts_skewness(&flat, 5).iter().skip(4).all(|v| v.is_nan()));
        assert!(ts_kurtosis(&flat, 5).iter().skip(4).all(|v| v.is_nan()));
        assert!(ts_skewness(&skewed, 2)[1].is_finite());
        assert!(ts_kurtosis(&skewed, 2)[1].is_finite());
    }

    #[test]
    fn ts_ir_matches_naive_and_nans_on_flat_windows() {
        let x = gen_series(161, 50);
        for w in [2usize, 5, 16, 50, 51, 1, 0] {
            assert_series_eq(&ts_ir(&x, w), &na_ir(&x, w), "ts_ir");
        }
        let flat = vec![2.5f64; 12];
        assert!(ts_ir(&flat, 6).iter().skip(5).all(|v| v.is_nan()));
    }

    #[test]
    fn ts_product_matches_naive_handles_zeros_and_nans() {
        let x: Vec<f64> = gen_series(171, 45).iter().map(|v| v / 25.0).collect();
        for w in [1usize, 2, 6, 20, 45, 46, 0] {
            assert_series_eq_tol(
                &ts_product(&x, w),
                &na_product(&x, w),
                1e-8,
                1e-12,
                "ts_product",
            );
        }
        let hand = [1.0, -2.0, 0.0, 4.0];
        let got = ts_product(&hand, 2);
        assert!(got[0].is_nan());
        assert_eq!(got[1], -2.0);
        assert_eq!(got[2], 0.0);
        assert_eq!(got[3], 0.0);
        let nan_series = [1.0, 2.0, f64::NAN, 4.0, 5.0];
        let got_nan = ts_product(&nan_series, 2);
        assert!(got_nan[2].is_nan());
        assert!(got_nan[3].is_nan());
        assert_eq!(got_nan[4], 20.0);
    }

    #[test]
    fn ts_scale_matches_naive_and_stays_in_unit_range() {
        let x = gen_series(181, 50);
        for w in [2usize, 5, 18, 50, 51, 0] {
            assert_series_eq(&ts_scale(&x, w), &na_scale(&x, w), "ts_scale");
        }
        for t in 4..50 {
            let v = ts_scale(&x, 5)[t];
            assert!((0.0..=1.0).contains(&v), "scale out of range: {}", v);
        }
        let flat = vec![3.0f64; 8];
        assert!(ts_scale(&flat, 4).iter().skip(3).all(|v| v.is_nan()));

        let mixed = [2.0, 0.0, 1.0];
        assert_eq!(ts_scale(&mixed, 3)[2], 0.5);
        assert_eq!(ts_scale(&[5.0, 1.0], 2)[1], 0.0);
        assert_eq!(ts_scale(&[1.0, 5.0], 2)[1], 1.0);
    }

    #[test]
    fn ts_quantile_pos_matches_naive_and_handles_ties() {
        let x: Vec<f64> = gen_series(191, 50).iter().map(|v| v.trunc()).collect();
        for w in [1usize, 3, 9, 30, 50, 51, 0] {
            assert_series_eq(&ts_quantile_pos(&x, w), &na_quantile_pos(&x, w), "qpos");
        }

        let ramp: Vec<f64> = (0..6).map(|i| i as f64).collect();
        let qp = ts_quantile_pos(&ramp, 4);
        assert_eq!(qp[3], 3.0 / 4.0);
        assert_eq!(qp[5], 3.0 / 4.0);

        let ties = ts_quantile_pos(&[5.0, 5.0, 5.0, 5.0], 4);
        assert_eq!(ties[3], 0.0);
    }

    #[test]
    fn ts_decay_linear_matches_naive_and_hand_weights() {
        let x = gen_series(201, 44);
        for w in [1usize, 2, 5, 12, 44, 45, 0] {
            assert_series_eq(&ts_decay_linear(&x, w), &na_decay_linear(&x, w), "decay");
        }

        let hand = ts_decay_linear(&[1.0, 2.0, 3.0], 3);
        assert_eq!(hand[2], 14.0 / 6.0);

        let flat = ts_decay_linear(&[4.0f64; 6], 6);
        assert!(flat.iter().skip(5).all(|v| *v == 4.0));
        let nan_in_window = ts_decay_linear(&[1.0, f64::NAN, 3.0], 3);
        assert!(nan_in_window[2].is_nan());
    }

    #[test]
    fn regression_beta_resid_and_covariance_match_naive() {
        let y = gen_series(211, 56);
        let x = gen_series(212, 56);
        for w in [2usize, 4, 11, 56, 57, 0] {
            let (got_beta, got_resid) = (
                ts_regression_beta(&y, &x, w),
                ts_regression_resid(&y, &x, w),
            );
            let (want_beta, want_resid) = na_ols(&y, &x, w);
            assert_series_eq(&got_beta, &want_beta, "beta");
            assert_series_eq_tol(&got_resid, &want_resid, 1e-8, 1e-8, "resid");
            assert_series_eq(&ts_covariance(&x, &y, w), &na_covariance(&x, &y, w), "cov");
        }

        let xs: Vec<f64> = (0..10).map(|i| i as f64 + 1.0).collect();
        let ys: Vec<f64> = xs.iter().map(|&v| 3.0 * v - 2.0).collect();
        let beta = ts_regression_beta(&ys, &xs, 5);
        let resid = ts_regression_resid(&ys, &xs, 5);
        let mut want_beta = vec![f64::NAN; 10];
        want_beta[4..].fill(3.0);
        assert_series_eq(&beta, &want_beta, "perfect-line beta");
        for r in resid.iter().skip(4) {
            assert!(r.abs() < 1e-9, "resid not ~0: {}", r);
        }

        let flat = vec![5.0f64; 10];
        assert!(ts_regression_beta(&y, &flat, 4).iter().all(|v| v.is_nan()));
        assert!(ts_regression_resid(&y, &flat, 4).iter().all(|v| v.is_nan()));
        let cov_flat = ts_covariance(&flat, &y[..10], 4);
        assert!(cov_flat.iter().skip(3).all(|v| v.abs() < 1e-9));

        let auto = ts_covariance(&x, &x, 10);
        let manual_var = na_stat(&x, 10, |win| {
            let n = win.len() as f64;
            let m = win.iter().sum::<f64>() / n;
            win.iter().map(|v| (v - m) * (v - m)).sum::<f64>() / (n - 1.0)
        });
        assert_series_eq(&auto, &manual_var, "cov(x,x)==var");
    }

    #[test]
    fn ts_returns_matches_naive_and_guards_zero_base() {
        let mut x = gen_series(221, 40);
        for v in x.iter_mut() {
            *v += 110.0;
        }
        for w in [1usize, 3, 10, 39, 40, 41, 0] {
            assert_series_eq(&ts_returns(&x, w), &na_returns(&x, w), "returns");
        }
        let simple = ts_returns(&[100.0, 110.0, 99.0], 1);
        assert_series_eq(&simple, &[f64::NAN, 0.1, 99.0 / 110.0 - 1.0], "returns");

        let guarded = ts_returns(&[0.0, 5.0, 1e-13, 4.0, 2.0], 1);
        assert!(guarded[1].is_nan());
        assert!(guarded[3].is_nan());
        assert!(guarded[4].is_finite());
    }

    #[test]
    fn ts_sign_delta_matches_naive_and_takes_three_values() {
        let x = gen_series(231, 40);
        for w in [1usize, 3, 10, 39, 40, 0] {
            assert_series_eq(&ts_sign_delta(&x, w), &na_sign_delta(&x, w), "sign_delta");
        }
        let hand = ts_sign_delta(&[1.0, 3.0, 3.0, 2.0], 2);

        assert_eq!(hand[2], 1.0);

        assert_eq!(hand[3], -1.0);
        let unchanged = ts_sign_delta(&[5.0, 9.0, 5.0, 9.0, 5.0], 4);
        assert_eq!(unchanged[4], 0.0);
    }

    #[test]
    fn ts_trend_slope_matches_naive_and_detects_ramps() {
        let x = gen_series(241, 50);
        for w in [2usize, 4, 12, 50, 51, 1, 0] {
            assert_series_eq(&ts_trend_slope(&x, w), &na_trend_slope(&x, w), "slope");
        }
        let ramp: Vec<f64> = (0..10).map(|i| 7.0 + 0.5 * i as f64).collect();
        let slopes = ts_trend_slope(&ramp, 6);
        let mut want_slopes = vec![f64::NAN; 10];
        want_slopes[5..].fill(0.5);
        assert_series_eq(&slopes, &want_slopes, "ramp slope 0.5");
        let flat = ts_trend_slope(&[3.0f64; 9], 5);
        assert!(flat.iter().skip(4).all(|v| *v == 0.0));
    }

    #[test]
    fn ts_backfill_fills_within_horizon_only() {
        let nan = f64::NAN;
        let x = [nan, 5.0, nan, nan, 7.0, nan, nan, nan];
        let filled = ts_backfill(&x, 2);
        let want = [nan, 5.0, 5.0, 5.0, 7.0, 7.0, 7.0, nan];
        assert_series_eq(&filled, &want, "backfill d=2");

        let tight = ts_backfill(&x, 1);
        let want_tight = [nan, 5.0, 5.0, nan, 7.0, 7.0, nan, nan];
        assert_series_eq(&tight, &want_tight, "backfill d=1");

        let none = ts_backfill(&x, 0);
        let want_none = [nan, 5.0, nan, nan, 7.0, nan, nan, nan];
        assert_series_eq(&none, &want_none, "backfill d=0");

        assert!(ts_backfill(&[nan, nan, 1.0], 5)[1].is_nan());
        assert_series_eq(&ts_backfill(&x, 2), &na_backfill(&x, 2), "backfill naive");
    }

    #[test]
    fn ts_count_valid_matches_naive_and_warms_up() {
        let nan = f64::NAN;
        let x = [1.0, nan, nan, 4.0, 5.0, nan, 7.0];
        for w in [1usize, 2, 4, 7, 8, 0] {
            assert_series_eq(
                &ts_count_valid(&x, w),
                &na_count_valid(&x, w),
                "count_valid",
            );
        }
        let cv = ts_count_valid(&x, 3);
        assert!(cv[..2].iter().all(|v| v.is_nan()));
        assert_eq!(cv[2], 1.0);
        assert_eq!(cv[3], 1.0);
        assert_eq!(cv[4], 2.0);
    }

    #[test]
    fn cs_rank_normalises_with_averaged_ties_and_skips_nan() {
        let x = [3.0, 1.0, 3.0, 2.0];
        let ranked = cs_rank(&x);

        assert_eq!(ranked[1], 0.25);
        assert_eq!(ranked[3], 0.5);
        assert_eq!(ranked[0], 0.875);
        assert_eq!(ranked[2], 0.875);

        let with_nan = [f64::NAN, 10.0, 20.0, 30.0];
        let r = cs_rank(&with_nan);
        assert!(r[0].is_nan());
        assert_eq!(r[1], 1.0 / 3.0);
        assert_eq!(r[2], 2.0 / 3.0);
        assert_eq!(r[3], 1.0);

        assert!(cs_rank(&[f64::NAN; 3]).iter().all(|v| v.is_nan()));
        assert_eq!(cs_rank(&[42.0])[0], 1.0);

        let big: Vec<f64> = gen_series(251, 64);
        for v in cs_rank(&big) {
            assert!(v.is_nan() || (v > 0.0 && v <= 1.0));
        }
    }

    #[test]
    fn cs_zscore_standardises_population_style() {
        let z = cs_zscore(&[1.0, 2.0, 3.0]);
        let s = (2.0f64 / 3.0).sqrt();
        assert_series_eq(&z, &[-1.0 / s, 0.0, 1.0 / s], "zscore");

        let with_nan = [1.0, f64::NAN, 3.0];
        let zn = cs_zscore(&with_nan);
        assert_eq!(zn[0], -1.0);
        assert!(zn[1].is_nan());
        assert_eq!(zn[2], 1.0);

        let flat = cs_zscore(&[4.0, 4.0, 4.0]);
        assert!(flat.iter().all(|v| v.is_nan()));
        assert!(cs_zscore(&[f64::NAN; 2]).iter().all(|v| v.is_nan()));

        let big: Vec<f64> = gen_series(261, 80);
        let zb = cs_zscore(&big);
        let valid: Vec<&f64> = zb.iter().filter(|v| !v.is_nan()).collect();
        let mean = valid.iter().map(|v| **v).sum::<f64>() / valid.len() as f64;
        let var = valid.iter().map(|v| *v * *v).sum::<f64>() / valid.len() as f64;
        assert!(mean.abs() < 1e-9, "mean {}", mean);
        assert!((var - 1.0).abs() < 1e-9, "var {}", var);
    }

    #[test]
    fn cs_scale_hits_target_absolute_sum() {
        let scaled = cs_scale(&[1.0, -2.0, 4.0], 10.0);
        assert_series_eq(&scaled, &[10.0 / 7.0, -20.0 / 7.0, 40.0 / 7.0], "cs_scale");
        let total: f64 = scaled.iter().map(|v| v.abs()).sum();
        assert!((total - 10.0).abs() < 1e-12);

        assert!(cs_scale(&[0.0, 0.0], 5.0).iter().all(|v| v.is_nan()));

        assert!(cs_scale(&[1.0, -3.0], 0.0).iter().all(|v| *v == 0.0));

        assert!(cs_scale(&[1.0, 2.0], f64::NAN).iter().all(|v| v.is_nan()));
        let mixed = cs_scale(&[1.0, f64::NAN], 6.0);
        assert_eq!(mixed[0], 6.0);
        assert!(mixed[1].is_nan());
    }

    #[test]
    fn cs_demean_centers_the_universe() {
        let d = cs_demean(&[1.0, 2.0, 6.0]);
        assert_series_eq(&d, &[-2.0, -1.0, 3.0], "demean");
        let dn = cs_demean(&[1.0, f64::NAN, 3.0]);
        assert_eq!(dn[0], -1.0);
        assert!(dn[1].is_nan());
        assert_eq!(dn[2], 1.0);
        assert!(cs_demean(&[f64::NAN; 2]).iter().all(|v| v.is_nan()));

        let big: Vec<f64> = gen_series(271, 70);
        let sum: f64 = cs_demean(&big).iter().sum();
        assert!(sum.abs() < 1e-9);
    }

    #[test]
    fn elementwise_unary_operators_follow_conventions() {
        let x = [-2.5, 0.0, -0.0, 3.75, f64::NAN];
        assert_series_eq(&abs_val(&x), &[2.5, 0.0, 0.0, 3.75, f64::NAN], "abs");

        let logs = log_nat(&[1.0, std::f64::consts::E, 0.0, -3.0, f64::NAN]);
        assert_series_eq(&logs, &[0.0, 1.0, f64::NAN, f64::NAN, f64::NAN], "log");

        let signs = sign_of(&[-9.0, -0.0, 0.0, 4.5, f64::NAN]);
        assert_eq!(signs[0], -1.0);
        assert_eq!(signs[1], 0.0);
        assert_eq!(signs[2], 0.0);
        assert_eq!(signs[3], 1.0);
        assert!(signs[4].is_nan());
    }

    #[test]
    fn elem_max_min_propagate_nan_and_align_lengths() {
        let a = [1.0, 5.0, f64::NAN, 0.0];
        let b = [2.0, 3.0, 7.0, -1.0, 9.0];
        assert_series_eq(
            &elem_max(&a, &b),
            &[2.0, 5.0, f64::NAN, 0.0, f64::NAN],
            "emax",
        );
        assert_series_eq(
            &elem_min(&a, &b),
            &[1.0, 3.0, f64::NAN, -1.0, f64::NAN],
            "emin",
        );
        assert!(elem_max(&[], &[]).is_empty());
        assert_series_eq(&elem_min(&[f64::NAN], &[-1.0]), &[f64::NAN], "emin nan");
    }

    #[test]
    fn if_else_selects_branches_and_pads_missing_operands() {
        let cond = [true, false, true, false];
        let then = [1.0, 2.0, 3.0];
        let els = [10.0, 20.0, 30.0, 40.0];
        let got = if_else(&cond, &then, &els);
        assert_series_eq(&got, &[1.0, 20.0, 3.0, 40.0], "if_else");

        let partial = if_else(&[true, true], &[1.0], &[9.0, 9.0]);
        assert_eq!(partial[0], 1.0);
        assert!(partial[1].is_nan());

        let missing_cond = if_else(&[false], &[1.0, 2.0], &[3.0, 4.0]);
        assert_eq!(missing_cond[0], 3.0);
        assert!(missing_cond[1].is_nan());
        assert!(if_else(&[], &[], &[]).is_empty());
    }

    type UnaryPair = (
        &'static str,
        Box<dyn Fn(&[f64], usize) -> Vec<f64>>,
        Box<dyn Fn(&[f64], usize) -> Vec<f64>>,
    );

    type BinaryPair = (
        &'static str,
        Box<dyn Fn(&[f64], &[f64], usize) -> Vec<f64>>,
        Box<dyn Fn(&[f64], &[f64], usize) -> Vec<f64>>,
    );

    #[test]
    fn nan_contamination_windows_match_naive_for_all_rolling_ops() {
        let base = gen_series(281, 40);
        let mut x = base.clone();
        x[10] = f64::NAN;
        let mut y = gen_series(282, 40);
        y[10] = f64::NAN;

        let unary: Vec<UnaryPair> = vec![
            (
                "min",
                Box::new(ts_min),
                Box::new(|s, w| na_extreme(s, w, false)),
            ),
            (
                "max",
                Box::new(ts_max),
                Box::new(|s, w| na_extreme(s, w, true)),
            ),
            (
                "argmax",
                Box::new(ts_argmax),
                Box::new(|s, w| bars_since_extreme(s, w, true)),
            ),
            (
                "argmin",
                Box::new(ts_argmin),
                Box::new(|s, w| bars_since_extreme(s, w, false)),
            ),
            ("median", Box::new(ts_median), Box::new(na_median)),
            ("skew", Box::new(ts_skewness), Box::new(na_skewness)),
            ("kurt", Box::new(ts_kurtosis), Box::new(na_kurtosis)),
            ("ir", Box::new(ts_ir), Box::new(na_ir)),
            ("product", Box::new(ts_product), Box::new(na_product)),
            ("scale", Box::new(ts_scale), Box::new(na_scale)),
            ("qpos", Box::new(ts_quantile_pos), Box::new(na_quantile_pos)),
            (
                "decay",
                Box::new(ts_decay_linear),
                Box::new(na_decay_linear),
            ),
            ("slope", Box::new(ts_trend_slope), Box::new(na_trend_slope)),
            ("count", Box::new(ts_count_valid), Box::new(na_count_valid)),
        ];
        for (name, fast, slow) in &unary {
            for w in [4usize, 7, 12] {
                assert_series_eq_tol(
                    &fast(&x, w),
                    &slow(&x, w),
                    1e-8,
                    1e-8,
                    &format!("{} contaminated w={}", name, w),
                );
            }
        }

        let binary: Vec<BinaryPair> = vec![
            ("cov", Box::new(ts_covariance), Box::new(na_covariance)),
            (
                "beta",
                Box::new(|a: &[f64], b: &[f64], w| ts_regression_beta(a, b, w)),
                Box::new(|a: &[f64], b: &[f64], w| na_ols(a, b, w).0),
            ),
            (
                "resid",
                Box::new(|a: &[f64], b: &[f64], w| ts_regression_resid(a, b, w)),
                Box::new(|a: &[f64], b: &[f64], w| na_ols(a, b, w).1),
            ),
        ];
        for (name, fast, slow) in &binary {
            for w in [4usize, 9] {
                assert_series_eq_tol(
                    &fast(&y, &x, w),
                    &slow(&y, &x, w),
                    1e-8,
                    1e-8,
                    &format!("{} contaminated w={}", name, w),
                );
            }
        }

        for w in [4usize, 9] {
            assert_series_eq_tol(
                &ts_quantile(&x, 0.3, w),
                &na_quantile(&x, 0.3, w),
                1e-8,
                1e-8,
                "quantile contaminated",
            );
        }

        let mins = ts_min(&x, 4);
        assert!(mins[10..=13].iter().all(|v| v.is_nan()));
        assert!(!mins[9].is_nan());
        assert!(!mins[14].is_nan());
    }

    #[test]
    fn outputs_are_causal_prefixes_of_full_series_outputs() {
        let full = gen_series(291, 60);
        for cut in [10usize, 31, 59] {
            let prefix = &full[..cut];
            assert_series_eq(&ts_max(prefix, 5), &ts_max(&full, 5)[..cut], "causal max");
            assert_series_eq(
                &ts_median(prefix, 6),
                &ts_median(&full, 6)[..cut],
                "causal median",
            );
            assert_series_eq(&ts_ir(prefix, 7), &ts_ir(&full, 7)[..cut], "causal ir");
            assert_series_eq(
                &ts_decay_linear(prefix, 4),
                &ts_decay_linear(&full, 4)[..cut],
                "causal decay",
            );
            assert_series_eq(
                &ts_trend_slope(prefix, 5),
                &ts_trend_slope(&full, 5)[..cut],
                "causal slope",
            );
        }
    }

    #[test]
    fn degenerate_windows_yield_all_nan() {
        let x = gen_series(301, 12);
        let y = gen_series(302, 12);
        for w in [0usize, 13] {
            for got in [
                ts_min(&x, w),
                ts_max(&x, w),
                ts_median(&x, w),
                ts_quantile(&x, 0.5, w),
                ts_skewness(&x, w),
                ts_kurtosis(&x, w),
                ts_ir(&x, w),
                ts_product(&x, w),
                ts_argmax(&x, w),
                ts_argmin(&x, w),
                ts_max_diff(&x, w),
                ts_min_diff(&x, w),
                ts_scale(&x, w),
                ts_quantile_pos(&x, w),
                ts_decay_linear(&x, w),
                ts_regression_beta(&y, &x, w),
                ts_regression_resid(&y, &x, w),
                ts_covariance(&x, &y, w),
                ts_returns(&x, w.min(12)),
                ts_sign_delta(&x, w.min(12)),
                ts_count_valid(&x, w),
            ] {
                assert_eq!(got.len(), 12);
                assert!(got.iter().all(|v| v.is_nan()));
            }
        }

        assert_eq!(ts_backfill(&x, 13), x.to_vec());
        assert_eq!(ts_backfill(&x, 0), x.to_vec());
    }
}
