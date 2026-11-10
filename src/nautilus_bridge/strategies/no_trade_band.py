from __future__ import annotations

# Basis, Grinold and Kahn, Active Portfolio Management, 2nd ed.:
# - Glossary, "Value added": "the return minus a risk aversion constant times the variance."
# - Chapter 16: "Chapter 14 dealt with transactions costs as an input to the portfolio construction exercise."
# - Chapter 16: "The optimal level of turnover will occur where marginal cost equals marginal value added"
# Not in the book: Claude Code assumed the objective max x·φ − λσ²x² − c·|x − x0| (cost linear in
# traded size) and derived its solution: keep x0 inside [x* − c/(2λσ²), x* + c/(2λσ²)], x* = φ/(2λσ²),
# otherwise trade to the nearer edge.


def next_position(current: float, target: float, half_width: float) -> float:
    lower = target - half_width
    upper = target + half_width
    if current < lower:
        return lower
    if current > upper:
        return upper
    return current
