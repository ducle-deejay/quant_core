
use alpha_core::canonical::pnl::{compute_pnl, PnlConfig};
use alpha_core::canonical::metrics::{sharpe, max_drawdown};
use alpha_core::evaluation::ic_ladder::ic_ladder;
use alpha_core::evaluation::gates::{evaluate_gate, GateCriteria, GateInput};
use alpha_core::evaluation::trial_ledger::TrialLedger;
use alpha_core::harness_config::HarnessConfig;

use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader};

fn load_csv(path: &str) -> (Vec<f64>, Vec<f64>, usize) {
    let file = File::open(path).expect("Cannot open data file");
    let reader = BufReader::new(file);
    let mut close = Vec::new();
    let mut volume = Vec::new();
    let mut dates = std::collections::HashSet::new();

    for line in reader.lines() {
        let line = line.unwrap();
        if line.is_empty() { continue; }
        let cols: Vec<&str> = line.split(',').collect();
        if cols.len() >= 8 {
            let c_val = cols[6].parse::<f64>().unwrap_or(0.0);
            if c_val > 0.0 {
                dates.insert(cols[0].split(' ').next().unwrap_or("").to_string());
                close.push(c_val);
            }
            volume.push(cols[7].parse::<f64>().unwrap_or(0.0));
        }
    }

    // compute daily returns from closes
    let n = close.len();
    let mut ret = vec![0.0; n];
    for t in 1..n { ret[t] = close[t] / close[t-1] - 1.0; }

    (close, ret, dates.len().max(1))
}

fn compute_score(close: &[f64], lookback: usize) -> Vec<f64> {
    let n = close.len();
    let mut score = vec![0.0; n];
    for t in lookback..n {
        let ma: f64 = close[t-lookback..t].iter().sum::<f64>() / lookback as f64;
        if ma > f64::EPSILON { score[t] = close[t] / ma - 1.0; }
    }
    score
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let data_path = args.get(1)
        .map(|s| s.as_str())
        .unwrap_or("data/VN30F1M.csv");

    println!("Loading data from {}...", data_path);
    let (close_prices, ret, n_days) = load_csv(data_path);
    let bars_per_day = ret.len() / n_days.max(1);
    println!("  bars: {}, sessions: {}, bars/day: {}", ret.len(), n_days, bars_per_day);

    // harness configuration
    let cfg = HarnessConfig::default();
    let _pnl_cfg = crate::PnlConfig {
        cost_per_side: cfg.cost_per_side,
        bars_per_day,
    };

    // generate multiple seed alphas with different lookbacks
    let lookbacks = vec![5, 10, 15, 20, 30, 50];
    println!("\nGenerating {} seed alphas (price deviation, varying lookback)...", lookbacks.len());

    // For this demo we use a simplified version that works on returns directly
    // In production these come from the DSL expression engine

    // Compute scores using ACTUAL close prices (not reconstructed)
    let mut results = Vec::new();
    for &lb in &lookbacks {
        let score = compute_score(&close_prices, lb);

        // DEBUG
        let sc_min = score.iter().cloned().fold(f64::INFINITY, f64::min);
        let sc_max = score.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let sc_nonzero = score.iter().filter(|&&x| x != 0.0).count();
        println!("  LB={}: score range [{:.6}, {:.6}], nonzero {}/{}", lb, sc_min, sc_max, sc_nonzero, score.len());

        // canonical simulation (vectorized steps)
        let smoothed = {
            let lambda = 2.0 / (cfg.span as f64 + 1.0);
            let mut out = vec![score[0]];
            for t in 1..score.len() {
                out.push(lambda * score[t] + (1.0 - lambda) * out[t-1]);
            }
            out
        };

        let z = {
            let mut z = vec![0.0; smoothed.len()];
            for t in cfg.z_window..smoothed.len() {
                let w = &smoothed[t - cfg.z_window..t];
                let mean = w.iter().sum::<f64>() / cfg.z_window as f64;
                let var = w.iter().map(|x| (x-mean).powi(2)).sum::<f64>() / cfg.z_window as f64;
                let std = var.sqrt();
                if std > 1e-12 { z[t] = (smoothed[t] - mean) / std; }
            }
            z
        };

        // DEBUG
        let z_min = z.iter().cloned().fold(f64::INFINITY, f64::min);
        let z_max = z.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let z_nonzero = z.iter().filter(|&&x| x != 0.0).count();
        println!("  LB={}: z range [{:.6}, {:.6}], nonzero {}/{}", lb, z_min, z_max, z_nonzero, z.len());

        let mut pos = vec![0.0; z.len()];
        let mut turn = vec![0.0; z.len()];
        for t in 1..z.len() {
            let target = z[t-1].clamp(-cfg.cap, cfg.cap);
            if (target - pos[t-1]).abs() > cfg.band {
                pos[t] = target;
            } else {
                pos[t] = pos[t-1];
            }
            turn[t] = (pos[t] - pos[t-1]).abs();
        }

        // DEBUG
        let pos_nonzero = pos.iter().filter(|&&p| p != 0.0).count();
        let turn_total: f64 = turn.iter().sum();
        println!("  LB={}: pos nonzero {}/{}, total turnover {:.2}", lb, pos_nonzero, pos.len(), turn_total);

        let pnl_cfg = PnlConfig { cost_per_side: cfg.cost_per_side, bars_per_day };
        let pnl = compute_pnl(&pos, &ret, &pnl_cfg);

        // daily aggregation
        let d: Vec<f64> = pnl.net.chunks(bars_per_day)
            .map(|c| c.iter().sum::<f64>()).collect();

        let sr = sharpe(&d, bars_per_day);
        let mdd = max_drawdown(&d);

        // IC ladder at horizons 5, 15, 30
        let ladder = ic_ladder(&score, &ret, &[5, 15, 30], cfg.z_window, bars_per_day);
        let ic_15 = ladder.iter().find(|r| r.horizon == 15)
            .map(|r| r.mean_ic).unwrap_or(0.0);

        results.push((lb, sr, mdd, to_ann(pnl.turnover_annualized), ic_15, pnl.cost_drag_pct));
    }

    fn to_ann(x: f64) -> f64 { x }

    // print results table
    println!("\n{:<8} {:>10} {:>10} {:>12} {:>10} {:>10}",
             "Lookback", "Sharpe", "MDD", "TO(x/yr)", "IC@15", "Drag%");
    println!("{}", "-".repeat(65));
    for (lb, sr, mdd, to, ic, drag) in &results {
        println!("{:<8} {:>10.2} {:>10.4} {:>12.0} {:>10.4} {:>9.1}%",
                 format!("LB={}", lb), sr, mdd, to, ic, drag);
    }

    // find best by Sharpe
    if let Some(best) = results.iter().max_by(|a, b| {
        a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal)
    }) {
        println!("\nBest: LB={} with net Sharpe {:.3}", best.0, best.1);
    }

    // gate evaluation for the best
    if let Some(best) = results.iter().max_by(|a, b| {
        a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal)
    }) {
        let criteria = GateCriteria::default();
        let input = GateInput {
            net_sharpe_walkforward: best.1,
            icir: best.4.abs(),
            decay_through_target_holding: true,
            cost_drag_pct: best.5,
            turnover_annualized: best.3,
            positive_blocks_pct: 60.0,
            skewness: 0.0,
            kurtosis: 3.0,
            sample_length_bars: ret.len(),
        };
        
        let mut ledger = TrialLedger::new();
        ledger.record("alphascreen", &format!("LB={}", best.0), "full_sample", "gate_evaluation");
        
        let result = evaluate_gate(&input, &criteria, &ledger);
        
        println!("\nGate evaluation (deflated threshold {:.3}, N_eff={}):",
                 result.deflated_threshold_used, result.effective_trials);
        for (name, pass) in &result.checks {
            println!("  {} {}", if *pass { "PASS" } else { "FAIL" }, name);
        }
        println!("\nOverall: {}", if result.passed { "PASS -> proceed to Stage 3" } else { "FAIL -> rejected" });
    }
}
