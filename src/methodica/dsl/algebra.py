import ast
import copy
import heapq
import inspect

from methodica.dsl.operators import OPERATORS

SERIES_PARAM_NAMES = ("x", "y")
WINDOW_PARAM_NAMES = ("d", "w", "span")
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


def _negation(node):
    return ast.UnaryOp(op=ast.USub(), operand=node)


def _is_negation(node):
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)


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
