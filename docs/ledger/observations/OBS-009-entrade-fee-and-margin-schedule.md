---
doc_id: OBS-009
title: Verified entrade fee and margin schedule for cost-model calibration
type: observation
owner: research
status: resolved
version: 1.0
components: [1, 5]
tags: [entrade, broker-fees, margin, cost-model, calibration, reference]
source: "verified 2026-08-30 against the official entrade help pages listed in References"
design: [STG-1-CANONICAL-SIM, STG-5-POSITION-CONSTRUCTION, CON-SIM-CANONICAL-PNL, CON-SZ-LEVERAGE-CAP]
code: [crates/alpha-core/src/harness_config.rs]
test: []
---

# OBS-009 - Verified entrade Fee and Margin Schedule

## 1. Summary

entrade (a DNSE subsidiary product) publishes its own fee and margin schedule, which differs materially from the DNSE schedule previously recorded in this project. This note records the verified numbers as the calibration reference for the harness cost model (Component 1) and the position cap computation (Component 5). The current canon cost estimates (broker fees 500-2,000 VND, total cost per side around 0.5 bp; margin rate 0.18) are outdated against this schedule; the canon is frozen, so the re-calibration will be recorded in a reconciliation note when the harness is re-wired.

## 2. Verified facts (as of 2026-08-30)

### 2.1 Margin

- Initial deposit (coc): **5%** of contract value: `deposit = 5% x price x 100,000 x quantity`.
- Warning ratio: 3.00%; handling (broker-forced) ratio: 2.00%.
- Published example: at price 1,700 points, one contract requires `1,700 x 100,000 x 5% = 8,500,000 VND`.
- Implication: at 100,000,000 VND capital and price ~1,900, the nominal `L_max` is about 10 contracts before any safety factor; volatility targeting will size well below this.

### 2.2 Trading fees - per contract, round trip (open + close)

| Component | Amount | Type |
|---|---|---|
| Trading fee (phi giao dich) | 6,000 VND | fixed |
| Platform fee (phi nen tang) | 15,000 VND | fixed |
| Exchange fee collected (phi thu ho so giao dich) | 5,400 VND | fixed |
| VSDC clearing fee collected (phi bu tru vi the thu ho VSDC) | 5,100 VND | fixed |
| Partnership investment fee (phi hop tac dau tu) | `0.045% x 18% x price x 100,000 = 8.1 x price` | price-dependent |

- Fixed round trip: **31,500 VND/contract**; total round trip: **31,500 + 8.1 x price** VND.
- The published total "45,473 VND" for opening and closing one contract equals `31,500 + 13,973`, where `13,973 = 8.1 x ~1,725` - it is an example at that price level, not a constant.
- Per side: `15,750 + 4.05 x price` VND, i.e. a relative cost per side of `0.1575/price + 0.0000405` (about 1.23 bp at price 1,900; about 1.72 bp at price 1,200).
- The current `HarnessConfig` default `cost_per_side = 0.0001` (1 bp) underestimates this schedule and must be re-calibrated.

### 2.3 Taxes

- Partnership investment tax: **5% of position profit** when the closed deal is profitable; 0% on losing deals; refunds are capped by the taxes collected from profitable deals in the same accounting period. Accounting is monthly (quarterly/yearly at the provider's discretion).
- Not a per-trade cost: model it at the accounting layer, not inside `cost_per_side`.

### 2.4 Exempted fees at entrade

- Margin deposit/withdrawal fee (5,500 VND per transaction) - waived.
- Asset management fee (100,000-1,600,000 VND/month) - waived.
- Transaction tax 0.05% per buy/sell side (~31,500 VND round trip at price 1,700) - waived.

## 3. Notes and caveats

- Two official help pages disagree because of age: `hdsd.entrade.com.vn` (deal page, last updated ~5 years ago) describes an older model (8,200 VND/side trading fee, 5,500 VND/night management fee); the schedule above comes from `hdsd2.entrade.com.vn` ("Ty le ky quy va Phi giao dich", updated ~5 months ago). Treat the newer page as authoritative and re-verify before going live.
- The partnership fee formula (0.045% on the 18% deposit portion of notional) is consistent across both pages.
- Recommended final verification: extract the actual fee lines from entrade demo-account deal/fill records before fixing cost-model constants; the nox demo audit infrastructure can record them.
- Margin ratios and fee tiers change with broker policy; re-verify periodically.

## 4. Impact on frozen canon (recorded here, canon untouched)

- `docs/enhanced/concepts/simulation/canonical-pnl.md` section 2.3 estimates total cost around 0.5 bp/side with broker fees 500-2,000 VND - outdated for entrade.
- `docs/enhanced/concepts/sizing/leverage-cap.md` uses `margin_rate = 0.18` - outdated for entrade (0.05).
- A reconciliation note will be written when the harness cost model is re-wired during the Nautilus wiring phase.

## References

- https://hdsd2.entrade.com.vn/man-hinh-giao-dich/quy-trinh-giao-dich/ty-le-ky-quy-va-phi-giao-dich (current, updated ~5 months ago)
- https://hdsd.entrade.com.vn/quan-ly-tai-san/deal (older, updated ~5 years ago)

## Related notes

- [OBS-008](OBS-008-user-acceptance-production-gaps.md) - prior production-readiness audit of the framework
- Future reconciliation note for harness cost-model calibration (planned with the Nautilus wiring phase)
