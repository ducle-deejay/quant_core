# Entrade Adapter Capability Matrix

Capability matrix and spec-coverage table for the `entrade_template` adapter (DNSE market data + Entrade execution, venue HNX derivatives), mapped against the NautilusTrader developer-guide testing specs (`spec_exec_testing.md`, `spec_data_testing.md`).

Status legend:


- **PASS** - executed live with broker-order or session evidence.

- **PENDING** - the adapter supports the capability; the case awaits a live session.

- **N/A** - the adapter does not support the capability; out of scope by design.

- **EX-*** - adapter-specific cases beyond the spec matrix.


## Capability matrix

### Orders


- LIMIT + DAY -> `LO`: supported

- MARKET + IOC -> `MAK`: supported

- MARKET + FOK -> `MOK`: supported

- MARKET_TO_LIMIT -> `MTL`: supported (adapter extension, beyond the spec matrix)

- LIMIT GTC/IOC/FOK/GTD, stop orders, brackets, post-only, reduce-only, iceberg, modify: rejected by design


### Market data


- Instruments (request/load/publish): supported

- Bars (subscribe + historical request): supported

- Quotes, trades, depth10 (subscribe): supported

- Book deltas/snapshots, historical quotes/trades, mark/index/funding, instrument status, options: unsupported


## Execution coverage (66 spec cases)


| Case | Description | Status | Evidence / reason |
|---|---|---|---|
| TC-E01 | Market BUY - submit and fill | N/A | market orders are IOC/FOK-only on HNX; plain GTC market is rejected by design |
| TC-E02 | Market SELL - submit and fill | N/A | market orders are IOC/FOK-only on HNX; plain GTC market is rejected by design |
| TC-E03 | Market order with IOC TIF | PASS | order 7321773 (MAK filled, stop cleanup 2026-09-16) |
| TC-E04 | Market order with FOK TIF | PENDING | awaiting live session |
| TC-E05 | Market order with quote quantity | N/A | quote-quantity orders unsupported |
| TC-E06 | Close position via market order on stop | PASS | order 7321773 (position closed via IOC market on stop) |
| TC-E10 | Limit BUY GTC - submit and accept | N/A | LIMIT GTC rejected by design (HNX LO is day-valid) |
| TC-E11 | Limit SELL GTC - submit and accept | N/A | LIMIT GTC rejected by design (HNX LO is day-valid) |
| TC-E12 | Limit BUY and SELL pair | PENDING | awaiting live session |
| TC-E13 | Limit IOC aggressive fill | N/A | LIMIT IOC unsupported by the venue mapping |
| TC-E14 | Limit IOC passive - no fill | N/A | LIMIT IOC unsupported by the venue mapping |
| TC-E15 | Limit FOK fill | N/A | LIMIT FOK unsupported by the venue mapping |
| TC-E16 | Limit FOK no fill | N/A | LIMIT FOK unsupported by the venue mapping |
| TC-E17 | Limit GTD - submit and accept | N/A | LIMIT GTD unsupported by the venue mapping |
| TC-E18 | Limit GTD expiry | N/A | LIMIT GTD unsupported by the venue mapping |
| TC-E19 | Limit DAY - submit and accept | PASS | order 7321768 (LO filled) |
| TC-E20 | StopMarket BUY | N/A | stop orders unsupported |
| TC-E21 | StopMarket SELL | N/A | stop orders unsupported |
| TC-E22 | StopLimit BUY | N/A | stop-limit orders unsupported |
| TC-E23 | StopLimit SELL | N/A | stop-limit orders unsupported |
| TC-E24 | MarketIfTouched BUY | N/A | market-if-touched orders unsupported |
| TC-E25 | MarketIfTouched SELL | N/A | market-if-touched orders unsupported |
| TC-E26 | LimitIfTouched BUY | N/A | limit-if-touched orders unsupported |
| TC-E27 | LimitIfTouched SELL | N/A | limit-if-touched orders unsupported |
| TC-E30 | Modify limit BUY price | N/A | order modification rejected by design (venue has no modify endpoint) |
| TC-E31 | Modify limit SELL price | N/A | order modification rejected by design |
| TC-E32 | Cancel-replace limit BUY | N/A | cancel-replace covered by separate cancel + submit |
| TC-E33 | Cancel-replace limit SELL | N/A | cancel-replace covered by separate cancel + submit |
| TC-E34 | Modify stop trigger price | N/A | stop orders unsupported |
| TC-E35 | Cancel-replace stop order | N/A | stop orders unsupported |
| TC-E36 | Modify rejected | PENDING | awaiting live session |
| TC-E40 | Cancel single limit order | PENDING | awaiting live session |
| TC-E41 | Cancel all on stop | PENDING | awaiting live session |
| TC-E42 | Individual cancels on stop | PENDING | awaiting live session |
| TC-E43 | Batch cancel on stop | N/A | batch-cancel command has no ExecTester flag; covered by contract tests |
| TC-E44 | Cancel already-canceled order | PENDING | awaiting live session |
| TC-E50 | Bracket BUY | N/A | brackets unsupported |
| TC-E51 | Bracket SELL | N/A | brackets unsupported |
| TC-E52 | Bracket entry fill activates TP/SL | N/A | brackets unsupported |
| TC-E53 | Bracket with post-only entry | N/A | brackets unsupported |
| TC-E60 | PostOnly accepted | N/A | post-only unsupported by the venue |
| TC-E61 | ReduceOnly on close | N/A | reduce-only flag unsupported |
| TC-E62 | Display quantity (iceberg) | N/A | iceberg display quantity unsupported |
| TC-E63 | Custom order params | PENDING | awaiting live session |
| TC-E70 | PostOnly rejection | N/A | post-only unsupported by the venue |
| TC-E71 | ReduceOnly rejection | N/A | reduce-only flag unsupported |
| TC-E72 | Unsupported order type | PENDING | awaiting live session |
| TC-E73 | Unsupported TIF | PENDING | awaiting live session |
| TC-E80 | Open position on start | PENDING | awaiting live session |
| TC-E81 | Cancel orders on stop | PENDING | awaiting live session |
| TC-E82 | Close positions on stop | PASS | order 7321773 |
| TC-E83 | Unsubscribe on stop | N/A | ExecTester issues no unsubscribe on stop |
| TC-E84 | Reconcile open orders | PENDING | awaiting live session |
| TC-E85 | Reconcile filled orders | PENDING | awaiting live session |
| TC-E86 | Reconcile open long position | PENDING | awaiting live session |
| TC-E87 | Reconcile open short position | PENDING | awaiting live session |
| TC-E88 | Reconciliation commission failure | PENDING | awaiting live session |
| TC-E89 | WebSocket commission failure | PENDING | awaiting live session |
| TC-E90 | Limit BUY option | N/A | options unsupported |
| TC-E91 | Limit SELL option | N/A | options unsupported |
| TC-E92 | Limit with alternative pricing | N/A | options unsupported |
| TC-E94 | Unsupported order type denied for options | N/A | options unsupported |
| TC-E96 | Conditional order rejected for options | N/A | options unsupported |
| TC-E99 | FOK limit option | N/A | options unsupported |
| TC-E100 | Cancel option order | N/A | options unsupported |
| TC-E101 | Reconcile option position | N/A | options unsupported |


### Adapter-specific cases


| EX-01 | MarketToLimit (MTL) submit and fill | PASS | order 7313762 (MTL filled) - adapter-specific wire type beyond the spec matrix |
| EX-02 | LIMIT GTC rejected by design | PENDING | unit-tested; live rejection pending a session |
| EX-03 | Buying-power qmax clamp before submit | PENDING | qmax query confirmed read-only; clamp pending live probe |
| EX-04 | Mass-status reconciliation via runtime report hooks | PASS | startup reconciliation completed on every tester session |


## Data coverage (26 spec cases)


| Case | Description | Status | Evidence / reason |
|---|---|---|---|
| TC-D01 | Request instruments | PASS | derivatives list loaded on every connect |
| TC-D02 | Subscribe instrument | PENDING | awaiting live session |
| TC-D03 | Load specific instrument | PASS | active contract resolved and published on every connect |
| TC-D10 | Subscribe book deltas | N/A | book deltas unsupported |
| TC-D11 | Subscribe book at interval | N/A | book at interval unsupported |
| TC-D12 | Subscribe book depth | PENDING | awaiting live session |
| TC-D13 | Request book snapshot | N/A | book snapshot request unsupported |
| TC-D14 | Managed book from deltas | N/A | managed book from deltas unsupported |
| TC-D20 | Subscribe quotes | PASS | quotes streamed in prior tester sessions |
| TC-D21 | Request historical quotes | N/A | historical quotes request unsupported |
| TC-D30 | Subscribe trades | PASS | trades streamed in prior tester sessions |
| TC-D31 | Request historical trades | N/A | historical trades request unsupported |
| TC-D40 | Subscribe bars | PASS | bars streamed in prior tester sessions |
| TC-D41 | Request historical bars | PASS | historical bars served via REST fallback |
| TC-D50 | Subscribe mark prices | N/A | mark prices unsupported |
| TC-D51 | Subscribe index prices | N/A | index prices unsupported |
| TC-D52 | Subscribe funding rates | N/A | funding rates unsupported |
| TC-D53 | Request historical funding rates | N/A | funding rates unsupported |
| TC-D60 | Subscribe instrument status | N/A | instrument status unsupported |
| TC-D61 | Subscribe instrument close | N/A | instrument close unsupported |
| TC-D62 | Subscribe option greeks | N/A | option greeks unsupported |
| TC-D63 | Subscribe option chain | N/A | option chain unsupported |
| TC-D70 | Unsubscribe on stop | PENDING | awaiting live session |
| TC-D71 | Custom subscribe params | N/A | custom subscribe params unsupported |
| TC-D72 | Custom request params | N/A | custom request params unsupported |
| TC-D73 | Retirement cleanup | PENDING | awaiting live session |


## Adapter-specific behavior notes


- HNX `LO` orders are day-valid; the adapter rejects LIMIT+GTC instead of silently downgrading.

- Order modification is rejected at the adapter level (`OrderModifyRejected`) because the venue exposes no modify endpoint.

- Submitting a marketable order requires a cached quote; without one the node risk engine denies the order with `MARKET_PRICE_UNAVAILABLE` before it reaches the broker.

- Each submit is preceded by a buying-power query (`qmax`); the quantity is clamped to the venue maximum.

- Fill commissions are derived from venue `tradingFee` + `tradingTax`, prorated per fill.


Summary: 12 PASS, 24 PENDING, 60 N/A (92 spec cases + 4 adapter-specific).
