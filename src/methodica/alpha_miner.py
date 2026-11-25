import ast
import copy
import heapq
import inspect

import numpy as np
import pandas as pd
from nautilus_trader.persistence import ParquetDataCatalog

from methodica.dsl import compute
from methodica.dsl.operators import OPERATORS
from nautilus_bridge.alphas.session_resampling import BAR_COLUMNS, bar_row, bars_frame
from nautilus_bridge.backtest.sample_split import sample_window
from nautilus_bridge.data.catalog import catalog_path

SERIES_PARAM_NAMES = ("x", "y")
WINDOW_PARAM_NAMES = ("d", "w", "span")
WINDOW_LENGTHS = (5, 10, 20, 40, 60)
ARITHMETIC_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
COMMUTATIVE_OPS = (ast.Add, ast.Mult)
MULTIPLICATIVE_OPS = (ast.Mult, ast.Div)


def _arg_kinds(operator_name, operator):
    kinds = []
    for param_name in inspect.signature(operator).parameters:
        if param_name in SERIES_PARAM_NAMES:
            kinds.append("series")
        elif param_name in WINDOW_PARAM_NAMES:
            kinds.append("window")
        else:
            raise ValueError(f"Operator {operator_name} has unknown parameter name: {param_name}")
    return tuple(kinds)


OPERATOR_ARG_KINDS = {name: _arg_kinds(name, operator) for name, operator in OPERATORS.items()}
OPERATOR_NAMES = list(OPERATOR_ARG_KINDS)


def _choose(rng, options):
    return options[rng.integers(len(options))]


def _name(identifier):
    return ast.Name(id=identifier, ctx=ast.Load())


def _negation(node):
    return ast.UnaryOp(op=ast.USub(), operand=node)


def _is_negation(node):
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)


def _random_subtree(depth, fields, rng):
    if depth == 0:
        return _name(_choose(rng, fields))
    node_type = _choose(rng, ("field", "operator", "operator", "arithmetic", "negation"))
    if node_type == "field":
        return _name(_choose(rng, fields))
    if node_type == "negation":
        return _negation(_random_subtree(depth - 1, fields, rng))
    if node_type == "arithmetic":
        return ast.BinOp(
            left=_random_subtree(depth - 1, fields, rng),
            op=_choose(rng, ARITHMETIC_OPS)(),
            right=_random_subtree(depth - 1, fields, rng),
        )
    operator_name = _choose(rng, OPERATOR_NAMES)
    args = [
        _random_subtree(depth - 1, fields, rng) if arg_kind == "series" else ast.Constant(value=_choose(rng, WINDOW_LENGTHS))
        for arg_kind in OPERATOR_ARG_KINDS[operator_name]
    ]
    return ast.Call(func=_name(operator_name), args=args, keywords=[])


def random_expression(depth, fields, rng):
    return ast.Expression(body=_random_subtree(depth, fields, rng))


def _series_positions(tree):
    positions = []
    for node in ast.walk(tree):
        match node:
            case ast.Expression():
                candidates = [(node, "body", None)]
            case ast.BinOp():
                candidates = [(node, "left", None), (node, "right", None)]
            case ast.UnaryOp():
                candidates = [(node, "operand", None)]
            case ast.Call(func=ast.Name(id=operator_name)):
                candidates = [
                    (node, "args", i) for i, arg_kind in enumerate(OPERATOR_ARG_KINDS[operator_name]) if arg_kind == "series"
                ]
            case _:
                candidates = []
        positions += [position for position in candidates if not isinstance(_subtree_at(position), ast.Constant)]
    return positions


def _subtree_at(position):
    parent, field, index = position
    child = getattr(parent, field)
    return child if index is None else child[index]


def _replace_at(position, subtree):
    parent, field, index = position
    if index is None:
        setattr(parent, field, subtree)
    else:
        getattr(parent, field)[index] = subtree


def tree_depth(node):
    match node:
        case ast.Expression(body=body):
            return tree_depth(body)
        case ast.UnaryOp(operand=operand):
            return tree_depth(operand)
        case ast.BinOp(left=left, right=right):
            return 1 + max(tree_depth(left), tree_depth(right))
        case ast.Call(func=ast.Name(id=operator_name), args=args):
            return 1 + max(
                tree_depth(arg) for arg, arg_kind in zip(args, OPERATOR_ARG_KINDS[operator_name]) if arg_kind == "series"
            )
        case _:
            return 0


def mutate(tree, fields, max_depth, rng):
    child = copy.deepcopy(tree)
    _replace_at(_choose(rng, _series_positions(child)), _random_subtree(int(rng.integers(max_depth)), fields, rng))
    return child if tree_depth(child) <= max(max_depth, tree_depth(tree)) else copy.deepcopy(tree)


def crossover(receiver, donor, max_depth, rng):
    child = copy.deepcopy(receiver)
    graft = copy.deepcopy(_subtree_at(_choose(rng, _series_positions(donor))))
    _replace_at(_choose(rng, _series_positions(child)), graft)
    return child if tree_depth(child) <= max(max_depth, tree_depth(receiver)) else copy.deepcopy(receiver)


def _chain_operands(node, op_type):
    if isinstance(node, ast.BinOp) and isinstance(node.op, op_type):
        return _chain_operands(node.left, op_type) + _chain_operands(node.right, op_type)
    return [node]


def _shallowest_chain(op_type, operands):
    heap = [(tree_depth(operand), ast.unparse(operand), i, operand) for i, operand in enumerate(operands)]
    heapq.heapify(heap)
    while len(heap) > 1:
        left_depth, _, _, left = heapq.heappop(heap)
        right_depth, _, i, right = heapq.heappop(heap)
        node = ast.BinOp(left=left, op=op_type(), right=right)
        heapq.heappush(heap, (1 + max(left_depth, right_depth), ast.unparse(node), i, node))
    return heap[0][3]


def _canonical_subtree(node):
    match node:
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            operand = _canonical_subtree(operand)
            return operand.operand if _is_negation(operand) else _negation(operand)
        case ast.BinOp(left=left, op=op, right=right):
            left, right = _canonical_subtree(left), _canonical_subtree(right)
            negated = False
            if isinstance(op, ast.Sub) and _is_negation(right):
                op, right = ast.Add(), right.operand
            elif isinstance(op, ast.Sub) and _is_negation(left):
                op, left, negated = ast.Add(), left.operand, True
            if isinstance(op, MULTIPLICATIVE_OPS):
                if _is_negation(left):
                    left, negated = left.operand, not negated
                if _is_negation(right):
                    right, negated = right.operand, not negated
            if isinstance(op, ast.Sub) and ast.unparse(left) > ast.unparse(right):
                left, right, negated = right, left, not negated
            node = ast.BinOp(left=left, op=op, right=right)
            if isinstance(op, COMMUTATIVE_OPS):
                node = _shallowest_chain(type(op), _chain_operands(node, type(op)))
            return _negation(node) if negated else node
        case ast.Call(func=func, args=args):
            return ast.Call(func=func, args=[_canonical_subtree(arg) for arg in args], keywords=[])
        case _:
            return node


def canonical_form(tree):
    body = _canonical_subtree(tree.body)
    return ast.Expression(body=body.operand if _is_negation(body) else body)


def _push_negation(node):
    match node:
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return operand
        case ast.BinOp(left=left, op=ast.Sub(), right=right):
            return ast.BinOp(left=right, op=ast.Sub(), right=left)
        case ast.BinOp(left=left, op=ast.Mult() | ast.Div() as op, right=right):
            return ast.BinOp(left=_push_negation(left), op=op, right=right)
        case _:
            return _negation(node)


def negate(tree):
    return ast.Expression(body=_push_negation(copy.deepcopy(tree.body)))


def information_coefficient(tree, data, forward_return):
    with np.errstate(all="ignore"):
        signal = compute(ast.unparse(tree), data).replace([np.inf, -np.inf], np.nan)
        ic = signal.corr(forward_return)
    return float(ic) if np.isfinite(ic) else 0.0


def fit_bars(instrument_id):
    bar_type = f"{instrument_id}-1-MINUTE-LAST-EXTERNAL"
    source_bars = bars_frame(bar_row(bar) for bar in ParquetDataCatalog(str(catalog_path())).query_bars([bar_type]))
    bars = source_bars.set_index(pd.to_datetime(source_bars["ts_init"], unit="ns", utc=True))[list(BAR_COLUMNS)]
    fit_start, fit_end = sample_window("FIT")
    return bars[(bars.index >= fit_start) & (bars.index < fit_end)]


def has_converged(previous_parents, parents):
    previous_expressions = {ast.unparse(tree) for tree in previous_parents}
    expressions = {ast.unparse(tree) for tree in parents}
    no_new_parent = expressions == previous_expressions
    return no_new_parent


def mine(instrument_id, seeds=(), horizon=10, population=100, top_k=10, max_depth=3, seed=0):
    return evolve(fit_bars(instrument_id), seeds, horizon, population, top_k, max_depth, seed)


def evolve(data, seeds=(), horizon=10, population=100, top_k=10, max_depth=3, seed=0):
    rng = np.random.default_rng(seed)
    fields = list(data.columns)
    forward_return = data.close.pct_change(horizon).shift(-horizon)
    n_parents = max(2, population // 4)
    ic_by_expression = {}

    def ic_of(tree):
        expression = ast.unparse(tree)
        if expression not in ic_by_expression:
            ic_by_expression[expression] = information_coefficient(tree, data, forward_return)
        return ic_by_expression[expression]

    def rank_by_abs_ic(trees):
        return sorted(trees, key=lambda tree: abs(ic_of(tree)), reverse=True)

    def top_up(trees, new_tree):
        by_expression = {ast.unparse(tree): tree for tree in trees}
        for _ in range(population * 10):
            if len(by_expression) >= population:
                break
            tree = canonical_form(new_tree())
            by_expression.setdefault(ast.unparse(tree), tree)
        return list(by_expression.values())

    def breed(parents):
        if rng.random() < 0.5:
            return crossover(_choose(rng, parents), _choose(rng, parents), max_depth, rng)
        return mutate(_choose(rng, parents), fields, max_depth, rng)

    seed_trees = [canonical_form(ast.parse(expression, mode="eval")) for expression in seeds]
    trees = top_up(seed_trees, lambda: random_expression(max_depth, fields, rng))
    parents = rank_by_abs_ic(trees)[:n_parents]
    while True:
        trees = top_up(parents, lambda: breed(parents))
        next_parents = rank_by_abs_ic(trees)[:n_parents]
        if has_converged(parents, next_parents):
            break
        parents = next_parents

    rows = []
    for tree in rank_by_abs_ic(trees)[:top_k]:
        ic = ic_of(tree)
        rows.append({"expression": ast.unparse(tree if ic >= 0 else negate(tree)), "ic": abs(ic)})
    return pd.DataFrame(rows, columns=["expression", "ic"])
