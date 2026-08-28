# quantcore

quantcore is a production-grade systematic-trading framework for VN30F1M intraday futures, with a Rust engine exposed to Python via PyO3; every pipeline stage is callable from Python notebooks.

## Requirements

- Rust toolchain
- Python >= 3.9
- pip

## Install from source

```sh
pip install .
```

## Development workflow

```sh
pip install maturin
maturin develop --manifest-path crates/alpha-core/Cargo.toml --features python-bindings
```

When using a project-local virtual environment, set `CARGO_HOME` to a writable directory if the default `~/.cargo` is restricted. When multiple Python interpreters are installed, pin the build interpreter explicitly:

```sh
PYO3_PYTHON="$(pwd)/.venv/bin/python3" maturin develop --manifest-path crates/alpha-core/Cargo.toml --features python-bindings
```

## Quick start

```python
import quantcore as q
scores = [7.5] * 1000
returns = [0.001] * 1000
bars_per_day = 240
pos = q.canonical_map_py(scores, span=8, z_window=480, band=0.35, cap=2.0, bars_per_day=240)
pnl = q.compute_pnl_py(pos.position, returns, cost_per_side=0.0001, bars_per_day=240)
# Aggregate per-bar net PnL into daily observations.
daily = [sum(pnl.net[i:i + bars_per_day]) for i in range(0, len(pnl.net), bars_per_day)]
print(q.sharpe_py(daily, bars_per_day=240))
```

The design canon is frozen under `docs/enhanced`; the living decision ledger is under `docs/ledger`. Run `python3 scripts/sweep_ledger.py` before committing.

License: TBD
