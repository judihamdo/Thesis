from typing import Any

from .program import (
    CompositeStatement,
    ConstantType,
    DataDeclaration,
    DescriptionStatement,
    EBoolOp,
    EConst,
    EFunCall,
    EIf,
    EIndex,
    EList,
    EmptyStatement,
    EOp1,
    EOp2,
    ESlice,
    ETuple,
    EVar,
    # Expressions
    Expression,
    FunctionDeclaration,
    FunctionType,
    Hole,
    Identifier,
    InjectedExpression,
    ListType,
    LiteralType,
    MixedType,
    Program,
    RecordType,
    ReturnStatement,
    SCase,
    SFor,
    SIf,
    SMatch,
    # Statments
    Statement,
    TBool,
    TComplex,
    TFloat,
    TInt,
    TStr,
    TupleType,
    # Types
    Type,
    TypeDeclaration,
    TypeRef,
    VariableDeclaration,
)
from .utility import UnexpectedValueError, pad_str


def pretty_type(t: Type) -> str:
    match t:
        case TInt():
            return "int"
        case TBool():
            return "bool"
        case TFloat():
            return "float"
        case TComplex():
            return "complex"
        case TStr():
            return "str"
        case FunctionType():
            params = ", ".join(pretty_type(p) for p in t.parameter_types)
            return f"({params}) -> {pretty_type(t.return_type)}"
        case TupleType():
            inner = ", ".join(pretty_type(t) for t in t.element_types)
            return f"tuple[{inner}]"
        case ListType():
            return f"list[{pretty_type(t.element_type)}]"
        case _:
            return "unknown"


# PRETTY PRINTING (AST)
def pretty_expr(e: Expression) -> str:
    if isinstance(e, EConst):
        # Strings should appear with quotes: 'Tiger'
        if isinstance(e.value, str):
            return repr(e.value)
        return str(e.value)
    elif isinstance(e, ETuple):
        inner = ", ".join(pretty_expr(x) for x in e.elts)
        return f"({inner})"
    elif isinstance(e, EList):
        inner = ", ".join(pretty_expr(x) for x in e.elts)
        return f"[{inner}]"
    elif isinstance(e, EVar):
        return e.name.value
    elif isinstance(e, EOp1):
        return f"{e.op}{pretty_expr(e.operand)}"
    elif isinstance(e, EOp2):
        return f"({pretty_expr(e.left)} {e.op} {pretty_expr(e.right)})"
    elif isinstance(e, InjectedExpression):
        return e.value
    elif isinstance(e, EIndex):
        return f"{pretty_expr(e.seq)}[{pretty_expr(e.index)}]"
    elif isinstance(e, ESlice):
        lo = "" if e.lower is None else pretty_expr(e.lower)
        hi = "" if e.upper is None else pretty_expr(e.upper)
        return f"{pretty_expr(e.seq)}[{lo}:{hi}]"
    else:
        return "unknown_expr"


def case_pattern_to_str(c: SCase) -> str:
    """
    Prints the pattern of a case:
    - without pattern_values:  case dog:
    - with pattern_values:     case Predator([0], [1]):
    - tuple pattern:           case ([0], [1], [2]):
    """
    pvs = c.pattern_values or []

    if pvs:
        inner = ", ".join(hole_to_str(h) for h in pvs)
        if c.pattern == "":
            return f"({inner})"
        return f"{c.pattern}({inner})"

    return c.pattern


def indent(text: str, level: int = 1, spaces: int = 4) -> str:
    """Indents the beginning of each line by `level * spaces` spaces."""
    prefix = " " * (level * spaces)
    return "\n".join(prefix + line if line.strip() != "" else line for line in text.splitlines())


def hole_to_str(hole) -> str:
    if isinstance(hole, Identifier):
        return hole.value

    if isinstance(hole, Hole) and getattr(hole, "kind", "normal") == "list":
        return "[**]" if hole.selected else "[*]"

    # normaler Hole: index kann am Anfang None sein
    idx = getattr(hole, "index", None)
    if idx is None:
        return "[?]" if not getattr(hole, "selected", False) else "[?*]"

    return f"[{idx}{'*' if getattr(hole, 'selected', False) else ''}]"


def identifier_to_str(identifier: Identifier | Hole) -> str:
    match identifier:
        case Hole():
            return hole_to_str(identifier)
        case Identifier(value):
            return value
        case _:
            raise UnexpectedValueError(identifier)


def type_to_str(type_: Type | Hole) -> str:
    match type_:
        case Hole():
            return hole_to_str(type_)
        case TInt():
            return "int"
        case TBool():
            return "bool"
        case TFloat():
            return "float"
        case TComplex():
            return "complex"
        case TStr():
            return "str"
        case LiteralType(cases, name):
            if name is not None:
                return name
            cases_str = ", ".join(str(c.value) for c in cases)
            return f"[{cases_str}]"
        case ListType(element_type):
            return f"list[{type_to_str(element_type)}]"
        case RecordType():
            # type_ here is the RecordType-Object
            if type_.name:  # check the name
                return type_.name
            fields_str = ", ".join(f"{k}: {type_to_str(v)}" for k, v in type_.fields.items())
            return f"{{{fields_str}}}"
        case MixedType(cases, name):
            # If the type has a name, display only the name (similar to LiteralType)
            if name is not None:
                return name
            # Otherwise, represent it as a union
            cases_str = " | ".join(type_to_str(c) for c in cases)
            return cases_str
        case TupleType() as tt:
            inner = ", ".join(type_to_str(t) for t in tt.element_types)
            return f"tuple[{inner}]"
        case TypeRef(name):
            return name
        case FunctionType(parameter_types, return_type):
            parameter_types_str = ", ".join(type_to_str(parameter_type) for parameter_type in parameter_types)
            return_type_str = type_to_str(return_type)
            return f"Callable[[{parameter_types_str}], {return_type_str}]"
        case _:
            raise UnexpectedValueError(type_)


def expression_to_str(expression: Expression | Hole) -> str:
    match expression:
        case None:
            return "<?>"

        case Identifier(value):
            return value

        case ConstantType(value):
            return repr(value) if isinstance(value, str) else str(value)

        case Hole() as h:
            # print list_hole as list: [1, 2 [*]]
            if getattr(h, "kind", "normal") == "list":
                elems = getattr(h, "list_elements", []) or []
                inner = ", ".join(expression_to_str(e) for e in elems)

                # empty list: [[*]]
                if inner.strip() == "":
                    return f"[{hole_to_str(h)}]"

                return f"[{inner} {hole_to_str(h)}]"

            # normal hole: [0] or [0*]
            return hole_to_str(h)
        case EIndex(seq, index):
            return f"{pretty_expr(seq)}[{pretty_expr(index)}]"
        case ESlice(seq, lower, upper):
            lo = "" if lower is None else pretty_expr(lower)
            hi = "" if upper is None else pretty_expr(upper)
            return f"{pretty_expr(seq)}[{lo}:{hi}]"
        case InjectedExpression(value):
            return value
        case EConst(v):
            return repr(v) if isinstance(v, str) else str(v)
        case EList(elts, _element_type):
            inner = ", ".join(expression_to_str(e) for e in elts)
            return f"[{inner}]"
        case EVar(name):
            return name.value
        case EOp1(op, operand):
            return f"{op}{expression_to_str(operand)}"
        case EOp2(left, op, right):
            return f"({expression_to_str(left)} {op} {expression_to_str(right)})"
        case EFunCall(func, args):
            args_str = ", ".join(expression_to_str(a) for a in args)
            return f"{expression_to_str(func)}({args_str})"
        case EIf(test, body, orelse):
            return f"({expression_to_str(body)} if {expression_to_str(test)} else {expression_to_str(orelse)})"
        case EBoolOp(op, left, right):
            return f"({expression_to_str(left)} {op} {expression_to_str(right)})"
        case ETuple(elts):
            inner = ", ".join(expression_to_str(e) for e in elts)
            return f"({inner})"
        case EIndex(seq, index):
            return f"{expression_to_str(seq)}[{expression_to_str(index)}]"
        case ESlice(seq, lower, upper):
            lo = "" if lower is None else expression_to_str(lower)
            hi = "" if upper is None else expression_to_str(upper)
            return f"{expression_to_str(seq)}[{lo}:{hi}]"
        case _:
            return str(expression)  # fallback


def statement_to_str(statement: Statement | Hole, program, indent_level: int = 0) -> str:
    match statement:
        case Hole():
            return hole_to_str(statement)
        case EmptyStatement():
            return ""
        case DescriptionStatement(value):
            return f"{pad_str(value, '\n# ')}"
        case CompositeStatement(first, second):
            first_str = statement_to_str(first, program)
            second_str = statement_to_str(second, program)
            return f"{first_str}\n{second_str}"
        case DataDeclaration(name, parameters):
            name_str = identifier_to_str(name)
            # parameters is a dict[str, Type]; convert each field into the form "name: type"
            params_str = "\n    ".join(f"{k}: {type_to_str(v)}" for k, v in parameters.items())
            if params_str:
                return f"@dataclass\nclass {name_str}:\n    {params_str}"
            else:
                return f"@dataclass\nclass {name_str}:\n    pass"
        case FunctionDeclaration(name, function_type, parameters, statement):
            name_str = identifier_to_str(name)
            parameter_list: list[str] = []
            for parameter, parameter_type in zip(parameters, function_type.parameter_types):
                parameter_str = identifier_to_str(parameter)
                parameter_type_str = type_to_str(parameter_type)
                parameter_list.append(f"{parameter_str}: {parameter_type_str}")
            parameter_list_str = ", ".join(parameter_list)
            return_type_str = type_to_str(function_type.return_type)
            signature_str = f"def {name_str}({parameter_list_str}) -> {return_type_str}:"
            statement_str = statement_to_str(statement, program)
            return f"{signature_str}\n{pad_str(statement_str, '    ')}"
        case ReturnStatement(value, _):
            val_str = expression_to_str(value)
            return f"return {val_str}"
        case VariableDeclaration(name, type_, expression):
            name_str = identifier_to_str(name)
            type_str = type_to_str(type_)
            expression_str = expression_to_str(expression)
            return f"{name_str}: {type_str} = {expression_str}"
        case TypeDeclaration(name, type_):
            name_str = identifier_to_str(name)
            # Always render LiteralType explicitly as Literal[...]
            if isinstance(type_, MixedType):
                rhs = " | ".join(type_to_str(c) for c in type_.cases)
                return f"type {name_str} = {rhs}"
            elif isinstance(type_, LiteralType):
                cases_str = ", ".join(repr(c.value) for c in type_.cases)
                return f"type {name_str} = Literal[{cases_str}]"
            type_str_ = type_to_str(type_)
            return f"type {name_str} = {type_str_}"
        case SFor(var, iterable, body):
            var_str = identifier_to_str(var)  # var is Identifier or Hole(intro)
            it_str = expression_to_str(iterable)

            body_str = "\n".join(statement_to_str(s, program) for s in body)
            return f"for {var_str} in {it_str}:\n{indent(body_str)}"

        case SMatch(expr, cases):
            expr_str = expression_to_str(expr)
            cases_str = []

            for c in cases:
                body_str = "\n".join(statement_to_str(s, program) for s in c.body)
                pvs = c.pattern_values or []
                if pvs:
                    fields_str = ", ".join(hole_to_str(h) for h in pvs)
                    if c.pattern == "":
                        # Tuple-Pattern: case ([0], [1], [2]):
                        pattern_str = f"({fields_str})"
                    else:
                        # RecordType or Primitive (e.g. str): case Predator(...): / case str(...):
                        pattern_str = f"{c.pattern}({fields_str})"

                else:
                    # Kein pattern_values: entweder RecordType ohne Felder ODER Literal
                    if c.pattern in program.defined_types:
                        # RecordType without fields: Handy()
                        if c.pattern.isidentifier() and not c.pattern_values:
                            pattern_str = f"{c.pattern}()"
                        else:
                            pattern_str = c.pattern
                    else:
                        # Literal pattern: 'cat', 'dog', ...
                        pattern_str = repr(c.pattern)

                cases_str.append(f"case {pattern_str}:\n{indent(body_str)}")

            joined_cases = "\n".join(cases_str)
            return f"match {expr_str}:\n{indent(joined_cases)}"

        case SIf(test, body, orelse):
            body_str = "\n".join(statement_to_str(s, program) for s in body)
            # Prüfe, ob orelse nur ein einzelner Hole ist -> direkt inline ohne extra indent
            if len(orelse) == 1 and isinstance(orelse[0], Hole):
                orelse_str = statement_to_str(orelse[0], program)
                return f"if {pretty_expr(test)}:\n{indent(body_str)}\nelse:\n    {orelse_str}"
            # sonst normale verschachtelte orelse
            orelse_str = "\n".join(statement_to_str(s, program) for s in orelse)
            return f"if {pretty_expr(test)}:\n{indent(body_str)}\nelse:\n{indent(orelse_str)}"
        case _:
            raise UnexpectedValueError(statement)


def program_contains_data(stmt: Any) -> bool:
    """Checks whether a DataDeclaration occurs anywhere in the AST."""
    match stmt:
        case DataDeclaration(_, _):
            return True

        case CompositeStatement(first, second):
            return program_contains_data(first) or program_contains_data(second)

        case FunctionDeclaration(_, _, _, body):
            return program_contains_data(body)

        case VariableDeclaration(_, _, expr):
            return program_contains_data(expr)

        case ReturnStatement(value, _):
            return program_contains_data(value)

        case SIf(_, body, orelse):
            return any(program_contains_data(s) for s in body) or any(program_contains_data(s) for s in orelse)
        case SMatch(_, cases):
            return any(any(program_contains_data(s) for s in c.body) for c in (cases or []) if c is not None)
        case Hole() as h:
            # If the hole is filled, continue searching inside it
            return program_contains_data(h.filler) if h.filler is not None else False

        case _:
            return False


def program_to_str(program: Program) -> str:
    parts: list[str] = []
    if program_contains_data(program.statement):
        parts.append("from dataclasses import dataclass\n")

    parts.append(statement_to_str(program.statement, program))
    return "\n".join(parts)
