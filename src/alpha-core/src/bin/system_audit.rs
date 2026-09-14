use std::time::Instant;

use alpha_core::canonical::mapping::{canonical_map, ewma_smooth, rolling_zscore, sanitize_scores};
use alpha_core::canonical::metrics::{max_drawdown, sharpe};
use alpha_core::canonical::pnl::{compute_pnl, PnlConfig};
use alpha_core::evaluation::screening::{rank_survivors, screen_candidates, ScreeningThresholds};
use alpha_core::harness_config::HarnessConfig;
use alpha_core::strategies::mining::alpha_generator::{AlphaGenerator, GeneratorConfig};
use alpha_core::strategies::mining::batch_executor::execute_batch;
use alpha_core::strategies::mining::dag_builder::build_dag;

const SWEEP_SIZE: usize = 500;
const METAMORPHIC_SERIES: usize = 16;

struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self { Rng(seed | 1) }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545F4914F6CDD1D)
    }

    fn f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
}

fn load_csv(path: &str) -> (std::collections::HashMap<String, Vec<f64>>, usize) {
    let content = std::fs::read_to_string(path).expect("Cannot open data file");
    let mut close = Vec::new();
    let mut volume = Vec::new();
    let mut dates = std::collections::HashSet::new();

    for line in content.lines() {
        if line.is_empty() || line.starts_with("datetime") { continue; }
        let cols: Vec<&str> = line.split(',').collect();
        if cols.len() >= 8 {
            let c_val: f64 = cols[6].parse().unwrap_or(0.0);
            if c_val > 0.0 {
                close.push(c_val);
                volume.push(cols[7].parse::<f64>().unwrap_or(0.0));
                dates.insert(cols[0].split(' ').next().unwrap_or("").to_string());
            }
        }
    }

    let n = close.len();
    let mut ret = vec![0.0; n];
    for t in 1..n { ret[t] = close[t] / close[t-1] - 1.0; }

    let mut data: std::collections::HashMap<String, Vec<f64>> = std::collections::HashMap::new();
    data.insert("close".into(), close);
    data.insert("volume".into(), volume);
    data.insert("ret".into(), ret);

    (data, dates.len().max(1))
}

fn naive_rolling_zscore(smoothed: &[f64], window: usize) -> Vec<f64> {
    let n = smoothed.len();
    let mut z = vec![0.0; n];
    if n < window || window == 0 { return z; }
    for t in window..n {
        let w = &smoothed[t - window..t];
        let wf = window as f64;
        let mean = w.iter().sum::<f64>() / wf;
        let var = w.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / wf;
        let std = var.max(0.0).sqrt();
        if std > f64::EPSILON {
            z[t] = (smoothed[t] - mean) / std;
        }
    }
    z
}

struct CheckOutcome {
    name: String,
    ok: bool,
    detail: String,
}

fn check(name: &str, ok: bool, detail: String) -> CheckOutcome {
    CheckOutcome { name: name.to_string(), ok, detail }
}

fn print_section(title: &str, outcomes: &[CheckOutcome]) {
    let failed = outcomes.iter().filter(|o| !o.ok).count();
    println!("\n=== {} ===", title);
    for o in outcomes {
        println!("  [{:>4}] {} -- {}", if o.ok { "PASS" } else { "FAIL" }, o.name, o.detail);
    }
    if failed == 0 {
        println!("  Section result: {} checks, all passed", outcomes.len());
    } else {
        println!("  Section result: {} checks, {} FAILED", outcomes.len(), failed);
    }
}

fn mismatch_count(a: &[f64], b: &[f64], tol: f64) -> usize {
    a.iter().zip(b.iter()).filter(|(x, y)| (*x - *y).abs() > tol).count()
}

fn std_dev(v: &[f64]) -> f64 {
    let n = v.len() as f64;
    if v.is_empty() { return 0.0; }
    let mean = v.iter().sum::<f64>() / n;
    (v.iter().map(|x| (x - mean) * (x - mean)).sum::<f64>() / n).sqrt()
}

fn main() {
    let total_start = Instant::now();
    println!("============================================================");
    println!("  System Audit - QuantCore validation battery");
    println!("============================================================");

    let cfg = HarnessConfig::default();
    let (data, n_sessions) = load_csv("data/VN30F1M.csv");
    let bars = data.get("close").map(|c| c.len()).unwrap_or(0);
    let bars_per_day = bars / n_sessions.max(1);
    let ret = data.get("ret").cloned().unwrap_or_default();
    let pnl_cfg = PnlConfig { cost_per_side: cfg.cost_per_side, bars_per_day };
    println!("Loaded {} bars across {} sessions ({} bars/day)",
             bars, n_sessions, bars_per_day);

    let gen_cfg = GeneratorConfig {
        fields: vec!["close".into(), "volume".into()],
        ..Default::default()
    };
    let mut gen = AlphaGenerator::new(&gen_cfg, 20240601);
    let asts: Vec<_> = (0..SWEEP_SIZE).map(|_| gen.generate()).collect();
    let dag = build_dag(&asts);
    let score_matrix = execute_batch(&dag, &data, &dag.roots);

    let mut all_failed = 0usize;

    let mut s1: Vec<CheckOutcome> = Vec::new();

    let ref_idx = score_matrix.iter().take(METAMORPHIC_SERIES)
        .enumerate()
        .max_by(|(_, a), (_, b)| {
            std_dev(a).partial_cmp(&std_dev(b)).unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(i, _)| i)
        .unwrap_or(0);
    let base_score = sanitize_scores(&score_matrix[ref_idx]);
    let base = canonical_map(&base_score, &cfg, bars_per_day);
    let base_trades = base.trades_per_day;

    let scaled: Vec<f64> = base_score.iter().map(|v| v * 137.0).collect();
    let scaled_res = canonical_map(&scaled, &cfg, bars_per_day);
    let mm = mismatch_count(&base.position, &scaled_res.position, 1e-6);
    let allow = base.position.len() / 100;
    s1.push(check(
        "scale invariance (score x 137)",
        mm <= allow && base_trades > 0.0,
        format!("{} mismatched positions (allowed {}), reference trades/day {:.2}",
                mm, allow, base_trades),
    ));

    let shifted: Vec<f64> = base_score.iter().map(|v| v - 987654.0).collect();
    let shifted_res = canonical_map(&shifted, &cfg, bars_per_day);
    let mm = mismatch_count(&base.position, &shifted_res.position, 1e-6);
    s1.push(check(
        "shift invariance (score - 987654)",
        mm <= allow && base_trades > 0.0,
        format!("{} mismatched positions (allowed {})", mm, allow),
    ));

    let mirrored: Vec<f64> = base_score.iter().map(|v| -v).collect();
    let mirrored_res = canonical_map(&mirrored, &cfg, bars_per_day);
    let mm = mismatch_count(
        &base.position.iter().map(|p| -p).collect::<Vec<_>>(),
        &mirrored_res.position, 1e-9,
    );
    s1.push(check(
        "sign mirror (position(-s) == -position(s))",
        mm == 0,
        format!("{} mismatched positions (required 0)", mm),
    ));

    let prefix_len = 300;
    let mut prefixed = vec![f64::NAN; prefix_len];
    prefixed.extend_from_slice(&base_score);
    let prefixed_res = canonical_map(&prefixed, &cfg, bars_per_day);
    let margin = cfg.z_window + 128;
    let (sa, ea) = (margin, base.position.len() - margin);
    let mm = mismatch_count(
        &base.position[sa..ea],
        &prefixed_res.position[sa + prefix_len..ea + prefix_len],
        1e-6,
    );
    let checked = ea - sa;
    s1.push(check(
        "warmup-NaN prefix neutrality",
        mm <= checked / 100 && base_trades > 0.0 && prefixed_res.trades_per_day > 0.0,
        format!("{} mismatched of {} aligned bars (allowed <= {})",
                mm, checked, checked / 100),
    ));

    print_section("SECTION 1 - METAMORPHIC (real alpha scores)", &s1);
    all_failed += s1.iter().filter(|o| !o.ok).count();

    let mut s2: Vec<CheckOutcome> = Vec::new();
    let mut bad_nonfinite_pos = 0usize;
    let mut bad_cap = 0usize;
    let mut bad_identity = 0usize;
    let mut bad_turnover = 0usize;
    let mut bad_trade_count = 0usize;
    let mut bad_metric_finite = 0usize;
    let mut bad_sanitize = 0usize;
    let mut trading_alphas = 0usize;

    let days = score_matrix[0].len() as f64 / bars_per_day as f64;

    for score in &score_matrix {
        let sanitized = sanitize_scores(score);
        if !sanitized.iter().all(|v| v.is_finite()) { bad_sanitize += 1; }

        let cr = canonical_map(score, &cfg, bars_per_day);
        let pnl = compute_pnl(&cr.position, &ret, &pnl_cfg);

        if cr.position.iter().any(|p| !p.is_finite()) { bad_nonfinite_pos += 1; }
        if cr.position.iter().any(|p| p.abs() > cfg.cap + 1e-9) { bad_cap += 1; }

        for t in (1..cr.position.len()).step_by(97) {
            let change = (cr.position[t] - cr.position[t - 1]).abs();
            if (pnl.net[t] - (pnl.gross[t] - change * pnl_cfg.cost_per_side)).abs() > 1e-12 {
                bad_identity += 1;
                break;
            }
        }

        let canon_sum: f64 = cr.turnover.iter().sum();
        let implied = pnl.turnover_annualized / 250.0 * days;
        if (canon_sum - implied).abs() > 1e-6 * implied.abs().max(1.0) {
            bad_turnover += 1;
        }

        let changes = cr.position.windows(2)
            .filter(|w| (w[1] - w[0]).abs() > f64::EPSILON)
            .count();
        if (cr.trades_per_day - changes as f64 / bars_per_day as f64).abs() > 1e-12 {
            bad_trade_count += 1;
        }
        if changes > 0 { trading_alphas += 1; }

        let daily: Vec<f64> = pnl.net.chunks(bars_per_day)
            .map(|c| c.iter().sum::<f64>()).collect();
        let sr = sharpe(&daily, bars_per_day);
        let mdd = max_drawdown(&daily);
        if !(sr.is_finite() && mdd.is_finite() && pnl.cost_drag_pct.is_finite()
            && pnl.cost_drag_pct >= 0.0) {
            bad_metric_finite += 1;
        }
    }

    s2.push(check("sanitize_scores emits finite everywhere",
        bad_sanitize == 0, format!("{} violations", bad_sanitize)));
    s2.push(check("positions all finite",
        bad_nonfinite_pos == 0, format!("{} violations", bad_nonfinite_pos)));
    s2.push(check("|position| <= cap everywhere",
        bad_cap == 0, format!("{} violations", bad_cap)));
    s2.push(check("net == gross - cost*|dp| bar-by-bar",
        bad_identity == 0, format!("{} violations", bad_identity)));
    s2.push(check("cross-module turnover consistency",
        bad_turnover == 0, format!("{} violations", bad_turnover)));
    s2.push(check("trades_per_day == position changes / day",
        bad_trade_count == 0, format!("{} violations", bad_trade_count)));
    s2.push(check("metrics finite and drag >= 0",
        bad_metric_finite == 0, format!("{} violations", bad_metric_finite)));
    s2.push(check("sweep actually exercises trading",
        trading_alphas > 0,
        format!("{}/{} alphas traded at least once", trading_alphas, SWEEP_SIZE)));

    print_section(&format!("SECTION 2 - INVARIANT SWEEP ({} alphas)", SWEEP_SIZE), &s2);
    all_failed += s2.iter().filter(|o| !o.ok).count();

    let mut s3: Vec<CheckOutcome> = Vec::new();

    let smooth_real = ewma_smooth(&base_score, cfg.span);
    let fast_z = rolling_zscore(&smooth_real, cfg.z_window);
    let slow_z = naive_rolling_zscore(&smooth_real, cfg.z_window);
    let mut worst_rel = 0.0f64;
    let diffs: Vec<f64> = fast_z.iter().zip(slow_z.iter())
        .filter_map(|(&a, &b)| {
            if b.is_finite() && b.abs() > 1e-6 {
                Some((a - b).abs() / b.abs())
            } else {
                None
            }
        })
        .collect();
    if let Some(w) = diffs.iter().fold(None::<f64>, |acc, &d| Some(acc.unwrap_or(0.0).max(d))) {
        worst_rel = w;
    }
    s3.push(check(
        "rolling_zscore vs naive O(n*w) reference",
        worst_rel < 1e-8,
        format!("worst relative deviation {:.2e} over {} comparable bars",
                worst_rel, diffs.len()),
    ));

    let daily_ref: Vec<f64> = {
        let pnl = compute_pnl(&base.position, &ret, &pnl_cfg);
        pnl.net.chunks(bars_per_day).map(|c| c.iter().sum::<f64>()).collect()
    };
    let n_d = daily_ref.len() as f64;
    let mean_d = daily_ref.iter().sum::<f64>() / n_d;
    let sd_d = (daily_ref.iter().map(|x| (x - mean_d) * (x - mean_d)).sum::<f64>()
        / (n_d - 1.0).max(1.0)).sqrt();
    let manual_sharpe = if sd_d > 1e-12 { mean_d / sd_d * 250f64.sqrt() } else { 0.0 };
    let lib_sharpe = sharpe(&daily_ref, bars_per_day);
    let dev = (manual_sharpe - lib_sharpe).abs();
    s3.push(check(
        "sharpe vs manual formula",
        dev < 1e-9,
        format!("manual {:.12}, library {:.12}, deviation {:.2e}",
                manual_sharpe, lib_sharpe, dev),
    ));

    print_section("SECTION 3 - DIFFERENTIAL (optimised vs naive)", &s3);
    all_failed += s3.iter().filter(|o| !o.ok).count();

    let mut s4: Vec<CheckOutcome> = Vec::new();

    let n_canary = 20_000;
    let mut close_c = vec![100.0; n_canary];
    for t in 1..n_canary {
        let r_t = 0.0008 * (2.0 * std::f64::consts::PI * t as f64 / 64.0).sin();
        close_c[t] = close_c[t - 1] * (1.0 + r_t);
    }
    let mut ret_c = vec![0.0; n_canary];
    for t in 1..n_canary { ret_c[t] = close_c[t] / close_c[t - 1] - 1.0; }

    let oracle: Vec<f64> = (0..n_canary)
        .map(|t| if t + 1 < n_canary {
            if ret_c[t + 1] > 0.0 { 5.0 } else { -5.0 }
        } else { 0.0 })
        .collect();

    let oracle_long = canonical_map(&oracle, &cfg, bars_per_day);
    let pnl_long = compute_pnl(&oracle_long.position, &ret_c, &pnl_cfg);
    let daily_long: Vec<f64> = pnl_long.net.chunks(bars_per_day)
        .map(|c| c.iter().sum::<f64>()).collect();
    let sr_long = sharpe(&daily_long, bars_per_day);

    s4.push(check(
        "oracle alpha earns strongly positive Net Sharpe",
        sr_long > 5.0,
        format!("Net Sharpe {:.2} (required > 5)", sr_long),
    ));

    let anti: Vec<f64> = oracle.iter().map(|v| -v).collect();
    let anti_res = canonical_map(&anti, &cfg, bars_per_day);
    let pnl_anti = compute_pnl(&anti_res.position, &ret_c, &pnl_cfg);
    let daily_anti: Vec<f64> = pnl_anti.net.chunks(bars_per_day)
        .map(|c| c.iter().sum::<f64>()).collect();
    let sr_anti = sharpe(&daily_anti, bars_per_day);

    s4.push(check(
        "mirrored oracle earns strongly negative Net Sharpe",
        sr_anti < -5.0,
        format!("Net Sharpe {:.2} (required < -5)", sr_anti),
    ));

    let gross_long = compute_pnl(&oracle_long.position, &ret_c, &pnl_cfg).gross;
    let gross_mirror = compute_pnl(&anti_res.position, &ret_c, &pnl_cfg).gross;
    let worst_gross_asym = gross_long.iter().zip(gross_mirror.iter())
        .map(|(g, gm)| (g + gm).abs())
        .fold(0.0f64, f64::max);
    s4.push(check(
        "oracle pair gross PnL mirrors exactly",
        worst_gross_asym == 0.0,
        format!("worst |gross + mirrored gross| = {:.2e}", worst_gross_asym),
    ));

    let zero_cfg = PnlConfig { cost_per_side: 0.0, bars_per_day };
    let pnl_zero = compute_pnl(&oracle_long.position, &ret_c, &zero_cfg);
    let identical = pnl_zero.net.iter().zip(pnl_zero.gross.iter()).all(|(n, g)| n == g);
    s4.push(check(
        "zero-cost config leaves net identical to gross",
        identical,
        "elementwise equality over full oracle path".into(),
    ));

    print_section("SECTION 4 - KNOWN-ANSWER CANARIES", &s4);
    all_failed += s4.iter().filter(|o| !o.ok).count();

    let mut s5: Vec<CheckOutcome> = Vec::new();
    let thresholds = ScreeningThresholds::default();
    let mut rng = Rng::new(0xDEADBEEF);
    let mut prop_fail = 0usize;

    for _ in 0..200 {
        let len = 1 + (rng.next_u64() % 60) as usize;
        let ics: Vec<f64> = (0..len).map(|_| rng.f64() * 0.4 - 0.2).collect();
        let drags: Vec<f64> = (0..len).map(|_| rng.f64() * 120.0).collect();
        let scores: Vec<f64> = (0..len).map(|_| rng.f64() * 10.0 - 5.0).collect();

        let (funnel, survivors) = screen_candidates(&ics, &drags, &thresholds);
        let ranked = rank_survivors(&survivors, &scores);

        if funnel.total_candidates != len { prop_fail += 1; }
        if funnel.survivor_count != survivors.len() { prop_fail += 1; }
        if funnel.ic_pass_count + funnel.drag_pass_count
            < funnel.survivor_count { prop_fail += 1; }

        if ranked.len() != survivors.len() { prop_fail += 1; }
        for w in ranked.windows(2) {
            if scores[w[0]] < scores[w[1]] { prop_fail += 1; }
        }
        for &idx in &ranked {
            let passes = ics[idx].abs() > thresholds.min_abs_ic
                && drags[idx] < thresholds.max_cost_drag_pct;
            if !passes { prop_fail += 1; }
        }
    }

    s5.push(check(
        "screening properties hold over 200 random gates",
        prop_fail == 0,
        format!("{} property violations", prop_fail),
    ));

    print_section("SECTION 5 - SCREENING PROPERTIES", &s5);
    all_failed += s5.iter().filter(|o| !o.ok).count();

    println!("\n============================================================");
    if all_failed == 0 {
        println!("  SYSTEM AUDIT PASSED - all sections green ({:.1}s)",
                 total_start.elapsed().as_secs_f64());
    } else {
        println!("  SYSTEM AUDIT FAILED - {} failing check(s) ({:.1}s)",
                 all_failed, total_start.elapsed().as_secs_f64());
    }
    println!("============================================================");

    if all_failed > 0 {
        std::process::exit(1);
    }
}
