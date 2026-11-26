from nautilus_trader.model import Money


def cost_per_contract(commission, slippage, multiplier):
    return Money.from_str(commission).as_double() + slippage * multiplier
