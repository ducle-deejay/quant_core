# Quantitative Researcher - operating cadence

Module: `quant_api.alpha`. Decision notes DEC-017/DEC-018 govern this API.
Canon: Component 0 - Alpha Mining, Component 1 - Canonical Simulation,
Component 2 - Evaluation and Screening.

## Daily cycle (research replenishes the pool)

1. Write a new hypothesis as a DSL seed, e.g. `"close - ewma(close, 8)"`.
   Canonicalize it first: `validate_seed(dsl)` (raises ValueError on bad syntax).
2. Evaluate it as a SINGLE alpha (WorldQuant-style: no mining before a seed
   proves itself): `evaluate_seed(dsl, config)` -> TearSheet with verdict
   IN/OUT and failing reasons. This runs Component 1 + Component 2
   (canonical simulation, Sharpe, max drawdown, cost drag, IC ladder,
   walk-forward, ICIR). Expressions referencing fields absent from the
   data (only close/volume exist) raise an explicit error. Set
   `AlphaConfig(n_trials=N)` from your trial-ledger count to wire the
   deflated-Sharpe check (canon 3.4) - the bar rises with the effective
   number of trials.
3. If the seed passes, breed from it: `mine_seeds([passing_seeds], config)`
   -> ranked DSL list from the engine GA (fixed fitness = mean score x
   next-bar return; deterministic per seed).
4. Evaluate the bred candidates: `evaluate_candidate(dsl, config)` (same
   pipeline, source="ga").
5. Batch funnel with trial accounting: `screen_batch(expressions, config,
   record_trials=True, source="ga")` -> funnel counts + tear sheets; pass
   `source="ga"` for bred batches so the trial ledger is not misattributed.
   Every candidate is appended to the trial ledger
   (data/research/trial_ledger.jsonl) - the append-only trial accounting
   that feeds deflated thresholds and blocks re-mining of dead ideas.
   `funnel.survivor_count` counts FULL-gate survivors (== len(survivors));
   `ic_pass_count`/`drag_pass_count` are the forecast- and cost-gate counts.
6. Deliver passing alphas to the pool: `build_spec_sheet(tear, config)` ->
   `deliver_to_pool(tear, spec, source="ga")` writes the alpha file into
   data/pool/alphas/ and regenerates index.json. The pool folder is the
   handoff artifact the Portfolio Researcher loads.

Notes from real-data acceptance: with fewer than two walk-forward blocks
the stability check is reported as not-applicable (hint in
`tear.metrics["hints"]`) instead of a 0%/100% coin flip; a strong INVERSE
signal fails the signed ICIR check - negate the expression (hint included);
`mine_seeds` validates, canonicalizes and dedupes custom-fitness output.

## Custom GA fitness (extension slot)

`ga_fitness` registry: default "engine" delegates to the Rust GA. A custom
fitness is a Python function with the same signature
`fn(seeds, close, volume, population_size, generations, seed) -> list[str]`
and is registered via `ga_fitness.register(name, fn)`. Inside a custom
fitness use `quant_api.alpha.score(expressions, close, volume)` as the
scoring primitive (one engine batch call). Research fast in Python,
migrate into the engine after validation (DEC-017).

## Monthly

Pool health check: re-screen pool alphas on the latest window; flag alphas
whose verdict flips to OUT for post-mortem / replacement.

## Trial ledger hygiene

Never edit trial_ledger.jsonl in place - it is append-only (canon
Component 2 section 3.4; ledger rule M2).
