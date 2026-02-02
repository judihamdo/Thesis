import ast
from utility import TacticError
import re
from immutable_list import IList
from dataclasses import dataclass
from typing import Optional, Any, Literal
from program import *

# Token-String -> Type-Objekt
token_to_type = {"int": TInt(),"bool": TBool(),"float": TFloat(),
    "complex": TComplex(),"str": TStr()}

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
    (?P<IDENTIFIER>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


PRIMITIVES = {"bool", "int", "float", "complex", "str"}
#wenn ( ) nicht balanciert sind, ist alles ok --> sollte Fehler geben
def lex_type(type_str: str) -> list[Token]:
    """ for t in (lex_type('(int -> (bool->float))')):
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
            #!r  wendet repr() auf den Wert an. repr() gibt die offizielle String-Darstellung des Objekts zurück
            raise TacticError(f"Unexpected character at position {pos}: {type_str[pos]!r}")
        kind = match_.lastgroup
        text = match_.group()
        match kind:
            case "WHITESPACE":
                pass
            case "IDENTIFIER":
                tokens.append(Token("identifier", text))
                """if text in token_to_type:
                    tokens.append(Token("primitive", text))
                else:
                    raise TacticError(f"Unexpected token at position {pos}: {text!r}")
                    """
            case "LPAREN":
                tokens.append(Token("("))
            #new
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
        pos = match_.end()
    if pos != len(type_str):
        raise TacticError(f"Unexpected character at position {pos}: {type_str[pos]!r}")
    return tokens

class TokenStream:
    """ ti = TokenStream(lex_type('(int -> (bool->float)))'))
        ti.consume() ----> Token(kind='(', value=None)
        ti.consume() ----> Token(kind='primitive', value='int')
        ti.consume() ----> Token(kind='->', value=None) .... usw , also token für token bewegen
    """
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, kind: str | None = None) -> Token:
        token = self.peek()
        if token is None:
            raise TacticError(f"Unexpected end of input")
        if kind is not None and token.kind != kind:
            raise TacticError(f"Expected {kind!r}, found {token.kind!r}")
        self.pos += 1
        return token

#*******************************************************************************************
def parse_type_tokens(stream: TokenStream, custom_types: dict[str, Type] | None = None) -> Type:
    token = stream.peek()
    if token is None:
        raise TacticError("Missing a type")

    if token.kind == "primitive":
        stream.consume()
        return token_to_type[token.value]


    elif token.kind == "identifier":
        stream.consume()

        # 1) Custom Types (z.B. RecordType, LiteralType, MixedType, Aliases)
        if custom_types and token.value in custom_types:
            val = custom_types[token.value]

            # data: Name(...) wird bei dir oft als dict gespeichert
            if isinstance(val, dict):
                return RecordType(fields=val, name=token.value)

            # alles andere direkt zurückgeben (LiteralType / RecordType / MixedType / TInt() usw.)
            return val

        # 2) Primitive types wie "int", "bool", ...
        if token.value in token_to_type:
            return token_to_type[token.value]

        raise TacticError(f"Unknown type '{token.value}'")

    elif token.kind == "(":
        #Tupel/Funktionsargumente
        left = parse_tuple_tokens(stream, custom_types)
        if stream.peek() is not None and stream.peek().kind == "->":
            stream.consume("->")
            right = parse_type_tokens(stream, custom_types)
            return FunctionType(left, right)
        if len(left) != 1:
            raise TacticError("Unexpected tuple type")
        return left[0]
    else:
        raise TacticError(f"Misplaced token {token.kind!r}")
#*******************************************************************************************
def parse_literal(literal_str: str, name: str | None = None) -> LiteralType:
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
#*******************************************************************************************
def parse_type(type_str: str, custom_types: dict[str, Type] | None = None) -> Type:
    type_str = type_str.strip()  # Entfernt führende und nachfolgende Leerzeichen
    tokens = lex_type(type_str)
    stream = TokenStream(tokens)
    result = parse_type_tokens(stream, custom_types)

    # alle verbleibenden Tokens prüfen, nur WHITESPACE ist erlaubt
    while stream.peek() is not None and stream.peek().kind == "WHITESPACE":
        stream.consume()

    if stream.peek() is not None:
        raise TacticError(f"Unexpected trailing tokens: {stream.peek()}")

    return result
#***********************************************************************************************************************
def parse_data_fields(stream: TokenStream, custom_types: dict[str, Type] | None = None) -> list[tuple[Identifier, Type]]:
    fields: list[tuple[Identifier, Type]] = []
    stream.consume("(")

    if stream.peek() and stream.peek().kind == ")":
        stream.consume(")")
        return fields

    while True:
        # Feldname
        name_tok = stream.consume("identifier")
        field_name = Identifier(name_tok.value)

        # :
        stream.consume(":")

        # Typ
        field_type = parse_type_tokens(stream, custom_types)

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

def parse_data_type(type_str: str,custom_types: dict[str, Type] | None = None) -> DataDeclaration:
    type_str = type_str.strip()
    tokens = lex_type(type_str)
    stream = TokenStream(tokens)

    # Name des Datentyps
    name_tok = stream.consume("identifier")
    data_name = Identifier(name_tok.value)

    # Felder parsen
    fields_list = parse_data_fields(stream, custom_types)  # <- hier
    parameters = {name.value: typ for name, typ in fields_list}  # <- konvertieren

    # Keine Tokens mehr erlaubt
    if stream.peek() is not None:
        raise TacticError(f"Unexpected trailing tokens: {stream.peek()}")

    # DataDeclaration zurückgeben
    return data_name, parameters
#***********************************************************************************************************************
def parse_tuple_tokens(stream: TokenStream, custom_types: dict[str, Type] | None = None) -> list[Type]:
    entries: list[Type] = []
    stream.consume("(")
    if stream.peek() is not None and stream.peek().kind == ")":
        stream.consume(")")
        return entries
    while True:
        entries.append(parse_type_tokens(stream, custom_types))
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

#*******************************************************************************************                      
def parse_expression(expression_str: str) -> Expression:
    expression_str = expression_str.strip()
    try:
        node = ast.parse(expression_str, mode="eval").body
    except SyntaxError:
        raise TacticError(f"Invalid expression {expression_str!r}")

    match node:
        case ast.Constant(value):
            return EConst(value)
        case ast.Name(id):
            return EVar(Identifier(id))
        case ast.BinOp() | ast.UnaryOp() | ast.BoolOp() | ast.Call() | ast.IfExp():
            return map_node(node)  # benutze meinen AST Mapper für komplexe Expressions
        case _:
            return InjectedExpression(expression_str)
#*******************************************************************************************
def parse_identifier(identifier_str: str) -> Identifier:
    identifier_str = identifier_str.strip()
    try:
        #.body[0].value, Holt den ersten Ausdruck im AST
        match ast.parse(identifier_str).body[0].value: # type:ignore
            case ast.Name(value):
                return Identifier(value)
    except SyntaxError:
        pass
    raise TacticError(f"Invalid identifier {identifier_str!r}")
#*******************************************************************************************
def parse_integer(integer_str: str) -> int:
    integer_str = integer_str.strip()
    try:
        match ast.parse(integer_str).body[0].value: # type:ignore
            case ast.Constant(int(value)):
                return value
    except SyntaxError:
        pass
    raise TacticError(f"Invalid integer {integer_str!r}")
#************************************************************************************************************
def parse_mixed_type(mixed_str: str, name: str | None = None,
                     custom_types: dict[str, Type] | None = None) -> MixedType:
    mixed_str = mixed_str.strip()
    if mixed_str == "":
        raise TacticError("MixedType cannot be empty")
    tokens = lex_type(mixed_str)
    stream = TokenStream(tokens)
    cases: list[NonFunType] = []
    def parse_one_nonfun() -> NonFunType:
        t = parse_type_tokens(stream, custom_types)
        #Keine Fubnktionen sind erlaubt, alles andere ist ok
        if isinstance(t, FunctionType):
            raise TacticError("Function types are not allowed inside a MixedType")
        return t

    #füge erstes Element hinzu
    cases.append(parse_one_nonfun())

    #füge weitere Elemente mit '|' hinzu
    while stream.peek() is not None:
        tok = stream.peek()
        if tok.kind == "WHITESPACE":
            stream.consume()
            continue
        if tok.kind == "|":
            stream.consume("|")
            cases.append(parse_one_nonfun())
            continue
        #gib Fehler zurück wenn etwas anderes kommt
        raise TacticError(f"Unexpected token {tok.kind!r} in mixed type")
    if len(cases) == 0:
        raise TacticError("MixedType cannot be empty")
    return MixedType(cases=cases, name=name)
