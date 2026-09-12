# Portfolio Researcher quickstart

Combine the delivered alpha pool into one composite, refit weights, and backtest it at the position level.

| Method | Module | Role |
| --- | --- | --- |
| `score_pool(pool, bars)` | `quantcore.portfolio` | Score every pool alpha over one aligned bar window. |
| `combine(scores, method="inverse_vol", weights=None, *, window)` | `quantcore.portfolio` | Combine per-alpha scores into one `Composite` (z-units). |
| `equal_weight(scores)` | `quantcore.portfolio` | Equal-weight combine method returning composite + weights. |
| `inverse_vol(scores)` | `quantcore.portfolio` | Inverse-volatility combine method returning composite + weights. |
| `orthogonalize(candidate, scores, min_residual_sharpe=0.0)` | `quantcore.portfolio` | Residualize a candidate against the pool into an `OrthoReport`. |
| `refit_weights(pool, bars, method="inverse_vol")` | `quantcore.portfolio` | Refit pool weights into a `WeightsArtifact`. |
| `health_report(composite, bars)` | `quantcore.portfolio` | Pool health diagnostics into a `PortfolioHealth`. |
| `backtest_portfolio(composite, bars, config=None, *, apply_policy=False)` | `quantcore.risk` | Position-level backtest of the composite (policy opt-in). |
| `WeightsArtifact.save(root=None)` | `core.artifacts` | Persist the weights artifact for the live runner. |
| `portfolio_config_from_pool(artifact, pool=None, instrument=None, *, limits=None)` | `strategy.portfolio` | Build the live `PortfolioConfig` from the weights artifact. |
| `default_seed_portfolio_config()` | `strategy.portfolio` | Seed-expression fallback configuration (research bootstrap). |
