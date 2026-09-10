# Quantcore Python API guide

Quantcore exposes four researcher modules on one shared core, plus the live wiring used by the Quant Developer. Rust remains the computation backend and Nautilus Trader remains responsible for runtime state, orders, positions, and fills.

## Setup

Open the notebook with a Jupyter kernel that uses the repository virtual environment:

```bash
cd /Users/ducle/repos/quant_core
source .venv/bin/activate
```

Research examples below use the fuller NOX catalog explicitly:

```python
from quantcore.core import DataConfig, load_bars

data = DataConfig(
    catalog_path="/Users/ducle/repos/nox_system/data/catalog",
    start="2026-07-15",
    end="2026-08-29",
)
bars = load_bars(data)
```

`DataConfig` is the shared data input. Passing a catalog path and time window explicitly prevents a notebook from silently using a different dataset.

## Shared domain contracts

There are only two cross-role position contracts:

- `TargetPosition`: the Portfolio Researcher's desired signed number of contracts. It is not an order or the actual position.
- `RiskDecision`: the Risk Researcher's approved target and action: `approve`, `cap`, `block`, or `force-flat`.

The authority chain is:

```text
scores → portfolio → TargetPosition → risk → RiskDecision
       → execution pursues approved_target_contracts
       → Nautilus owns orders, actual positions, and fills
```

For example:

```python
from datetime import datetime, timezone
from trading.contracts import RiskDecision, TargetPosition

desired = TargetPosition(
    ts=datetime.now(timezone.utc),
    target_contracts=5,
    z_target=1.1,
    reason="signal",
)

approved = RiskDecision(
    desired=desired,
    approved_target_contracts=2,
    action="cap",
    reason="exposure-limit",
    current_contracts=1,
)
```

Invalid combinations fail immediately. A `cap` cannot increase or reverse desired exposure, a `block` must retain the actual position, and `force-flat` must approve zero contracts.

## 1. Quantitative Researcher

Use `quantcore.alpha` to validate and evaluate Rust DSL expressions:

```python
from quantcore.alpha import AlphaConfig, evaluate_seed

result = evaluate_seed(
    "close - ewma(close, 8)",
    config=AlphaConfig(data=data),
    record_trial=False,
)
print(result.verdict, result.metrics["net_sharpe"])
```

Use the `QuantitativeModel` protocol for a custom score model. Its contract is `score(close, volume) -> list[float]`, with one score per input bar:

```python
import math
from quantcore.alpha import quantitative_models, score_model

class VolumeAdjustedMomentum:
    def score(self, close, volume):
        out = [0.0]
        for i in range(1, len(close)):
            ret = close[i] / close[i - 1] - 1.0
            out.append(ret * math.log1p(max(volume[i], 0.0)))
        return out

quantitative_models.register("volume-adjusted-momentum", VolumeAdjustedMomentum())
scores = score_model(
    "volume-adjusted-momentum",
    bars["close"].tolist(),
    bars["volume"].tolist(),
)
```

`EngineQuantitativeModel(dsl)` is the Rust-backed implementation when an explicit DSL expression is needed. `evaluate_seed` remains DSL-only; it never labels a custom model result with a fake DSL identity.

## 2. Portfolio Researcher

Use `quantcore.portfolio.combine` for built-in allocation:

```python
from quantcore.portfolio import combine

score_set = {
    "close": bars["close"].astype(float).tolist(),
    "volume-adjusted-momentum": scores,
}
portfolio_result = combine(score_set, method="inverse_vol")
composite = portfolio_result["composite"]
weights = portfolio_result["weights"]
```

A custom `PortfolioOptimizer` implements `optimize(scores) -> list[float]` and is registered in the established `combine_methods` registry:

```python
from quantcore.portfolio import combine_methods

class EqualBlend:
    def optimize(self, score_rows):
        count = len(score_rows)
        return [sum(values) / count for values in zip(*score_rows)]

combine_methods.register("equal-blend", EqualBlend())
custom_result = combine(score_set, method="equal-blend")
```

The workflow rejects empty inputs, unequal series lengths, wrong output lengths, and non-finite custom output.

## 3. Risk Researcher

Use `quantcore.risk.backtest_portfolio` to compare desired exposure with risk-approved exposure:

```python
from quantcore.risk import RiskBacktestConfig, backtest_portfolio

risk_result = backtest_portfolio(
    composite,
    data=data,
    sizing="vol_target_drawdown",
    policy="trigger_matrix",
    config=RiskBacktestConfig(data=data),
)
print(risk_result["before"]["performance"])
print(risk_result["after"]["risk_process"])
```

A custom `RiskMeasure` implements:

```text
adjust(z_scores, vol_est, target_vol, drawdowns=None, floor=None) -> list[float]
```

Register it through `sizing_methods`; the same public backtest workflow executes it:

```python
from quantcore.risk import sizing_methods

class HalfExposure:
    def adjust(self, z_scores, vol_est, target_vol, drawdowns=None, floor=None):
        return [0.5 * value for value in z_scores]

sizing_methods.register("half-exposure", HalfExposure())
custom_risk_result = backtest_portfolio(
    composite,
    data=data,
    sizing="half-exposure",
    policy="trigger_matrix",
    config=RiskBacktestConfig(data=data),
)
```

The live risk layer emits `RiskDecision`. Loss-limit and stale-feed emergency triggers emit `force-flat`; ordinary denials emit `block` at the actual current position.

## 4. Execution Researcher

An `ExecutionAlgorithm` implements `plan(gap_contracts, config) -> list[int]`. Every child quantity must be a non-zero integer, have the same direction as the gap, and sum exactly to the gap:

```python
from quantcore.execution import ExecutionConfig, execution_algorithms, plan_orders

class TwoSlice:
    def plan(self, gap_contracts, config):
        first = gap_contracts // 2
        second = gap_contracts - first
        return [quantity for quantity in (first, second) if quantity]

execution_algorithms.register("two-slice", TwoSlice())
chunks = plan_orders(5, "two-slice", ExecutionConfig(slice_bars=2))
```

Use `backtest_execution` for Nautilus-backed execution research:

```python
import pandas as pd
from quantcore.execution import backtest_execution

targets = pd.DataFrame(
    {
        "ts": bars.iloc[[50, 100, 150]]["ts"].tolist(),
        "target_contracts": [2, -1, 0],
    }
)
execution_result = backtest_execution(
    targets,
    config=ExecutionConfig(cooldown_secs=0.0, min_gap_contracts=1),
    data=data,
    algo="two-slice",
)
```

Nautilus performs order simulation and fill accounting. Quantcore does not reproduce that machinery.

## 5. Quant Developer

Use `trading.node` to build the Nautilus live runtime. The runtime environment and the broker account environment are separate concepts:

- Paper: Nautilus `Environment.LIVE` + live DNSE data + Entrade `DEMO` account.
- Live: Nautilus `Environment.LIVE` + live DNSE data + Entrade `LIVE` account.

The repository currently guards Entrade `LIVE`; changing `TradingEnvironment.DEMO` to `TradingEnvironment.LIVE` raises until broker validation is complete.

```python
from pathlib import Path
from trading.instruments import load_futures_instrument_spec
from trading.node import (
    ExecutionBroker,
    TradingEnvironment,
    TradingRuntimeConfig,
    build_trading_node_config,
)

instrument = load_futures_instrument_spec(
    Path("/Users/ducle/repos/quant_core/src/market_data/instrument_definitions/vn30f1m.hnx.json")
)
runtime = TradingRuntimeConfig(
    api_key="<API_KEY>",
    api_secret="<API_SECRET>",
    instrument_spec=instrument,
    alpha_path="data/pool/weights.json",
    execution_broker=ExecutionBroker.ENTRADE,
    execution_environment=TradingEnvironment.DEMO,
    max_exposure_contracts=3,
)
node_config = build_trading_node_config(runtime)  # builds config; does not connect
```

For the fully wired paper application:

```bash
.venv/bin/python3 apps/trading/paper.py --dry-run
```

Do not use a backtest or Nautilus sandbox runtime as a substitute for paper trading. Paper and live both use the Nautilus live runtime; only the Entrade account environment differs.

## Extension map

| Role | Protocol | Registry | Public workflow |
|---|---|---|---|
| Quantitative Researcher | `QuantitativeModel` | `quantitative_models` | `score_model` |
| Portfolio Researcher | `PortfolioOptimizer` | `combine_methods` | `combine` |
| Risk Researcher | `RiskMeasure` | `sizing_methods` | `backtest_portfolio` |
| Execution Researcher | `ExecutionAlgorithm` | `execution_algorithms` | `plan_orders`, `backtest_execution` |

The protocols are importable from `quantcore.core`. Registered Python implementations use the same role workflows as built-ins. Rust-backed computations and Nautilus behavior stay behind those workflows rather than being reimplemented in Python.
