"""
Verify: Search fitness proxy vs Canonical simulation on REAL VN30F1M data.
Uses a price-based seed (OHLCV only, no book depth available).

Run: uv run python3 examples/verify_real_data.py
"""

import numpy as np
import pandas as pd
import time

# ---------------------------------------------------------------------------
# Load real data
# ---------------------------------------------------------------------------
print("Loading VN30F1M.csv ...")
df = pd.read_csv("data/VN30F1M.csv", parse_dates=["datetime"])
df = df.sort_values("datetime").reset_index(drop=True)
close = df["close"].to_numpy()
N = len(df)
n_dates = df["datetime"].dt.date.nunique()
BARS_DAY = N // n_dates
n_days = n_dates
STEP = BARS_DAY  # rough estimate
SIG_BAR = close.std() / np.sqrt(N) if N > 0 else 0
print(f"  bars: {N}, date range: {df.datetime.iloc[0]} to {df.datetime.iloc[-1]}")
print(f"  close: min={close.min():.1f} max={close.max():.1f}")
print(f"  estimated sessions: {n_days}")
n_dates = df["datetime"].dt.date.nunique()
BARS_DAY = N // n_dates
print(f"  avg bars/day: {BARS_DAY:.0f}")

ret = np.zeros(N)
ret[1:] = close[1:] / close[:-1] - 1

# ---------------------------------------------------------------------------
# Seed: short-term deviation from rolling mean (price reversion + momentum mix)
# Simple enough to work on OHLCV only, meaningful for intraday
# ---------------------------------------------------------------------------

SPAN_SMOOTH = 8
K_LOOKBACK  = 15
Z_WINDOW    = 480
LEVEL_CAP   = 2.0
NO_TRADE_B  = 0.35

def compute_score(close_arr):
    """Price deviation from rolling mean -> smoothed -> z-scored."""
    s = pd.Series(close_arr)
    ma = s.rolling(K_LOOKBACK).mean()
    dev = s / ma - 1
    sm = dev.ewm(span=SPAN_SMOOTH).mean()
    m = sm.rolling(Z_WINDOW).mean()
    sd = sm.rolling(Z_WINDOW).std()
    return ((sm - m) / sd.replace(0, np.nan)).fillna(0).to_numpy()

score = compute_score(close)

# ---------------------------------------------------------------------------
# METHOD A: Raw-score proxy fitness (Stage 0 search metric)
# Score treated as direct position. No transforms. Pure vectorised.
# ---------------------------------------------------------------------------

def eval_raw_proxy():
    t0 = time.perf_counter()

    pnl_proxy = np.zeros(N)
    pnl_proxy[1:] = score[:-1] * ret[1:]

    d = np.array([pnl_proxy[i*BARS_DAY:(i+1)*BARS_DAY].sum()
                  for i in range(n_days) if (i+1)*BARS_DAY <= N])

    r_ann = float(np.mean(d)) * 250
    sharpe = float(np.mean(d) / np.std(d) * np.sqrt(250)) if np.std(d) > 0 else 0

    # IC: correlation between score and next-bar return, block-mean
    ic_blocks = []
    step = BARS_DAY
    for start in range(Z_WINDOW, N - STEP - 1, STEP):
        end = min(start + STEP, N - 1)
        sc_chunk = score[start:end]
        rt_chunk = ret[start+1:end+1]
        if len(sc_chunk) > 5 and np.std(sc_chunk) > 0 and np.std(rt_chunk) > 0:
            ic_blocks.append(float(np.corrcoef(sc_chunk, rt_chunk)[0, 1]))
    ic_mean = np.mean(ic_blocks) if ic_blocks else 0
    ic_std_val = np.std(ic_blocks) if len(ic_blocks) > 1 else 0.01
    icir = ic_mean / max(ic_std_val, 1e-6)

    # turnover on raw score changes
    to_ann = float(np.sum(np.abs(np.diff(score)))) / n_days * 250

    elapsed = time.perf_counter() - t0

    to_floor = 0.125
    fitness = icir * np.sqrt(abs(r_ann)) / max(to_ann, to_floor)

    return {
        "method": "Raw-score proxy",
        "R_ann": r_ann,
        "TO_x_yr": round(to_ann),
        "ICIR": round(icir, 4),
        "fitness": round(fitness, 4),
        "elapsed_ms": round(elapsed * 1000, 1),
        "sharpe_gross": round(sharpe, 2),
    }


# ---------------------------------------------------------------------------
# METHOD B: Canonical simulation (Stage 1 full harness)
# ---------------------------------------------------------------------------

HALF_SPREAD_REL = 0.05 / 1200   # half-spread in relative terms at mid ~1200
FEE_SIDE_REL     = 0.00002      # fee per side as fraction of notional

def eval_canonical():
    t0 = time.perf_counter()

    # Step A: EWMA smoothing
    sm = pd.Series(score).ewm(span=SPAN_SMOOTH).mean().to_numpy()

    # Step B: rolling z-score
    zs = pd.Series(sm)
    m = zs.rolling(Z_WINDOW).mean()
    sd = zs.rolling(Z_WINDOW).std()
    z = ((zs - m) / sd.replace(0, np.nan)).fillna(0).to_numpy()

    # Step C+D: band + cap -> position
    tgt = np.clip(z, -LEVEL_CAP, LEVEL_CAP)
    pos = np.zeros_like(tgt)
    turn = np.zeros_like(tgt)
    n_trades = 0
    for t in range(1, len(tgt)):
        new = pos[t-1]
        if abs(tgt[t-1] - new) > NO_TRADE_B:
            new = tgt[t-1]; n_trades += 1
        pos[t] = new; turn[t] = abs(new - pos[t-1])

    # PnL identity
    cost_rate = HALF_SPREAD_REL + FEE_SIDE_REL
    pnl_gross = np.zeros(N); pnl_net = np.zeros(N)
    pnl_gross[1:] = pos[:-1] * ret[1:]
    pnl_net = pnl_gross - turn * cost_rate

    d = np.array([pnl_net[i*BARS_DAY:(i+1)*BARS_DAY].sum()
                  for i in range(n_days) if (i+1)*BARS_DAY <= N])

    r_ann = float(np.mean(d)) * 250
    sharpe = float(np.mean(d) / np.std(d) * np.sqrt(250)) if np.std(d) > 0 else 0
    to_ann = float(np.sum(turn)) / n_days * 250

    # rolling IC on composite position (for spec sheet comparison)
    ic_blocks = []
    for start in range(Z_WINDOW, N - STEP - 1, STEP):
        end = min(start + STEP, N - 1)
        pos_chunk = pos[start:end]
        rt_chunk = ret[start+1:end+1]
        if len(pos_chunk) > 5 and np.std(pos_chunk) > 0 and np.std(rt_chunk) > 0:
            ic_blocks.append(float(np.corrcoef(pos_chunk, rt_chunk)[0, 1]))
    ic_pos_mean = np.mean(ic_blocks) if ic_blocks else 0

    elapsed = time.perf_counter() - t0

    return {
        "method": "Canonical simulation",
        "R_ann": r_ann,
        "TO_x_yr": round(to_ann),
        "ICIR_pos": round(ic_pos_mean, 4),
        "sharpe_net": round(sharpe, 2),
        "elapsed_ms": round(elapsed * 1000, 1),
        "trades_per_day": round(n_trades / n_days, 1),
        "cost_drag_pct": round(float(np.sum(turn * cost_rate)) /
                               max(abs(pnl_gross.sum()), 1e-10) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Run both and compare
# ---------------------------------------------------------------------------

print("\nComputing score series...")
t_score = time.perf_counter()
score = compute_score(close)
print(f"  done in {(time.perf_counter()-t_score)*1000:.1f} ms")

print("\nRunning evaluations...")
res_a = eval_raw_proxy()
res_b = eval_canonical()

print(f"\n{'='*72}")
print(f"{'Metric':<20}{'Raw Proxy':>16}{'Canonical':>16}{'Delta':>12}  Note")
print(f"{'='*72}")

rows = [
    ("R_ann",       f"{res_a['R_ann']:.4f}",      f"{res_b['R_ann']:.4f}",
     f"{res_b['R_ann']-res_a['R_ann']:+.4f}",  "proxy ignores costs"),
    ("Sharpe",      f"{res_a['sharpe_gross']:.2f}", f"{res_b.get('sharpe_net',0):.2f}",
     "-",                                       "proxy is GROSS only"),
    ("TO (x/nam)",  f"{res_a['TO_x_yr']:,.0f}",    f"{res_b['TO_x_yr']:,.0f}",
     "-",                                       "proxy uses raw score diff"),
    ("IC/ICIR",     f"{res_a['ICIR']:.4f}",       f"{res_b.get('ICIR_pos',0):.4f}",
     "-",                                       "different quantities"),
    ("Time (ms)",   f"{res_a['elapsed_ms']:.1f}", f"{res_b['elapsed_ms']:.1f}",
     "-",                                       "proxy faster (no loop)"),
]

for row in rows:
    print(f"{row[0]:<20}{row[1]:>16}{row[2]:>16}{row[3]:>12}  {row[4]}")

print(f"\nAdditional canonical metrics:")
print(f"  trades/day: {res_b.get('trades_per_day','?')}")
print(f"  cost drag (% gross eaten): {res_b.get('cost_drag_pct','?')}%")
print(f"\nCONCLUSION:")
print("  Proxy fitness ranks candidates cheaply at Stage 0.")
print("  Canonical simulation gives the numbers you can trust.")
print("  Gap between them = cost impact + transform lag.")
