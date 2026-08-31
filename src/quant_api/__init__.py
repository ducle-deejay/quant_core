"""quant_api - role-scoped Python API for the quant_core framework.

One module per practitioner role (decision note DEC-017):

- ``quant_api.research``      Quantitative Researcher: seed -> single-alpha
                              evaluation -> GA breeding -> pool delivery.
- ``quant_api.portfolio``     Portfolio Researcher: pool, orthogonalization,
                              combination, weight refit, health report.
- ``quant_api.execution``     Execution Researcher: Nautilus-based offline
                              execution backtest, urgency, slippage report.
- ``quant_api.risk``          Quant Risk Researcher: sizing models, risk
                              policies, portfolio backtest, gauges, post-mortem.
- ``quant_api.core``          Shared: config, catalog data access, artifact
                              writers, pool loader/writer, registries.

Design contract: notebook-first, deterministic, agent-ready. Market data is
resolved automatically from the research catalog (users never pass data).
Only handoff artifacts are auto-saved; reports stay in-memory.
"""
from quant_api import core  # noqa: F401

__version__ = "0.1.0"
