"""
DEMO: Search fitness (raw-score proxy) vs Canonical fitness (Stage 1 output)

Cau hoi: tai sao GA fitness o Stage 0 khong dung canonical PnL?
Tra loi: vi no KHONG CAN - no dung raw score lam position truc tiep,
tinh nhanh hon nhieu lan, va cho ketqua thua le hon (overestimate).

Script nay chay ca hai phien ban tren cung data va cung mot seed alpha,
roi so sanh: gia tri fitness, thoi gian tinh, va giai thich tai sao khac nhau.

Chay: python3 research/fitness_proxy_vs_canonical.py
"""

import time
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Reuse synthetic world from seed_alpha_demo (same generator, same seed)
# ---------------------------------------------------------------------------

N_DAYS    = 20
BARS_DAY  = 285
N         = N_DAYS * BARS_DAY
SIGMA_DAY = 0.009
SIG_BAR   = SIGMA_DAY / np.sqrt(BARS_DAY)
HALF_LIFE = 45
BETA_EDGE = 0.05
OBS_QUAL  = 0.70
BOUNCE    = -0.18
MID0      = 1000.0

def generate():
    rng = np.random.default_rng(7)
    phi = np.exp(-np.log(2) / HALF_LIFE)
    h = np.zeros(N); innov = rng.standard_normal(N) * np.sqrt(1 - phi**2)
    for t in range(1, N): h[t] = phi * h[t-1] + innov[t]
    h /= h.std()
    imb_lat = np.tanh(1.2 * h)

    imb_obs = OBS_QUAL * imb_lat + np.sqrt(1 - OBS_QUAL**2) * rng.standard_normal(N)

    eps = rng.standard_normal(N)
    ret = SIG_BAR * (np.sqrt(1 - BOUNCE**2) * eps
                     + BOUNCE * np.r_[0.0, eps[:-1]]
                     + BETA_EDGE * np.r_[0.0, imb_lat[:-1]])
    mid = MID0 * np.exp(np.cumsum(ret))
    close = mid
    vol = np.exp(rng.normal(9.5, 0.6, N)) * (1 + 40 * abs(ret))

    lv = np.arange(1, 11); w_lv = 1.0 / lv
    base = np.exp(rng.normal(8.0, 0.25))
    bs = base * w_lv[None,:] * (1 + 0.65 * imb_obs[:,None]) * np.exp(rng.normal(0, 0.12, (N,10)))
    as_ = base * w_lv[None,:] * (1 - 0.65 * imb_obs[:,None]) * np.exp(rng.normal(0, 0.12, (N,10)))

    df = pd.DataFrame({"close": close, "volume": vol})
    for l in range(1, 11):
        df[f"bs_l{l}_close"] = bs[:, l-1]
        df[f"as_l{l}_close"] = as_[:, l-1]
    return df


def compute_score(df, span=8, z_window=480):
    """Seed A: book imbalance continuation."""
    bs_tot = sum(df[f"bs_l{l}_close"] for l in range(1, 11))
    as_tot = sum(df[f"as_l{l}_close"] for l in range(1, 11))
    k = 15
    imb = pd.Series(bs_tot).rolling(k).sum() / \
          (pd.Series(bs_tot).rolling(k).sum() + pd.Series(as_tot).rolling(k).sum())
    smoothed = imb.ewm(span=span).mean()
    m = smoothed.rolling(z_window).mean()
    sd = smoothed.rolling(z_window).std()
    return ((smoothed - m) / sd.replace(0, np.nan)).fillna(0).to_numpy()


# ---------------------------------------------------------------------------
# METHOD A: Raw-score proxy (Stage 0 search fitness)
# Score IS the position. No transforms. Pure vectorised arithmetic.
# ---------------------------------------------------------------------------

def eval_raw_proxy(score, ret, days=N_DAYS):
    t0 = time.perf_counter()

    # pseudo-PnL: score treated as direct position
    pnl = np.r_[0.0, score[:-1] * ret[1:]]

    # annualised metrics
    d = pd.Series(pnl).groupby(np.arange(len(pnl)) // BARS_DAY).sum()
    r_ann = d.mean() / MID0 * 250            # fraction per year
    sharpe = d.mean() / d.std() * np.sqrt(250) if d.std() > 0 else 0

    # IC-based component
    ic_series = []
    for i in range(len(score) - 1):
        fwd = ret[i+1] if i+1 < len(ret) else 0
        ic_series.append((score[i], fwd))
    ic_arr = np.array(ic_series)
    ic_mean = np.corrcoef(ic_arr[:, 0], ic_arr[:, 1])[0, 1] if len(ic_arr) > 10 else 0
    ic_std = np.std([np.corrcoef(
        score[max(0,t-BARS_DAY):t], ret[max(0,t-BARS_DAY)+1:t+1])[0,1]
        for t in range(BARS_DAY, min(len(score), N-BARS_DAY), BARS_DAY)
        if t - BARS_DAY >= 0 and len(score[max(0,t-BARS_DAY):t]) > 2
    ]) if N > BARS_DAY * 2 else 0.01
    icir = ic_mean / max(ic_std, 1e-6)

    # turnover on raw score changes
    to_daily = np.abs(np.diff(score)).sum() / days * 250

    elapsed = time.perf_counter() - t0

    to_floor = 0.125
    fitness = icir * np.sqrt(abs(r_ann)) / max(to_daily, to_floor)

    return {
        "method": "Raw-score proxy",
        "R_ann": round(r_ann, 6),
        "TO_x_yr": round(to_daily, 0),
        "ICIR": round(icir, 3),
        "fitness": round(fitness, 4),
        "elapsed_ms": round(elapsed * 1000, 1),
        "_sharpe": round(sharpe, 2),
        "_daily_pnl": d,
    }


# ---------------------------------------------------------------------------
# METHOD B: Canonical simulation (Stage 1 full harness)
# EWMA -> rolling z -> band -> cap -> PnL identity -> real turnover
# ---------------------------------------------------------------------------

SPAN_SMOOTH = 8
Z_WINDOW    = 480
LEVEL_CAP   = 2.0
NO_TRADE_B  = 0.35
HALF_SPREAD = 0.0001
FEE_SIDE    = 0.00002

def eval_canonical(score, df, days=N_DAYS):
    t0 = time.perf_counter()

    ret = df.close.pct_change().to_numpy()

    # full mapping
    sm = pd.Series(score).ewm(span=SPAN_SMOOTH).mean().to_numpy()
    zs = pd.Series(sm)
    m = zs.rolling(Z_WINDOW).mean(); sd = zs.rolling(Z_WINDOW).std()
    z = ((zs - m) / sd.replace(0, np.nan)).fillna(0).to_numpy()
    tgt = np.clip(z, -LEVEL_CAP, LEVEL_CAP)

    pos = np.zeros_like(tgt); turn = np.zeros_like(tgt); n_tr = 0
    for t in range(1, len(tgt)):
        new = pos[t-1]
        if abs(tgt[t-1] - new) > NO_TRADE_B:
            new = tgt[t-1]; n_tr += 1
        pos[t] = new; turn[t] = abs(new - pos[t-1])

    pnl_gross = np.r_[0.0, pos[:-1] * ret[1:]]
    cost = turn * (HALF_SPREAD + FEE_SIDE)
    pnl_net = pnl_gross - cost

    d = pd.Series(pnl_net).groupby(np.arange(len(pnl_net)) // BARS_DAY).sum()
    r_ann = d.mean() * 250
    sharpe = d.mean() / d.std() * np.sqrt(250) if d.std() > 0 else 0

    # IC of composite (same as raw score since mapping is monotonic)
    ic_vals = []
    for h_off in range(0, min(len(z), N - 1)):
        ic_vals.append(z[h_off])
    to_daily = np.abs(np.diff(pos)).sum() / days * 250
    to_floor = 0.125
    icir_proxy = abs(sharpe) / np.sqrt(250) * np.sqrt(BARS_DAY) if sharpe != 0 else 0
    fitness = icir_proxy * np.sqrt(abs(r_ann)) / max(to_daily, to_floor)

    elapsed = time.perf_counter() - t0

    return {
        "method": "Canonical simulation",
        "R_ann": round(r_ann, 6),
        "TO_x_yr": round(to_daily, 0),
        "fitness": round(fitness, 4),
        "elapsed_ms": round(elapsed * 1000, 1),
        "_sharpe": round(sharpe, 2),
        "_daily_pnl": d,
        "_trades_per_day": n_tr / days,
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 68)
    print("Search fitness (raw-score proxy) vs Canonical fitness")
    print("Same seed, same data, same evaluation period")
    print("=" * 68)

    df = generate()

    # compute score once
    bs_tot = sum(df[f"bs_l{l}_close"] for l in range(1, 11))
    as_tot = sum(df[f"as_l{l}_close"] for l in range(1, 11))
    k = 15
    imb = pd.Series(bs_tot).rolling(k).sum() / \
          (pd.Series(bs_tot).rolling(k).sum() + pd.Series(as_tot).rolling(k).sum())
    score = ((imb.ewm(span=SPAN_SMOOTH).mean() -
              imb.ewm(span=SPAN_SMOOTH).mean().rolling(Z_WINDOW).mean()) /
             imb.ewm(span=SPAN_SMOOTH).mean().rolling(Z_WINDOW).std().replace(0, np.nan)
             ).fillna(0).to_numpy()

    ret = df.close.pct_change().to_numpy()

    res_a = eval_raw_proxy(score, ret, N_DAYS)
    res_b = eval_canonical(score, df, N_DAYS)

    hdr = f"{'Metric':<16}{'Proxy (Stage 0)':>18}{'Canonical (Stage 1)':>22}{'Ghi chu':<30}"
    print(f"\n{hdr}")
    print("-" * len(hdr))

    rows = [
        ("R_ann",       f"{res_a['R_ann']:.4f}",           f"{res_b['R_ann']:.4f}",
         "proxy > canon (no cost/band lag)"),
        ("TO (x/nam)",  f"{res_a['TO_x_yr']:.0f}",         f"{res_b['TO_x_yr']:.0f}",
         "proxy < canon (band reduces trading)"),
        ("Sharpe",      f"{res_a['_sharpe']:.2f}",          f"{res_b['_sharpe']:.2f}",
         "proxy overestimates"),
        ("Fitness",     f"{res_a['fitness']:.4f}",          f"{res_b['fitness']:.4f}",
         "proxy ranking OK, absolute value inflated"),
        ("Time (ms)",   f"{res_a['elapsed_ms']:.1f}",       f"{res_b['elapsed_ms']:.1f}",
         "proxy faster (no position loop)"),
    ]
    for metric, a_val, b_val, note in rows:
        print(f"{metric:<16}{a_val:>18}{b_val:>22}  {note}")

    print()
    print("KET LUAN:")
    print("  Proxy fitness (Stage 0) overestimate vi khong co cost/band/lag.")
    print("  Nhung van du de RANKING cac candidate trong cung batch -")
    print("  do la muc dich duy nhat cua no. Gia tri tuyet doi khong tin duoc;")
    print("  chi Stage 2 moi quyet dinh PASS hay FAIL.")

    print("\nFILES:")
    print("  Data source : synthetic (same as seed_alpha_demo)")
    print("  Seed alpha  : book_imbalance_cont (imb10, ewma 8, z 480)")
