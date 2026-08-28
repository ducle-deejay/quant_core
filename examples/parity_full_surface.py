"""Phase 4 parity suite: exercise every exported quantcore function.

Run with the project virtualenv after a maturin build:
    .venv/bin/python3 examples/parity_full_surface.py

Anchors mirror the Rust unit tests so Python results are compared against
the values the core itself asserts.
"""
import math
import quantcore as q

checks = []


def check(name, condition):
    checks.append((name, bool(condition)))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}")


# --- Component 1: canonical mapping -----------------------------------------
flat = q.canonical_map_py([7.5] * 1000, span=8, z_window=480,
                          band=0.35, cap=2.0, bars_per_day=240)
check("constant score stays flat", all(p == 0.0 for p in flat.position))

osc = q.canonical_map_py([math.sin(i * 0.11) * 5 for i in range(3000)],
                         span=8, z_window=480, band=0.35, cap=2.0,
                         bars_per_day=240)
check("oscillating score trades", osc.trades_per_day > 0)

# --- Component 1: PnL identity -------------------------------------------------
pnl = q.compute_pnl_py(pos=[0.0, 1.0, 1.0], ret=[0.0, 0.01, 0.01],
                       cost_per_side=0.0, bars_per_day=100)
check("pnl identity basic", abs(pnl.gross[2] - 0.01) < 1e-10
      and pnl.net == pnl.gross)

anti = q.compute_pnl_py(pos=[1.0, 2.0], ret=[0.0, -0.05],
                        cost_per_side=0.0, bars_per_day=100)
check("anti-lookahead earns r(t) with p(t-1)",
      abs(anti.gross[1] + 0.05) < 1e-12)

# --- Component 1: metrics ------------------------------------------------------
sr = q.sharpe_py([3, 1, 3, 1], bars_per_day=100)
check("sharpe matches hand-computed annualization",
      math.isclose(sr, math.sqrt(3) * math.sqrt(250), abs_tol=1e-9))
check("max drawdown known answer", q.max_drawdown_py([1, 1, -2]) == -2.0)

# --- Component 2: evaluation ---------------------------------------------------
n = 600
score = [math.sin(t * 0.21) + 0.3 * math.cos(t * 0.53) for t in range(n)]
ret = [0.0] + [0.01 * score[t - 1] + 0.001 * math.sin(t * 0.077)
               for t in range(1, n)]
ladder = q.ic_ladder_py(score, ret, [1], window=20, bars_per_day=10)
check("lead-lag IC near one at horizon 1", ladder[0].mean_ic > 0.9)

wf = q.walk_forward_py([2.0, 0.0, -2.0, 0.0], block_days=2, ann_factor=4.0)
check("walk-forward two-block known answer",
      len(wf.blocks) == 2
      and math.isclose(wf.positive_pct, 50.0)
      and math.isclose(wf.worst_block_sharpe, -math.sqrt(4.0)))

outcome = q.screen_candidates_py(ic_values=[0.05, -0.03],
                                 cost_drag_pcts=[10.0, 50.0])
check("screening funnel counts",
      outcome.total_candidates == 2 and outcome.survivor_count == 1
      and outcome.survivor_indices == [0])
check("rank survivors descending", q.rank_survivors_py([0, 1], [1.0, 2.0]) == [1, 0])

check("deflated threshold zero at single trial",
      q.deflated_threshold_py(n_trials=1, variance_of_sharpes=0.25) == 0.0)
prob = q.deflated_sharpe_probability_py(observed_sharpe=6.0, n_trials=50,
                                        skewness=0.0, kurtosis=3.0,
                                        sample_length=20000)
check("clean strong candidate has tiny spurious probability", prob < 0.001)

# --- Component 0: mining -------------------------------------------------------
check("validate expression round-trips",
      q.validate_expression_py("ts_rank(close,20)") != "")
try:
    q.validate_expression_py("not valid !!")
    raised = False
except ValueError:
    raised = True
check("invalid expression raises ValueError", raised)

bars = 500
close = [100 + math.sin(t * 0.05) for t in range(bars)]
volume = [1000 + 200 * math.cos(t * 0.03) for t in range(bars)]
matrix = q.execute_batch_py(["close", "ts_rank(volume,20)"], close, volume)
check("batch executor returns one series per expression",
      len(matrix) == 2 and all(len(row) == bars for row in matrix))

best = q.ga_best_expression_py(close, volume, population_size=20,
                               generations=2, seed=42)
check("GA loop returns a non-empty best expression", isinstance(best, str) and best != "")

# --- Components 3-5: portfolio trio --------------------------------------------
n = 200
x1 = [math.sin(t * 0.23) for t in range(n)]
x2 = [math.cos(t * 0.11) for t in range(n)]
candidate = [a + 2 * b for a, b in zip(x1, x2)]
residual = q.orthogonalize_py(candidate, [x1, x2])
check("in-span candidate fully absorbed",
      sum(r * r for r in residual) < 1e-12)

comp = q.composite_score_py([[1, 2], [2, 4]], [0.5, 0.5])
check("composite weighted sum", comp == [1.5, 3.0])

inv = q.inverse_vol_combine_py([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0]])
check("inverse-vol combine runs", len(inv) == 3 and all(math.isfinite(v) for v in inv))

z = [2.0, -1.0, 0.5]
vt = q.vol_target_py(z, vol_est=[1.0] * 3, target_vol=0.1, floor=None)
check("vol targeting scales z-scores", vt == [0.2, -0.1, 0.05])

dd = q.drawdown_multiplier_py([0.0, 0.03, 0.07, 0.12, 0.17, 0.22])
check("drawdown ladder multipliers monotone non-increasing",
      all(a >= b for a, b in zip(dd, dd[1:])))

failed = [name for name, ok in checks if not ok]
print(f"\nPARITY SUITE: {len(checks) - len(failed)}/{len(checks)} passed")
if failed:
    print("FAILED:", failed)
    raise SystemExit(1)
print("ALL GREEN")
