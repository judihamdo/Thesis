from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Sequence, TypeAlias, Union

from .immutable_list import IList


# TYPES
class Type:
    pass


# PRIMITIVE TYPES
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


@dataclass(frozen=True)
class ConstantType(Type):
    value: int | float | bool | str | complex


@dataclass
class ListType(Type):
    element_type: Type


@dataclass
class TupleType(Type):
    element_types: list[Type]


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
        return self.name == other.name and self.fields == other.fields


@dataclass
class MixedType(Type):
    cases: list[NonFunType]
    name: str | None = None


@dataclass(frozen=True)
class TypeRef(Type):
    name: str


@dataclass
class RangeType(Type):
    element_type: Type = field(default_factory=TInt)


NonFunType: TypeAlias = Union[
    TInt,
    TBool,
    TFloat,
    TComplex,
    TStr,
    LiteralType,
    RecordType,
    TupleType,
    ListType,
    "MixedType",
]


@dataclass(frozen=True)
class Identifier:
    value: str


# EXPRESSIONS (AST)
class Expression:
    pass


Op1 = Literal["-"]
Op2 = Literal["+", "-", "*", "/"]


@dataclass(frozen=True)
class EIndex(Expression):
    seq: Expression
    index: Expression


@dataclass(frozen=True)
class ESlice(Expression):
    seq: Expression
    lower: Expression | None
    upper: Expression | None


@dataclass(frozen=True)
class EConst(Expression):
    value: int | float | bool | str | complex


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
    func: Expression
    args: list[Expression]


@dataclass(frozen=True)
class EIf:
    test: Expression
    body: Expression
    orelse: Expression


@dataclass(frozen=True)
class ETuple(Expression):
    elts: list[Expression]


@dataclass(frozen=True)
class EList(Expression):
    elts: list[Expression]
    element_type: Optional[Type] = None


@dataclass(frozen=True)
class EBoolOp(Expression):
    op: Literal["and", "or"]
    left: Expression
    right: Expression


@dataclass
class InjectedExpression(Expression):
    value: str


class Scope:
    """The Scope class answers the following questions:
    Which variables are visible in this scope?
    Where does a variable come from (the current block or an outer scope)?
    Which variables must not be used in other branches?"""

    def __init__(self, parent: Optional["Scope"] = None):
        self.vars: dict[str, Type] = {}  # Contains only the variables of this scope, not variables from outer scopes.
        self.parent = parent  # Points to the outer scope.
        self.has_destruct_child: bool = False  # Used by the empty rule to indicate that a destruct operation occurred somewhere in this scope.

    def freeze(self) -> "Scope":
        """
        Create a copy of the entire scope chain, including all parent scopes.
        As a result, later `add(...)` calls in the original scope do not affect
        branch scopes that have already been created. In other words, nested
        destructs do not need to know about variables introduced later in the
        main destruct.
        """
        parent_copy = self.parent.freeze() if self.parent else None
        s = Scope(parent=parent_copy)
        s.vars = self.vars.copy()
        s.has_destruct_child = self.has_destruct_child
        return s

    def _key(self, name: Identifier | str) -> str:
        return name.value if isinstance(name, Identifier) else name

    def add(self, name: Identifier | str, typ: Type):
        """e.g.: scope.add("x", TInt())"""
        self.vars[self._key(name)] = typ

    def get(self, name: Identifier | str) -> Optional[Type]:
        k = self._key(name)
        if k in self.vars:
            return self.vars[k]
        if self.parent:
            return self.parent.get(k)
        return None

    # Both freeze() and copy_all() have the same variables at the end, but the first stores them as Scope, wheres the second as dictionary
    def copy_all(self) -> dict[str, Type]:
        """
        Collect all visible variables: return all variables as a dictionary,
        including variables inherited from parent scopes.
        """
        result = self.parent.copy_all() if self.parent else {}  # Collect parent Variables firstly
        result.update(self.vars)  # Add own variables
        return result


@dataclass
class Hole:
    tactics: set[str]
    selected: bool = False
    index: int = 0
    length: int = 0
    kind: Literal["normal", "list"] = "normal"
    list_element_type: Optional[Type] = None
    list_elements: list[Any] = field(default_factory=list)  # Elemente are Expressions or Holes
    type: Optional[Type] = None
    filler: Optional[Any] = None
    is_return_hole: bool = False
    scope: Optional[Scope] = None
    owner: str | None = None


@dataclass
class SCase:
    pattern: str  # das Label of Case: e.g. "Computer" or Literal
    body: IList  # List of Statements/Holes
    pattern_values: Optional[List[Hole]] = None  # Holes just for RecordType
    scope: Optional["Scope"] = None


# STATEMENTS
class Statement:
    pass


@dataclass
class SMatch(Statement):
    expr: Expression
    cases: list["SCase"]
    scope: Optional["Scope"] = None


@dataclass(frozen=True)
class SFor(Statement):
    var: Identifier | Hole  # intro hole
    iterable: Expression
    body: IList[Statement]
    scope: Optional["Scope"] = None


@dataclass(frozen=True)
class SData(Statement):
    name: Identifier
    parameters: dict[str, Type]


@dataclass(frozen=True)
class SExpr(Statement):
    expr: Expression


@dataclass(frozen=True)
class SIf(Statement):
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
    # type: Tier = kater | Hund
    name: Identifier
    type_: Type


@dataclass
class ReturnStatement(Statement):
    value: Expression | Hole
    expected_type: Type | None = None


@dataclass
class Program:
    statement: Statement | Hole
    variables: dict = field(default_factory=dict)
    defined_types: dict[str, Type] = field(default_factory=dict)
    # defined_classes: Optional[List[DataDeclaration]] = None
    selected_hole: Optional[Hole] = None
    holes: list[Hole] = field(default_factory=list)
    list_lengths: dict[str, int | None] = field(default_factory=dict)
    # Store the lengths of nested lists.
    # Example: {("first_list", (0, 1, 3)): 5} means that first_list[0][1][3] has 5 elements.
    nested_list_lengths: dict[tuple[str, tuple[int, ...]], int] = field(default_factory=dict)
