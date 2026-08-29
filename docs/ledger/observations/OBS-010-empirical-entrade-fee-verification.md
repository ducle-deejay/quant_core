---
doc_id: OBS-010
title: Empirical verification of entrade fees and margin from demo deal records
type: observation
owner: research
status: resolved
version: 1.0
components: [1, 5]
tags: [entrade, broker-fees, margin, verification, cost-model]
source: "verified 2026-08-30 from entrade demo-account exports (deals, orders, transactions); raw files in verification/fee_model/ are gitignored, this note holds aggregates only"
design: [STG-1-CANONICAL-SIM, STG-5-POSITION-CONSTRUCTION, CON-SIM-CANONICAL-PNL, CON-SZ-LEVERAGE-CAP]
code: [crates/alpha-core/src/harness_config.rs]
test: []
---

# OBS-010 - Empirical Verification of entrade Fee and Margin

## 1. Summary

Seven real demo-account deals (2026-07-20, symbol 41I1G8000, all long, one contract each, opened and closed intraday) were cross-checked against the published entrade schedule recorded in OBS-009. Every component verifies exactly, with one systematic discrepancy: the partnership investment fee is measured at **8.22015 VND per index point** instead of the published 8.1 (0.045% x 18% of notional) - about 1.5% higher.

## 2. Verified identities (7/7 deals match)

- **PnL identity**: reported deal profit/loss = gross PnL - total fees and taxes, exactly: `PnL = (close - open) x 100,000 x qty - fees`, e.g. gross -50,000 minus fees 47,110 = reported -97,110.
- **Margin**: deposit booked per deal equals exactly `5% x open x 100,000` (e.g. open 1,899.0 -> 9,495,000 VND). The 5% rate is confirmed to the dong.
- **Tax credit**: losing deals receive a credit of exactly `5% x |gross PnL|` (e.g. gross -50,000 -> +2,500). Empirical behavior is a symmetric signed tax: `tax = 5% x gross PnL` (charge on profit, credit on loss), credited immediately at deal close. The published note about periodic caps was not observed in this sample.
- **Order types exercised**: MAK, MOK, MTL and LO all filled; cancelled orders report status "Huy" with no fill. Fill prices equal the deal average open/close prices.

## 3. Measured fee schedule (round trip, per contract)

- Fixed components: 31,500 VND (6,000 trading + 15,000 platform + 5,400 exchange + 5,100 VSDC clearing) - consistent with actuals.
- Partnership fee: **8.22015 x open price** (implied rate per deal: 8.2201 to 8.2203; mean 8.22015) vs published 8.1.
- Total: `31,500 + 8.22015 x open` VND round trip.
- Per side: `15,750 + 4.1101 x open` VND -> about **1.236 bp/side at open prices 1,899-1,924** (mean of the seven deals); 1.72 bp at 1,200, 1.34 bp at 1,700, 1.24 bp at 1,900, 1.16 bp at 2,100.
- All seven deals were intraday; no overnight management fee observed (our 14:00 force-close design avoids it by construction).

## 4. Discrepancy and recommendation

The measured partnership rate (8.22015/point) exceeds the published formula (0.045% x 18% x 100,000 = 8.1/point) by ~1.48%. Possible causes: a slightly different deposit base (18.266% vs 18%) or fee rate (0.045667% vs 0.045%); the data cannot separate the two. Treat the empirical rate as authoritative for cost-model calibration. The published example total of 45,473 VND matches 31,500 + 8.1 x ~1,725 (the page's own example price), so the published figure itself is internally consistent but slightly low against measured behavior.

## 5. Caveats

- The sample is seven losing intraday deals; the tax charge on profitable deals has not yet been observed empirically (only the credit side).
- One sample per contract size; fee tiers (800/500/300 VND) apply above 100 filled contracts/day and were not exercised.
- Re-verify with a larger sample, including profitable deals, before freezing the harness cost model.

## Related notes

- [OBS-009](OBS-009-entrade-fee-and-margin-schedule.md) - published schedule this note verifies; its partnership rate is superseded in practice by the empirical 8.22015
- Future reconciliation note for harness cost-model calibration (planned with the Nautilus wiring phase)
