# Entrade/DNSE Adapter

Custom Python adapter for the Vietnamese derivatives market, following the
NautilusTrader [Python adapter template] layout and lifecycle contract.
DNSE OpenAPI supplies market data; Entrade supplies execution (demo by default,
because DNSE OpenAPI offers no demo account).

[Python adapter template]: https://github.com/nautechsystems/nautilus_trader/blob/nightly/examples/live/_template/README.md

## Module layout

Template-standard modules:

- `constants.py`: Shared client names, VN timezone, DNSE resolution set, and the
  unsupported-operation message.
- `config.py`: `DnseDataClientConfig` and `EntradeExecClientConfig` node extensions.
- `providers.py`: Instrument loading and storage for both venues.
- `data.py`: DNSE bar, quote, trade and depth-10 subscriptions, historical
  requests, and reconnect recovery. Quotes, trades and depth are published from
  DNSE board G1 only (`DNSE_MAIN_BOARD`). Whether DNSE serves quotes, trades and
  depth for the continuous symbol VN30F1M has not been confirmed.
- `execution.py`: Entrade account state, reconciliation reports, and order execution.
- `factories.py`: Client and provider construction from node configuration.

Broker API modules in `api/`:

- `api/dnse_api.py`: DNSE REST client construction (TLS verification is forced
  on; the SDK defaults it off) and quota-header observation.
- `api/entrade_api.py`: Entrade HTTP transport and endpoint client.
- `api/contracts.py`: Entrade monthly-contract boundary representation.
- `api/audit.py`: Demo-account acceptance harness (`EntradeDemoAuditor`);
  refuses to run against the real-money account.

## Lifecycle contract

The template rules are enforced by this package:

- Constructors retain configuration only; network clients are created in
  `_connect` (or injected for tests) and closed in `_disconnect`.
- Instrument providers are loaded through `initialize()`, so
  `InstrumentProviderConfig(load_all=..., load_ids=...)` is honored; the package
  defaults to `load_all=True` when no provider config is supplied.
- Blocking DNSE and Entrade HTTP calls run through `asyncio.to_thread` so the
  node's event loop is never stalled by the 30s connect / 60s read timeouts.
- Background order polling is scheduled through `self.create_task`.
- The read-only cache is used for order lookup and open-order iteration.
- All output is typed: `_handle_instrument` / `_handle_data` / `_handle_response`
  and the `generate_*` event family; reconciliation emits `ExecutionMassStatus`
  plus order, fill, and position status reports.
- Bars carry `ts_init` at the close of their interval (a bar opening at 14:45 keeps
  `ts_init` at 14:45), the same rule as `_bar_ts_init` in market_data.
- After a WebSocket reconnect the bars missed during the outage are fetched from
  the REST API (three attempts) and published before live bars resume; a failed
  recovery is logged as ERROR.
- A DNSE SDK error event is logged as ERROR only when the SDK receive loop has
  stopped, otherwise as WARNING. During continuous sessions (09:00-11:30 and
  13:00-14:30 local time) three minutes without a one-minute bar are logged as
  ERROR. Trading days for this check come from the DNSE working-date list
  (`use_dnse_working_dates`, on by default). When the list cannot be loaded (three
  attempts at connect, retried by each watchdog check), Monday to Friday count as
  trading days and a stall is reported as ERROR only if the REST API has bars for
  that day or cannot be reached; otherwise the day is treated as closed. Bar
  filtering only drops weekends, because the list starts at the current day.
- Unsupported data operations raise `NotImplementedError` with the shared
  `NOT_IMPLEMENTED` message. Order modification is handled as a typed
  `generate_order_modify_rejected` instead, because the venue surface is known.

## Continuous symbol and rollover

The execution client takes a `symbol_resolver`. `EntradeLiveExecClientFactory`
passes `VN30F1MResolver`: orders on `VN30F1M.HNX` are sent to the front-month
contract (the loaded contract with the earliest expiry not yet past 14:45 of its
expiry day), and fills and positions of that contract are reported as
`VN30F1M.HNX`. Without a resolver every instrument is sent under its own ID.

The adapter does not roll positions. `nautilus_bridge.strategies.rollover.FuturesRollover`
is an optional strategy-side helper that signals CLOSE and OPEN around expiry. At
connect the adapter logs a WARNING for any broker expiry that differs from
`vn30f_expiry_date`.

## Order mapping

Nautilus orders are sent as:

- `MARKET` + `GTC`/`DAY` (the Nautilus default) → `MTL`; `MARKET_TO_LIMIT` → `MTL`.
- `MARKET` + `IOC` → `MAK`; `MARKET` + `FOK` → `MOK`.
- `LIMIT` + `DAY`/`GTC`/`GTD` → `LO`. The venue receives no expiry time, so a GTD
  expiry is not enforced by the venue.
- Anything else (`LIMIT` + `IOC`/`FOK`, stop orders, auction TIFs) is denied.

The Nautilus risk engine, not this adapter, denies a `MARKET` order with
`MARKET_PRICE_UNAVAILABLE` when the cache holds no price for the order's
instrument. It looks for a quote, then a trade, then the close of the latest
EXTERNAL bar of that instrument; which of these exist depends on the data the
node subscribes, which this adapter does not decide.

Execution safety:

- Orders are denied, not shrunk, when Entrade buying power (`qmax`) is too small;
  reduce-only orders skip the check.
- A submission whose response is lost is looked up in the broker order list for
  30 s before it is reported as rejected.
- One polling loop tracks every working order and survives request failures.
- Orders that reconciliation rebuilds after a restart are handed to the adapter
  through `_register_external_order`, so their fills keep arriving and they can
  be canceled.
- HTTP 401/403 triggers one sign-in and one retry of the request.

## Register the adapter

Keep node configuration and strategies outside the adapter package. The
following registers both factories and enables instrument loading:

```python
from nautilus_trader.common import Environment
from nautilus_trader.config import DataClientConfig, ExecutionClientConfig
from nautilus_trader.config import InstrumentProviderConfig, LiveNodeConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId

from nautilus_bridge.adapters.entrade.config import DnseDataClientConfig, EntradeExecClientConfig
from nautilus_bridge.adapters.entrade.factories import DnseLiveDataClientFactory
from nautilus_bridge.adapters.entrade.factories import EntradeLiveExecClientFactory

config = LiveNodeConfig(
    environment=Environment.LIVE,
    trader_id=TraderId("QUANTCORE-001"),
    data_clients={
        "DNSE": DnseDataClientConfig(
            api_key="...",
            api_secret="...",
            historical_source="api",
        ),
    },
    exec_clients={
        "DNSE": EntradeExecClientConfig(
            username="...",
            password="...",
            account_id="DNSE-123456",
            account="demo",
        ),
    },
)
node = LiveNode.build(
    "QUANTCORE",
    config,
    data_factories={"DNSE": DnseLiveDataClientFactory},
    exec_factories={"DNSE": EntradeLiveExecClientFactory},
)
```

The data and execution client IDs are both `"DNSE"` by default so the core can
pair the venues. These are two independent axes: the Nautilus `Environment`
context selects the node runtime mode (Backtest = historical + simulated
execution, Sandbox = real-time + simulated execution, Live = real-time + real
venue connections, including paper or real accounts), while
`EntradeExecClientConfig.account` selects the Entrade account (demo
papertrade vs real money). For a real account on either axis, use
`Environment.LIVE` on the node.
