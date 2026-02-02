from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Sequence, List, TypeAlias
from immutable_list import IList
import ast

#TYPES
class Type:
    pass
#PRIMITIVE TYPES
@dataclass
class TInt:
    pass

@dataclass
class TBool:
    pass

@dataclass
class TFloat:
    pass

@dataclass
class TComplex:
    pass

@dataclass
class TStr:
    pass

@dataclass(frozen=True)
class FunctionType(Type):
    parameter_types: list[Type]
    return_type: Type
#Das ist ein TypBaustein für LiteralType.   
@dataclass(frozen=True)
class ConstantType(Type):
    value: int | float | bool | str | complex 



    
@dataclass
class LiteralType(Type):
    cases: list[ConstantType]
    name: str | None = None

    def type_of(self, literal: ConstantType) -> Type:
        value = literal.value
        if isinstance(value, bool):
            return TBool()
        elif isinstance(value, int):
            return TInt()
        elif isinstance(value, float):
            return TFloat()
        elif isinstance(value, complex):
            return TComplex()
        elif isinstance(value, str):
            return TStr()
        else:
            raise TypeError(f"Unsupported literal value: {value}")
       
class RecordType(Type):
    def __init__(self, fields: dict[str, Type], name: str):
        self.fields = fields
        self.name = name
    def __eq__(self, other):
        if not isinstance(other, RecordType):
            return False
        # gleiche Namen und gleiche Felder (inkl. Typen)
        return self.name == other.name and self.fields == other.fields
    def __repr__(self):
        return f"RecordType({self.name}, {self.fields})"
    
NonFunType: TypeAlias = TInt | TBool | TFloat | TComplex | TStr | LiteralType | RecordType | "MixedType"
@dataclass
class MixedType(Type):
    cases: list[NonFunType]
    name: str | None = None
#Alle Typen zusammenfassen
Type = TInt | TBool | TFloat | TComplex | TStr |FunctionType |LiteralType |RecordType |MixedType
# PRETTY PRINTING
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
        case _:
            return "unknown"
# IDENTIFIER
@dataclass(frozen=True)
class Identifier:
    value: str
    

# EXPRESSIONS (AST)
class Expression:
    pass

Op1 = Literal["-"]
Op2 = Literal["+", "-", "*", "/"]

@dataclass(frozen=True)
class EConst(Expression):
    value: int| float | bool | str | complex

@dataclass(frozen=True)
class EVar(Expression):
    name: Identifier

@dataclass(frozen=True)
class EOp1(Expression):
    op: Op1
    operand: Expression

@dataclass(frozen=True)
class EOp2(Expression):
    left: Expression
    op: Op2
    right: Expression
@dataclass(frozen=True)
class EFunCall(Expression):
    func: Expression       # der Funktions-Ausdruck selbst, z. B. EVar(Id("f"))
    args: list[Expression] # Liste der Argumente
@dataclass(frozen=True)
class EIf:
    test: Expression
    body: Expression
    orelse: Expression
@dataclass(frozen=True)
class EBoolOp(Expression):
    op: Literal["and", "or"]
    left: Expression
    right: Expression
@dataclass
class InjectedExpression(Expression):
    value: str

#class Scope ist fuer folgenden Fragen: Welche Variablen sind hier sichtbar? Woher kommt eine Variable(aus dem aktuellen Block oder von außen)?
#Welche Variablen dürfen nicht in andere Branches verwendet werden?
class Scope:
    def __init__(self, parent: Optional['Scope'] = None):
        self.vars: dict[str, Type] = {}    #enthält nur die Variablen dieses Scopes, keine Variablen von außen
        self.parent = parent   #zeigt auf den äußeren Scope
        self.has_destruct_child: bool = False  #wird benutzt für die empty-Regel um zu zeigen: In diesem Scope gab es irgendwo eine destruct-Aktivität

    def freeze(self) -> "Scope":
        """ Erzeugt eine Kopie der gesamten Scope-Kette. Es erstellt eine komplette Kopie der gesamten Scope-Kette Eltern , Eltern der Eltern ..
        Dadurch wirken spätere `add(...)` im ursprünglichen Scope NICHT rückwirkend
        auf bereits erzeugte Branch-Scopes.Also Verschachtelte destructs muessen nicht von variables die danach im Hauptdestruct kommen wissen."""
        parent_copy = self.parent.freeze() if self.parent else None   #wenn es einen Eltern-Scope gibt->kopiere ihn rekursiv, sonst: Ende der Kette
        s = Scope(parent=parent_copy)  #neuer Scope mit kopiertem Eltern-Scope
        s.vars = self.vars.copy()  #Variablen dieses Scopes kopieren
        s.has_destruct_child = self.has_destruct_child 
        return s

    def _key(self, name: Identifier | str) -> str:
        """ versichert, dass man str bekommt und keine Identifier """
        return name.value if isinstance(name, Identifier) else name

    def add(self, name: Identifier | str, typ: Type):
        """ Bsp: scope.add("x", TInt()) """
        self.vars[self._key(name)] = typ 

    def get(self, name: Identifier | str) -> Optional[Type]:
        k = self._key(name)
        if k in self.vars:
            return self.vars[k]
        if self.parent:
            return self.parent.get(k)
        return None

    def copy_all(self) -> dict[str, Type]:
        """alle sichtbaren Variablen sammeln: Alle Variablen als dict zurück + Variables geerbt von Eltern."""
        result = self.parent.copy_all() if self.parent else {}  #sammle Eltern Variables zuerst
        result.update(self.vars)   #fuege zu den Eltern Variables die eigenge variables
        return result

@dataclass
class Hole:
    tactics: set[str]
    selected: bool = False
    index: int = 0
    type: Optional[Type] = None  
    filler: Optional[Any] = None
    is_return_hole: bool = False
    scope: Optional[Scope] = None  #in welchem scope ich mich befinde, Scope-Objekt oder None


@dataclass
class SCase:
    pattern: str                # das Label des Case: z.B. "Computer" oder Literal
    body: IList                 # Liste von Statements/Holes
    pattern_values: Optional[List[Hole]] = None  # Löcher NUR für RecordType
    scope: Optional["Scope"] = None  #Alles was in diesem Case definiert wird,ist nur hier sichtbar: enthaelt ram, processor in case data:Computer(..) z.B.
@dataclass
class SMatch:
    expr: Expression
    cases: list["SCase"]
    scope: Optional["Scope"] = None  #Scope VOR dem match, enthält:Funktionsparameter, vorherige let-Variablen von Program.

# STATEMENTS (AST)
class Statement:
    pass
@dataclass(frozen=True)
class SData(Statement):
    name: Identifier
    parameters: dict[str, Type]
@dataclass(frozen=True)
class SExpr(Statement):
    expr: Expression

@dataclass(frozen=True)
class SAssign(Statement):
    lhs: Identifier
    rhs: Expression
    
@dataclass(frozen=True)
class SIf:
    test: Expression
    body: IList[Statement]
    orelse: IList[Statement]

@dataclass
class EmptyStatement(Statement):
    pass

@dataclass
class DescriptionStatement(Statement):
    value: str

@dataclass
class CompositeStatement(Statement):
    first: Statement
    second: Statement | Hole

@dataclass
class DataDeclaration(Statement):
    name: Identifier
    parameters: dict[str, Type]
  
@dataclass
class FunctionDeclaration(Statement):
    name: Identifier
    function_type: FunctionType
    parameters: Sequence[Identifier | Hole]
    statement: Statement | Hole

@dataclass
class VariableDeclaration(Statement):
    name: Identifier
    type_: Type
    expression: Expression | Hole
    
@dataclass
class TypeDeclaration(Statement):
    name: Identifier
    type_: Type

@dataclass
class ReturnStatement(Statement):
    value: Expression | Hole
    expected_type: Type | None = None

#***************************************************************************************
# PROGRAM (mit Holes)
@dataclass
class Program:
    statement: Statement | Hole
    variables: dict = field(default_factory=dict)
    defined_types: dict[str, Type] = field(default_factory=dict)
    defined_classes: Optional[List[DataDeclaration]] = None
    selected_hole: Optional[Hole] = None
    holes: list[Hole] = field(default_factory=list)

# PRETTY PRINTING (AST)
def pretty_expr(e: Expression) -> str:
    if isinstance(e, EConst):
                # Strings sollen mit Quotes erscheinen: 'Tiger'
        if isinstance(e.value, str):
            return repr(e.value)
        return str(e.value)
    
    elif isinstance(e, EVar):
        return e.name.value
    elif isinstance(e, EOp1):
        return f"{e.op}{pretty_expr(e.operand)}"
    elif isinstance(e, EOp2):
        return f"({pretty_expr(e.left)} {e.op} {pretty_expr(e.right)})"
    elif isinstance(e, InjectedExpression):
        return e.value
    else:
        return "unknown_expr"

#****************     #*******************     #*******************      #********************
#von python Ast zu meinem Ast
@dataclass(frozen=True)
class ParseError(Exception):
    pass

@dataclass(frozen=True)
class UnsupportedFeature(ParseError):
    node: Any

    def __str__(self) -> str:
        return f"Found unsupported AST node {self.node} that represents `{ast.unparse(self.node)}`\n\n `{ast.dump(self.node, indent=4)}`"

@dataclass(frozen=True)
class IllegalName(ParseError):
    name: str

    def __str__(self) -> str:
        return f"The `name` {self.name} is not a valid variable name, use only letters and numbers"
    
def map_node(node: ast.AST) -> Any:
    """ Wandelt einen Python-AST-Knoten in unseren eigenen AST um."""
    match node:
        #Operatoren
        case ast.Add():
            return "+"

        case ast.Sub() | ast.USub():
            return "-"

        case ast.Mult():
            return "*"

        case ast.Div():
            return "/"

        #Zahlen(Konstanten)
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

        #Variablen: Er überprüft:ist das ein gültiger Name? -> Dann wird daraus eine Variable in deinem eigenen AST gemacht
        case ast.Name(id):
            for c in id:
                if not (c.isalnum() or c == "_"):
                    raise IllegalName(id)
            return EVar(Identifier(id))

        #Unary Operation (-x)
        case ast.UnaryOp(op, operand):
            operator = map_node(op)
            expr = map_node(operand)
            return EOp1(operator, expr)

        # Binary Operation (z.B. x + y)
        case ast.BinOp(left, op, right):
            left_expr = map_node(left)
            operator = map_node(op)
            right_expr = map_node(right)
            return EOp2(left_expr, operator, right_expr)

        #Zuweisung(x=y)
        case ast.Assign([ast.Name(name)], value, _):
            expr = map_node(value)
            #not id, but identifier
            return SAssign(Identifier(name), expr)

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

        #print()
        case ast.Call(func, args, keywords):
            if len(keywords) > 0:
                raise UnsupportedFeature(node)
            func_expr = map_node(func)
            arg_exprs = [map_node(a) for a in args]
            return EFunCall(func_expr, arg_exprs)

        #Allgemeiner Ausdruck
        case ast.Expr(value):
            return SExpr(map_node(value))

        #Alles andere ist verboten
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
        case _:
            raise UnsupportedFeature(node)

def map_nodes(nodes: Sequence[Any]) -> IList[Statement]:
    return IList([map_node(node) for node in nodes])

#Dieser Teilcode basiert direkt auf dem Python-AST.
def parse_expr(src: str) -> Expression:
    """ Parst einen einzelnen Ausdruck (z. B. f, f(x), x+1) in DEINEN AST."""
    node = ast.parse(src, mode="eval").body
    return map_node(node)






























