import pytest

# passe den Modulnamen ggf. an:
from src.tactics_lang.parser import (
    TokenStream,
    lex_type,
    parse_data_fields,
    parse_data_type,
    parse_expression,
    parse_identifier,
    parse_integer,
    parse_literal,
    parse_mixed_type,
    parse_tuple_tokens,
    parse_type,
    parse_type_tokens,
)
from src.tactics_lang.program import (
    ConstantType,
    EConst,
    EVar,
    FunctionType,
    Identifier,
    InjectedExpression,
    ListType,
    LiteralType,
    MixedType,
    RecordType,
    TBool,
    TFloat,
    TInt,
    TStr,
    TupleType,
    TypeRef,
)
from src.tactics_lang.utility import TacticError


# ---------------------------
# lex_type
# ---------------------------
def test_lex_type_basic_tokens():
    toks = lex_type("(int -> (bool->float))")
    kinds = [t.kind for t in toks]
    assert kinds == ["(", "identifier", "->", "(", "identifier", "->", "identifier", ")", ")"]
    assert toks[1].value == "int"
    assert toks[4].value == "bool"
    assert toks[6].value == "float"


def test_lex_type_unexpected_character_raises():
    with pytest.raises(TacticError) as e:
        lex_type("int$")
    assert "Unexpected character" in str(e.value)


def test_lex_type_allows_whitespace_ignored():
    toks = lex_type("  int   ->   bool ")
    kinds = [t.kind for t in toks]
    assert kinds == ["identifier", "->", "identifier"]


# ---------------------------
# TokenStream
# ---------------------------
def test_tokenstream_peek_consume():
    ts = TokenStream(lex_type("int -> bool"))
    assert ts.peek().kind == "identifier"
    t1 = ts.consume("identifier")
    assert t1.value == "int"
    assert ts.peek().kind == "->"
    ts.consume("->")
    t2 = ts.consume("identifier")
    assert t2.value == "bool"
    assert ts.peek() is None


def test_tokenstream_consume_wrong_kind_raises():
    ts = TokenStream(lex_type("int"))
    with pytest.raises(TacticError) as e:
        ts.consume("->")
    assert "Expected" in str(e.value)


def test_tokenstream_consume_eof_raises():
    ts = TokenStream([])
    with pytest.raises(TacticError) as e:
        ts.consume()
    assert "Unexpected end of input" in str(e.value)


# ---------------------------
# parse_type_tokens
# ---------------------------
def test_parse_type_tokens_primitive_identifier_int():
    ts = TokenStream(lex_type("int"))
    t = parse_type_tokens(ts, custom_types=None, allow_typeref=False)
    assert t == TInt()
    assert ts.peek() is None


def test_parse_type_tokens_list_type():
    ts = TokenStream(lex_type("list[int]"))
    t = parse_type_tokens(ts, custom_types=None, allow_typeref=False)
    assert isinstance(t, ListType)
    assert t.element_type == TInt()


def test_parse_type_tokens_list_unclosed_bracket_raises():
    ts = TokenStream(lex_type("list[int"))
    with pytest.raises(TacticError) as e:
        parse_type_tokens(ts)
    assert "Unclosed '[' in list type" in str(e.value)


def test_parse_type_tokens_tuple_empty():
    ts = TokenStream(lex_type("tuple[]"))
    t = parse_type_tokens(ts)
    assert isinstance(t, TupleType)
    assert t.element_types == []


def test_parse_type_tokens_tuple_nonempty():
    ts = TokenStream(lex_type("tuple[int,bool,float]"))
    t = parse_type_tokens(ts)
    assert isinstance(t, TupleType)
    assert t.element_types == [TInt(), TBool(), TFloat()]


def test_parse_type_tokens_tuple_unclosed_bracket_raises():
    ts = TokenStream(lex_type("tuple[int,bool"))
    with pytest.raises(TacticError) as e:
        parse_type_tokens(ts)
    assert "Unclosed '[' in tuple type" in str(e.value)


def test_parse_type_tokens_tuple_unexpected_token_raises():
    # tuple[int bool] -> fehlt comma
    ts = TokenStream(lex_type("tuple[int bool]"))
    with pytest.raises(TacticError) as e:
        parse_type_tokens(ts)
    assert "Unexpected token" in str(e.value)


def test_parse_type_tokens_paren_function_type():
    ts = TokenStream(lex_type("(int, bool) -> float"))
    t = parse_type_tokens(ts)
    assert isinstance(t, FunctionType)
    assert t.parameter_types == [TInt(), TBool()]
    assert t.return_type == TFloat()


def test_parse_type_tokens_paren_singleton_returns_inner_type():
    ts = TokenStream(lex_type("(int)"))
    t = parse_type_tokens(ts)
    assert t == TInt()


def test_parse_type_tokens_paren_tuple_without_arrow_raises():
    ts = TokenStream(lex_type("(int, bool)"))
    with pytest.raises(TacticError) as e:
        parse_type_tokens(ts)
    assert "Multiple types in parentheses are only allowed in function types" in str(e.value)


def test_parse_type_tokens_custom_type_dict_becomes_recordtype():
    custom = {"Computer": {"ram": TInt(), "name": TStr()}}
    ts = TokenStream(lex_type("Computer"))
    t = parse_type_tokens(ts, custom_types=custom)
    assert isinstance(t, RecordType)
    assert t.name == "Computer"
    assert t.fields["ram"] == TInt()
    assert t.fields["name"] == TStr()


def test_parse_type_tokens_custom_type_direct_type():
    custom = {"MyInt": TInt()}
    ts = TokenStream(lex_type("MyInt"))
    t = parse_type_tokens(ts, custom_types=custom)
    assert t == TInt()


def test_parse_type_tokens_unknown_type_allow_typeref_true():
    ts = TokenStream(lex_type("Foo"))
    t = parse_type_tokens(ts, custom_types=None, allow_typeref=True)
    assert isinstance(t, TypeRef)
    assert t.name == "Foo"


def test_parse_type_tokens_unknown_type_allow_typeref_false_raises():
    ts = TokenStream(lex_type("Foo"))
    with pytest.raises(TacticError) as e:
        parse_type_tokens(ts, custom_types=None, allow_typeref=False)
    assert "Unknown type" in str(e.value)


# ---------------------------
# parse_literal
# ---------------------------
def test_parse_literal_single_case():
    t = parse_literal("Literal['cat']")
    assert isinstance(t, LiteralType)
    assert len(t.cases) == 1
    assert isinstance(t.cases[0], ConstantType)
    assert t.cases[0].value == "cat"


def test_parse_literal_multiple_cases():
    t = parse_literal("Literal['cat', 'dog', 3]")
    assert isinstance(t, LiteralType)
    assert [c.value for c in t.cases] == ["cat", "dog", 3]


def test_parse_literal_empty_raises():
    with pytest.raises(TacticError) as e:
        parse_literal("Literal[]")
    assert "Invalid literal type" in str(e.value)


def test_parse_literal_non_literal_prefix_raises():
    with pytest.raises(TacticError) as e:
        parse_literal("Foo['x']")
    assert "Literal must start" in str(e.value)


def test_parse_literal_non_constant_case_raises():
    with pytest.raises(TacticError) as e:
        parse_literal("Literal[x]")
    assert "Literal cases must be constants" in str(e.value)


def test_parse_literal_syntax_error_raises():
    with pytest.raises(TacticError) as e:
        parse_literal("Literal[")
    assert "Invalid literal type" in str(e.value)


# ---------------------------
# parse_type (wrapper)
# ---------------------------
def test_parse_type_strips_whitespace():
    assert parse_type("   int   ") == TInt()


def test_parse_type_trailing_tokens_raises():
    with pytest.raises(TacticError) as e:
        parse_type("int bool")
    assert "Unexpected trailing tokens" in str(e.value)


def test_parse_type_uses_custom_types():
    custom = {"X": TBool()}
    assert parse_type("X", custom_types=custom) == TBool()


def test_parse_type_allow_typeref_true():
    t = parse_type("Unknown", custom_types={}, allow_typeref=True)
    assert isinstance(t, TypeRef)
    assert t.name == "Unknown"


# ---------------------------
# parse_data_fields / parse_data_type
# ---------------------------
def test_parse_data_fields_empty():
    ts = TokenStream(lex_type("()"))
    fields = parse_data_fields(ts, custom_types=None)
    assert fields == []
    assert ts.peek() is None


def test_parse_data_fields_nonempty():
    ts = TokenStream(lex_type("(ram:int, name:str)"))
    fields = parse_data_fields(ts)
    assert fields[0][0] == Identifier("ram")
    assert fields[0][1] == TInt()
    assert fields[1][0] == Identifier("name")
    assert fields[1][1] == TStr()


def test_parse_data_fields_unclosed_paren_raises():
    ts = TokenStream(lex_type("(ram:int"))
    with pytest.raises(TacticError) as e:
        parse_data_fields(ts)
    assert "Unclosed '(' in data declaration" in str(e.value)


def test_parse_data_fields_unexpected_token_raises():
    ts = TokenStream(lex_type("(ram int)"))  # fehlt ':'
    with pytest.raises(TacticError) as e:
        parse_data_fields(ts)
    assert "Expected" in str(e.value) or "Unexpected token" in str(e.value)


def test_parse_data_type_basic():
    name, params = parse_data_type("Computer(ram:int, name:str)")
    assert name == Identifier("Computer")
    assert params["ram"] == TInt()
    assert params["name"] == TStr()


def test_parse_data_type_trailing_tokens_raises():
    with pytest.raises(TacticError) as e:
        parse_data_type("Computer(ram:int) extra")
    assert "Unexpected trailing tokens" in str(e.value)


# ---------------------------
# parse_tuple_tokens
# ---------------------------
def test_parse_tuple_tokens_empty():
    ts = TokenStream(lex_type("()"))
    entries = parse_tuple_tokens(ts)
    assert entries == []


def test_parse_tuple_tokens_nonempty():
    ts = TokenStream(lex_type("(int, bool, float)"))
    entries = parse_tuple_tokens(ts)
    assert entries == [TInt(), TBool(), TFloat()]


def test_parse_tuple_tokens_unclosed_paren_raises():
    ts = TokenStream(lex_type("(int, bool"))
    with pytest.raises(TacticError) as e:
        parse_tuple_tokens(ts)
    assert "Unclosed '('" in str(e.value)


def test_parse_tuple_tokens_unexpected_token_raises():
    ts = TokenStream(lex_type("(int bool)"))  # fehlt comma
    with pytest.raises(TacticError) as e:
        parse_tuple_tokens(ts)
    assert "Unexpected token" in str(e.value)


# ---------------------------
# parse_expression
# ---------------------------
def test_parse_expression_constant():
    e = parse_expression("42")
    assert e == EConst(42)


def test_parse_expression_name():
    e = parse_expression("x")
    assert e == EVar(Identifier("x"))


def test_parse_expression_invalid_syntax_raises():
    with pytest.raises(TacticError) as e:
        parse_expression("1+")
    assert "Invalid expression" in str(e.value)


def test_parse_expression_fallback_injected():
    """ " "lambda" causes a SyntaxError in eval mode, which would raise a TacticError.
    Therefore we use something that is parseable but does not match any of the existing AST cases.
    A dict literal is parsed as ast.Dict and falls into the default case -> InjectedExpression."""
    e = parse_expression("{1:2}")
    assert isinstance(e, InjectedExpression)
    assert e.value.strip() == "{1:2}"


# ---------------------------
# parse_identifier
# ---------------------------
def test_parse_identifier_ok():
    assert parse_identifier("  hello_1 ") == Identifier("hello_1")


def test_parse_identifier_invalid_raises():
    with pytest.raises(TacticError):
        parse_identifier("1abc")


# ---------------------------
# parse_integer
# ---------------------------
def test_parse_integer_ok():
    assert parse_integer("  123 ") == 123


def test_parse_integer_invalid_raises():
    with pytest.raises(TacticError):
        parse_integer("12.3")


# ---------------------------
# parse_mixed_type
# ---------------------------
def test_parse_mixed_type_empty_raises():
    with pytest.raises(TacticError) as e:
        parse_mixed_type("")
    assert "MixedType cannot be empty" in str(e.value)


def test_parse_mixed_type_simple():
    mt = parse_mixed_type("int | bool | str", name="X")
    assert isinstance(mt, MixedType)
    assert mt.name == "X"
    assert mt.cases == [TInt(), TBool(), TStr()]


def test_parse_mixed_type_disallows_function_type_inside():
    with pytest.raises(TacticError) as e:
        parse_mixed_type("int | (int -> bool)")
    msg = str(e.value)
    assert ("Function types are not allowed inside a MixedType" in msg) or ("Unexpected token" in msg)


def test_parse_mixed_type_unexpected_token_raises():
    with pytest.raises(TacticError) as e:
        parse_mixed_type("int , bool")
    assert "Unexpected token" in str(e.value)
