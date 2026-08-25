"""
DEMO: Seed alpha trong nha may formulaic — Stage 1 (canonical simulation)

Muc tieu minh hoa tron 1 vong doi cua 1 seed alpha:
  [0] Data contract  : ohlcv + book depth 10 levels (resample kieu OHLC bar)
  [1] Seed library   : bieu thuc DSL viet tay boi researcher (causal, stateless)
  [2] Canonical map  : score -> position theo QUY TAC CHUAN chung moi alpha
                       (smooth -> rolling z -> no-trade band -> cap)
                       => fitness giua cac alpha comparable tuyet doi
  [3] Evaluation     : IC theo horizon (do chat luong du bao TRUOC khi tinh tien)
                       + Sharpe net-of-cost cua canonical position (kiem chung)
  [4] Pool preview   : corr PnL giua 2 seed -> y tuong Stage 3

The gioi gia lap: imbalance do sau (bid vs ask) AR(1) ban-tuoi ~45 bar
an mot phan vao return tuong lai (continuation); gia co micro-bounce lag-1
de seed reversion co viec an. Moi quan he nay dai dien cho "edge" thuc
ma researcher tin la ton tai trong data VN30F1M.

Chi dung numpy/pandas. Chay: python3 research/seed_alpha_demo.py
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(7)

# ----------------------------- cau hinh the gioi -----------------------------
N_DAYS      = 20
BARS_DAY    = 285          # 1-min bars, phien VN ~4h45'
N           = N_DAYS * BARS_DAY
SIGMA_DAY   = 0.009        # vol ngay ~0.9%
SIG_BAR     = SIGMA_DAY / np.sqrt(BARS_DAY)
HALF_LIFE   = 45           # ban tuoi imbalance (bar)
BETA_EDGE   = 0.05         # do manh edge latent -> fwd ret
OBS_QUAL    = 0.70         # chat luong quan sat imbalance tu book
BOUNCE      = -0.18        # auto-corr lag-1 cua ret (micro-bounce)
MID0        = 1000.0       # gia mid khoi dau
TICK        = 0.1

# ------------------------- canonical harness (chung) -------------------------
SPAN_SMOOTH = 8            # EWMA lam muot score (~8 phut)
Z_WINDOW    = 480          # cua so rolling z-score (~1.7 ngay)
LEVEL_CAP   = 2.0          # |position| toi da (don vi notional x von)
NO_TRADE_B  = 0.35         # band z: chi doi vi tri khi vuot band
HALF_SPREAD = 0.0001       # 1 bp notional moi chieu (spread thuc te)
FEE_SIDE    = 0.00002      # phi san moi chieu


# =============================================================================
# [0] DATA CONTRACT — truong du lieu ma moi alpha duoc phep dung
# =============================================================================
def gen_world():
    """Sinh the gioi gia lap: ohlcv + book depth 10 levels (OHLC-style bar)."""
    n, rng = N, RNG

    # --- latent imbalance OU, don vi chuan, squash qua tanh ve [-1, 1] ---
    phi  = np.exp(-np.log(2) / HALF_LIFE)
    h    = np.zeros(n)
    innov = rng.standard_normal(n) * np.sqrt(1 - phi**2)
    for t in range(1, n):
        h[t] = phi * h[t - 1] + innov[t]
    h /= h.std()
    imb_lat = np.tanh(1.2 * h)                      # latent, [-1, 1]

    # --- imbalance quan sat duoc tu book (co nhieu) ---
    imb_obs = OBS_QUAL * imb_lat + np.sqrt(1 - OBS_QUAL**2) \
              * rng.standard_normal(n)

    # --- forward return: mot phan bi imb_lat(t) dieu khien (continuation),
    #     cong micro-bounce lag-1 tren phan nhiễu ---
    eps  = rng.standard_normal(n)
    ret  = SIG_BAR * (np.sqrt(1 - BOUNCE**2) * eps
                      + BOUNCE * np.r_[0.0, eps[:-1]]
                      + BETA_EDGE * np.r_[0.0, imb_lat[:-1]])
    mid  = MID0 * np.exp(np.cumsum(ret))

    # --- OHLCV tu nhieu trong-bar quanh mid ---
    intrabar = rng.standard_normal((n, 4)) * SIG_BAR * 0.55
    o = mid * np.exp(intrabar[:, 0])
    h_ = mid * np.exp(np.abs(intrabar[:, 1]))
    l_ = mid * np.exp(-np.abs(intrabar[:, 2]))
    c = mid
    vol = np.exp(rng.normal(9.5, 0.6, n)) * (1 + 40 * np.abs(ret))

    # --- book depth 10 levels: gia lech theo tick, size theo imb_obs ---
    lv   = np.arange(1, 11)
    w_lv = 1.0 / lv                                  # level sau mong hon
    base = np.exp(rng.normal(8.0, 0.25))
    bs   = base * w_lv[None, :] * (1 + 0.65 * imb_obs[:, None]) \
           * np.exp(rng.normal(0, 0.12, (n, 10)))
    as_  = base * w_lv[None, :] * (1 - 0.65 * imb_obs[:, None]) \
           * np.exp(rng.normal(0, 0.12, (n, 10)))
    bp   = np.round(mid[:, None] - TICK * (2 * lv[None, :] - 1) / 2, 1)
    ap   = np.round(mid[:, None] + TICK * (2 * lv[None, :] - 1) / 2, 1)

    df = pd.DataFrame({
        "open": o, "high": h_, "low": l_, "close": c, "volume": vol,
        # snapshot cuoi bar (du lieu da resample thanh bar, style ohlc:
        # price giu o/h/l/c, size giu sum + close — day la convention)
        **{f"bs_l{l}_close": bs[:, l - 1] for l in lv},
        **{f"as_l{l}_close": as_[:, l - 1] for l in lv},
        **{f"bs_l{l}_sum":   bs[:, l - 1] for l in lv},
        **{f"as_l{l}_sum":   as_[:, l - 1] for l in lv},
        **{f"bp_l{l}_close": bp[:, l - 1] for l in lv},
        **{f"ap_l{l}_close": ap[:, l - 1] for l in lv},
    })
    return df, imb_lat


# =============================================================================
# OPERATORS — ngu phap DSL, tat ca CAUSAL (chi nhin qua khu), vectorised
# =============================================================================
def ts_delay(x, d):  return pd.Series(x).shift(d).to_numpy()
def ts_delta(x, d):  return pd.Series(x).diff(d).to_numpy()
def ts_mean(x, w):   return pd.Series(x).rolling(w).mean().to_numpy()
def ts_std(x, w):    return pd.Series(x).rolling(w).std().to_numpy()
def ts_sum(x, w):    return pd.Series(x).rolling(w).sum().to_numpy()
def ts_max(x, w):    return pd.Series(x).rolling(w).max().to_numpy()
def ts_min(x, w):    return pd.Series(x).rolling(w).min().to_numpy()
def sign(x):         return np.sign(x)
def clip(x, lo, hi): return np.clip(x, lo, hi)


def ts_zscore(x, w):
    s = pd.Series(x)
    m = s.rolling(w).mean()
    sd = s.rolling(w).std()
    return ((s - m) / sd.replace(0, np.nan)).to_numpy()


# =============================================================================
# [1] SEED LIBRARY — moi seed = 1 gia thuyet hanh vi nen thanh cong thuc
#     Researcher viet tay. GA sau nay lai ghep cac sub-expression nay.
# =============================================================================
SEEDS = {}

SEEDS["book_imbalance_cont"] = {
    "hypothesis": "Book bid nang hon ask (chua don hang mua) -> gia tiep tuc di len",
    "dsl": ("imb10   = (ts_sum(bs_total, {k}) - ts_sum(as_total, {k})) / "
            "(ts_sum(bs_total, {k}) + ts_sum(as_total, {k}));\n"
            "score   = ts_zscore(ewma(imb10, {s}), {w})"),
    "params": {"k": 15, "s": SPAN_SMOOTH, "w": Z_WINDOW},
    "expr": lambda D, p: (
        lambda imb: ts_zscore(
            pd.Series(imb).ewm(span=p["s"]).mean().to_numpy(), p["w"])
    )(ts_sum(D.bs_tot.to_numpy(), p["k"]) /
      (ts_sum(D.bs_tot.to_numpy(), p["k"]) +
       ts_sum(D.as_tot.to_numpy(), p["k"]))),
}

SEEDS["price_bounce_rev"] = {
    "hypothesis": "Gia chay nhanh 5 phut qua mid ngan han -> hat ve lai (bounce)",
    "dsl": ("dev     = close / ts_mean(close, {k}) - 1;\n"
            "score   = -ts_zscore(ewma(dev, {s}), {w})"),
    "params": {"k": 5, "s": SPAN_SMOOTH, "w": Z_WINDOW},
    "expr": lambda D, p: (
        -ts_zscore(
            pd.Series(D.close.to_numpy() /
                      ts_mean(D.close.to_numpy(), p["k"]) - 1)
            .ewm(span=p["s"]).mean().to_numpy(), p["w"])
    ),
}


def show_tree(name, seed):
    print(f"  [{name}]")
    print(f"    hypothesis : {seed['hypothesis']}")
    print("    dsl        :")
    for line in seed["dsl"].format(**seed["params"]).splitlines():
        print(f"      {line}")
    print(f"    params     : {seed['params']}")


# =============================================================================
# [2]+[3] CANONICAL HARNESS + EVALUATION — cung quy tac cho MOI alpha
# =============================================================================
def canonical_position(score):
    """score -> target position. QUY TAC CHUAN, khong phai cua tung alpha."""
    sm = pd.Series(score).ewm(span=SPAN_SMOOTH).mean().to_numpy()
    z  = ts_zscore(sm, Z_WINDOW)
    z  = np.nan_to_num(z, nan=0.0)
    tgt = clip(z, -LEVEL_CAP, LEVEL_CAP)

    pos  = np.zeros_like(tgt)
    turn = np.zeros_like(tgt)
    n_tr = 0
    for t in range(1, len(tgt)):
        new = pos[t - 1]
        if abs(tgt[t - 1] - new) > NO_TRADE_B:      # no-trade band
            new = tgt[t - 1]
            n_tr += 1
        pos[t]  = new
        turn[t] = abs(new - pos[t - 1])
    return pos, turn, n_tr


def eval_seed(df, score, label):
    ret  = df.close.pct_change().to_numpy()          # ret[t]: bar t-1 -> t
    pos, turn, n_tr = canonical_position(score)

    # PnL: quyet dinh cuoi bar t -> earn ret[t+1]; tru cost theo turnover
    pnl_gross = np.r_[0.0, pos[:-1] * ret[1:]]
    pnl_net   = pnl_gross - turn * (HALF_SPREAD + FEE_SIDE)

    days = N_DAYS
    def sr_daily(p):
        d = pd.Series(p).groupby(np.arange(len(p)) // BARS_DAY).sum()
        return d.mean() / d.std() * np.sqrt(250)
    eq  = np.cumsum(pnl_net)
    peak = np.maximum.accumulate(eq)
    mdd  = (eq - peak).min()          # fixed-notional: von = 1 don vi

    # --- IC theo horizon: corr(score_t, tong ret t+1..t+h) ---
    ics = {}
    for hzn in (1, 5, 15):
        fwd = pd.Series(ret).shift(-1).rolling(hzn).sum().shift(-hzn + 1)
        ic_series = pd.Series(score).rolling(Z_WINDOW).corr(fwd)
        blk = ic_series.dropna().groupby(
            np.arange(ic_series.dropna().size) // BARS_DAY)   # block theo ngay
        m = blk.mean()
        ics[hzn] = (m.mean(), m.mean() / (m.std() / np.sqrt(len(m))))

    out = {
        "ic1": ics[1], "ic5": ics[5], "ic15": ics[15],
        "sr_gross": sr_daily(pnl_gross),
        "sr_net":   sr_daily(pnl_net),
        "to_x_yr":  turn.sum() / days * 250,
        "mdd":      mdd,
        "tpd":      n_tr / days,
        "_pnl_daily": pd.Series(pnl_net)
                        .groupby(np.arange(N) // BARS_DAY).sum(),
    }
    return out


def sparkline(x, width=64):
    idx = np.linspace(0, len(x) - 1, width).astype(int)
    v = np.asarray(x)[idx]
    lo, hi = v.min(), v.max()
    if hi - lo < 1e-12:
        return " " * width
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[int((y - lo) / (hi - lo) * 7)] for y in v)


# =============================================================================
def main():
    df, imb_lat = gen_world()

    print("=" * 74)
    print("[0] DATA CONTRACT — truong du lieu alpha duoc phep dung")
    print("=" * 74)
    groups = {
        "ohlcv"        : ["open high low close volume"],
        "book size bid": ["bs_l{1..10}_close  bs_l{1..10}_sum"],
        "book size ask": ["as_l{1..10}_close  as_l{1..10}_sum"],
        "book px  bid" : ["bp_l{1..10}_close"],
        "book px  ask" : ["ap_l{1..10}_close"],
    }
    for g, f in groups.items():
        print(f"  {g:<15}: {f[0]}")
    print(f"  ({len(df.columns)} cot x {N} bar 1-phut = {N_DAYS} ngay)")

    print()
    print("=" * 74)
    print("[1] SEED LIBRARY — viet tay boi researcher")
    print("=" * 74)
    for nm, sd in SEEDS.items():
        show_tree(nm, sd)
        print()

    print("=" * 74)
    print(f"[2] CANONICAL HARNESS: ewma({SPAN_SMOOTH}) -> z({Z_WINDOW}) "
          f"-> band {NO_TRADE_B} -> cap ±{LEVEL_CAP}")
    print(f"    cost/side = half-spread {HALF_SPREAD:.0e} + fee {FEE_SIDE:.0e}"
          " (notional)")
    print("=" * 74)

    df = df.assign(bs_tot=sum(df[f"bs_l{l}_close"] for l in range(1, 11)),
                   as_tot=sum(df[f"as_l{l}_close"] for l in range(1, 11)))

    results, scores = {}, {}
    for nm, sd in SEEDS.items():
        sc = sd["expr"](df, sd["params"])
        scores[nm] = sc
        results[nm] = eval_seed(df, sc, nm)

    hdr = (f"{'seed':<22}{'IC@1':>12}{'IC@5':>12}{'IC@15':>12}"
           f"{'SRgross':>9}{'SRnet':>8}{'TOx/nam':>9}{'MDD':>8}{'TPD':>6}")
    print()
    print(hdr)
    print("-" * len(hdr))
    for nm, r in results.items():
        ic1, t1 = r["ic1"]; ic5, _ = r["ic5"]; ic15, _ = r["ic15"]
        print(f"{nm:<22}{ic1:>7.3f} t={t1:<3.1f}{ic5:>7.3f}"
              f"{ic15:>12.3f}{r['sr_gross']:>9.2f}{r['sr_net']:>8.2f}"
              f"{r['to_x_yr']:>9.0f}{r['mdd']:>8.1%}{r['tpd']:>6.0f}")

    print()
    print("=" * 74)
    print("[4] POOL PREVIEW — corr PnL ngay giua cac seed (Stage-3 y tuong)")
    print("=" * 74)
    keys = list(results)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            c = results[keys[i]]["_pnl_daily"].corr(
                results[keys[j]]["_pnl_daily"])
            print(f"  corr('{keys[i]}', '{keys[j]}') = {c:+.2f}")

    r0 = results["book_imbalance_cont"]
    print()
    print("=" * 74)
    print("[5] CHART — seed 'book_imbalance_cont'")
    print("=" * 74)
    eqd = r0["_pnl_daily"].cumsum()
    print("  Equity net (theo ngay):")
    print("   " + sparkline(eqd.to_numpy()))
    ic_roll = (pd.Series(scores["book_imbalance_cont"])
               .rolling(Z_WINDOW)
               .corr(pd.Series(df.close.pct_change().to_numpy()).shift(-1)))
    ic_blk = ic_roll.dropna().groupby(
        np.arange(ic_roll.dropna().size) // BARS_DAY).mean()
    print("  Rolling IC (block ngay):")
    print("   " + sparkline(ic_blk.to_numpy()))
    lat_ic = np.corrcoef(imb_lat[:-1], df.close.pct_change()
                         .to_numpy()[1:])[0, 1]
    print(f"\n  (tham chieu: corr latent imbalance -> fwd ret = {lat_ic:+.3f})")


if __name__ == "__main__":
    main()
