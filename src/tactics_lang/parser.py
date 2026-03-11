import ast
import re
from dataclasses import dataclass
from typing import Any, Optional

from .ast_converter import map_node
from .program import (
    ConstantType,
    DataDeclaration,
    Expression,
    FunctionType,
    # AST nodes
    Identifier,
    InjectedExpression,
    ListType,
    LiteralType,
    MixedType,
    NonFunType,
    RecordType,
    TBool,
    TComplex,
    TFloat,
    TInt,
    TStr,
    TupleType,
    # Types
    Type,
    TypeRef,
)
from .utility import TacticError

# Token-String -> Type-Objekt
token_to_type = {
    "int": TInt(),
    "bool": TBool(),
    "float": TFloat(),
    "complex": TComplex(),
    "str": TStr(),
}


@dataclass
class Token:
    kind: str
    value: Optional[Any] = None


TOKEN_REGEX = re.compile(
    r"""
    (?P<WHITESPACE>\s+) |
    (?P<COLON>:) |
    (?P<ARROW>->) |
    (?P<PIPE>\|) |
    (?P<LPAREN>\() |
    (?P<RPAREN>\)) |
    (?P<COMMA>,) |
    (?P<LBRACK>\[) |
    (?P<RBRACK>\]) |
    (?P<IDENTIFIER>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


PRIMITIVES = {"bool", "int", "float", "complex", "str"}


# If the parentheses are not balanced, it should raise an error.
def lex_type(type_str: str) -> list[Token]:
    """for t in (lex_type('(int -> (bool->float))')):
        print(str(str(t)))

    Token(kind='(', value=None)
    Token(kind='primitive', value='int')
    Token(kind='->', value=None)
    Token(kind='(', value=None)
    Token(kind='primitive', value='bool')
    Token(kind='->', value=None)
    Token(kind='primitive', value='float')
    Token(kind=')', value=None)
    Token(kind=')', value=None)

    """

    tokens: list[Token] = []
    pos = 0
    for match_ in TOKEN_REGEX.finditer(type_str):
        if match_.start() != pos:
            raise TacticError(f"Unexpected character at position {pos}: {type_str[pos]!r}")
        kind = match_.lastgroup
        text = match_.group()
        match kind:
            case "WHITESPACE":
                pass
            case "IDENTIFIER":
                tokens.append(Token("identifier", text))
            case "LPAREN":
                tokens.append(Token("("))
            case "COLON":
                tokens.append(Token(":"))
            case "RPAREN":
                tokens.append(Token(")"))
            case "COMMA":
                tokens.append(Token(","))
            case "ARROW":
                tokens.append(Token("->"))
            case "PIPE":
                tokens.append(Token("|"))
            case "LBRACK":
                tokens.append(Token("["))
            case "RBRACK":
                tokens.append(Token("]"))
        pos = match_.end()
    if pos != len(type_str):
        raise TacticError(f"Unexpected character at position {pos}: {type_str[pos]!r}")
    return tokens


class TokenStream:
    """ti = TokenStream(lex_type('(int -> (bool->float)))'))
    ti.consume() ----> Token(kind='(', value=None)
    ti.consume() ----> Token(kind='primitive', value='int')
    ti.consume() ----> Token(kind='->', value=None) .... etc. , move token by token.
    """

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Token]:
        """Peek at the next token without consuming it."""
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, kind: str | None = None) -> Token:
        """It does two things: returns the current token and advances the position."""
        token = self.peek()
        if token is None:
            raise TacticError("Unexpected end of input")
        if kind is not None and token.kind != kind:
            raise TacticError(f"Expected {kind!r}, found {token.kind!r}")
        self.pos += 1
        return token


# *******************************************************************************************
def parse_tuple_tokens(stream: TokenStream, custom_types: dict[str, Type] | None = None, allow_typeref: bool = False) -> list[Type]:
    """Helper function for parse_type_tokens,
    Example: (int, bool, str) -> [TInt(), TBool(), TStr()]"""

    entries: list[Type] = []
    stream.consume("(")
    if stream.peek() is not None and stream.peek().kind == ")":
        stream.consume(")")
        return entries
    while True:
        entries.append(parse_type_tokens(stream, custom_types, allow_typeref=allow_typeref))
        token = stream.peek()
        if token is None:
            raise TacticError("Unclosed '('")
        if token.kind == ",":
            stream.consume(",")
            continue
        if token.kind == ")":
            stream.consume(")")
            break
        raise TacticError(f"Unexpected token {token.kind!r}")
    return entries


# *******************************************************************************************
def parse_type_tokens(stream: TokenStream, custom_types: dict[str, Type] | None = None, allow_typeref: bool = False) -> Type:
    """recursively reads tokens from a TokenStream and converts them into the corresponding internal Type object.
    Example: for the token sequence of list[int], it returns ListType(TInt())."""
    token = stream.peek()
    if token is None:
        raise TacticError("Missing a type")

    if token.kind == "identifier":
        stream.consume()

        # list[...]
        if token.value == "list" and stream.peek() is not None and stream.peek().kind == "[":
            stream.consume("[")
            # Exactly one type argument.
            inner = parse_type_tokens(stream, custom_types, allow_typeref=allow_typeref)
            tok = stream.peek()
            if tok is None or tok.kind != "]":
                raise TacticError("Unclosed '[' in list type")
            stream.consume("]")
            return ListType(inner)
        # tuple[...]
        if token.value == "tuple" and stream.peek() is not None and stream.peek().kind == "[":
            stream.consume("[")
            elts: list[Type] = []
            # Empty tuple
            if stream.peek() is not None and stream.peek().kind == "]":
                stream.consume("]")
                return TupleType(elts)
            # Tuple contains elements
            while True:
                elts.append(parse_type_tokens(stream, custom_types, allow_typeref=allow_typeref))
                tok = stream.peek()
                if tok is None:
                    raise TacticError("Unclosed '[' in tuple type")
                if tok.kind == ",":
                    stream.consume(",")
                    continue
                if tok.kind == "]":
                    stream.consume("]")
                    break
                raise TacticError(f"Unexpected token {tok.kind!r} in tuple type")
            return TupleType(elts)

        # 1) Custom Types (e.g. RecordType, LiteralType, MixedType, Aliases)
        if custom_types and token.value in custom_types:
            val = custom_types[token.value]

            # data: Name(...) # Is often stored as a dict here.
            if isinstance(val, dict):
                return RecordType(fields=val, name=token.value)

            # Return everything else directly (LiteralType / RecordType / MixedType / TInt(), etc.).
            return val

        # 2) Primitive types e.g. "int", "bool", ...
        if token.value in token_to_type:
            return token_to_type[token.value]
        if allow_typeref:
            return TypeRef(token.value)
        raise TacticError(f"Unknown type '{token.value}'")

    # For inputs like (int, (bool -> float)) -> str
    elif token.kind == "(":
        # Tupel/function arguments
        left = parse_tuple_tokens(stream, custom_types)
        if stream.peek() is not None and stream.peek().kind == "->":
            stream.consume("->")
            right = parse_type_tokens(stream, custom_types, allow_typeref=allow_typeref)
            return FunctionType(left, right)
        if len(left) != 1:
            raise TacticError("Multiple types in parentheses are only allowed in function types")
        return left[0]
    else:
        raise TacticError(f"Misplaced token {token.kind!r}")


# *******************************************************************************************
def parse_type(type_str: str, custom_types: dict[str, Type] | None = None, allow_typeref: bool = False) -> Type:
    """Example1: "(int, bool) -> str" → FunctionType([TInt(), TBool()], TStr()) ,
    Example2: "int" → TInt()"""
    type_str = type_str.strip()  # Remove leading and trailing whitespace.
    tokens = lex_type(type_str)
    stream = TokenStream(tokens)
    result = parse_type_tokens(stream, custom_types, allow_typeref=allow_typeref)
    if stream.peek() is not None:
        raise TacticError(f"Unexpected trailing tokens: {stream.peek()}")

    return result


# ***********************************************************************************************************************
def parse_identifier(identifier_str: str) -> Identifier:
    """Check whether a string is a valid name and return an Identifier(...)."""
    identifier_str = identifier_str.strip()
    try:
        # .body[0].value retrieves the first expression in the AST.
        match ast.parse(identifier_str).body[0].value:
            case ast.Name(value):
                return Identifier(value)
    except SyntaxError:
        pass
    raise TacticError(f"Invalid identifier {identifier_str!r}")


# *******************************************************************************************
def parse_integer(integer_str: str) -> int:
    """Check whether a string is a valid integer and return a Python int."""
    integer_str = integer_str.strip()
    try:
        match ast.parse(integer_str).body[0].value:
            case ast.Constant(int(value)):
                return value
    except SyntaxError:
        pass
    raise TacticError(f"Invalid integer {integer_str!r}")


# ************************************************************************************************************
def parse_expression(expression_str: str) -> Expression:
    """Parse a general expression and convert it into the internal AST expression."""
    expression_str = expression_str.strip()
    try:
        node = ast.parse(expression_str, mode="eval").body
    except SyntaxError:
        raise TacticError(f"Invalid expression {expression_str!r}")

    try:
        result = map_node(node)
        if isinstance(result, Expression):
            return result
        return InjectedExpression(expression_str)
    except Exception:
        return InjectedExpression(expression_str)


# *******************************************************************************************
def parse_literal(literal_str: str, name: str | None = None) -> LiteralType:
    """Converts a string such a Literal['cat', 'dog']
    into the internal type representation: LiteralType([ ConstantType('cat'), ConstantType('dog') ])"""

    literal_str = literal_str.strip()
    try:
        node = ast.parse(literal_str, mode="eval").body
        if isinstance(node, ast.Subscript):
            if not (isinstance(node.value, ast.Name) and node.value.id == "Literal"):
                raise TacticError("Literal must start with `Literal[...]`")
            sub = node.slice
            if isinstance(sub, ast.Tuple):
                elts = sub.elts
            else:
                elts = [sub]
            cases = []
            for elt in elts:
                if isinstance(elt, ast.Constant):
                    cases.append(ConstantType(elt.value))
                else:
                    raise TacticError("Literal cases must be constants")
            if not cases:
                raise TacticError("Literal cannot be empty")
            return LiteralType(cases, name=name)
        else:
            raise TacticError("Literal must be of form `Literal[...]`")
    except SyntaxError:
        raise TacticError(f"Invalid literal type {literal_str!r}")


# *******************************************************************************************
def parse_data_fields(stream: TokenStream, custom_types: dict[str, Type] | None = None) -> list[tuple[Identifier, Type]]:
    """
    Read from a TokenStream a list of fields of the form name: type
    and return them as a list of tuples.
    Example: (ram: int, processor: int)  ->  [(Identifier("ram"), TInt()),(Identifier("processor"), TInt())]
    """

    fields: list[tuple[Identifier, Type]] = []
    stream.consume("(")
    # Empty list
    if stream.peek() and stream.peek().kind == ")":
        stream.consume(")")
        return fields

    while True:
        # Field name
        name_tok = stream.consume("identifier")
        field_name = Identifier(name_tok.value)

        # :
        stream.consume(":")

        # Type
        field_type = parse_type_tokens(stream, custom_types, True)

        fields.append((field_name, field_type))

        token = stream.peek()
        if token is None:
            raise TacticError("Unclosed '(' in data declaration")

        if token.kind == ",":
            stream.consume(",")
            continue

        if token.kind == ")":
            stream.consume(")")
            break

        raise TacticError(f"Unexpected token {token.kind!r} in data declaration")

    return fields


# **************************************************************************************************
def parse_data_type(type_str: str, custom_types: dict[str, Type] | None = None) -> DataDeclaration:
    """parses a data type declaration string into a data type name and its field-type mapping.
    Example: Computer(ram: int, processor: int) → (Identifier("Computer"), {"ram": TInt(), "processor": TInt()})"""
    type_str = type_str.strip()
    tokens = lex_type(type_str)
    stream = TokenStream(tokens)

    # Name of Data Type
    name_tok = stream.consume("identifier")
    data_name = Identifier(name_tok.value)

    # Parse Field
    fields_list = parse_data_fields(stream, custom_types)  # <- hier
    parameters = {name.value: typ for name, typ in fields_list}  # <- konvertieren

    # No more tokens allowed
    if stream.peek() is not None:
        raise TacticError(f"Unexpected trailing tokens: {stream.peek()}")

    # Return DataDeclaration
    return data_name, parameters


# ***********************************************************************************************************************
def parse_mixed_type(mixed_str: str, name: str | None = None, custom_types: dict[str, Type] | None = None) -> MixedType:
    """parses a union-like type expression into a MixedType object.
    Example: int | bool → MixedType([TInt(), TBool()])"""
    mixed_str = mixed_str.strip()
    if mixed_str == "":
        raise TacticError("MixedType cannot be empty")
    tokens = lex_type(mixed_str)
    stream = TokenStream(tokens)
    cases: list[NonFunType] = []

    def parse_one_nonfun() -> NonFunType:
        t = parse_type_tokens(stream, custom_types, allow_typeref=True)
        # No functions are allowed, everything else is ok
        if isinstance(t, FunctionType):
            raise TacticError("Function types are not allowed inside a MixedType")
        return t

    # Add first element
    cases.append(parse_one_nonfun())

    # Add more elements with '|'
    while stream.peek() is not None:
        tok = stream.peek()
        if tok.kind == "WHITESPACE":
            stream.consume()
            continue
        if tok.kind == "|":
            stream.consume("|")
            cases.append(parse_one_nonfun())
            continue
        # Give back error in all other cases
        raise TacticError(f"Unexpected token {tok.kind!r} in mixed type")
    if len(cases) == 0:
        raise TacticError("MixedType cannot be empty")
    return MixedType(cases=cases, name=name)
