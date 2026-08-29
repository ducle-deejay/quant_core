/// PnL identity for continuous positions under flat costs.
///
/// ```text
/// pnl(t) = p(t-1) * r(t) - c * abs(p(t) - p(t-1))
/// ```
///
/// This is the exact PnL definition (not an approximation) when position
/// is a real number and cost is flat per unit notional per side.
#[derive(Debug, Clone)]
pub struct PnlResult {
    pub gross: Vec<f64>,
    pub net: Vec<f64>,
    pub turnover_annualized: f64,
    pub cost_drag_pct: f64,
    pub trades_per_day: f64,
}

pub struct PnlConfig {
    pub cost_per_side: f64,
    pub bars_per_day: usize,
}

/// Compute gross and net PnL from canonical position series.
///
/// Anti-lookahead is enforced by construction: `p(t-1)` earns `r(t)`,
/// never `p(t)` times `r(t)`.
pub fn compute_pnl(pos: &[f64], ret: &[f64], cfg: &PnlConfig) -> PnlResult {
    let n = pos.len().min(ret.len());
    let mut gross = vec![0.0; n];
    let mut net = vec![0.0; n];
    let mut total_turnover = 0.0;
    let mut total_cost = 0.0;
    let mut trade_count = 0usize;

    for t in 1..n {
        let change = (pos[t] - pos[t - 1]).abs();
        if change > f64::EPSILON {
            trade_count += 1;
        }
        total_turnover += change;
        total_cost += change * cfg.cost_per_side;

        gross[t] = pos[t - 1] * ret[t];
        net[t] = gross[t] - change * cfg.cost_per_side;
    }

    let days = n as f64 / cfg.bars_per_day as f64;
    let turnover_annualized = total_turnover / days * 250.0;

    let gross_sum: f64 = gross.iter().sum();
    let cost_drag_pct = if gross_sum.abs() > 1e-12 {
        (total_cost / gross_sum.abs()) * 100.0
    } else {
        0.0
    };

    PnlResult {
        gross,
        net,
        turnover_annualized,
        cost_drag_pct,
        trades_per_day: trade_count as f64 / days,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pnl_identity_basic() {
        // hold +1, return +1% -> earn +1%
        let pos = [0.0, 1.0, 1.0];
        let ret = [0.0, 0.01, 0.01];
        let cfg = PnlConfig {
            cost_per_side: 0.0,
            bars_per_day: 100,
        };
        let r = compute_pnl(&pos, &ret, &cfg);
        assert!((r.gross[1] - 0.0).abs() < 1e-10); // p(0)=0 -> no earnings bar 1
        assert!((r.gross[2] - 0.01).abs() < 1e-10); // p(1)=1 * 1% = 1%
    }

    #[test]
    fn test_no_lookahead() {
        // position decided at end of t-1 earns return of bar t
        // if we wrote p(t)*r(t) that would be lookahead
        let pos = [1.0, 2.0]; // decided to go to 2.0 at end of bar 0
        let ret = [0.0, -0.05]; // bar 1 return is negative
        let cfg = PnlConfig {
            cost_per_side: 0.0,
            bars_per_day: 100,
        };
        let r = compute_pnl(&pos, &ret, &cfg);
        // p(0)=1.0 earns r(1)=-5%, NOT p(1)=2.0 times anything
        assert!((r.gross[1] - (-0.05)).abs() < 1e-10);
    }

    #[test]
    fn test_turnover_counts_absolute_changes() {
        // +5 then -5: signed sum is zero, absolute sum is ten
        let pos = vec![0.0, 5.0, 0.0];
        let ret = vec![0.0, 0.0, 0.0];
        let cfg = PnlConfig {
            cost_per_side: 0.001,
            bars_per_day: 2,
        };
        let r = compute_pnl(&pos, &ret, &cfg);
        // total abs changes: |5-0| + |0-5| = 10; days = 3/2 = 1.5
        // annualized = 10/1.5 * 250 = 1666.67
        assert!((r.turnover_annualized - 1666.67).abs() < 1.0);
    }

    // -------------------------------------------------------------------
    // Structural invariants (hold for EVERY input, not just fixtures)
    // -------------------------------------------------------------------

    #[test]
    fn net_equals_gross_minus_costs_bar_by_bar() {
        let n = 500;
        let pos: Vec<f64> = (0..n)
            .map(|t| ((t as f64) * 0.07).sin() * 1.7)
            .collect();
        let ret: Vec<f64> = (0..n)
            .map(|t| ((t as f64) * 0.13).cos() * 0.02)
            .collect();
        let cfg = PnlConfig { cost_per_side: 0.0003, bars_per_day: 100 };

        let r = compute_pnl(&pos, &ret, &cfg);
        for t in 1..n {
            let change = (pos[t] - pos[t - 1]).abs();
            let expected_net = r.gross[t] - change * cfg.cost_per_side;
            assert!(
                (r.net[t] - expected_net).abs() < 1e-12,
                "PnL identity violated at bar {}",
                t
            );
        }
    }

    #[test]
    fn zero_cost_makes_net_identical_to_gross() {
        let n = 300;
        let pos: Vec<f64> = (0..n).map(|t| if t % 7 == 0 { 1.0 } else { -1.0 }).collect();
        let ret: Vec<f64> = vec![0.001; n];
        let cfg = PnlConfig { cost_per_side: 0.0, bars_per_day: 100 };

        let r = compute_pnl(&pos, &ret, &cfg);
        for t in 0..n {
            assert_eq!(r.net[t], r.gross[t], "net must equal gross at zero cost, bar {}", t);
        }
        assert_eq!(r.cost_drag_pct, 0.0);
    }

    #[test]
    fn gross_is_independent_of_cost_parameter() {
        // Costs must only affect `net`: gross PnL is a property of position
        // and returns alone.
        let n = 200;
        let pos: Vec<f64> = (0..n).map(|t| ((t as f64) * 0.05).sin()).collect();
        let ret: Vec<f64> = (0..n).map(|t| ((t as f64) * 0.11).cos() * 0.01).collect();

        let cheap = compute_pnl(&pos, &ret, &PnlConfig { cost_per_side: 0.0001, bars_per_day: 100 });
        let dear = compute_pnl(&pos, &ret, &PnlConfig { cost_per_side: 0.0050, bars_per_day: 100 });

        assert_eq!(cheap.gross, dear.gross);
    }

    #[test]
    fn reported_trades_match_position_changes_exactly() {
        let n = 400;
        let pos: Vec<f64> = (0..n)
            .map(|t| if t % 23 < 5 { 1.5 } else { 0.0 })
            .collect();
        let cfg = PnlConfig { cost_per_side: 0.0001, bars_per_day: 50 };

        let r = compute_pnl(&pos, &ret_dummy(n), &cfg);
        let changes = pos.windows(2)
            .filter(|w| (w[1] - w[0]).abs() > f64::EPSILON)
            .count();
        assert_eq!(r.trades_per_day, changes as f64 / (n as f64 / 50.0));
    }

    fn ret_dummy(n: usize) -> Vec<f64> {
        (0..n).map(|t| ((t as f64) * 0.19).sin() * 0.01).collect()
    }
}
