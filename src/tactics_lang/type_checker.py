import ast
from typing import TypeAlias

from .ast_converter import map_node
from .immutable_list import IList
from .program import (
    CompositeStatement,
    DataDeclaration,
    EBoolOp,
    EConst,
    EFunCall,
    EIf,
    EIndex,
    EList,
    EOp1,
    EOp2,
    ESlice,
    ETuple,
    EVar,
    # Expressions
    Expression,
    FunctionType,
    Hole,
    Identifier,
    InjectedExpression,
    ListType,
    MixedType,
    Program,
    RangeType,
    RecordType,
    ReturnStatement,
    SExpr,
    SIf,
    SMatch,
    # Statements
    Statement,
    TBool,
    TComplex,
    TFloat,
    TInt,
    TStr,
    TupleType,
    # Types
    Type,
    TypeRef,
    VariableDeclaration,
)
from .utility import TypeCheckerError

TCtx: TypeAlias = dict[str, Type]


# ----------------------
# Helper functions
# ----------------------
def does_block_always_return(block: IList[Statement]) -> bool:
    """A block guarantees a return if any statement in it guarantees a return
    (since everything after that becomes unreachable)."""
    if not block:
        return False
    for stmt in block:
        if does_stmt_always_return(stmt):
            return True
    return False


def does_stmt_always_return(s: Statement) -> bool:
    """checks, if a Statement has 'return' in all paths"""
    match s:
        case ReturnStatement(_):
            return True
        case CompositeStatement(first, second):
            # Sequence: if the first statement guarantees a return, the second is irrelevant;
            # otherwise the second must guarantee a return , it is helpful in nested case
            return does_stmt_always_return(first) or does_stmt_always_return(second)
        # Return must be garanteed in both brachnes if & else
        case SIf(_, body, orelse):
            return does_block_always_return(body) and does_block_always_return(orelse)
        case SMatch(_, cases):
            # In a match statement, all cases must guarantee a return
            return all(does_block_always_return(c.body) for c in (cases or []))
        case _:
            return False


# ***********************************************************************************************************
def typecheck_or_rollback(interpreter, expected: Type, err_prefix: str, hole, ctx, filler) -> bool:
    """Returns True if type checking succeeds; otherwise rolls back the hole filler and returns False."""
    try:
        expr_type = type_check_expr(ctx, filler, interpreter.program)
        check_type_equal(expr_type, expected, filler, interpreter.program)
        return True
    except TypeCheckerError as e:
        print(f"❌ {err_prefix}{e}")
        hole.filler = None
        return False


def typecheck_filler(interp, hole, parent_decl, ctx, filler) -> bool:
    # Return-hole
    if getattr(hole, "is_return_hole", False):
        return typecheck_or_rollback(interp, interp.return_type, "Typfehler beim Return: ", hole, ctx, filler)

    # expression holes with expected type
    if hole.type is not None and ("fill" in hole.tactics or "new" in hole.tactics):
        return typecheck_or_rollback(interp, hole.type, "Typfehler: ", hole, ctx, filler)

    # Fallback: use the initializer of the VariableDeclaration.
    if parent_decl is not None:
        return typecheck_or_rollback(interp, parent_decl.type_, "Typfehler: ", hole, ctx, filler)

    return True  # nothing to check


# ***********************************************************************************************************
def _get_list_len_if_known(seq: Expression, program: Program) -> int | None:
    """Return the known length of a list (or nested list) expression if it can be determined, otherwise None.
    Example: _get_list_len_if_known(new_test[0], program) -> ("new_test", (0)) -> 3"""
    # xs
    if isinstance(seq, EVar):
        # n = program.list_lengths.get("xs")
        n = program.list_lengths.get(seq.name.value)
        return n if isinstance(n, int) else None

    # Length of nested lists, e.g. seq = new_test[0][0] (The full expression)
    path: list[int] = []
    cur = seq
    while isinstance(cur, EIndex):
        try:
            idx = _require_int_const(cur.index)
        except (TypeCheckerError, AttributeError, TypeError):
            return None
        path.append(idx)
        cur = cur.seq

    if isinstance(cur, EVar):
        base = cur.name.value
        path = list(reversed(path))
        return program.nested_list_lengths.get((base, tuple(path)))

    return None


def _require_int_const(e: Expression) -> int:
    """Is the Index an integer Constant? not x+i for example?"""
    # 1) normal constants: 0, 1, 2
    if isinstance(e, EConst) and isinstance(e.value, int) and not isinstance(e.value, bool):
        return e.value

    # 2) Negative constant: -1 is parsed as EOp1("-", EConst(1))
    if isinstance(e, EOp1) and e.op == "-" and isinstance(e.operand, EConst):
        v = e.operand.value
        if isinstance(v, int) and not isinstance(v, bool):
            return -v

    raise TypeCheckerError("❌ Index/slice bound must be an int constant")


def _slice_bound(e: Expression | None) -> int | None:
    """Return the integer value of a slice bound, or None if the bound is omitted."""
    if e is None:
        return None
    return _require_int_const(e)


# ----------------------
# Expressions checking
# ----------------------
def type_check_expr(ctx: TCtx, e: Expression, program: Program, len_ctx: dict[str, int | None] | None = None) -> Type:
    """Infers and returns the type of an expression, or raises a type error if the expression is invalid."""
    if len_ctx is None:
        len_ctx = {}
    match e:
        # new for new
        case Hole() as h:
            # unfilled expression hole
            if h.filler is None:
                if h.type is None:
                    raise TypeCheckerError("❌ Unfilled expression hole has no type")
                return h.type
            # filled hole -> type of filler
            return type_check_expr(ctx, h.filler, program, len_ctx=len_ctx)

        case EFunCall(func_expr, arg_exprs):
            if not isinstance(func_expr, EVar):
                raise TypeCheckerError(f"❌ This is unsupported function expression: {func_expr}")

            fname = func_expr.name.value
            # --- SPECIAL: built-in range(int) -> RangeType(int) ---
            if fname == "range":
                if len(arg_exprs) != 1:
                    raise TypeCheckerError("❌ range expects exactly one argument")
                t0 = type_check_expr(ctx, arg_exprs[0], program, len_ctx=len_ctx)
                check_type_equal(t0, TInt(), arg_exprs[0], program)
                return RangeType(TInt())

            if fname not in ctx:
                raise TypeCheckerError(f"❌ Function {fname} not defined")
            ftype = ctx[fname]

            # Determine the parameter and return type
            if isinstance(ftype, FunctionType):
                param_types = ftype.parameter_types
                ret_type = ftype.return_type
            elif isinstance(ftype, RecordType):
                # A RecordType behaves like a constructor:
                # arguments = field types (in definition order), return type = the RecordType itself
                param_types = list(ftype.fields.values())
                ret_type = ftype
            else:
                raise TypeCheckerError(f"❌ {fname} is not callable")

            if len(arg_exprs) != len(param_types):
                raise TypeCheckerError(f"❌ {fname} expects {len(param_types)} args")

            for arg, expected in zip(arg_exprs, param_types):
                # Allow holes as arguments (e.g. Mobile([0],[1]))
                if isinstance(arg, Hole):
                    if arg.filler is None:
                        arg.type = arg.type or expected
                        check_type_equal(arg.type, expected, arg, program)
                    else:
                        t = type_check_expr(ctx, arg.filler, program, len_ctx=len_ctx)
                        check_type_equal(t, expected, arg, program)
                else:
                    t = type_check_expr(ctx, arg, program, len_ctx=len_ctx)
                    check_type_equal(t, expected, arg, program)

            return ret_type
        case InjectedExpression(value):
            if value in ctx:
                return ctx[value]
            try:
                val_ast = ast.parse(value, mode="eval")
                expr = map_node(val_ast.body)
                return type_check_expr(ctx, expr, program, len_ctx=len_ctx)
            except Exception as e:
                raise TypeCheckerError(f"❌ Can't evaluate InjectedExpression {value}") from e
        case EBoolOp(op, left, right):
            t1 = type_check_expr(ctx, left, program, len_ctx=len_ctx)
            t2 = type_check_expr(ctx, right, program, len_ctx=len_ctx)
            check_type_equal(t1, TBool(), left, program)
            check_type_equal(t2, TBool(), right, program)
            return TBool()
        case ETuple(elts):
            ts = [type_check_expr(ctx, x, program) for x in elts]
            return TupleType(ts)
        case EList(elts, element_type=et):
            # Use the provided element_type if available
            if et is not None:
                # All Elements must have et
                for x in elts:
                    tx = type_check_expr(ctx, x, program, len_ctx=len_ctx)
                    check_type_equal(tx, et, x, program)
                return ListType(et)

            # Otherwise: infer it from the first element
            if len(elts) == 0:
                raise TypeCheckerError("❌ Cannot infer type of empty list; use a typed construction via new: list[T] then cons/nil")
            t0 = type_check_expr(ctx, elts[0], program, len_ctx=len_ctx)
            for x in elts[1:]:
                tx = type_check_expr(ctx, x, program, len_ctx=len_ctx)
                check_type_equal(tx, t0, x, program)
            return ListType(t0)

        case EConst(x):
            match x:
                case bool():
                    return TBool()
                case int():
                    return TInt()
                case float():
                    return TFloat()
                case complex():
                    return TComplex()
                case str():
                    return TStr()
                case _:
                    raise TypeCheckerError(f"❌ Unsupported constant type: {type(x)}")
        case EVar(name):
            if name.value in ctx:
                return ctx[name.value]
            if name.value in program.defined_types:
                ty = program.defined_types[name.value]
                if isinstance(ty, dict):
                    return RecordType(fields=ty, name=name.value)
                return ty

            raise TypeCheckerError(f"❌ Unknown variable/type {name.value}")

        case EOp1(op, e):
            te = type_check_expr(ctx, e, program, len_ctx=len_ctx)
            match op:
                case "-":
                    if isinstance(te, TInt):
                        return TInt()
                    if isinstance(te, TFloat):
                        return TFloat()
                    if isinstance(te, TComplex):
                        return TComplex()
                    raise TypeCheckerError(f"❌ Unary '-' not supported for type {te} in {e}")
        case EOp2(left, op, right):
            t1 = type_check_expr(ctx, left, program, len_ctx=len_ctx)
            t2 = type_check_expr(ctx, right, program, len_ctx=len_ctx)
            match op:
                case "+" | "-" | "*" | "/":
                    if isinstance(t1, TInt) and isinstance(t2, TInt):
                        return TInt()
                    if isinstance(t1, TFloat) and isinstance(t2, (TInt, TFloat)):
                        return TFloat()
                    if isinstance(t1, TInt) and isinstance(t2, TFloat):
                        return TFloat()
                    if isinstance(t1, TComplex) or isinstance(t2, TComplex):
                        return TComplex()
                    if isinstance(t1, TStr) and isinstance(t2, TStr) and op == "*":
                        return TStr()
                    raise TypeCheckerError(f"❌ Operator {op} not supported for types {t1}, {t2}")
                case "and" | "or":
                    check_type_equal(t1, TBool(), left, program)
                    check_type_equal(t2, TBool(), right, program)
                    return TBool()
                case "==" | "!=" | "<" | ">" | "<=" | ">=":
                    check_type_equal(t1, t2, left, program)
                    return TBool()
        case EIf(test, body, orelse):
            ttest = type_check_expr(ctx, test, program, len_ctx=len_ctx)
            tbody = type_check_expr(ctx, body, program, len_ctx=len_ctx)
            torelse = type_check_expr(ctx, orelse, program, len_ctx=len_ctx)
            check_type_equal(ttest, TBool(), test, program)
            check_type_equal(tbody, torelse, e, program)
            return tbody

        case EIndex(seq, index):
            len_ctx = len_ctx or {}

            t_seq = type_check_expr(ctx, seq, program, len_ctx=len_ctx)
            t_i = type_check_expr(ctx, index, program, len_ctx=len_ctx)
            check_type_equal(t_i, TInt(), index, program)

            t_seq = resolve_type(t_seq, program)
            if not isinstance(t_seq, ListType):
                raise TypeCheckerError("❌ Indexing only allowed on list[T]")

            # Determine the sequence length: either from a direct variable (xs) or from an indexed element (my_li[0])
            n = _get_list_len_if_known(seq, program)

            if n is not None:
                i = _require_int_const(index)  # allows -1 etc. also
                if not (-n <= i <= n - 1):
                    raise TypeCheckerError(f"❌ Index {i} out of bounds for list of length {n}")
            return t_seq.element_type

        case ESlice(seq, lower, upper):
            len_ctx = len_ctx or {}

            t_seq = type_check_expr(ctx, seq, program, len_ctx=len_ctx)
            t_seq = resolve_type(t_seq, program)

            if not isinstance(t_seq, ListType):
                raise TypeCheckerError("❌ Slicing only allowed on list[T]")

            # Type-check the bounds (if present)
            if lower is not None:
                check_type_equal(type_check_expr(ctx, lower, program, len_ctx=len_ctx), TInt(), lower, program)
            if upper is not None:
                check_type_equal(type_check_expr(ctx, upper, program, len_ctx=len_ctx), TInt(), upper, program)

            # xs[:] always ok
            if lower is None and upper is None:
                return ListType(t_seq.element_type)

            # Extract the bounds as integers (including negative values)
            lo = _slice_bound(lower)  # int | None
            hi = _slice_bound(upper)  # int | None

            # Rule: when both are here, must lo <= hi
            if lo is not None and hi is not None and lo > hi:
                raise TypeCheckerError("❌ Slice lower bound must be <= upper bound")

            # If the length is known: check the bounds
            n = None
            if isinstance(seq, EVar):
                n = program.list_lengths.get(seq.name.value)

            if n is not None:
                # Wir allow None like Python:
                # lower default = 0, upper default = n
                lo_chk = 0 if lo is None else lo
                hi_chk = n if hi is None else hi

                # Python-like index bounds:
                # lower must be in [-n, n-1]
                # upper must be in [-n, n]   (because upper is exclusive and may equal n)
                if not (-n <= lo_chk <= n - 1):
                    raise TypeCheckerError(f"❌ Slice lower {lo_chk} out of bounds for list of length {n}")
                if not (-n <= hi_chk <= n):
                    raise TypeCheckerError(f"❌ Slice upper {hi_chk} out of bounds for list of length {n}")

                # Additionally: check the defaults
                if lo_chk > hi_chk:
                    raise TypeCheckerError("❌ Slice lower bound must be <= upper bound")

            # Result is again list[T]
            return ListType(t_seq.element_type)
        case _:
            raise TypeCheckerError(f"❌ Unknown expression-type: {e}")


def check_expr(
    ctx: TCtx,
    e: Expression,
    ty: Type,
    program: Program,
    len_ctx: dict[str, int | None] | None = None,
) -> None:
    """Checks that an expression has the expected type."""
    te = type_check_expr(ctx, e, program, len_ctx=len_ctx)
    check_type_equal(te, ty, e, program)


# **********************************************************************************************************
def resolve_type(t: Type, program: Program) -> Type:
    """Resolves a TypeRef via program.defined_types, or raises a TypeCheckerError."""
    if isinstance(t, TypeRef):
        name = t.name
        if name not in program.defined_types:
            raise TypeCheckerError(f"❌ Unknown type '{name}'")
        real = program.defined_types[name]
        # defined_types contains sometimes dict (data fields)
        if isinstance(real, dict):
            return RecordType(fields=real, name=name)
        return real
    # If it is not a typRef, stay unchanged
    return t


def check_type_equal(thave: Type, texpect: Type, es: Expression | Statement, program) -> None:
    """Checks whether the actual type is compatible with the expected type, raising an error if not."""
    thave = resolve_type(thave, program)
    texpect = resolve_type(texpect, program)

    # Allowed implicit promotion: int → float or complex
    # If 2 Tuples, compare their type and length
    if isinstance(thave, TupleType) and isinstance(texpect, TupleType):
        if len(thave.element_types) != len(texpect.element_types):
            raise TypeCheckerError(f"❌ Expected {texpect}, got {thave}")
        for a, b in zip(thave.element_types, texpect.element_types):
            check_type_equal(a, b, es, program)
        return
    # If 2 lists, compare their type
    if isinstance(thave, ListType) and isinstance(texpect, ListType):
        check_type_equal(thave.element_type, texpect.element_type, es, program)
        return

    elif isinstance(thave, RangeType) and isinstance(texpect, RangeType):
        check_type_equal(thave.element_type, texpect.element_type, es, program)
        return

    if isinstance(thave, TInt) and isinstance(texpect, (TFloat, TComplex)):
        return
    if isinstance(thave, TFloat) and isinstance(texpect, TComplex):
        return
    if thave == texpect:
        return
    # In this case, the expected type can be one of the alternatives
    if isinstance(texpect, MixedType):
        for alt in texpect.cases:
            try:
                check_type_equal(thave, alt, es, program)
                return  # Matches an alternative
            except TypeCheckerError:
                pass
        raise TypeCheckerError(f"❌ Expected {texpect}, got {thave}")

    raise TypeCheckerError(f"❌ Expected {texpect}, got {thave}")


# ----------------------
# Statements checking
# ----------------------
def type_check_stmts(
    ctx: TCtx,
    ss: IList[Statement],
    program: Program,
    expected_return_type: Type | None = None,
    len_ctx: dict[str, int | None] | None = None,
) -> None:
    if len_ctx is None:
        len_ctx = {}
    for s in ss:
        type_check_stmt(ctx, s, program, expected_return_type, len_ctx=len_ctx)


def type_check_stmt(
    ctx: TCtx,
    s: Statement,
    program: Program,
    expected_return_type: Type | None = None,
    len_ctx=None,
) -> None:
    """Type-Check for a Statement"""
    if len_ctx is None:
        len_ctx = {}
    match s:
        case ReturnStatement(expr):
            if isinstance(expr, Hole):
                return
            if expected_return_type is None:
                raise TypeCheckerError("❌ ReturnStatement outside of function")
            t = type_check_expr(ctx, expr, program, len_ctx=len_ctx)
            check_type_equal(t, expected_return_type, s, program)
        case CompositeStatement(first, second):
            type_check_stmt(ctx, first, program, expected_return_type, len_ctx=len_ctx)
            type_check_stmt(ctx, second, program, expected_return_type, len_ctx=len_ctx)
        case DataDeclaration(name, parameters):
            # Construct a RecordType for the type checker
            record_type = RecordType(fields=parameters, name=name.value)
            ctx[name.value] = record_type
            program.defined_types[name.value] = record_type
            return DataDeclaration(name, parameters)
        case VariableDeclaration(name, type_, expression):
            # Resolve the identifier to its corresponding RecordType
            if isinstance(type_, Identifier) and type_.value in program.defined_types:
                type_ = program.defined_types[type_.value]
                if isinstance(type_, dict):
                    type_ = RecordType(fields=type_, name=type_.value)
            if not isinstance(expression, Hole):
                t_expr = type_check_expr(ctx, expression, program, len_ctx=len_ctx)
                check_type_equal(t_expr, type_, expression, program)
                if isinstance(expression, EList):
                    # name is Identifier
                    len_ctx[name.value] = len(expression.elts)
                else:
                    len_ctx[name.value] = None
            else:
                len_ctx[name.value] = None
            ctx[name.value] = type_
        case SExpr(e):
            _ = type_check_expr(ctx, e, program, len_ctx=len_ctx)

        case SMatch(expr, cases):
            type_check_expr(ctx, expr, program, len_ctx=len_ctx)

            for case_ in cases or []:
                ctx_case = ctx.copy()

                pvals = getattr(case_, "pattern_values", []) or []

                # 1) If pattern_values still contain holes (e.g., before applying intro)
                for pv in pvals:
                    if isinstance(pv, Hole) and isinstance(pv.filler, Identifier):
                        ctx_case[pv.filler.value] = pv.type

                # 2) If pattern_values are already identifiers (after intro and cleaning):
                #    infer their types from the RecordType using the case name (pattern)
                if pvals and all(isinstance(pv, Identifier) for pv in pvals):
                    rec = program.defined_types.get(case_.pattern)

                    # defined_types can contain dict oder RecordType
                    if isinstance(rec, dict):
                        field_types = list(rec.values())
                    elif isinstance(rec, RecordType):
                        field_types = list(rec.fields.values())
                    else:
                        field_types = []

                    # Pair the identifiers with the field types positionally
                    for ident, ty in zip(pvals, field_types):
                        ctx_case[ident.value] = ty

                # Check the body within the case context
                for stmt in case_.body or []:
                    type_check_stmt(ctx_case, stmt, program, expected_return_type, len_ctx=len_ctx)
            return

        case SIf(test, body, orelse):
            ttest = type_check_expr(ctx, test, program, len_ctx=len_ctx)
            check_type_equal(ttest, TBool(), test, program)
            ctx_body = ctx.copy()
            ctx_orelse = ctx.copy()
            type_check_stmts(ctx_body, body, program, len_ctx=len_ctx)
            type_check_stmts(ctx_orelse, orelse, program, len_ctx=len_ctx)
            if expected_return_type is not None:
                all_branches_return = all(does_stmt_always_return(stmt) for stmt in body) and all(does_stmt_always_return(stmt) for stmt in orelse)
                if not all_branches_return:
                    for stmt in body + orelse:
                        if isinstance(stmt, Hole) and "empty" in getattr(stmt, "tactics", []):
                            continue
                        elif not does_stmt_always_return(stmt):
                            raise TypeCheckerError(f"❌ Not all branches of SIf return a value in {s}")
        case _:
            pass


# ---------------------------
# Type-Checking main function
# ---------------------------
def type_check(program: Program) -> None:
    ctx: TCtx = {name: record if isinstance(record, Type) else RecordType(fields=record, name=name) for name, record in program.defined_types.items()}
    len_ctx: dict[str, int | None] = {}
    type_check_stmt(ctx, program.statement, program, len_ctx=len_ctx)
