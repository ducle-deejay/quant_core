# VN30F1M 1-minute bar correction, attempt 2

## Scope

This report records the second attempt to fill and correct the VN30F1M
1-minute bars (`VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL`). It covers the fill of
days on which DNSE has data but misses bars. Attempt 1 is recorded in
`vn30f1m_bar_correction_attempt_1.md` and is kept unchanged for comparison.

## Why a second attempt

The catalog errors found in attempt 1 come from the ingest pipeline, not only
from the sources:

- **Whole-day replacement.** When DNSE misses even one bar of a day and Mirae
  has all 241, the day is replaced by Mirae without any check
  (`src/market_data/sources/mirae/load.py`, `_select_day_bars`). Mirae's own
  errors enter the catalog this way: the missing ATO match, F2M in place of
  F1M on 2025-06-19, and the previous session copied onto 2022-01-03.
- **No value check.** Validation checks structure only (minute grid, contract
  identity, record counts), so DNSE value errors also pass.

Agreed pipeline changes, not implemented yet:
1. Remove whole-day replacement; fill only bars that are truly missing, after
   comparison with other sources.
2. Compare daily aggregates with the exchange after each ingest.

Attempt 2 restarts from DNSE raw data, without the Mirae backfill, and splits
the work by cause:
- **Fill:** days on which DNSE has fewer than 241 bars.
- **Correct:** days on which DNSE has all 241 bars, so any error is DNSE's.

## Requirements

- Data is split by calendar year (2018 to 2026).
- From 2022-01-01 the data must have no wrong and no missing bars, and cannot
  be cut. Earlier years may be cut.
- A bar is wrong when it deviates beyond an agreed threshold; exact equality
  is not required.
- Missing data is one of:
  - **Missing day:** the exchange publishes the trading day and DNSE has no bar.
  - **Missing bars:** DNSE has the day but misses minutes, either because the
    DNSE feed lost them (an error) or because the exchange published no trade
    in that minute, which shows as the minute missing in every broker (not an
    error).

## Data

Paths below are relative to one of two folders with the same layout:
- this folder (in git): the correction outputs (`attempt_*/VN30F1M_missing.csv`,
  `attempt_*/VN30F1M_wrong.csv`), the day lists (`attempt_2/*.json`) and the
  exchange reference `vn30f1m_hnx.csv`;
- `$DATA_ROOT/validation/vn30f1m/` (outside git, too large): broker bars
  (`bars/`), the raw exchange and VPBankS daily files (`hnx_1d.csv`,
  `vpbanks_1d.csv`), the attempt 1 catalog export and step files, and the
  rebuildable `attempt_2/VN30F1M_dnse.csv` and `attempt_2/VN30F1M_corrected.csv`
  (DNSE with both correction files applied, 2018-09-25 to 2026-10-30).

- **DNSE:** `attempt_2/VN30F1M_dnse.csv`. Built from every DNSE raw download in
  `$DATA_ROOT/raw/vietnam/dnse/`, with the 11:30 and 14:30 records merged into
  the preceding minute by the pipeline function `_normalize_boundary_bars`
  (`src/market_data/sources/dnse/transform.py`). No Mirae bars. Every bar lies
  on the 241-minute grid (09:00-11:29, 13:00-14:29, 14:45). On days with 241
  bars it is identical to the catalog.
- **Exchange:** `vn30f1m_hnx.csv`, column `volume`: matched volume per day,
  put-through excluded.
- **Brokers:** `bars/*.csv`, with 11:30 and 14:30 merged by the same rule.
  `bars/dnse.csv` is DNSE's own raw download, identical to the DNSE raw data,
  and is not used as a broker.

## Step 1: missing days and missing bars

Compared with the exchange trading calendar, 2018-08-13 to 2026-10-30
(2,052 trading days):
- 1,740 days with 241 bars;
- 182 days with fewer than 241 bars (`partial_bars`);
- 130 days with no DNSE bar (`no_bars`).

Every DNSE day is an exchange trading day. The two lists are in
`attempt_2/VN30F1M_dnse_missing_days.json`.

From 2022-01-01 to 2026-10-30 (1,201 trading days): 1,066 days with 241
bars, 9 with missing bars, 126 with no bar.

`attempt_2/VN30F1M_missing.csv` holds the 312 days, 241 rows per day: DNSE
values where DNSE has a bar, empty otherwise.

## Step 2: classification rule for days with missing bars

### Day

Compare DNSE daily volume with the exchange:
- **DNSE matches the exchange:** no volume is lost.
- **DNSE below the exchange, with a reference broker:** at least one broker's
  daily volume equals the exchange.
- **DNSE below the exchange, without a reference broker.**
- **DNSE above the exchange.**

A reference broker is a broker whose daily volume equals the exchange. The
last two cases are decided day by day.

### Minute

For each minute DNSE misses, using the reference brokers:
- **No trade published:** the reference broker has no bar either. Not filled.
- **Volume shifted by DNSE:** the reference broker has the bar, and a
  neighbouring DNSE bar holds that volume on top of its own.
- **Lost by DNSE:** the reference broker has the bar, and the volume of these
  minutes equals the DNSE daily shortfall.

### Daily volume threshold: 0 contracts

The threshold separates "DNSE lost volume" from "DNSE lost nothing", so it
must lie above the normal DNSE-to-exchange gap and below the volume of the
smallest real bar. Both were measured from 2022-01-01 to 2026-10-30:
- Normal gap, on the 1,066 days with 241 bars (no bar can be missing): 1,050
  days differ from the exchange by exactly 0 contracts. The other 16 days are
  isolated errors grouped in time, not spread noise; they belong to Correct.
- Smallest real bar: 1 contract.

The two do not overlap, so the threshold is 0.

### Minute volume

With only 9 days in scope, no minute-level threshold is set. Each day is
checked directly against the reference brokers. Where reference brokers
differ on a minute, the majority value is used.

## Step 3: results, 2022-01-01 to 2026-10-30

| Day | DNSE vs exchange | Finding | Action |
|---|---|---|---|
| 2022-01-21 | equal | No reference broker; DNSE matches the exchange, so no volume is lost. Mirae also lacks 09:46-10:03. | Not filled |
| 2023-11-29 | equal | DNSE shifted 11:06-11:07 into 11:05 and 11:08. Reference: Mirae. | Fill 2 bars, replace 2 |
| 2023-12-26 | equal | 09:00 missing in the reference brokers too. | Not filled |
| 2024-09-19 | +33,362 | DNSE shifted 10:10-10:17 into 10:18, and 10:18 carries 33,362 extra contracts. | Moved to Correct |
| 2024-12-23 | equal | DNSE shifted 09:00-09:07 into 09:08. | Fill 8 bars, replace 1 |
| 2025-01-02 | equal | DNSE shifted the 16 traded minutes of 09:10-09:34 into 09:35. 09:00-09:09, 09:11 and 09:22-09:29 missing in the reference brokers too. | Fill 16 bars, replace 1 |
| 2025-04-10 | -1 | 14:01 (1 contract) lost by DNSE. The other 108 minutes missing in the reference brokers too. | Fill 1 bar |
| 2025-06-19 | equal | DNSE shifted 13:57-13:59 into 13:56 and 14:00. | Fill 3 bars, replace 2 |
| 2025-08-25 | -3,924 | 11:29, 13:01, 13:03 lost by DNSE; their volume is exactly 3,924. | Fill 3 bars |

Shifting is specific to DNSE: on the shifted days every other broker has the
shifted minutes, except BSC, which lacks one of the two on 2023-11-29.

Shifted volume is moved back to its minute rather than kept as the feed
publishes it: research data must reflect the trades, and a feed that
publishes wrong data is a reason to change the feed.

## Correction output

- `attempt_2/VN30F1M_missing.csv`: 33 filled bars on 6 days, values from the
  reference broker majority.
- `attempt_2/VN30F1M_wrong.csv`: 6 bars replaced (`action = replace`) on the 4
  shifted days, values from the reference broker majority.
- `attempt_2/VN30F1M_dnse_correct_days.json`: days for Correct; holds
  2024-09-19.

## Check

DNSE bars with both files applied, per day:

| Day | Bars | Daily volume minus exchange |
|---|---|---|
| 2022-01-21 | 223 | 0 |
| 2023-11-29 | 241 | 0 |
| 2023-12-26 | 240 | 0 |
| 2024-12-23 | 241 | 0 |
| 2025-01-02 | 222 | 0 |
| 2025-04-10 | 133 | 0 |
| 2025-06-19 | 241 | 0 |
| 2025-08-25 | 241 | 0 |

Every remaining missing minute is one in which the exchange published no
trade: daily volume equals the exchange, and the reference brokers have no
bar there.

## Step 4: fill days with no DNSE bar, 2022-01-01 to 2026-10-30

126 days have no DNSE bar. On 109 of them at least one broker's daily volume
equals the exchange; on the other 17 (2023-03-24 to 2023-05-04) none does.
This step fills the 109.

### Rule

- The day is filled whole from the reference brokers. A minute the reference
  brokers have no bar for is not filled: daily volume already equals the
  exchange, so no trade is missing there.
- With several reference brokers, each field (open, high, low, close,
  volume) takes the majority value.
- HSC is excluded from 2023-08-18 to 2023-09-08: its prices are about 1,200
  points below the exchange on every day of that period (close on 2023-08-18:
  1,186.8 below), while its volume matches.

### Daily price threshold: 1 point

Measured on the 1,066 DNSE days with 241 bars, 2022-01-01 to 2026-10-30:
the daily close always equals the exchange, while open, high and low often
differ from it by up to 1 point. The gaps form a continuous spread, so no
separating value exists as for volume. A filled day whose daily open, high,
low or close differs from the exchange by more than 1 point is reviewed.

10 days exceed it, all in 2023: 04-03, 04-05, 05-16, 06-09, 06-12, 06-16,
08-18, 08-23, 09-11, 09-20. On each, every broker with data shows the same
gap, BSC included, which is independent of Mirae and SHS. The gap is in the
published feed, so these days are filled the same way (attempt 1, rule 3).

### Sources

- 2023-03-22 to 2023-09-21: Mirae and SHS, whose bars are identical; Mirae
  alone on 2023-05-05.
- 2024-03-05 to 2024-03-14: majority of BSC, Mirae and Vietcap, plus HSC on
  2024-03-14. On 2024-03-14 14:07, BSC differs on open and HSC on volume;
  each field takes the value 3 of the 4 brokers report (open 1260.1, volume
  2,193).

Nearly all 2023 fills rest on one source, Mirae/SHS, supported by daily
volume equal to the exchange and daily prices within 1 point or shared by
every broker.

### Check

- `attempt_2/VN30F1M_missing.csv` holds the filled bars of the 109 days.
- Daily volume equals the exchange on all 109 days.
- Daily price is within 1 point on 99 days; the other 10 are the days above.
- 108 days have 241 bars. 2023-06-28 has 240: 09:01 is absent from Mirae
  and SHS, and daily volume equals the exchange, so no trade is missing.

## Step 5: fill days with no DNSE bar and no reference broker

17 days, 2023-03-24 to 2023-05-04. Only two sources have data:
- BSC: daily volume above the exchange by thousands of contracts every day.
  Not used.
- Mirae/SHS (identical bars): daily volume within 0.41% of the exchange;
  daily price within 1 point except 2023-04-19 (1.2 points). On 2023-04-13
  every broker's ATC volume exceeds the exchange by the same 7,297 contracts,
  which is the published feed value (attempt 1, rule 3), not counted against
  Mirae.

The minute holding Mirae's volume gap cannot be identified, so no bar can be
adjusted. Leaving the days empty would break the requirement that data from
2022-01-01 has no missing days.

**Decision:** the 17 days are filled whole from Mirae/SHS, accepting a daily
volume gap of up to 0.41%. **Their daily volume does not match the exchange
exactly.**

**Check:** all 17 days have 241 bars in `attempt_2/VN30F1M_missing.csv`.

## Step 6: correct, scope

Days from 2022-01-01 to 2026-10-30 whose DNSE daily aggregate differs from
the exchange: daily volume not equal (16 days with 241 bars), or daily open,
high or low more than 1 point away (61 days with 241 bars), plus 2024-09-19.
The lists are in `attempt_2/VN30F1M_dnse_correct_days.json`.

**Bar-level comparison was not used to widen the scope.** Comparing each
DNSE bar with the broker majority at a zero threshold flags 417 of 1,066
days. Brokers split into groups at minute level: in about half of the
mismatches another broker reports the DNSE value, mostly MBS, Vietstock or
VPS. Minute-level majority is therefore not a ground truth, and days that
match the exchange are left as they are.

**55 days need no correction.** All differ from the exchange in price only
(1.1 to 16.7 points); volume matches. On 29 of them DNSE equals the majority
of three or more independent sources on every bar. On the other 26
(2022-04-27 to 2023-03-10) only Mirae/SHS and BSC have data: Mirae/SHS equals
DNSE on every bar, and BSC's daily price is never closer to the exchange.
The intraday data the exchange publishes differs from its own daily report
on these days; the feed values are kept.

**22 days remain:** 15 with a volume gap, 5 with a price gap, 1 with both,
and 2024-09-19.

## Correction: 2024-09-19

- **Finding:** DNSE misses 10:10-10:17 and puts their volume, 10 contracts of
  10:09 and 33,362 extra contracts into 10:18 (35,684 contracts). BSC, Mirae,
  PHS and SHS match the exchange daily volume and equal DNSE on every other
  minute.
- **Correction:** 10:10-10:17 filled in `VN30F1M_missing.csv`; 10:09 and
  10:18 replaced in `VN30F1M_wrong.csv` (10:09: high and close 1314.8, volume
  84; 10:18: volume 233). Values from the majority of the four brokers.
- **Check:** 241 bars; daily volume equals the exchange.

## Correction: 2022-12-27

- **Finding:** DNSE daily volume is 829 below the exchange; daily low is 1.4
  points above it. DNSE bars 09:35 and 09:59 miss trades (volume 322 and 507
  short, low and close differ); Mirae/SHS, whose daily volume equals the
  exchange, and BSC agree on their prices. The low of 983.5 is in DNSE,
  Mirae/SHS and BSC alike, against 982.1 at the exchange.
- **Correction:** 09:35 and 09:59 replaced in `VN30F1M_wrong.csv` with the
  Mirae/SHS bars (09:35: low 990.0, close 990.0, volume 534; 09:59: low
  989.5, close 990.4, volume 864). The low gap is kept, as on the 55 days.
- **Check:** daily volume equals the exchange; prices equal Mirae/SHS on every
  minute.

## Correction: volume-gap days without a reference broker

On 2022-02-22 and 2022-03-02 only DNSE and Mirae/SHS have data, and neither
matches the exchange daily volume. **Rule:** keep the source whose daily
volume is closer to the exchange. This is a best choice, not a proven
correction: the closer daily total does not show which minute is right.
- 2022-02-22: DNSE 3 below, Mirae/SHS 45 below. DNSE kept.
- 2022-03-02: DNSE 93 below, Mirae/SHS 55 below. The 6 bars where they
  differ (09:15, 09:16, 09:17, 09:25, 09:26, 09:29) are replaced with
  Mirae/SHS in `VN30F1M_wrong.csv`. Daily volume is 55 below the exchange.

## Correction: volume-gap days with a reference broker, 13 days

- **Days:** 2022-11-17, 2022-11-18, 2022-11-21, 2022-11-28, 2022-11-29,
  2022-11-30, 2022-12-01, 2023-02-22, 2023-03-31 (reference: Mirae/SHS);
  2023-12-29 (Mirae); 2025-05-05, 2025-06-23, 2025-09-18 (two or three of
  BSC, HSC, SHS, Vietcap).
- **Finding:** DNSE differs from the reference brokers on 1 to 33 minutes a
  day, mostly between 09:15 and 09:30 in late 2022.
- **Correction:** each such bar is replaced whole (open, high, low, close,
  volume) with the reference broker majority in `VN30F1M_wrong.csv`; every
  field had a majority.
- **Check:** daily volume equals the exchange on all 13 days; no daily price
  moves further from the exchange, and all are within 1 point.

## Decision: price-gap days shared by every broker, 5 days

2022-01-18 (low +1.3), 2022-04-19 (low +1.1), 2022-05-13 (high -1.1),
2022-06-03 (high -2.0), 2022-12-20 (low +1.1). Every broker with data has
the same daily gap as DNSE; BSC on 2022-05-13 is further away, in a month
excluded for BSC price errors. No source is closer to the exchange, so the
gap is in the data the exchange publishes intraday, as on the 55 days. Not
corrected.

## Before 2022-01-01: fill days with missing bars

From 2018-08-13 to 2021-12-31 (851 trading days) DNSE has 674 days with 241
bars, 173 with missing bars and 4 with no bar. The only other sources are
Mirae/SHS from 2018-09-25 and VNDirect from 2021-11-05.

Of the 173 days, 144 have DNSE daily volume below the exchange and no
reference broker. 138 of them miss the 09:00 bar, and 134 miss only that
bar.

### The 134 days missing only 09:00

- **Finding:** on every one of the 138 days the DNSE shortfall exceeds the
  exchange ATO volume, typically by 100 to 1,000 contracts: DNSE lacks the
  whole 09:00 bar (ATO match and the first minute of continuous trading), not
  only the ATO. Mirae's 09:00 volume is unusable: it is below the exchange
  ATO volume on 100 of 137 days, and never equals the shortfall. Mirae's
  09:00 prices are consistent: its close is within 1 point of the DNSE 09:01
  open on 134 of 137 days, and its open is within 1 point of the exchange
  ATO price on 131 of the 134 days.
- **Fill** (`VN30F1M_missing.csv`): the 09:00 bar takes open, high, low and
  close from Mirae and volume equal to the exchange daily volume minus the
  DNSE daily volume. Mirae's open is kept on the 3 days it differs from the
  ATO price by more than 1 point: 2020-08-04 (-2.0), 2020-09-08 (-1.3),
  2021-01-29 (+4.0). **No minute feed confirms this volume.**
- **Check:** 241 bars and daily volume equal to the exchange on all 134 days.
  Daily price is more than 1 point from the exchange on 6 days: the 3 open
  gaps above, and low gaps on 2021-01-20 (+2.7), 2021-02-04 (+1.5) and
  2021-03-26 (+1.1).

### 2021-01-28

- **Finding:** DNSE misses 09:00 and 44 minutes between 13:10 and 14:24, and
  is 4,938 contracts below the exchange; its daily open and high are 5.0 and
  2.3 points below. The close, 1006.5, is the exchange floor price, and
  Mirae also has no bar in the 44 afternoon minutes: no trade there. Mirae's
  09:00 bar has open and high 1050.0, the exchange daily open and high.
- **Fill:** 09:00 with Mirae's prices (1050.0, 1050.0, 1044.0, 1044.0) and
  volume 4,938, the exchange daily volume minus DNSE, as for the 134 days.
  The 44 afternoon minutes are not filled.
- **Check:** daily volume, open, high, low and close equal the exchange; 197
  bars.

### 2019-12-19 and 2020-10-21

- **2019-12-19:** DNSE misses 09:00, 10:38, 10:47 and 10:49, 541 below the
  exchange. Mirae has 09:00 and no bar at the other three: no trade there.
  09:00 is filled with Mirae's prices and volume 541.
- **2020-10-21:** DNSE misses 09:00 and 13:00, 1,629 below the exchange.
  13:00 is filled with Mirae's bar (656). 09:00 takes Mirae's prices and the
  remaining volume, 973.
- **Check:** daily volume equals the exchange on both days; daily price is
  within 1 point.

### 2020-11-13

- **Finding:** DNSE misses 09:00 to 09:10; Mirae and SHS (identical) miss
  09:00 to 09:09 and have 09:10 (40 contracts). Both sources are 1,782
  contracts below the exchange in 09:00 to 09:09, which holds the ATO match
  (634): the trades happened, but the exchange published no intraday data
  for them.
- **Fill:** 09:10 with Mirae's bar. 09:00 to 09:09 are left empty, as on
  the days whose gap is in the data the exchange publishes.
- **Check:** daily volume is 1,782 below the exchange, 1.98% of its 90,068.

### 6 no-reference days that keep 09:00

On each, the DNSE shortfall equals the volume of the bars DNSE lost.
- **2018-08-13, 2018-10-18, 2018-11-08:** DNSE misses the 14:45 ATC bar; the
  shortfall equals the exchange ATC volume (2,214, 1,238, 4,052). 2018-10-18
  and 2018-11-08 are filled with Mirae's 14:45 bar, which matches the
  exchange close and ATC volume. 2018-08-13 has no Mirae data; the ATC is a
  single match, so the bar is built from the exchange: open, high, low and
  close 953.0 (the exchange close), volume 2,214.
- **2019-12-23:** 09:30 filled with Mirae (130). 65 contracts (0.085% of
  76,689) remain below the exchange, spread over minutes where DNSE and
  Mirae differ both ways; accepted.
- **2021-03-10:** 13:33 filled and 13:32 replaced with Mirae.
- **2021-05-13:** 13:02 and 13:03 filled and 13:01 replaced with Mirae.
- **Check:** 241 bars on all 6 days; daily volume equals the exchange except
  2019-12-23 (-65). Daily open on 2021-05-13 is 1.9 points from the exchange,
  from the DNSE 09:00 bar, not from these fixes.

### The other 29 days with missing bars

- **13 days, no fix:** DNSE daily volume equals the exchange and the missing
  minutes are absent from Mirae too (no Mirae data on 2018-08-28 and
  2018-08-29): no trade.
- **4 days with a reference broker** (2018-10-25, 2019-03-12, 2019-05-08,
  2019-05-13): missing bars filled with Mirae, whose daily volume equals the
  exchange. 2019-05-08 stays 435 contracts below (0.48% of 91,122).
- **5 days where DNSE moved a minute's volume into a neighbour bar:**
  2020-03-23, 2020-04-06, 2020-05-12, 2020-05-28 (the 14:45 ATC volume into
  14:29), 2018-10-01 (10:33 into 10:34, 10:50 into 10:51). The missing bar
  is filled with Mirae's bar, which matches the exchange close and ATC
  volume, and that volume is taken out of the neighbour bar (wrong file);
  neighbour prices are unchanged. Whole neighbour bars are not copied from
  Mirae, because in this period Mirae differs from DNSE on over 100 minutes
  a day for unrelated reasons. Exception: on 2020-05-28 the DNSE 14:29 high
  and close are the ATC price (790.0); they are set to Mirae's 784.0.
- **Check:** 241 bars on all 9 days; daily volume equals the exchange except
  2019-05-08.
- **2020-07-28 and 2020-06-05:** DNSE has no 09:00 bar and lumps the opening
  minutes into 09:01 at a flat price (20,190 contracts at 726.9 on
  2020-07-28, while Mirae shows the price rising from 716 to 727; 2,062 at
  813.4 on 2020-06-05). The opening bars are taken from Mirae: 09:00 to
  09:10 on 2020-07-28, with 4,526 contracts added to 09:00 (exchange ATO
  4,441 plus 85, which Mirae lacks) and Mirae's open 716.0 kept (1 point from
  the ATO price); 09:00 to 09:03 on 2020-06-05. Daily volume equals the
  exchange on 2020-07-28 and is 1 contract below on 2020-06-05.
- **5 days with DNSE above the exchange:** the excess sits in a few DNSE
  bars, and Mirae plus the exchange ATO accounts for it exactly.
  - 2020-07-13 (+119,655): 10:06 and 14:45 filled; 10:07, 11:29 and 13:00
    replaced (10:07 and 13:00 carry 33,822 and 91,142 extra contracts).
  - 2020-07-15 (+80,468): 14:28, 14:29 and 14:45 filled; 11:10 and 11:11
    replaced (11:11 carries 85,479 extra).
  - 2021-06-22 (+1,280): DNSE moved 09:00-09:03 into 09:04 and its 14:45 is
    840 above the exchange ATC. 09:00-09:03 filled from Mirae with 1,348
    added to 09:00 (the ATO Mirae lacks); 09:04 and 14:45 replaced.
  - 2021-08-04 (+514): 09:12, 09:14 and 14:29 replaced; 10:20 and 10:21
    are absent from Mirae too (no trade).
  - 2021-08-09 (+315): 14:29 and 14:45 replaced; 11:16-11:28 absent from
    Mirae too (no trade).
  - Values from Mirae. Prices change on three replaced bars, by at most 1.9
    points: 14:29 on 2021-08-04 and 2021-08-09, 09:04 on 2021-06-22.
  - **Check:** daily volume equals the exchange on all 5 days.

### 4 days with no DNSE bar

Mirae/SHS (identical) has 241 bars on each; daily price within 1 point.
- 2020-07-16, 2020-07-17, 2020-07-20: Mirae is below the exchange by its
  ATO plus a few contracts (640, 1,570, 951). Filled from Mirae with the
  gap added to 09:00; daily volume equals the exchange.
- 2018-10-19: Mirae's 09:00 already holds the ATO; it is 234 contracts
  (0.2% of 116,399) below the exchange with no minute to place them.
  Filled from Mirae; the gap is accepted.

## Before 2022-01-01: correct days with 241 bars

Of 674 days with 241 DNSE bars, 124 differ from the exchange: 96 in daily
volume, 35 in daily price beyond 1 point, 7 in both. The 96 volume days:
- 71 days (70 in 2021-02 to 2021-08, plus 2020-07-30): DNSE is above the
  exchange by exactly the exchange put-through volume (median 0.21% of the
  day, at most 1.21%);
- 12 days in 2019: DNSE volume about ten times the exchange (attempt 1);
- 13 other days.

### Put-through volume in DNSE bars, 71 days

- **Finding:** in this period the DNSE feed counted put-through trades in its
  1-minute bars. Put-through trades run through the session, 08:45-11:30
  and 13:00-14:45 (KBSV and DNSE trading rules; the DNSE KRX notes state
  derivatives hours did not change with KRX), so the volume lands in bars
  from 09:00 to 14:45. Mirae lacks the put-through volume where it can be
  located, and DNSE excludes it on 128 other pre-2022 days with put-through
  and on every day from 2022: the cause is the DNSE feed, not the exchange.
- **21 days corrected:** all put-through volume located: in 14:45 as the
  excess over the exchange ATC volume, elsewhere as the excess over Mirae.
  It is removed from 34 bars (`VN30F1M_wrong.csv`). On 8 of them the
  put-through price had also changed the bar's prices; those take Mirae's
  prices (on the three 14:45 bars Mirae equals the exchange ATC price).
  Daily volume equals the exchange; no daily price moves further from it.
- **50 days without full location.** Mirae's prices equal DNSE on all but a
  few minutes a day; Mirae lacks the ATO and part of the opening minute.
  - 35 days: Mirae with the exchange ATO added to 09:00 is closer to the
    exchange than DNSE. Bars where Mirae differs from DNSE are replaced in
    `VN30F1M_wrong.csv`. The 09:00 bar keeps DNSE's prices, because DNSE's
    open is the exchange ATO price and Mirae's is not; its volume is
    Mirae's plus the ATO. 2021-06-28 14:29 keeps DNSE (equal volume, and
    DNSE's high is the exchange daily high). Against DNSE, daily volume is
    closer on 34 days and equal on 1; daily price is unchanged on 34 days
    and closer on 1. Not exact.
  - 15 days DNSE kept: 14, mostly 2021-08, where Mirae plus ATO is further
    from the exchange (0.32% to 1.15%) than DNSE (0.05% to 0.24% above),
    likely because Mirae's 09:00 already holds the ATO; and 2021-06-04,
    where Mirae lacks a minute and the replacement moved further away.

### DNSE volume about ten times the exchange, 12 days in 2019

- **Days:** 2019-03-26, 03-27, 03-28, 03-29, 04-11, 04-12, 04-17, 04-18,
  05-10, 05-30, 07-11, 07-16. DNSE daily volume is 6.6 to 14.7 times the
  exchange.
- **Correction** (`VN30F1M_wrong.csv`, 2,883 bars): every bar's volume
  takes Mirae's; prices keep DNSE. DNSE and Mirae daily prices have the same
  gap to the exchange (under 0.5 points) on all 12 days, and their minute
  prices differ by at most 0.9 points, with no evidence for either.
- **Check:** daily volume equals the exchange on 10 days; 182 and 65
  contracts below on 2019-07-11 and 2019-07-16.

### The other 13 volume-gap days

Daily price is within 1 point on all 13.
- **2020-07-03, 2020-07-09, 2020-07-14:** one DNSE bar each (14:23, 13:27,
  13:44) carries over 100,000 extra contracts against a few hundred to 1,000
  in Mirae. Its volume takes Mirae's; prices kept. Daily volume after: -19,
  +44, -158.
- **2021-02-26, 2021-03-16, 2021-07-13, 2021-07-14:** taken from Mirae with
  the exchange ATO added to 09:00 and 09:00 prices from DNSE, as for the 35
  put-through days. Daily volume after: -30, -10, -80, -1 (DNSE was off by
  378 to 1,218).
- **Not corrected:** 2019-06-03, 2019-07-29, 2019-07-30, 2019-08-01,
  2019-11-12 (at most 19 contracts off), and 2018-09-10 (DNSE 2.03% above,
  no other source).

### Price-gap days

From 2018-09-25, 35 days with 241 DNSE bars have a daily open, high or low
more than 1 point from the exchange; 33 remain after the volume corrections.
- **28 days not corrected:** Mirae has the same daily gap as DNSE, so the
  gap is in the data the exchange publishes intraday, as on the 55 days
  after 2022.
- **2020-03-16 and 2021-04-29:** the DNSE 14:29 bar sets a daily extreme
  Mirae does not have (low 666.0 against 671.8; high 1320.0 against
  1304.1), with equal volume. Prices from Mirae; daily price then within 1
  point.
- **2020-05-04:** DNSE's 09:00 open is 682.0 against the exchange 680.1;
  Mirae's is 680.0 and is used. The 1.9-point low gap is shared with Mirae
  and kept.
- **2020-05-29 and 2021-10-20:** DNSE kept; Mirae is further from the
  exchange.
- Found in the full check (days with missing bars, outside the step above):
  - 2020-06-05 14:29: DNSE high and close 838.3, above the exchange daily
    high 825.0; set to Mirae's 820.5.
  - 2021-05-13 09:00: DNSE open 1377.9; the exchange and Mirae have 1376.0,
    which is used.
  - 2020-04-06 09:00: DNSE open 638.0 against the exchange 639.9; Mirae
    (636.3) is further; DNSE kept.

## Full check, 2018-09-25 to 2026-10-30

DNSE with `VN30F1M_missing.csv` and `VN30F1M_wrong.csv` applied, 2,022
trading days:
- Bars: every day has data; 2,001 days have 241 bars, 21 fewer, each
  missing only minutes without a trade.
- Volume: 1,935 days equal the exchange. Each of the other 87 is a gap
  recorded above.
- Price: days more than 1 point from the exchange either share the gap with
  a broker (the exchange intraday data) or are kept by a decision above
  (2020-04-06, 2020-05-29, 2021-10-20).

## Decision: start date

The dataset starts on **2018-09-25**, the first day with Mirae data. Before
it DNSE has no source to compare with (2018-09-10, for example, is 2.03%
above the exchange with no way to check).

## Open

- Apply `VN30F1M_missing.csv` and `VN30F1M_wrong.csv` to the data
  researchers use, from 2018-09-25.
- The two pipeline changes in "Why a second attempt".
