# Alpha Researcher quickstart

Score, gate, and deliver individual alpha expressions from DSL seeds over bar windows.

| Method | Module | Role |
| --- | --- | --- |
| `validate_seed(dsl)` | `quantcore.alpha` | Validate one DSL expression against the engine grammar. |
| `score(expressions, close, volume)` | `quantcore.alpha` | Evaluate expressions over raw close/volume buffers to score rows. |
| `score_model(model, close, volume)` | `quantcore.alpha` | Evaluate one named or custom model over close/volume buffers. |
| `evaluate_seed(dsl, bars, config=None)` | `quantcore.alpha` | Full tear sheet for one seed expression over a bar window. |
| `screen_batch(seeds, bars, config=None)` | `quantcore.alpha` | Screen many seeds at once into a `ScreenResult`. |
| `mine_seeds(seeds, bars, config=None)` | `quantcore.alpha` | Return only the seeds that pass the gate criteria. |
| `build_spec_sheet(sheet, bars)` | `quantcore.alpha` | Derive the live-monitoring spec sheet from a tear sheet. |
| `deliver(pool, sheet, spec, *, alpha_id=None, author="research", tags=(), family=None, source="seed")` | `quantcore.alpha` | Append a passing alpha to the pool as a `PoolEntry`. |
| `AlphaConfig(...)` | `quantcore.alpha` | Gate/evaluation configuration for the screening workflows. |
| `GateCriteria(...)` | `quantcore.alpha` | Acceptance thresholds (IC, sharpe, turnover) for seeds. |
| `AlphaPool.load(root=None)` | `core.artifacts` | Load the delivered-alpha pool artifact. |
| `SpecSheet.load(root=None)` | `core.artifacts` | Load the spec sheet consumed by divergence monitoring. |
