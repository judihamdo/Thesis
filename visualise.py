from typing import Optional
from utility import UnexpectedValueError, pad_str
from program import *

def indent(text: str, level: int = 1, spaces: int = 4) -> str:
    """Rückt jeden Zeilenanfang um `level * spaces` Leerzeichen ein."""
    prefix = " " * (level * spaces)
    return "\n".join(prefix + line if line.strip() != "" else line for line in text.splitlines())

def hole_to_str(hole) -> str:
    if isinstance(hole, Identifier):
        return hole.value
    return f"[{hole.index}{'*' if hole.selected else ''}]"

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
        case RecordType():
            # type_ ist hier das RecordType-Objekt
            if type_.name:  # Name prüfen
                return type_.name
            fields_str = ", ".join(f"{k}: {type_to_str(v)}" for k, v in type_.fields.items())
            return f"{{{fields_str}}}"
        case MixedType(cases, name):
            # Wenn benannt: nur Namen anzeigen (wie bei LiteralType)
            if name is not None:
                return name
            # sonst als Union ausgeben
            cases_str = " | ".join(type_to_str(c) for c in cases)
            return cases_str

        case FunctionType(parameter_types, return_type):
            parameter_types_str = ", ".join(type_to_str(parameter_type) for parameter_type in parameter_types)
            return_type_str = type_to_str(return_type)
            return f"Callable[[{parameter_types_str}], {return_type_str}]"
        case _:
            raise UnexpectedValueError(type_)

def expression_to_str(expression: Expression | Hole) -> str:
    match expression:
        case Hole():
            return hole_to_str(expression)
        case InjectedExpression(value):
            return value
        case EConst(v):
            return repr(v) if isinstance(v, str) else str(v)

            return str(value)
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
        case _:
            return str(expression)  #fallback

def statement_to_str(statement: Statement | Hole, program, indent_level: int = 0) -> str:
    match statement:
        case Hole():
            return hole_to_str(statement)
        case EmptyStatement():
                return ""
        case DescriptionStatement(value):
            return f'{pad_str(value, "# ")}'
        case CompositeStatement(first, second):
            first_str = statement_to_str(first, program)
            second_str = statement_to_str(second, program)
            return f"{first_str}\n{second_str}"
        case DataDeclaration(name, parameters):
            name_str = identifier_to_str(name)
            # parameters ist dict[str, Type], wir wandeln jedes Feld in "name: type" um
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
            return f'{signature_str}\n{pad_str(statement_str, "    ")}'
        case ReturnStatement(value, expected_type):
            val_str = expression_to_str(value)
            return f"return {val_str}"
        case VariableDeclaration(name, type_, expression):
            name_str = identifier_to_str(name)
            type_str = type_to_str(type_)
            expression_str = expression_to_str(expression)
            return f"{name_str}: {type_str} = {expression_str}"
        case TypeDeclaration(name, type_):
            name_str = identifier_to_str(name)
            # LiteralType immer explizit als Literal[...] ausgeben
            if isinstance(type_, MixedType):
                rhs = " | ".join(type_to_str(c) for c in type_.cases)
                return f"type {name_str} = {rhs}"
            elif isinstance(type_, LiteralType):
                cases_str = ", ".join(repr(c.value) for c in type_.cases)
                return f"type {name_str} = Literal[{cases_str}]"
            type_str_ = type_to_str(type_)
            return f"type {name_str} = {type_str_}"
        



            
        case SMatch(expr, cases):
            expr_str = expression_to_str(expr)
            cases_str = []
            for c in cases:
                body_str = "\n".join(statement_to_str(s, program) for s in c.body)
                pattern_str = c.pattern

                # RecordType-Pattern: bei dir sind das normalerweise Dataclass-Namen (Handy, Computer, ...)
                # Wenn pattern_values vorhanden ist:
                #if hasattr(c, "pattern_values"):#früher
                if c.pattern in program.defined_types: #RecordType
                    if c.pattern_values is not None:
                        # >0 Felder (oder auch 0 als leere Liste, falls du das mal so machst)
                        fields_str = ", ".join(hole_to_str(h) for h in c.pattern_values)
                        pattern_str = f"{pattern_str}({fields_str})"
                    else:
                        # pattern_values is None -> das ist genau dein Fall: Handy ohne Felder
                        # Aber NICHT für Literals! Daher nur bei "Klassen-Namen" (heuristisch: Identifier + Großbuchstabe)
                        if pattern_str.isidentifier() and pattern_str[0].isupper():
                            pattern_str = f"{pattern_str}()"

                else: #füer literaltype
                    pattern_str = repr(pattern_str)

                cases_str.append(f"case {pattern_str}:\n{indent(body_str)}")

            joined_cases = "\n".join(cases_str)
            return f"match {expr_str}:\n{indent(joined_cases)}"
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

def program_to_str(program: Program) -> str:
    #print(program.defined_types)
    print(program.variables)
    for pi, pa in program.defined_types.items():
        print(pi, pa)
    return statement_to_str(program.statement, program)















