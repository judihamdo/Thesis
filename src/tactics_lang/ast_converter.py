import ast
from typing import Any, Sequence

from .immutable_list import IList
from .program import (
    EBoolOp,
    EConst,
    EFunCall,
    EIndex,
    EOp1,
    EOp2,
    ESlice,
    ETuple,
    EVar,
    Identifier,
    SExpr,
    Statement,
)
from .utility import IllegalName, UnsupportedFeature


def map_node(node: ast.AST) -> Any:
    """Converts a Python AST node into the corresponding node in our custom AST."""
    match node:
        # Operators
        case ast.Add():
            return "+"

        case ast.Sub() | ast.USub():
            return "-"

        case ast.Mult():
            return "*"

        case ast.Div():
            return "/"

        # Numbers(constants)
        case ast.Constant(value):
            if type(value) is bool:
                return EConst(value)
            elif type(value) is int:
                return EConst(value)
            elif type(value) is str:
                return EConst(value)
            elif type(value) is float:
                return EConst(value)
            elif type(value) is complex:
                return EConst(value)

        # Variables: Check whether the identifier is a valid name -> then convert it into a variable in the custom AST
        case ast.Name(id):
            for c in id:
                if not (c.isalnum() or c == "_"):
                    raise IllegalName(id)
            return EVar(Identifier(id))

        # Unary operation (-x)
        case ast.UnaryOp(op, operand):
            operator = map_node(op)
            expr = map_node(operand)
            return EOp1(operator, expr)

        # Binary operation (z.B. x + y)
        case ast.BinOp(left, op, right):
            left_expr = map_node(left)
            operator = map_node(op)
            right_expr = map_node(right)
            return EOp2(left_expr, operator, right_expr)

        case ast.Compare(left, [op], [right]):
            left_expr = map_node(left)
            right_expr = map_node(right)
            match op:
                case ast.Eq():
                    op_str = "=="
                case ast.NotEq():
                    op_str = "!="
                case ast.Lt():
                    op_str = "<"
                case ast.LtE():
                    op_str = "<="
                case ast.Gt():
                    op_str = ">"
                case ast.GtE():
                    op_str = ">="
                case _:
                    raise UnsupportedFeature(op)
            return EOp2(left_expr, op_str, right_expr)

        case ast.Call(func, args, keywords):
            if len(keywords) > 0:
                raise UnsupportedFeature(node)
            func_expr = map_node(func)
            arg_exprs = [map_node(a) for a in args]
            return EFunCall(func_expr, arg_exprs)

        # General Expression
        case ast.Expr(value):
            return SExpr(map_node(value))

        case ast.BoolOp(op, values):
            if len(values) != 2:
                raise UnsupportedFeature(node)
            left = map_node(values[0])
            right = map_node(values[1])
            match op:
                case ast.And():
                    return EBoolOp("and", left, right)
                case ast.Or():
                    return EBoolOp("or", left, right)
                case _:
                    raise UnsupportedFeature(node)

        case ast.Tuple(elts, _ctx):
            return ETuple([map_node(e) for e in elts])

        # Handle square bracket access in Python, distinguishing between slicing and indexing.
        case ast.Subscript(value=v, slice=s):
            seq = map_node(v)
            if isinstance(s, ast.Slice):
                lo = map_node(s.lower) if s.lower else None
                hi = map_node(s.upper) if s.upper else None
                return ESlice(seq, lo, hi)
            else:
                return EIndex(seq, map_node(s))

        case _:
            raise UnsupportedFeature(node)


def map_nodes(nodes: Sequence[Any]) -> IList[Statement]:
    return IList([map_node(node) for node in nodes])
