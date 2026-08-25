"""
DEMO: Grinold's Fundamental Law — IC nhỏ (0.02-0.05) kiếm tiền bằng cách nào?

Exp 1: Trí tuệ thuần túy — các cược độc lập, không chi phí.
       Kiểm chứng: realized Sharpe ~= IC * sqrt(B)   (B = số bets/năm)

Exp 2: Mô phỏng thực tế hơn — index futures intraday, bar 5 phút,
       formulaic alpha "VWAP-deviation reversion", tín hiệu bền (persistent),
       sizing theo vol-target, no-trade band, chi phí giao dịch.
       Sweep IC x cost -> bảng net Sharpe cho thấy IC nào sống sót.

Thế giới giả định: có biến ẩn h_t (OU, halflife 20 bar) điều khiển một phần
return bar tới. Score quan sát được = h + noise -> IC raw đặt được theo ý muốn.
"""

import numpy as np

RNG_SEEDS = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41]

# ----------------------------------------------------------------------
# Exp 1: Grinold thuan tuy — iid bets
# ----------------------------------------------------------------------
def exp1_grinold():
    print("=" * 64)
    print("EXP 1 — Grinold: IR ~ IC * sqrt(B)   (khong chi phi)")
    print("=" * 64)
    n = 400_000
    rng = np.random.default_rng(42)
    s = rng.standard_normal(n)
    print(f"{'IC':>5} {'Bets/yr':>8} {'IR ly thuyet':>13} {'IR mo phong':>12}")
    for ic in (0.02, 0.03, 0.05):
        r = ic * s + np.sqrt(1 - ic**2) * rng.standard_normal(n)
        pnl = s * r                      # position = z-scored signal
        sr_bet = pnl.mean() / pnl.std()
        for B in (250, 1600, 6500):      # daily / hourly / 15-min
            print(f"{ic:>5.2f} {B:>8} {ic * np.sqrt(B):>13.2f} "
                  f"{sr_bet * np.sqrt(B):>12.2f}")
    print()

# ----------------------------------------------------------------------
# Exp 2: intraday futures — VWAP reversion alpha trong the gioi gia lap
# ----------------------------------------------------------------------
BARS_PER_DAY = 75          # 5-min bars, phien ~6h15'
DAYS = 250                 # 1 nam giao dich
SIGMA_DAY = 0.009          # vol ngay cua futures ~0.9%
HALFLIFE_BARS = 20         # tin hieu ben: chu ky doi ~100 phut
SPAN_F = 12                # EWMA lam muot score (~1 gio)
LEVEL_CAP = 2.0            # lever notional toi da (|pos| <= 2)
BAND = 1.00                # no-trade band (don vi z)
OBS_QUALITY_C = 0.70       # chat luong quan sat score = c*h + noise

def simulate(ic_target, cost_rts, seed):
    """Chay 1 lan: gross pnl + turnover; tinh net theo tung muc cost."""
    n = DAYS * BARS_PER_DAY
    sig_bar = SIGMA_DAY / np.sqrt(BARS_PER_DAY)
    rng = np.random.default_rng(seed)

    # --- latent signal OU, halflife 20 bars, don vi chuan ---
    phi = np.exp(-np.log(2) / HALFLIFE_BARS)
    innov = rng.standard_normal(n) * np.sqrt(1 - phi**2)
    h = np.zeros(n)
    for t in range(1, n):
        h[t] = phi * h[t - 1] + innov[t]
    h /= h.std()                                      # std = 1 (chuan hoa mau)

    # --- ret[t] = return tu cuoi bar t den cuoi bar t+1, mot phan bi h[t] ---
    rho = min(ic_target / OBS_QUALITY_C, 0.95)
    ret = sig_bar * (rho * h + np.sqrt(1 - rho**2) * rng.standard_normal(n))

    # --- observed score tai cuoi bar t ("VWAP-deviation reversion") ---
    c = OBS_QUALITY_C
    s = c * h + np.sqrt(1 - c**2) * rng.standard_normal(n)

    # --- forecast: EWMA lam muot score (chi dung qua khu) ---
    lam = 1.0 / SPAN_F
    f = np.empty(n); f[0] = s[0]
    for t in range(1, n):
        f[t] = (1 - lam) * f[t - 1] + lam * s[t]

    # z-score rolling de sizing on dinh
    w = 500
    cs = np.cumsum(np.insert(f, 0, 0.0))
    cs2 = np.cumsum(np.insert(f**2, 0, 0.0))
    idx = np.arange(n)
    lo = np.maximum(idx - w + 1, 0)
    cnt = idx + 1 - lo
    rm = (cs[idx + 1] - cs[lo]) / cnt
    rs = np.sqrt(np.maximum((cs2[idx + 1] - cs2[lo]) / cnt - rm**2, 1e-12))
    z = (f - rm) / rs
    z[:w] = 0.0                                       # warm-up

    target = np.clip(LEVEL_CAP * z, -LEVEL_CAP, LEVEL_CAP)

    # --- trading voi no-trade band; quyet dinh cuoi bar t -> earn ret[t] ---
    pos = np.zeros(n)                                 # pos[t]: giu tu cuoi bar t
    turn = np.zeros(n)                                # |Δpos| tai bar t
    trades = 0
    for t in range(1, n):
        new = pos[t - 1]
        tgt = target[t - 1]
        if abs(tgt - new) > BAND:
            new = tgt
            trades += 1
        pos[t] = new
        turn[t] = abs(new - pos[t - 1])

    nb = DAYS * BARS_PER_DAY                          # so bar tinh PnL
    gross_bar = pos[:nb] * ret[:nb]
    turn_bar = turn[:nb]

    def sr(pnl_bar):
        d = pnl_bar.reshape(DAYS, BARS_PER_DAY).sum(axis=1)
        return d.mean() / d.std() * np.sqrt(250)

    sr_gross = sr(gross_bar)

    out = {
        "sr_gross": sr_gross,
        "sr_nets": {cst: sr(gross_bar - turn_bar * cst / 2.0)
                    for cst in cost_rts},             # cost tinh per side
        "trades_per_day": trades / DAYS,
        "ann_turnover_x": turn_bar.sum() / DAYS * 250,
        "ic_raw": np.corrcoef(s[w : nb - 1], ret[w : nb - 1])[0, 1],
        "ic_fcst": np.corrcoef(f[w : nb - 1], ret[w : nb - 1])[0, 1],
    }
    return out

def exp2_intraday():
    print("=" * 72)
    print("EXP 2 — Intraday futures 5', alpha VWAP-reversion co ban")
    print(f"  ({DAYS} ngay x {BARS_PER_DAY} bar, vol ngay {SIGMA_DAY:.1%}, "
          f"halflife {HALFLIFE_BARS} bar, band {BAND}, cap {LEVEL_CAP}x)")
    print("=" * 72)
    ics = (0.01, 0.02, 0.03, 0.05)
    costs = (0.0, 0.0001, 0.0002)                     # roundtrip 0/1bp/2bp
    acc = {}
    for ic in ics:
        res = [simulate(ic, costs, sd) for sd in RNG_SEEDS]
        acc[ic] = {
            "gross": np.mean([x["sr_gross"] for x in res]),
            "nets": {cst: np.mean([x["sr_nets"][cst] for x in res])
                     for cst in costs},
            "tpd": np.mean([x["trades_per_day"] for x in res]),
            "tox": np.mean([x["ann_turnover_x"] for x in res]),
            "ic_raw": np.mean([x["ic_raw"] for x in res]),
            "ic_fcst": np.mean([x["ic_fcst"] for x in res]),
        }
    print(f"{'IC raw':>7} {'IC fcst':>8} {'l/ngay':>7} {'TO(x/nam)':>10} "
          f"{'SR gross':>9} {'SR 0bp':>8} {'SR 1bp':>8} {'SR 2bp':>8}")
    for ic in ics:
        a = acc[ic]
        print(f"{a['ic_raw']:>7.3f} {a['ic_fcst']:>8.3f} {a['tpd']:>7.1f} "
              f"{a['tox']:>10.0f} {a['gross']:>9.2f} {a['nets'][0.0]:>8.2f} "
              f"{a['nets'][0.0001]:>8.2f} {a['nets'][0.0002]:>8.2f}")
    print("(SR = Sharpe annualized, trung binh 10 seeds")
    print(" IC raw  = corr(score tho, return 1 bar toi)")
    print(" IC fcst = corr(forecast EWMA, return 1 bar toi) — smooth tang IC!")
    print(" TO      = turnover notional annualized, don vi 'x von')")
    print()

if __name__ == "__main__":
    exp1_grinold()
    exp2_intraday()
