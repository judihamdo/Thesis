import pytest

from src.tactics_lang.context import ctx_from_program
from src.tactics_lang.program import (
    CompositeStatement,
    EBoolOp,
    EConst,
    EFunCall,
    EIf,
    EIndex,
    EList,
    EOp1,
    EOp2,
    ESlice,
    # Expr/Stmt:
    EVar,
    FunctionType,
    Identifier,
    ListType,
    MixedType,
    Program,
    RangeType,
    RecordType,
    ReturnStatement,
    SExpr,
    SIf,
    TBool,
    TComplex,
    TFloat,
    # Types:
    TInt,
    TStr,
    TupleType,
    TypeRef,
    VariableDeclaration,
)
from src.tactics_lang.type_checker import (
    check_type_equal,
    does_block_always_return,
    does_stmt_always_return,
    resolve_type,
    type_check,
    type_check_expr,
    type_check_stmt,
)
from src.tactics_lang.utility import TypeCheckerError


# ---------------------------
# Helpers for Tests
# ---------------------------
def mk_program(stmt=None) -> Program:
    """Create a minimal Program instance that our type checker functions accept."""
    if stmt is None:
        stmt = SExpr(EConst(0))
    p = Program(stmt)
    if not hasattr(p, "defined_types"):
        p.defined_types = {}
    if not hasattr(p, "list_lengths"):
        p.list_lengths = {}
    if not hasattr(p, "nested_list_lengths"):
        p.nested_list_lengths = {}
    return p


def ctx(**kwargs):
    """
    Context dict[str, Type]
    Example: ctx(xs=ListType(TInt()), x=TInt())
    """
    return {k: v for k, v in kwargs.items()}


# ---------------------------
# does_..._always_return
# ---------------------------
def test_does_stmt_always_return_return_stmt_true():
    s = ReturnStatement(EConst(1))
    assert does_stmt_always_return(s) is True


def test_does_stmt_always_return_composite_first_returns_true():
    s = CompositeStatement(ReturnStatement(EConst(1)), SExpr(EConst(2)))
    assert does_stmt_always_return(s) is True


def test_does_stmt_always_return_composite_second_returns_true():
    s = CompositeStatement(SExpr(EConst(1)), ReturnStatement(EConst(2)))
    assert does_stmt_always_return(s) is True


def test_does_stmt_always_return_if_all_paths_return_true():
    s = SIf(
        test=EConst(True),
        body=[ReturnStatement(EConst(1))],
        orelse=[ReturnStatement(EConst(2))],
    )
    assert does_stmt_always_return(s) is True


def test_does_stmt_always_return_if_not_all_paths_return_false():
    s = SIf(
        test=EConst(True),
        body=[ReturnStatement(EConst(1))],
        orelse=[SExpr(EConst(2))],
    )
    assert does_stmt_always_return(s) is False


def test_does_block_always_return_any_stmt_returns_true():
    block = [SExpr(EConst(1)), ReturnStatement(EConst(2)), SExpr(EConst(3))]
    assert does_block_always_return(block) is True


def test_does_block_always_return_empty_false():
    assert does_block_always_return([]) is False


# ---------------------------
# resolve_type / check_type_equal
# ---------------------------
def test_resolve_type_typeref_to_recordtype_from_dict():
    p = mk_program()
    p.defined_types["Pet"] = {"name": TStr()}
    t = resolve_type(TypeRef("Pet"), p)
    assert isinstance(t, RecordType)
    assert t.name == "Pet"
    assert "name" in t.fields


def test_resolve_type_unknown_typeref_raises():
    p = mk_program()
    with pytest.raises(TypeCheckerError):
        resolve_type(TypeRef("Unknown"), p)


def test_check_type_equal_int_to_float_promotion_ok():
    p = mk_program()
    check_type_equal(TInt(), TFloat(), EConst(1), p)


def test_check_type_equal_mixed_type_accepts_alt():
    p = mk_program()
    m = MixedType(cases=[TInt(), TStr()], name="X")
    check_type_equal(TInt(), m, EConst(1), p)
    with pytest.raises(TypeCheckerError):
        check_type_equal(TBool(), m, EConst(True), p)


def test_check_type_equal_list_type_recurses():
    p = mk_program()
    check_type_equal(ListType(TInt()), ListType(TInt()), EConst(0), p)
    with pytest.raises(TypeCheckerError):
        check_type_equal(ListType(TInt()), ListType(TStr()), EConst(0), p)


def test_check_type_equal_tuple_length_mismatch_raises():
    p = mk_program()
    with pytest.raises(TypeCheckerError):
        check_type_equal(
            TupleType([TInt(), TInt()]),
            TupleType([TInt()]),
            EConst(0),
            p,
        )


# ---------------------------
# type_check_expr Basics
# ---------------------------
def test_type_check_expr_const_types():
    p = mk_program()
    c = ctx()
    assert isinstance(type_check_expr(c, EConst(True), p), TBool)
    assert isinstance(type_check_expr(c, EConst(1), p), TInt)
    assert isinstance(type_check_expr(c, EConst(1.0), p), TFloat)
    assert isinstance(type_check_expr(c, EConst(1 + 2j), p), TComplex)
    assert isinstance(type_check_expr(c, EConst("x"), p), TStr)


def test_type_check_expr_var_from_ctx():
    p = mk_program()
    c = ctx(x=TInt())
    assert isinstance(type_check_expr(c, EVar(Identifier("x")), p), TInt)


def test_type_check_expr_unknown_var_raises():
    p = mk_program()
    c = ctx()
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EVar(Identifier("x")), p)


def test_type_check_expr_list_infers_element_type():
    p = mk_program()
    c = ctx()
    t = type_check_expr(c, EList([EConst(1), EConst(2)]), p)
    assert isinstance(t, ListType)
    assert isinstance(t.element_type, TInt)


def test_type_check_expr_list_mixed_element_types_raises():
    p = mk_program()
    c = ctx()
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EList([EConst(1), EConst("x")]), p)


def test_type_check_expr_list_typed_element_type_ok():
    p = mk_program()
    c = ctx()
    t = type_check_expr(c, EList([EConst(1), EConst(2)], element_type=TInt()), p)
    assert isinstance(t, ListType)
    assert isinstance(t.element_type, TInt)


def test_type_check_expr_empty_list_raises():
    p = mk_program()
    c = ctx()
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EList([]), p)


def test_type_check_expr_unary_minus_int_ok():
    p = mk_program()
    c = ctx()
    t = type_check_expr(c, EOp1("-", EConst(1)), p)
    assert isinstance(t, TInt)


def test_type_check_expr_unary_minus_str_raises():
    p = mk_program()
    c = ctx()
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EOp1("-", EConst("x")), p)


def test_type_check_expr_binop_int_int_plus_int():
    p = mk_program()
    c = ctx()
    t = type_check_expr(c, EOp2(EConst(1), "+", EConst(2)), p)
    assert isinstance(t, TInt)


def test_type_check_expr_boolop_requires_bool():
    p = mk_program()
    c = ctx()
    ok = type_check_expr(c, EBoolOp("and", EConst(True), EConst(False)), p)
    assert isinstance(ok, TBool)
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EBoolOp("and", EConst(1), EConst(True)), p)


def test_type_check_expr_if_requires_bool_test_and_same_branch_types():
    p = mk_program()
    c = ctx()
    ok = type_check_expr(c, EIf(EConst(True), EConst(1), EConst(2)), p)
    assert isinstance(ok, TInt)
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EIf(EConst(1), EConst(1), EConst(2)), p)  # test not bool
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EIf(EConst(True), EConst(1), EConst("x")), p)  # branch mismatch


# ---------------------------
# Indexing + bounds (list_lengths + nested_list_lengths)
# ---------------------------
def test_indexing_on_list_type_ok_and_returns_element_type():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    t = type_check_expr(c, EIndex(EVar(Identifier("xs")), EConst(0)), p)
    assert isinstance(t, TInt)


def test_indexing_out_of_bounds_raises_when_length_known():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    with pytest.raises(TypeCheckerError) as e:
        type_check_expr(c, EIndex(EVar(Identifier("xs")), EConst(4)), p)
    assert "out of bounds" in str(e.value).lower()


def test_indexing_negative_index_ok_when_in_bounds():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    # -1 is parsed as EOp1("-", EConst(1))
    t = type_check_expr(c, EIndex(EVar(Identifier("xs")), EOp1("-", EConst(1))), p)
    assert isinstance(t, TInt)


def test_nested_indexing_bounds_uses_nested_list_lengths():
    p = mk_program()
    c = ctx(my_li=ListType(ListType(TInt())))
    p.nested_list_lengths[("my_li", (0,))] = 3
    inner_seq = EIndex(EVar(Identifier("my_li")), EConst(0))  # my_li[0]
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EIndex(inner_seq, EConst(4)), p)


# ---------------------------
# Slicing + bounds
# ---------------------------


def test_slicing_xs_colon_colon_ok_returns_listtype():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    t = type_check_expr(c, ESlice(EVar(Identifier("xs")), None, None), p)
    assert isinstance(t, ListType)
    assert isinstance(t.element_type, TInt)


def test_slicing_bounds_type_must_be_int():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, ESlice(EVar(Identifier("xs")), EConst("0"), EConst(2)), p)


def test_slicing_lower_greater_than_upper_raises():
    p = mk_program()
    p.list_lengths["xs"] = 5
    c = ctx(xs=ListType(TInt()))
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, ESlice(EVar(Identifier("xs")), EConst(3), EConst(2)), p)


def test_slicing_out_of_bounds_raises_when_length_known():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    with pytest.raises(TypeCheckerError):
        # upper darf max n sein (3) -> 4 ist out-of-bounds
        type_check_expr(c, ESlice(EVar(Identifier("xs")), EConst(0), EConst(4)), p)


def test_slicing_upper_equal_len_ok():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    # upper darf = n sein
    t = type_check_expr(c, ESlice(EVar(Identifier("xs")), EConst(0), EConst(3)), p)
    assert isinstance(t, ListType)


def test_slicing_negative_bounds_ok_if_in_range():
    p = mk_program()
    p.list_lengths["xs"] = 3
    c = ctx(xs=ListType(TInt()))
    lo = EOp1("-", EConst(3))  # -3
    hi = EConst(3)  # 3
    t = type_check_expr(c, ESlice(EVar(Identifier("xs")), lo, hi), p)
    assert isinstance(t, ListType)


# ---------------------------
# range special-case
# ---------------------------
def test_fun_call_range_int_returns_range_type():
    p = mk_program()
    t = type_check_expr(ctx(), EFunCall(EVar(Identifier("range")), [EConst(3)]), p)
    assert isinstance(t, RangeType)
    assert isinstance(t.element_type, TInt)


def test_fun_call_range_wrong_arity_raises():
    p = mk_program()
    with pytest.raises(TypeCheckerError):
        type_check_expr(ctx(), EFunCall(EVar(Identifier("range")), [EConst(1), EConst(2)]), p)


def test_fun_call_range_arg_must_be_int():
    p = mk_program()
    with pytest.raises(TypeCheckerError):
        type_check_expr(ctx(), EFunCall(EVar(Identifier("range")), [EConst("x")]), p)


# ---------------------------
# function calls (normal)
# ---------------------------
def test_fun_call_user_defined_function_ok():
    p = mk_program()
    fty = FunctionType([TInt(), TBool()], TStr())
    c = ctx(f=fty)
    t = type_check_expr(
        c,
        EFunCall(EVar(Identifier("f")), [EConst(1), EConst(True)]),
        p,
    )
    assert isinstance(t, TStr)


def test_fun_call_wrong_arg_type_raises():
    p = mk_program()
    fty = FunctionType([TInt()], TInt())
    c = ctx(f=fty)
    with pytest.raises(TypeCheckerError):
        type_check_expr(c, EFunCall(EVar(Identifier("f")), [EConst("x")]), p)


def test_fun_call_unknown_function_raises():
    p = mk_program()
    with pytest.raises(TypeCheckerError):
        type_check_expr(ctx(), EFunCall(EVar(Identifier("f")), [EConst(1)]), p)


# ---------------------------
# Statements: VariableDeclaration / Return / If
# ---------------------------
def test_type_check_stmt_variable_declaration_sets_ctx_and_checks_rhs():
    p = mk_program()
    c = ctx()
    s = VariableDeclaration(Identifier("x"), TInt(), EConst(1))
    type_check_stmt(c, s, p)
    assert "x" in c
    assert isinstance(c["x"], TInt)


def test_type_check_stmt_variable_declaration_type_mismatch_raises():
    p = mk_program()
    c = ctx()
    s = VariableDeclaration(Identifier("x"), TInt(), EConst("d"))
    with pytest.raises(TypeCheckerError):
        type_check_stmt(c, s, p)


def test_type_check_stmt_if_requires_bool_test():
    p = mk_program()
    c = ctx()
    s = SIf(test=EConst(1), body=[SExpr(EConst(0))], orelse=[SExpr(EConst(0))])
    with pytest.raises(TypeCheckerError):
        type_check_stmt(c, s, p)


def test_type_check_stmt_return_outside_function_raises():
    p = mk_program()
    c = ctx()
    with pytest.raises(TypeCheckerError):
        type_check_stmt(c, ReturnStatement(EConst(1)), p, expected_return_type=None)


def test_type_check_stmt_return_checks_expected_type():
    p = mk_program()
    c = ctx()
    # expected_return_type = int
    with pytest.raises(TypeCheckerError):
        type_check_stmt(c, ReturnStatement(EConst("x")), p, expected_return_type=TInt())


# ---------------------------
# ctx_from_program test
# ---------------------------
def test_ctx_from_program_collects_var_declarations():
    p = mk_program(
        CompositeStatement(
            VariableDeclaration(Identifier("x"), TInt(), EConst(1)),
            SExpr(EConst(0)),
        )
    )
    c = ctx_from_program(p)
    assert "x" in c
    assert isinstance(c["x"], TInt)


# ---------------------------
# type_check(program) test
# ---------------------------
def test_type_check_program_ok():
    p = mk_program(VariableDeclaration(Identifier("x"), TInt(), EConst(1)))
    # program.statement ist VariableDeclaration
    type_check(p)


def test_type_check_program_raises_on_bad_types():
    p = mk_program(VariableDeclaration(Identifier("x"), TInt(), EConst("d")))
    with pytest.raises(TypeCheckerError):
        type_check(p)
