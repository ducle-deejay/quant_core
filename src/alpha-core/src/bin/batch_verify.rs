use std::time::{Duration, Instant};

use alpha_core::canonical::mapping::{canonical_map, CanonicalResult};
use alpha_core::canonical::metrics::{max_drawdown, sharpe};
use alpha_core::canonical::pnl::{compute_pnl, PnlConfig, PnlResult};
use alpha_core::evaluation::screening::{rank_survivors, screen_candidates, ScreeningThresholds};
use alpha_core::harness_config::HarnessConfig;
use alpha_core::strategies::mining::alpha_generator::{AlphaGenerator, GeneratorConfig};
use alpha_core::strategies::mining::batch_executor::execute_batch;
use alpha_core::strategies::mining::dag_builder::build_dag;

const IC_GATE: f64 = 0.02;

const COST_DRAG_GATE_PCT: f64 = 40.0;

const TOP_N: usize = 5;

const EXPR_COLUMN_WIDTH: usize = 64;

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

fn compute_ic_simple(score: &[f64], ret: &[f64]) -> f64 {
    let n = score.len().min(ret.len());
    let pairs: Vec<(f64, f64)> = (0..n.saturating_sub(1))
        .map(|t| (score[t], ret[t+1]))
        .filter(|(a, b)| a.is_finite() && b.is_finite())
        .collect();
    if pairs.len() < 10 { return 0.0; }
    let np = pairs.len() as f64;
    let ms: f64 = pairs.iter().map(|p| p.0).sum::<f64>() / np;
    let mr: f64 = pairs.iter().map(|p| p.1).sum::<f64>() / np;
    let cov: f64 = pairs.iter().map(|p| (p.0-ms)*(p.1-mr)).sum::<f64>();
    let ss: f64 = pairs.iter().map(|p| (p.0-ms).powi(2)).sum::<f64>().sqrt();
    let sr: f64 = pairs.iter().map(|p| (p.1-mr).powi(2)).sum::<f64>().sqrt();
    if ss < 1e-12 || sr < 1e-12 { return 0.0; }
    cov / (ss * sr)
}

struct CandidateMetrics {
    sharpe: f64,
    max_drawdown: f64,
    ic: f64,
    cost_drag_pct: f64,
}

#[derive(Clone, Copy)]
enum Align { Left, Right }

fn pad_cell(cell: &str, width: usize, align: Align) -> String {
    let pad = width.saturating_sub(cell.chars().count());
    match align {
        Align::Left => format!("{}{}", cell, " ".repeat(pad)),
        Align::Right => format!("{}{}", " ".repeat(pad), cell),
    }
}

fn render_table(headers: &[&str], aligns: &[Align], rows: &[Vec<String>]) -> String {
    debug_assert_eq!(headers.len(), aligns.len());
    let ncols = headers.len();

    let mut widths: Vec<usize> = headers.iter().map(|h| h.chars().count()).collect();
    for row in rows {
        for (i, cell) in row.iter().enumerate().take(ncols) {
            widths[i] = widths[i].max(cell.chars().count());
        }
    }

    let rule = |left: &str, mid: &str, right: &str| -> String {
        let mut s = String::from(left);
        for (i, w) in widths.iter().enumerate() {
            s.push_str(&"\u{2500}".repeat(w + 2));
            if i + 1 < widths.len() { s.push_str(mid); }
        }
        s.push_str(right);
        s
    };

    let render_row = |cells: &[String]| -> String {
        let mut s = String::from("\u{2502}");
        for i in 0..ncols {
            let cell = cells.get(i).map(|c| c.as_str()).unwrap_or("");
            s.push(' ');
            s.push_str(&pad_cell(cell, widths[i], aligns[i]));
            s.push_str(" \u{2502}");
        }
        s
    };

    let header_cells: Vec<String> = headers.iter().map(|h| h.to_string()).collect();
    let mut out = String::new();
    out.push_str(&rule("\u{250c}", "\u{252c}", "\u{2510}"));
    out.push('\n');
    out.push_str(&render_row(&header_cells));
    out.push('\n');
    out.push_str(&rule("\u{251c}", "\u{253c}", "\u{2524}"));
    out.push('\n');
    for row in rows {
        out.push_str(&render_row(row));
        out.push('\n');
    }
    out.push_str(&rule("\u{2514}", "\u{2534}", "\u{2518}"));
    out
}

fn print_table(title: &str, headers: &[&str], aligns: &[Align], rows: &[Vec<String>]) {
    println!("\n=== {} ===", title);
    println!("{}", render_table(headers, aligns, rows));
}

fn fmt_duration(d: Duration) -> String {
    let ns = d.as_nanos();
    if ns < 1_000 {
        format!("{} ns", ns)
    } else if ns < 1_000_000 {
        format!("{:.1} us", ns as f64 / 1e3)
    } else if ns < 1_000_000_000 {
        format!("{:.1} ms", ns as f64 / 1e6)
    } else {
        format!("{:.2} s", ns as f64 / 1e9)
    }
}

fn fmt_int(n: usize) -> String {
    let digits = n.to_string();
    let bytes = digits.as_bytes();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3);
    for (i, b) in bytes.iter().enumerate() {
        if i > 0 && (bytes.len() - i) % 3 == 0 { out.push(','); }
        out.push(*b as char);
    }
    out
}

fn pct(part: usize, whole: usize) -> f64 {
    if whole == 0 { return 0.0; }
    part as f64 / whole as f64 * 100.0
}

fn truncate_chars(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let cut: String = s.chars().take(max.saturating_sub(1)).collect();
    format!("{}...", cut)
}

fn step_log(step: usize, msg: &str) {
    println!("[Step {}/7] {} ... done", step, msg);
}

fn main() {
    let total_start = Instant::now();

    println!("==================================================");
    println!("  Batch Verification - QuantCore Alpha Pipeline");
    println!("==================================================");

    let t0 = Instant::now();
    let (data, n_sessions) = load_csv("data/VN30F1M.csv");
    let bars = data.get("close").map(|c| c.len()).unwrap_or(0);
    let t_load = t0.elapsed();
    step_log(1, "load real market data");

    let gen_cfg = GeneratorConfig {
        fields: vec![
            "close".into(), "volume".into(),
        ],
        ..Default::default()
    };
    let t0 = Instant::now();
    let mut gen = AlphaGenerator::new(&gen_cfg, 42);
    let asts: Vec<_> = (0..250)
        .map(|_| gen.generate())
        .collect();
    let t_generate = t0.elapsed();
    step_log(2, "grammar-guided expression generation");

    let t0 = Instant::now();
    let dag = build_dag(&asts);
    let t_dag = t0.elapsed();
    let unique_nodes = dag.nodes.len();
    let total_ops: usize = asts.iter()
        .map(|a| count_ops(a))
        .sum();
    let dedup_pct = if total_ops > 0 {
        (1.0 - unique_nodes as f64 / total_ops as f64) * 100.0
    } else { 0.0 };
    step_log(3, "shared computation DAG construction");

    let t0 = Instant::now();
    let score_matrix = execute_batch(&dag, &data, &dag.roots);
    let t_exec = t0.elapsed();
    let exec_throughput = if t_exec.as_secs_f64() > 0.0 {
        score_matrix.len() as f64 / t_exec.as_secs_f64()
    } else { 0.0 };
    step_log(4, "batch score execution");

    let cfg = HarnessConfig::default();
    let ret = data.get("ret").cloned().unwrap_or_default();
    let bars_per_day = bars / n_sessions.max(1);
    let pnl_cfg = PnlConfig { cost_per_side: cfg.cost_per_side, bars_per_day };

    let t0 = Instant::now();
    let canonical_results: Vec<CanonicalResult> = score_matrix.iter()
        .map(|score| canonical_map(score, &cfg, bars_per_day))
        .collect();
    let t_canonical = t0.elapsed();
    step_log(5, "canonical mapping");

    let t0 = Instant::now();
    let pnl_results: Vec<PnlResult> = canonical_results.iter()
        .map(|cr| compute_pnl(&cr.position, &ret, &pnl_cfg))
        .collect();
    let t_pnl = t0.elapsed();
    step_log(6, "PnL computation");

    let t0 = Instant::now();
    let metrics: Vec<CandidateMetrics> = pnl_results.iter()
        .zip(score_matrix.iter())
        .map(|(pnl, sc)| {
            let d: Vec<f64> = pnl.net.chunks(bars_per_day)
                .map(|c| c.iter().sum::<f64>()).collect();
            CandidateMetrics {
                sharpe: sharpe(&d, bars_per_day),
                max_drawdown: max_drawdown(&d),
                ic: compute_ic_simple(sc, &ret),
                cost_drag_pct: pnl.cost_drag_pct,
            }
        })
        .collect();
    let t_metrics = t0.elapsed();
    step_log(7, "metrics computation");

    let total_elapsed = total_start.elapsed();

    let thresholds = ScreeningThresholds {
        min_abs_ic: IC_GATE,
        max_cost_drag_pct: COST_DRAG_GATE_PCT,
    };
    let ic_values: Vec<f64> = metrics.iter().map(|m| m.ic).collect();
    let drag_values: Vec<f64> = metrics.iter().map(|m| m.cost_drag_pct).collect();
    let sharpe_values: Vec<f64> = metrics.iter().map(|m| m.sharpe).collect();
    let (funnel, survivors) = screen_candidates(&ic_values, &drag_values, &thresholds);
    let ranked_survivors = rank_survivors(&survivors, &sharpe_values);
    let total_candidates = funnel.total_candidates;

    let stage_headers = ["Step", "Stage", "Time", "Throughput"];
    let stage_aligns = [
        Align::Right, Align::Left, Align::Right, Align::Right,
    ];
    let stage_rows: Vec<Vec<String>> = vec![
        vec![
            "1".into(),
            format!("Load CSV ({} bars, {} sessions)", fmt_int(bars), fmt_int(n_sessions)),
            fmt_duration(t_load),
            "-".into(),
        ],
        vec![
            "2".into(),
            format!("Grammar-guided generation ({} trees)", asts.len()),
            fmt_duration(t_generate),
            "-".into(),
        ],
        vec![
            "3".into(),
            format!(
                "Shared DAG build ({} unique nodes, {:.1}% dedup saved)",
                fmt_int(unique_nodes), dedup_pct
            ),
            fmt_duration(t_dag),
            "-".into(),
        ],
        vec![
            "4".into(),
            format!("Batch execution ({} score series)", score_matrix.len()),
            fmt_duration(t_exec),
            format!("{:.0} alphas/sec", exec_throughput),
        ],
        vec![
            "5".into(),
            format!("Canonical mapping ({} positions)", canonical_results.len()),
            fmt_duration(t_canonical),
            "-".into(),
        ],
        vec![
            "6".into(),
            format!("PnL computation ({} curves)", pnl_results.len()),
            fmt_duration(t_pnl),
            "-".into(),
        ],
        vec![
            "7".into(),
            format!("Metrics computation ({} candidates)", metrics.len()),
            fmt_duration(t_metrics),
            "-".into(),
        ],
        vec![
            "all".into(),
            "End-to-end wall time".into(),
            fmt_duration(total_elapsed),
            format!("{:.0} alphas/sec", total_candidates as f64 / total_elapsed.as_secs_f64().max(0.001)),
        ],
    ];
    print_table("PIPELINE STAGES", &stage_headers, &stage_aligns, &stage_rows);

    let funnel_headers = ["Gate", "Threshold", "Passed", "Total", "Pass Rate"];
    let funnel_aligns = [
        Align::Left, Align::Left, Align::Right, Align::Right, Align::Right,
    ];
    let funnel_rows: Vec<Vec<String>> = vec![
        vec![
            "Information Coefficient (Pearson)".into(),
            format!("|IC| > {}", IC_GATE),
            funnel.ic_pass_count.to_string(),
            total_candidates.to_string(),
            format!("{:.1}%", pct(funnel.ic_pass_count, total_candidates)),
        ],
        vec![
            "Cost drag".into(),
            format!("< {}% of gross", COST_DRAG_GATE_PCT),
            funnel.drag_pass_count.to_string(),
            total_candidates.to_string(),
            format!("{:.1}%", pct(funnel.drag_pass_count, total_candidates)),
        ],
        vec![
            "Both gates combined".into(),
            "IC gate AND drag gate".into(),
            funnel.survivor_count.to_string(),
            total_candidates.to_string(),
            format!("{:.1}%", pct(funnel.survivor_count, total_candidates)),
        ],
    ];
    print_table("SCREENING FUNNEL", &funnel_headers, &funnel_aligns, &funnel_rows);

    if ranked_survivors.is_empty() {
        println!("\n=== TOP SURVIVING CANDIDATES ===");
        println!("(no candidate passed both screening gates)");
    } else {
        let cand_headers = ["#", "Net Sharpe", "Max Drawdown", "IC", "Cost Drag", "Expression"];
        let cand_aligns = [
            Align::Right, Align::Right, Align::Right, Align::Right, Align::Right, Align::Left,
        ];
        let cand_rows: Vec<Vec<String>> = ranked_survivors.iter().take(TOP_N).enumerate()
            .map(|(rank, &idx)| {
                let expr_str = asts.get(idx)
                    .map(|a| a.to_string())
                    .unwrap_or_else(|| "(unknown)".into());
                let m = &metrics[idx];
                vec![
                    (rank + 1).to_string(),
                    format!("{:.2}", m.sharpe),
                    format!("{:.1}%", m.max_drawdown * 100.0),
                    format!("{:.4}", m.ic),
                    format!("{:.1}%", m.cost_drag_pct),
                    truncate_chars(&expr_str, EXPR_COLUMN_WIDTH),
                ]
            })
            .collect();
        print_table(
            &format!("TOP {} SURVIVING CANDIDATES (ranked by Net Sharpe, both gates passed)", TOP_N),
            &cand_headers, &cand_aligns, &cand_rows,
        );
    }

    let best_surviving_sharpe = ranked_survivors.first()
        .map(|&idx| format!("{:.2}", metrics[idx].sharpe))
        .unwrap_or_else(|| "(none survived)".into());

    let sys_headers = ["Metric", "Value"];
    let sys_aligns = [Align::Left, Align::Left];
    let sys_rows: Vec<Vec<String>> = vec![
        vec![
            "Parse failures".into(),
            "0 (grammar-guided generation)".into(),
        ],
        vec![
            "DAG node dedup savings".into(),
            format!("{:.1}%", dedup_pct),
        ],
        vec![
            "Surviving candidates".into(),
            format!(
                "{} of {} ({:.1}%)",
                funnel.survivor_count, total_candidates, pct(funnel.survivor_count, total_candidates)
            ),
        ],
        vec![
            "Best surviving Net Sharpe".into(),
            best_surviving_sharpe,
        ],
    ];
    print_table("SYSTEM SUMMARY", &sys_headers, &sys_aligns, &sys_rows);

    fn count_ops(ast: &alpha_core::strategies::mining::expression_parser::AstNode) -> usize {
        use alpha_core::strategies::mining::expression_parser::{AstNode, TsArg};
        match ast {
            AstNode::Number(_) => 1,
            AstNode::Field(_) => 1,
            AstNode::BinaryOp { left, right, .. } => 1 + count_ops(left) + count_ops(right),
            AstNode::UnaryOp { operand, .. } => 1 + count_ops(operand),
            AstNode::TsFunc { args, .. } => 1 + args.iter()
                .map(|arg| match arg {
                    TsArg::Field(_) => 1,
                    TsArg::Expr(e) => count_ops(e),
                }).sum::<usize>(),
        }
    }
}
