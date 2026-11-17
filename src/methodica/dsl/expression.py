import ast

import pandas as pd

from methodica.dsl.operators import OPERATORS

_BINARY_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def _validate(node, fields):
    match node:
        case ast.BinOp(left=left, op=op, right=right) if isinstance(op, _BINARY_OPS):
            _validate(left, fields)
            _validate(right, fields)
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            _validate(operand, fields)
        case ast.Constant(value=value) if type(value) in (int, float):
            pass
        case ast.Name(id=name):
            if name not in fields:
                raise ValueError(f"Unknown field: {name}")
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]):
            if name not in OPERATORS:
                raise ValueError(f"Unknown operator: {name}")
            for arg in args:
                _validate(arg, fields)
        case _:
            raise ValueError(f"Unsupported syntax: {ast.unparse(node)}")


def compute(expression: str, data: pd.DataFrame) -> pd.Series:
    tree = ast.parse(expression, mode="eval")
    _validate(tree.body, set(data.columns))
    namespace = {**OPERATORS, **{name: data[name] for name in data.columns}}
    result = eval(compile(tree, "<dsl>", "eval"), {"__builtins__": {}}, namespace)
    return result if isinstance(result, pd.Series) else pd.Series(result, index=data.index)
