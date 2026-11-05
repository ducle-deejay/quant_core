# VN30F1M 1-minute bar correction report

## Scope

This report records how the VN30F1M 1-minute bars in the catalog
(`VN30F1M.HNX-1-MINUTE-LAST-EXTERNAL`) were checked for wrong values, and
what was corrected. Each step lists its inputs, method, and results.

## Root causes

**1. The Mirae backfill rule.** When DNSE lacks even one bar of a day and
Mirae has all 241, the whole day is replaced with Mirae
(`src/market_data/sources/mirae/load.py`, `_select_day_bars`). Mirae's own
errors then enter the catalog:
- missing ATO match, 108 days in 2019 to 2021: DNSE often has no 09:00 bar
  (it puts the opening volume in 09:01), the day is replaced with Mirae, and
  Mirae's 09:00 bar lacks the ATO match, so daily volume is short by the ATO
  volume and the open is not the ATO price;
- F2M in place of F1M on an expiry day: 2025-06-19;
- the previous session duplicated onto a holiday: 2022-01-03 holds
  2021-12-31.

**2. Errors in DNSE data.**
- Volume about 10 times the exchange on 12 days in 2019; the reason is not
  identified.
- Isolated bars whose price or volume differs from every other source, on
  about 128 days, mostly 1 to 5 bars a day; for example high 1320.0 at 14:29
  on 2021-04-29.

Not errors, and not corrected: minutes without trades, and gaps to the
exchange that every broker feed shares, because the live feed receives the
same values.

## Agreed rules

1. A deviation counts as an error only when it exceeds an agreed threshold.
   Exact equality is not required.
2. The exchange (HNX) daily results are the reference: daily open, high,
   low, close, matched volume per session (ATO, continuous, ATC), and the
   trading calendar.
3. When every broker reports the same value, that value is what the exchange
   feed published, and the live feed receives the same value. It is not
   corrected.
4. Only bars and fields with evidence from a source are corrected. Bars within
   the threshold are not touched.
5. The catalog is not overwritten. Corrected bars are written to
   `VN30F1M_wrong.csv`.
6. Each correction method is approved before it is applied.

## Data

- **Catalog:** 1-minute bars, 2018-08-13 to 2026-11-04.
- **Missing-data result:** `VN30F1M_missing.csv`. Bars filled there are
  overlaid on the catalog before every comparison in this report.
- **Exchange daily:** `vn30f1m_hnx.csv`, built from the HNX daily trading
  results (`hnx_1d.csv`). One row per trading day for the front contract.
  On an expiry day the front contract is the contract expiring that day.
- **Brokers:** 1-minute bars from 15 brokers, one CSV per broker.

## Step 1: compare catalog daily aggregates with the exchange

### Method

- Aggregate the catalog's 1-minute bars per trading day:
  - open: first bar's open
  - high: highest high
  - low: lowest low
  - close: close of the last bar, the 14:45 ATC bar
- Compare each day with the exchange daily row:
  - open, high, low, close
  - volume before 14:45 against ATO + continuous volume
  - volume of the 14:45 bar against ATC volume
  - total volume against total matched volume
  - whether the 09:00 bar volume is lower than the ATO volume
- Trading calendar: catalog days that the exchange does not list, and
  exchange days missing from the catalog.
- Expiry days: the day the front contract changes. Compare the catalog close
  with the closes of the expiring contract and of the next contract.
- Period: 2053 trading days, 2018-08-13 to 2026-11-02, the last day in the
  exchange file. 2026-11-03 and 2026-11-04 are not compared.

### Results

**Trading calendar**
- 2022-01-03 is in the catalog but not in the exchange calendar. It is a
  non-trading day.
- No exchange trading day is missing from the catalog.

**Expiry days**
- 99 expiry days checked.
- 1 day uses the wrong contract: on 2025-06-19 the catalog close is 1424.0,
  the close of the next contract. The expiring contract closed at 1440.8.

**Price deviation, number of days by absolute difference in points**

| Field | = 0 | (0, 0.1] | (0.1, 0.5] | (0.5, 1] | (1, 5] | > 5 |
|---|---|---|---|---|---|---|
| open | 1394 | 213 | 327 | 87 | 28 | 4 |
| high | 1077 | 420 | 447 | 80 | 24 | 5 |
| low | 1061 | 349 | 478 | 100 | 55 | 10 |
| close | 2052 | 0 | 0 | 0 | 0 | 1 |

**Volume deviation, number of days by absolute difference in contracts**

| Field | = 0 | (0, 10] | (10, 100] | (100, 1000] | (1000, 5000] | > 5000 |
|---|---|---|---|---|---|---|
| before 14:45 vs ATO + continuous | 1737 | 41 | 53 | 118 | 84 | 20 |
| 14:45 bar vs ATC | 1968 | 6 | 33 | 39 | 4 | 3 |
| total | 1762 | 35 | 24 | 118 | 92 | 22 |

- On 114 days the 09:00 bar volume is lower than the ATO volume.
- Every day has a 14:45 bar.

**Deviation by period, number of days with a non-zero difference**

| Period | Days | open | high | low | close | total volume |
|---|---|---|---|---|---|---|
| 2018-08-13 to 2025-05-04 | 1677 | 656 | 975 | 991 | 0 | 285 |
| 2025-05-05 to 2026-11-02 | 376 | 3 | 1 | 1 | 1 | 6 |

**Days with a price deviation above 5 points**
- open: 2018-10-11 (+7.0), 2022-06-02 (+7.0), 2026-06-23 (+1984.7),
  2026-10-09 (+1881.1)
  - On 2026-06-23 and 2026-10-09 the exchange file has open = 0, so these
    two deviations come from the exchange file, not the catalog.
- high: 2020-03-13 (−9.1), 2021-04-29 (+15.0), 2022-10-07 (−5.5),
  2023-06-12 (−41.0), 2025-06-19 (−15.1)
- low: 2020-05-08 (+6.9), 2021-02-24 (+5.3), 2021-06-08 (+12.0),
  2021-10-20 (+29.0), 2021-12-16 (+29.7), 2022-11-08 (+5.1),
  2023-02-24 (+5.4), 2023-09-11 (+16.0), 2025-04-04 (+16.7),
  2025-06-19 (−7.3)
- close: 2025-06-19 (−16.8)

**Days with a total volume deviation above 5000 contracts**
- 2019: 03-26 (+1,699,670), 03-27 (+1,309,474), 03-28 (+1,168,864),
  03-29 (+1,348,817), 04-11 (+1,076,673), 04-12 (+666,359),
  04-17 (+387,867), 04-18 (+215,836), 05-10 (+525,202), 05-30 (+496,759),
  07-11 (+860,647), 07-16 (+606,950)
- 2020: 07-03 (+158,544), 07-09 (+126,281), 07-14 (+140,197),
  07-15 (−6,230)
- 2023: 03-31 (−14,101), 04-13 (+7,737)
- 2025: 01-02 (+6,101), 06-19 (−124,457), 06-23 (+9,622), 07-21 (+6,411)

A positive difference means the catalog is higher than the exchange.

### Artifacts

- `step1_catalog_vs_hnx_daily.csv`: per-day differences for every field.
- `step1_expiry_days.csv`: catalog close against both contracts on each
  expiry day.

## Step 2: error thresholds

### Rule

- A bar is wrong when the catalog value differs from the value most brokers
  report for the same minute by more than the threshold below.
- The exchange publishes no per-minute data. Its daily data is used only to
  select the days checked in Step 3.
- Thresholds, applied per bar:
  - **Price** (open, high, low, close): 0.3 points.
  - **Volume:** 18% of the bar's volume.

### How a bar error reaches a signal

A feature computed from a wrong bar equals the true feature plus noise:

```
x' = x + e
x  : feature from correct bars, standard deviation σ_x
e  : error from the wrong bar, standard deviation σ_e, independent of x
```

From the definition of correlation:

```
cov(x, x')  = cov(x, x) + cov(x, e) = σ_x^2 + 0 = σ_x^2
var(x')     = σ_x^2 + σ_e^2

corr(x, x') = cov(x, x') / (σ_x * sqrt(σ_x^2 + σ_e^2))
            = σ_x / sqrt(σ_x^2 + σ_e^2)
            = 1 / sqrt(1 + ratio^2),   ratio = σ_e / σ_x
```

If the noise is also independent of the forward return, the information
coefficient (IC, the correlation between a feature and the forward return)
scales by the same factor:

```
IC_noisy = IC_clean × corr(x, x')
IC lost  = 1 - corr(x, x')
```

```
ratio   corr                         IC lost on wrong bars
0.10    1 / sqrt(1.01)   = 0.995     0.5%
0.25    1 / sqrt(1.0625) = 0.970     3%
0.50    1 / sqrt(1.25)   = 0.894     11%
1.00    1 / sqrt(2)      = 0.707     29%
```

Example: a feature with IC_clean = 0.05 keeps 0.05 × 0.970 = 0.0485 on
the wrong bars when ratio = 0.25.

The derivation holds for errors independent of the true value. A systematic
error, such as a high that is always too low, biases the feature instead and
is not covered by this rule.

### Choice of ratio and timeframe

- **Accepted IC loss on wrong bars: 3%, so ratio = 0.25.** The loss over the
  whole dataset is lower, because wrong bars are a small share of all bars.
- **Shortest timeframe: 1 minute.** All timeframes are built from the same
  1-minute bars, so the threshold must hold for the shortest one.
- The ratio is relative to each timeframe's standard deviation, so
  ratio = 0.25 gives corr = 0.970 on every timeframe; only the threshold in
  points changes.

### Standard deviation by timeframe

Measured on catalog bars before 14:45 from 2025-05-05 to 2026-11-04, the
period in which the catalog matches the exchange on almost every day
(Step 1). Price: change of close between consecutive k-minute bars within a
day. Volume: change of log volume between consecutive k-minute bars within a
day.

```
timeframe   σ close change   threshold = 0.25 × σ   corr
1m          1.21             0.30 points            0.970
5m          2.73             0.68 points            0.970
15m         4.39             1.10 points            0.970
30m         6.32             1.58 points            0.970
60m         8.52             2.13 points            0.970
```

```
timeframe   σ log-volume change   threshold = exp(0.25 × σ) - 1
1m          0.672                 18%
5m          0.562                 15%
15m         0.475                 13%
30m         0.458                 12%
60m         0.458                 12%
```

The volume threshold is relative (log volume), not in contracts. 1-minute
volume is strongly right-skewed (the 99th percentile is about 5.6 times the
median from 2025-05-05), volume features are normally built on normalized
volume (log volume, volume over a rolling mean), and the contract count per
minute differs by an order of magnitude between 2019 and today.

Worked example at 1 minute: a close that is 2 points wrong gives
ratio = 2 / 1.21 = 1.66 and corr = 1 / sqrt(1 + 2.75) = 0.52, so the
feature loses 48% of its IC on that bar. The same 2-point error on a
15-minute feature gives ratio = 2 / 4.39 = 0.46 and corr = 0.91.

## Step 3: locate wrong bars

### Majority rule

Applied per minute and per field:

1. Only sources independent of the catalog vote. On a day the catalog takes
   from DNSE, DNSE does not vote; on a day it takes from Mirae, Mirae does
   not vote.
2. Two sources agree when they differ by at most the Step 2 threshold.
3. A majority exists when the agreeing group holds more than half of the
   sources with data for that minute and has at least 2 sources. The
   majority value is the median of the group.
4. Without a majority, or with fewer than 2 independent sources, the bar is
   undetermined and is not corrected.
5. A source with a systematic error in a field does not vote on that field.

### Part 1: source quality (findings, decisions pending)

Method: for each source, field and minute, compare the source with the
median of the other sources that have data for that minute (at least 2), and
count the share of bars that differ by more than the Step 2 threshold.
Result per source, field and month: `step3_source_month_disagreement.csv`.

**Mirae and SHS are not independent.** Their bars are identical on every
field in 100% of shared minutes from 2018 to 2022, 99.43% in 2023 and 98.34%
in 2024. They count as one source until 2024.

**Consequence for 2018-09-25 to 2022-05-03.** Only DNSE and Mirae/SHS have
data. The catalog takes each day from one of them, so one independent source
is left, and rule 4 leaves every bar of this period undetermined.

**Sources with systematic price errors**
- SSI, from its first bar on 2025-07-21: prices are published in thousands
  with 2 decimals (1.64 for 1641.3), a resolution of 10 points; 95.7% of
  bars differ from the other sources. SSI volume agrees with the others.
- HSC, 2023-08-18 to 2023-09-08: prices about 1,200 points below the other
  sources on every bar.
- BSC, 2022-05-04 to 2022-06-01: prices 5 to 78 points away from the other
  sources on every bar.
- Mirae, 2025-05, 2025-06, 2025-08, 2025-09, 2025-11 and 2025-12: on 61 days
  more than half of its bars differ, by a daily median of up to 9 points; for
  example 3 to 7 points below the other sources on every bar from 2025-08-22
  to 2025-09-17.

**Reference level.** SHS, PHS, TCBS and Vietcap differ from the other
sources on at most 0.2% of bars per field over their whole history.

**Proposed exclusion rule (from 2022-05-04, when at least 4 sources have
data).** A source does not vote on a field for a month in which more than
5% of its bars on that field differ from the median of the other sources.
5% is 25 times the reference level. Before 2022-05-04 the median of the
other sources is built from 2 sources, one of which can be the faulty one,
so the rule cannot identify the faulty source there.

### Part 2: vote results

**Session-boundary folding.** The ingest folds the 11:30 and 14:30 broker
records into the 11:29 and 14:29 bars
(`src/market_data/sources/session_boundary.py`). The broker files keep them
as separate bars, so every broker file is folded the same way before any
comparison. Without folding, 602 bar-fields at 11:29 and 14:29 were
flagged; with folding, 100.

**Catalog source per day.** A day is assigned to a source when at least 90%
of its catalog bars are identical to that source.
- DNSE: 1,911 days.
- Mirae: 141 days, of which 123 run from 2023-03-22 to 2023-09-21, when DNSE
  has no data.
- No source: 2026-11-02 to 2026-11-04, after the broker files end.

**Source exclusions applied.** The exclusion rule is applied month by month,
removing the worst source first and recomputing the median of the others,
until no source is above 5%. Removing all sources above 5% at once
excludes good sources in months with few sources, because the faulty source
shifts the median of the others. 129 source-field-months are excluded:
`step3_excluded_source_months.csv`. SHS is not a voter through 2024-12-31
because it duplicates Mirae.

**Arbiter for 2018-09-25 to 2022-05-03.** DNSE and Mirae are scored per day
against the exchange, separately for price and volume:
- price score: 1 point for each of open, high, low and close within 0.3
  points of the exchange;
- volume score: 1 point when total volume is within 1% of the exchange.

When the catalog and the other source differ on a bar beyond the Step 2
threshold, the other source's value is taken only if its score for that
kind of field is higher. A first version used one combined score; it
replaced correct DNSE volume with Mirae volume on days where DNSE volume
matched the exchange and Mirae scored higher on price only (for example
2020-05-14).

**Result**
- Bars checked: 487,790 (2018-08-13 to 2018-09-24 has DNSE only and is not
  checked).
- Wrong: 3,599 bars on 147 days, 4,664 bar-fields:

```
field    arbiter (2018-09-25 to 2022-05-03)   majority (from 2022-05-04)
open     116                                  304
high     27                                   257
low      27                                   255
close    95                                   388
volume   2907                                 288
```

**Undetermined bars** (not corrected, rule 4)
- Arbiter period: 10,585 bars (equal scores, or the other source has no
  bar).
- Majority period: 35,783 bars. 29,643 of them are on the 123 Mirae days
  from 2023-03-22 to 2023-09-21: DNSE has no data and SHS duplicates Mirae,
  so BSC is the only voter.

**Effect of applying the corrections on the daily aggregate.** Wrong price
bars are replaced whole with the bar of one source that agrees with the
majority on all four prices (in the arbiter period, the other source's bar);
wrong volume is replaced with the reference volume. Compared with the
exchange, per day:

```
period     days   volume closer / same / further   OHLC closer / same / further
arbiter    39     16 / 23 / 0                      21 / 18 / 0
majority   108    10 / 96 / 2                      2 / 102 / 4
```

Days moved further from the exchange: price on 2022-05-31, 2022-07-06,
2022-07-15, 2022-08-08; volume on 2025-06-02 and 2026-05-29.

Per-bar votes: `step3_votes.csv`.

## Correction output format

`VN30F1M_wrong.csv` has the catalog bar columns plus two:

- `action`: `replace` (the row holds the corrected bar) or `delete` (the
  catalog bar is removed; price and volume are empty).
- `reason`: why the bar was corrected.

## Correction: 2022-01-03, non-trading day

- **Finding:** the exchange lists no trading on 2022-01-03, the substitute
  holiday for New Year's Day, which fell on Saturday 2022-01-01. The first
  trading day of 2022 is 2022-01-04.
- **Cause:** 99.6% of the catalog's 241 bars on 2022-01-03 are identical to
  the bars at the same minute on 2021-12-31. Mirae and SHS also carry this
  date, so the duplicate entered the catalog through the Mirae backfill.
- **Correction:** all 241 bars of 2022-01-03 are deleted
  (`action = delete`, `reason = non-trading day (exchange calendar)`).

## Correction: 2025-06-19, F2M in place of F1M

- **Finding:** 2025-06-19 is the expiry day of the June contract, so F1M is
  the June contract that day. Every catalog bar holds the July contract
  (F2M): catalog close 1424.0 and volume 21,867 against the exchange's
  F2M close 1424.0 and volume 21,864. The exchange F1M close is 1440.8.
- **Cause:** DNSE has 238 of 241 bars that day. The Mirae backfill replaces a
  whole day when DNSE is incomplete and Mirae is complete
  (`src/market_data/sources/mirae/load.py`, `_select_day_bars`), and Mirae
  holds F2M that day.
- **Correction:** all 241 bars are replaced with Vietcap bars
  (`action = replace`). Vietcap equals the per-bar majority on every field
  of every bar (HSC is identical), and its daily aggregate equals the
  exchange F1M row: open 1428.9, high 1441.0, low 1426.5, close 1440.8,
  matched volume 146,324.

## Correction: 12 days in 2019, DNSE volume

- **Days:** 2019-03-26, 03-27, 03-28, 03-29, 04-11, 04-12, 04-17, 04-18,
  05-10, 05-30, 07-11, 07-16.
- **Finding:** the catalog takes these days from DNSE, and its daily volume
  equals DNSE's: 4.8 to 17 times the exchange per bar (median about 10), for
  example 1,824,155 against 124,485 on 2019-03-26. Mirae's daily volume
  equals the exchange on 10 days and is 182 and 65 contracts lower on
  2019-07-11 and 2019-07-16. The reason DNSE returns this volume is not
  identified.
- **Correction** (`action = replace`, 2,883 bars): the volume of every bar
  except the 14:45 ATC bar, which already matched, is replaced with folded
  Mirae volume. Prices keep the catalog values: DNSE and Mirae have equal
  price scores on all 12 days, so price differences are undetermined. (A
  first version also replaced the price of 56 bars under the combined
  arbiter score; it was reverted.)
- **Check:** corrected daily volume equals the exchange on 10 days and is
  182 and 65 contracts lower on 2019-07-11 and 2019-07-16.

## Correction: remaining wrong bars, 128 days

- **Scope:** the 134 days still holding wrong bars after the corrections
  above (117 with price only, 11 with volume only, 6 with both), minus 6
  days excluded by the daily check below.
- **Method** (`action = replace`, 469 bars):
  - Wrong price: the whole bar's open, high, low and close are taken from
    one source. From 2022-05-04, the source agrees with the majority on all
    four prices; before, it is the other of DNSE and Mirae, which won the
    price arbiter.
  - Wrong volume: from 2022-05-04, the volume of the agreeing source nearest
    the majority median, so volume stays an integer; before, the other
    source's volume, which won the volume arbiter.
  - The `reason` column names the source used for price and for volume.
- **Daily check:** a day is corrected only if its corrected daily aggregate
  is not further from the exchange than the catalog's. Excluded, left as in
  the catalog: price on 2022-05-31, 2022-07-06, 2022-07-15, 2022-08-08
  (voters BSC and Mirae only); volume on 2025-06-02 and 2026-05-29.
- **Result against the exchange, per day:** daily OHLC closer on 22 days and
  unchanged on 106; daily volume closer on 13 days and unchanged on 115; no
  day further. No corrected bar has a high below its open or close or a low
  above them.
- **Voters by period for wrong price:** 2018-09-25 to 2022-05-03, DNSE and
  Mirae (23 days); 2022-05-04 to 2022-12-31, BSC and Mirae (31 days, 4 of
  them excluded above); 2023 and 2024, no day; 2025 and 2026, about 8 to 13
  brokers (69 days).

## Step 6: day-level check after corrections

The catalog with `VN30F1M_missing.csv` and `VN30F1M_wrong.csv` applied is
aggregated per day and compared with the exchange, 2018-08-13 to
2026-11-01 (2,052 trading days). Exchange file values fixed for this check:
open on 2026-06-23 and 2026-10-09 (missing, set to the catalog value) and
volume on 2025-07-21 (260,100).

A day passes when:
- total volume is within 1% of the exchange. The exchange records volume to
  the contract and brokers match it exactly on most days, so a larger gap
  signals an error; and
- open, high, low and close are within 0.3 points of the exchange, or the
  gap is shared by most brokers' daily aggregates, so it is in the published
  feed (rule 3).

A failing day is fixable when some broker's daily value is closer to the
exchange than the catalog's.

**Result after the corrections below:** 2,036 days pass (99.2%); 16 fail
and no broker is closer to the exchange on the failing field, so they are
left as they are:
- price: 2020-02-24, 2020-03-24, 2020-05-29 (open −2.6), 2020-11-10,
  2020-12-03, 2021-01-06, 2021-01-07, 2021-01-20 (low +2.7), 2021-04-26,
  2021-10-20 (low +29.0), 2022-06-02 (open +7.0, low +2.1), 2023-08-22;
  the others are within 1 point;
- volume: 2018-09-10 (+2.0%, DNSE only), 2020-02-10 (−1.3%), 2021-03-18
  (+1.2%), 2023-04-13 (+5.6%, every broker carries the same excess).


## Correction: 2020-07-28, missing ATO match

- **Finding:** DNSE has no 09:00 bar that day and puts 20,190 contracts in
  09:01, so the Mirae backfill replaced the whole day. Mirae's 09:00 bar
  (open 716.0, low 716.0, volume 1,036) misses the ATO match: the exchange
  records ATO 4,441 contracts at 715.0, which is also the day's open and
  low. Catalog daily volume is 4,526 below the exchange (4,441 ATO plus 85
  continuous).
- **Correction** (`action = replace`, 1 bar): 09:00 becomes open 715.0,
  high 718.8, low 715.0, close 717.1, volume 5,477 (1,036 + 4,441). The 85
  continuous contracts cannot be placed in a minute and are left out, as on
  2021-01-28.
- **Check:** daily open, low and close equal the exchange; daily volume is
  85 contracts (0.03%) below it.
- **Note:** the day-source rule (at least 90% of bars identical) assigned
  this day to DNSE, because DNSE and Mirae agree on most minutes; the
  catalog total equals Mirae's (317,494), so the day comes from Mirae.

## Correction: missing ATO match in the Mirae backfill, 106 days

- **Finding:** on 106 days (2019: 3, 2020: 80, 2021: 23) the catalog daily
  volume is below the exchange by the exchange ATO volume, within 300
  contracts and 20% of it. On 99 of them DNSE has no 09:00 bar, so the
  Mirae backfill replaced the whole day, and Mirae's 09:00 bar does not
  hold the ATO match. The day's open is then not the ATO price. 39 of these
  days are more than 1% below the exchange; 67 are within 1% and were not
  flagged by the volume check.
- **Correction** (`action = replace`, 1 bar per day): the 09:00 bar gets the
  exchange ATO volume added, open set to the exchange open (the ATO price),
  and high or low widened to include it. The remaining difference, a few
  dozen contracts, cannot be placed in a minute and is left out. 2020-07-28
  and 2021-01-28 were corrected the same way above.

## Correction: DNSE bars setting an unconfirmed daily price, 3 bars

The bar is replaced whole with the folded Mirae bar (`action = replace`):
- 2021-04-29 14:29: high 1320.0 becomes 1304.1; daily high gap +15.0 becomes
  −0.9.
- 2020-03-16 14:29: low 666.0 becomes 671.8; daily low gap −2.0 becomes 0.
- 2021-08-04 09:00: daily open gap −0.4 becomes −0.1.

## Decision: open and low gaps with no broker source

On 2020-05-29 (open: exchange 788.6, catalog 786.0) and 2022-06-02 (open and
low: exchange 1311.0, catalog open 1318.0) the exchange ATO price is not in
any broker feed, while the ATO volume is already in the 09:00 bar. These
bars keep the feed values, so backtest bars match what the live feed
publishes. The low gaps on 2021-01-20 (exchange 1067.3, catalog 1070.0) and
2021-10-20 (exchange 1451.0, catalog 1480.0) are also kept: no feed has the
price and its minute is unknown.

## Exchange reference file fixes

`vn30f1m_hnx.csv` is corrected where the exchange file is itself wrong; the
raw download `hnx_1d.csv` is kept as downloaded.
- 2026-06-23 and 2026-10-09: the exchange file has open = 0 for every
  contract while the front contract has ATO volume (1,497 and 1,264). Open
  is set to the broker majority: 1984.7 (12 of 13 brokers; SSI publishes
  prices in thousands) and 1881.1 (13 of 14).
- 2025-07-21: the exchange file has ATO and ATC volume 0 and continuous
  volume 253,689, while its total is 260,125 including 25 put-through
  contracts. Matched volume is set to 260,100, which every broker and
  VPBankS report. The session columns are left as published.
