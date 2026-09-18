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
- `data.py`: DNSE bar and quote subscriptions, historical requests, and
  reconnect recovery. Quotes are served per monthly contract only — the
  continuous symbol is bars-only, so resolve the active contract before
  subscribing quotes. TradeTick subscription is not implemented.
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
- Unsupported data operations raise `NotImplementedError` with the shared
  `NOT_IMPLEMENTED` message. Order modification is handled as a typed
  `generate_order_modify_rejected` instead, because the venue surface is known.

## Register the adapter

Keep node configuration and strategies outside the adapter package. The
following registers both factories and enables instrument loading:

```python
from nautilus_trader.common import Environment
from nautilus_trader.config import DataClientConfig, ExecutionClientConfig
from nautilus_trader.config import InstrumentProviderConfig, LiveNodeConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId

from trading.adapters.entrade_template.config import DnseDataClientConfig, EntradeExecClientConfig
from trading.adapters.entrade_template.factories import DnseLiveDataClientFactory
from trading.adapters.entrade_template.factories import EntradeLiveExecClientFactory
from market_data.instruments import load_futures_instrument_spec

spec = load_futures_instrument_spec("data/instruments/vn30f.json")

config = LiveNodeConfig(
    environment=Environment.LIVE,
    trader_id=TraderId("QUANTCORE-001"),
    data_clients={
        "DNSE": DnseDataClientConfig(
            api_key="...",
            api_secret="...",
            instrument_spec=spec,
            historical_source="api",
        ),
    },
    exec_clients={
        "DNSE": EntradeExecClientConfig(
            instrument_spec=spec,
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
