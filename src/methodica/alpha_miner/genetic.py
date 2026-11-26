import ast
import copy

import numpy as np
import pandas as pd

from methodica.common.dataset import forward_return
from methodica.common.metrics import ic
from methodica.dsl import compute
from methodica.dsl.algebra import OPERATOR_ARG_KINDS, canonical_form, negate, tree_depth

WINDOW_LENGTHS = (5, 10, 20, 40, 60)
ARITHMETIC_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
OPERATOR_NAMES = list(OPERATOR_ARG_KINDS)


def choose(rng, options):
    return options[rng.integers(len(options))]


def _name_node(identifier):
    return ast.Name(id=identifier, ctx=ast.Load())


def _random_subtree(depth, fields, rng):
    if depth == 0:
        return _name_node(choose(rng, fields))
    node_type = choose(rng, ("field", "operator", "operator", "arithmetic", "negation"))
    if node_type == "field":
        return _name_node(choose(rng, fields))
    if node_type == "negation":
        return ast.UnaryOp(op=ast.USub(), operand=_random_subtree(depth - 1, fields, rng))
    if node_type == "arithmetic":
        return ast.BinOp(
            left=_random_subtree(depth - 1, fields, rng),
            op=choose(rng, ARITHMETIC_OPS)(),
            right=_random_subtree(depth - 1, fields, rng),
        )
    operator_name = choose(rng, OPERATOR_NAMES)
    args = [
        _random_subtree(depth - 1, fields, rng) if arg_kind == "series" else ast.Constant(value=choose(rng, WINDOW_LENGTHS))
        for arg_kind in OPERATOR_ARG_KINDS[operator_name]
    ]
    return ast.Call(func=_name_node(operator_name), args=args, keywords=[])


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


def _limit_depth(child, parent, max_depth):
    return child if tree_depth(child) <= max(max_depth, tree_depth(parent)) else copy.deepcopy(parent)


def mutate(tree, fields, max_depth, rng):
    child = copy.deepcopy(tree)
    _replace_at(choose(rng, _series_positions(child)), _random_subtree(int(rng.integers(max_depth)), fields, rng))
    return _limit_depth(child, tree, max_depth)


def crossover(receiver, donor, max_depth, rng):
    child = copy.deepcopy(receiver)
    graft = copy.deepcopy(_subtree_at(choose(rng, _series_positions(donor))))
    _replace_at(choose(rng, _series_positions(child)), graft)
    return _limit_depth(child, receiver, max_depth)


def expression_ic(tree, data, fwd_ret):
    with np.errstate(all="ignore"):
        signal = compute(ast.unparse(tree), data).replace([np.inf, -np.inf], np.nan)
        value = ic(signal, fwd_ret)
    return float(value) if np.isfinite(value) else 0.0


def fitness(tree, data, fwd_ret):
    return abs(expression_ic(tree, data, fwd_ret))


def has_converged(previous_parents, parents):
    previous_expressions = {ast.unparse(tree) for tree in previous_parents}
    current_expressions = {ast.unparse(tree) for tree in parents}
    no_new_parent = current_expressions == previous_expressions
    return no_new_parent


def evolve(data, seeds=(), horizon=10, population=100, top_k=10, max_depth=3, seed=0):
    rng = np.random.default_rng(seed)
    fields = list(data.columns)
    fwd_ret = forward_return(data.close, horizon)
    n_parents = max(2, population // 4)
    fitness_by_expression = {}

    def fitness_of(tree):
        expression = ast.unparse(tree)
        if expression not in fitness_by_expression:
            fitness_by_expression[expression] = fitness(tree, data, fwd_ret)
        return fitness_by_expression[expression]

    def rank_by_fitness(trees):
        return sorted(trees, key=fitness_of, reverse=True)

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
            return crossover(choose(rng, parents), choose(rng, parents), max_depth, rng)
        return mutate(choose(rng, parents), fields, max_depth, rng)

    seed_trees = [canonical_form(ast.parse(expression, mode="eval")) for expression in seeds]
    trees = top_up(seed_trees, lambda: random_expression(max_depth, fields, rng))
    parents = rank_by_fitness(trees)[:n_parents]
    while True:
        trees = top_up(parents, lambda: breed(parents))
        next_parents = rank_by_fitness(trees)[:n_parents]
        if has_converged(parents, next_parents):
            break
        parents = next_parents

    rows = []
    for tree in rank_by_fitness(trees)[:top_k]:
        oriented = tree if expression_ic(tree, data, fwd_ret) >= 0 else negate(tree)
        rows.append({"expression": ast.unparse(oriented), "ic": fitness_of(tree)})
    return pd.DataFrame(rows, columns=["expression", "ic"])
