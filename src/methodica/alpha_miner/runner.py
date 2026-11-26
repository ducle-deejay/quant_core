from methodica.alpha_miner.genetic import evolve
from methodica.common.dataset import fit_mask, load_bars, session_bars


def run_alpha_miner(*, instrument_id, seeds=(), horizon=10, population=100, top_k=10, max_depth=3, seed=0):
    bars = session_bars(load_bars(instrument_id), "1-MINUTE")
    return evolve(bars, seeds, horizon, population, top_k, max_depth, seed, in_fit=fit_mask(bars.index, horizon))
