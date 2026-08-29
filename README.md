# quantcore

quantcore is a production-grade systematic-trading framework for VN30F1M intraday futures, with a Rust engine exposed to Python via PyO3; every pipeline stage is callable from Python notebooks.

## Requirements

- Rust toolchain
- Python >= 3.9
- uv

## Install from source

```sh
UV_CACHE_DIR="$PWD/.uv_cache" uv sync
```

## Development workflow

The sandbox blocks caches outside the workspace, so keep Cargo, uv, and pip state in project-local directories and pin PyO3 to the project virtual environment:

```sh
export CARGO_HOME="$PWD/.cargo-home"
export UV_CACHE_DIR="$PWD/.uv_cache"
export PIP_CACHE_DIR="$PWD/.uv_cache/pip"
export PYO3_PYTHON="$PWD/.venv/bin/python3"

.venv/bin/python3 -m maturin develop --manifest-path src/alpha-core/Cargo.toml --features python-bindings
cargo test --manifest-path src/alpha-core/Cargo.toml
```

## Quick start

```python
import alpha_core as q
scores = [7.5] * 1000
returns = [0.001] * 1000
bars_per_day = 240
pos = q.canonical_map_py(scores, span=8, z_window=480, band=0.35, cap=2.0, bars_per_day=240)
pnl = q.compute_pnl_py(pos.position, returns, cost_per_side=0.0001, bars_per_day=240)
# Aggregate per-bar net PnL into daily observations.
daily = [sum(pnl.net[i:i + bars_per_day]) for i in range(0, len(pnl.net), bars_per_day)]
print(q.sharpe_py(daily, bars_per_day=240))
```

## Repository structure

- `src/alpha-core/` — Rust engine (crate `alpha-core`).
- `src/alpha_core/` — Python package for the Rust extension (research API).
- `src/market_data/` — market-data pipeline: DNSE ETL -> Nautilus parquet catalog.
- `src/trading/` — live platform wiring: entrade/dnse adapters, trading node composition (Nautilus v1.231).
- `apps/` — entrypoints: `apps/data/` (daily ETL), trading/research entrypoints to follow.
- `operations/` — retained acceptance tooling.
- `verification/` — gitignored; broker export files with personal identifiers (aggregates live in ledger notes).

Each `src/*` package is an independent uv-workspace member with its own pyproject (distributions `alpha-core`, `market-data`, `trading`) so a future microservice split is a packaging-only change.

The design canon is frozen under `docs/enhanced`; the living decision ledger is under `docs/ledger`. Run `python3 scripts/sweep_ledger.py` before committing.

License: TBD
