from dataclasses import dataclass
from program import *
from immutable_list import IList
from typing import TypeAlias, Any
import ast

TCtx: TypeAlias = dict[str, Type]
# ----------------------
# Fehlerklasse
# ----------------------
@dataclass
class TypeError(Exception):
    msg: str
# ----------------------
# Hilfsfunktionen
# ----------------------
def does_block_always_return(block: IList[Statement]) -> bool:
    #Ein Block returnt sicher, wenn irgendein Statement darin sicher returnt
    #(denn danach ist alles unerreichbar).
    if not block:
        return False
    for stmt in block:
        if does_stmt_always_return(stmt):
            return True
    return False

def does_stmt_always_return(s: Statement) -> bool:
    # Prüft, ob ein Statement auf allen Pfaden return gibt 
    match s:
        case ReturnStatement(_):
            return True
        case CompositeStatement(first, second):
            # Sequenz: wenn first sicher returnt, ist second egal,
            # sonst muss second sicher returnen
            return does_stmt_always_return(first) or does_stmt_always_return(second)
        case SIf(_, body, orelse):
            return does_block_always_return(body) and does_block_always_return(orelse)
        case SMatch(_, cases):
            # Match: alle Cases müssen sicher returnen
            return all(does_block_always_return(c.body) for c in (cases or []))
        case _:
            return False

def ctx_from_program(program: Program) -> dict[str, Type]:
    #Baut Typ-Kontext aus einem Program-Objekt 
    ctx: dict[str, Type] = {}
    def collect(node: Any):
        match node:
            case FunctionDeclaration(name, function_type, parameters, stmt):
                ctx[name.value] = function_type
                for i, param in enumerate(parameters):
                    if isinstance(param, Identifier):
                        ctx[param.value] = function_type.parameter_types[i]
                collect(stmt)
            case VariableDeclaration(name, type_, expr):
                ctx[name.value] = type_
            case CompositeStatement(first, second):
                collect(first)
                collect(second)
            case SIf(_, body, orelse):
                for stmt in (body or []): collect(stmt)
                for stmt in (orelse or []): collect(stmt)
            case SMatch(expr, cases):
                collect(expr)
                for c in (cases or []):
                    if c is None:
                        continue
                    for h in (getattr(c, "pattern_values", []) or []):
                        if h is not None:
                            collect(h)
                    for stmt in (c.body or []):
                        if stmt is not None:
                            collect(stmt)
            case TypeDeclaration(_, _):
                pass
            case _:
                pass
    collect(program.statement)
    return ctx
# ----------------------
# Type-Checking Hauptfunktion
# ----------------------
def type_check(program: Program) -> None:
    """ Type-Checker für das gesamte Programm """
    ctx: TCtx = {name: record if isinstance(record, Type) else RecordType(fields=record, name=name)
                 for name, record in program.defined_types.items()}
    type_check_stmt(ctx, program.statement, program)
# ----------------------
# Statements prüfen
# ----------------------
def type_check_stmts(ctx: TCtx, ss: IList[Statement], program: Program) -> None:
    for s in ss:
        type_check_stmt(ctx, s, program)

def type_check_stmt(ctx: TCtx, s: Statement, program: Program, expected_return_type: Type | None = None) -> None:
    """ Type-Check für ein Statement """
    match s:
        case ReturnStatement(expr):
            if isinstance(expr, Hole):
                return
            if expected_return_type is None:
                raise TypeError("ReturnStatement outside of function")
            t = type_check_expr(ctx, expr, program)
            check_type_equal(t, expected_return_type, s)
        case CompositeStatement(first, second):
            type_check_stmt(ctx, first, program, expected_return_type)
            type_check_stmt(ctx, second, program, expected_return_type)
        case DataDeclaration(name, parameters):
            # RecordType für Type-Checker erzeugen
            record_type = RecordType(fields=parameters, name=name.value)
            ctx[name.value] = record_type
            program.defined_types[name.value] = record_type
            return DataDeclaration(name, parameters)
        case VariableDeclaration(name, type_, expression):
            # Identifier → RecordType auflösen
            if isinstance(type_, Identifier) and type_.value in program.defined_types:
                type_ = program.defined_types[type_.value]
                if isinstance(type_, dict):
                    type_ = RecordType(fields=type_, name=type_.value)
            if not isinstance(expression, Hole):
                t_expr = type_check_expr(ctx, expression, program)
                check_type_equal(t_expr, type_, expression)
            ctx[name.value] = type_
        case SExpr(e):
            _ = type_check_expr(ctx, e, program)
        case SAssign(x, e):
            name = x.value if isinstance(x, Identifier) else x
            te = type_check_expr(ctx, e, program)
            if name in ctx:
                check_type_equal(te, ctx[name], s)
            else:
                ctx[name] = te
        case SMatch(expr, cases):
            type_check_expr(ctx, expr, program)

            for case_ in (cases or []):
                ctx_case = ctx.copy()

                pvals = (getattr(case_, "pattern_values", []) or [])

                # 1) Falls pattern_values noch Holes sind (z.B. vor dem intro)
                for pv in pvals:
                    if isinstance(pv, Hole) and isinstance(pv.filler, Identifier):
                        ctx_case[pv.filler.value] = pv.type
                        
                # 2) Falls pattern_values schon Identifiers sind (nach intro + cleaning):
                #    Typen aus dem RecordType ableiten anhand des Case-Namens (pattern)
                if pvals and all(isinstance(pv, Identifier) for pv in pvals):
                    rec = program.defined_types.get(case_.pattern)

                    # defined_types kann dict oder RecordType enthalten
                    if isinstance(rec, dict):
                        field_types = list(rec.values())
                    elif isinstance(rec, RecordType):
                        field_types = list(rec.fields.values())
                    else:
                        field_types = []

                    # Identifier-Liste positional mit Feldtypen zippen
                    for ident, ty in zip(pvals, field_types):
                        ctx_case[ident.value] = ty

                # Body prüfen im Case-Kontext
                for stmt in (case_.body or []):
                    type_check_stmt(ctx_case, stmt, program, expected_return_type)

            return

            """case SMatch(expr, cases):
            # Typ des Match-Ausdrucks prüfen
            type_check_expr(ctx, expr, program)
            for case_ in (cases or []):
                ctx_case = ctx.copy()  # neuer Kontext pro Case
                # Pattern-Variablen (intro-holes) in den Case-Kontext bringen
                for h in (getattr(case_, "pattern_values", []) or []):
                    if isinstance(h, Hole) and isinstance(h.filler, Identifier):
                        # Hole trägt den Typ im h.type
                        ctx_case[h.filler.value] = h.type
                # Body prüfen im Case-Kontext
                for stmt in (case_.body or []):
                    type_check_stmt(ctx_case, stmt, program, expected_return_type)
            return"""
        case SIf(test, body, orelse):
            ttest = type_check_expr(ctx, test, program)
            check_type_equal(ttest, TBool(), test)
            ctx_body = ctx.copy()
            ctx_orelse = ctx.copy()
            type_check_stmts(ctx_body, body, program)
            type_check_stmts(ctx_orelse, orelse, program)
            if expected_return_type is not None:
                all_branches_return = all(does_stmt_always_return(stmt) for stmt in body) and \
                                      all(does_stmt_always_return(stmt) for stmt in orelse)
                if not all_branches_return:
                    for stmt in body + orelse:
                        if isinstance(stmt, Hole) and "empty" in getattr(stmt, "tactics", []):
                            continue
                        elif not does_stmt_always_return(stmt):
                            raise TypeError(f"Not all branches of SIf return a value in {s}")
        case _:
            pass
# ----------------------
# Expressions prüfen
# ----------------------
def type_check_expr(ctx: TCtx, e: Expression, program: Program) -> Type:
    match e:
        #new for new
        case Hole() as h:
            # unfilled expression hole
            if h.filler is None:
                if h.type is None:
                    raise TypeError("Unfilled expression hole has no type")
                return h.type
            # filled hole -> type of filler
            return type_check_expr(ctx, h.filler, program)

            """case EFunCall(func_expr, arg_exprs):
            if not isinstance(func_expr, EVar):
                raise TypeError(f"This is unsupported function expression: {func_expr}")

            name = func_expr.name.value
            if name not in ctx:
                raise TypeError(f"Function {name} not defined")

            f = ctx[name]

            # Parameter-Typen + Return-Typ bestimmen
            if isinstance(f, FunctionType):
                param_types = f.parameter_types
                ret_type = f.return_type
            elif isinstance(f, RecordType):
                # RecordType als "Konstruktor": args = Feldtypen, Rückgabe = RecordType selbst
                param_types = list(f.fields.values())
                ret_type = f
            else:
                raise TypeError(f"{name} is not callable")

            if len(arg_exprs) != len(param_types):
                raise TypeError(f"{name} expects {len(param_types)} args")

            for arg, expected in zip(arg_exprs, param_types):
                # Hole in Ausdruck-Position ist erlaubt
                if isinstance(arg, Hole):
                    if arg.filler is None:
                        arg.type = arg.type or expected
                        check_type_equal(arg.type, expected, arg)
                    else:
                        t = type_check_expr(ctx, arg.filler, program)
                        check_type_equal(t, expected, arg)
                else:
                    t = type_check_expr(ctx, arg, program)
                    check_type_equal(t, expected, arg)

            return ret_type"""
        case EFunCall(func_expr, arg_exprs):
            if not isinstance(func_expr, EVar):
                raise TypeError(f"This is unsupported function expression: {func_expr}")

            fname = func_expr.name.value
            if fname not in ctx:
                raise TypeError(f"Function {fname} not defined")

            ftype = ctx[fname]

            # Parameter- und Return-Typ bestimmen
            if isinstance(ftype, FunctionType):
                param_types = ftype.parameter_types
                ret_type = ftype.return_type
            elif isinstance(ftype, RecordType):
                # RecordType wird wie ein Konstruktor aufgerufen:
                # args = Feldtypen (in Definition-Reihenfolge), return = RecordType selbst
                param_types = list(ftype.fields.values())
                ret_type = ftype
            else:
                raise TypeError(f"{fname} is not callable")

            if len(arg_exprs) != len(param_types):
                raise TypeError(f"{fname} expects {len(param_types)} args")

            for arg, expected in zip(arg_exprs, param_types):
                # Holes als Argumente erlauben (z.B. Mobile([0],[1]))
                if isinstance(arg, Hole):
                    if arg.filler is None:
                        arg.type = arg.type or expected
                        check_type_equal(arg.type, expected, arg)
                    else:
                        t = type_check_expr(ctx, arg.filler, program)
                        check_type_equal(t, expected, arg)
                else:
                    t = type_check_expr(ctx, arg, program)
                    check_type_equal(t, expected, arg)

            return ret_type


        case InjectedExpression(value):
            if value in ctx:
                return ctx[value]
            try:
                val_ast = ast.parse(value, mode="eval")
                expr = map_node(val_ast.body)
                return type_check_expr(ctx, expr, program)
            except Exception:
                raise TypeError(f"Can't evaluate InjectedExpression {value}")
        case EBoolOp(op, left, right):
            t1 = type_check_expr(ctx, left, program)
            t2 = type_check_expr(ctx, right, program)
            check_type_equal(t1, TBool(), left)
            check_type_equal(t2, TBool(), right)
            return TBool()
        case EConst(x):
            match x:
                case bool(): return TBool()
                case int(): return TInt()
                case float(): return TFloat()
                case complex(): return TComplex()
                case str(): return TStr()
                case _: raise TypeError(f"Unsupported constant type: {type(x)}")
        case EVar(name):
            if name.value in ctx:
                return ctx[name.value]
            if name.value in program.defined_types:
                ty = program.defined_types[name.value]
                if isinstance(ty, dict):
                    return RecordType(fields=ty, name=name.value)
                return ty
            raise TypeError(f"Unknown variable/type {name.value}")
        case EOp1(op, e):
            te = type_check_expr(ctx, e, program)
            match op:
                case "-":
                    if isinstance(te, TInt): return TInt()
                    if isinstance(te, TFloat): return TFloat()
                    if isinstance(te, TComplex): return TComplex()
                    raise TypeError(f"Unary '-' not supported for type {te} in {e}")
        case EOp2(left, op, right):
            t1 = type_check_expr(ctx, left, program)
            t2 = type_check_expr(ctx, right, program)
            match op:
                case "+" | "-" | "*" | "/":
                    if isinstance(t1, TInt) and isinstance(t2, TInt): return TInt()
                    if isinstance(t1, TFloat) and isinstance(t2, (TInt, TFloat)): return TFloat()
                    if isinstance(t1, TInt) and isinstance(t2, TFloat): return TFloat()
                    if isinstance(t1, TComplex) or isinstance(t2, TComplex): return TComplex()
                    if isinstance(t1, TStr) and isinstance(t2, TStr) and op == "*": return TStr()
                    raise TypeError(f"Operator {op} not supported for types {t1}, {t2}")
                case "and" | "or":
                    check_type_equal(t1, TBool(), left)
                    check_type_equal(t2, TBool(), right)
                    return TBool()
                case "==" | "!=" | "<" | ">" | "<=" | ">=":
                    check_type_equal(t1, t2, left)
                    return TBool()
        case EIf(test, body, orelse):
            ttest = type_check_expr(ctx, test, program)
            tbody = type_check_expr(ctx, body, program)
            torelse = type_check_expr(ctx, orelse, program)
            check_type_equal(ttest, TBool(), test)
            check_type_equal(tbody, torelse, e)
            return tbody
        case _:
            raise TypeError(f"Unknown expression-type: {e}")
# ----------------------
# Hilfsfunktionen
# ----------------------
def check_expr(ctx: TCtx, e: Expression, ty: Type, program: Program) -> None:
    te = type_check_expr(ctx, e, program)
    check_type_equal(te, ty, e)

def check_type_equal(thave: Type, texpect: Type, es: Expression | Statement) -> None:
    # erlaubte automatische Promotion: int → float/complex
    if isinstance(thave, TInt) and isinstance(texpect, (TFloat, TComplex)): return
    if isinstance(thave, TFloat) and isinstance(texpect, TComplex): return
    if thave == texpect: return
    if isinstance(texpect, MixedType):
        for alt in texpect.cases:
            try:
                check_type_equal(thave, alt, es)
                return  # passt zu einer Alternative
            except TypeError:
                pass
        raise TypeError(f"Expected {texpect}, got {thave} in {es}")
    raise TypeError(f"Expected {texpect}, got {thave} in {es}")

def check_ctx_equal(ctx1: TCtx, ctx2: TCtx, es: Expression | Statement) -> None:
    for x in ctx1.keys():
        if x in ctx2:
            check_type_equal(ctx1[x], ctx2[x], es)
