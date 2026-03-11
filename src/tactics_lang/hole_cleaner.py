from typing import Any, Optional

from .immutable_list import IList
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
    # statements
    EmptyStatement,
    EOp1,
    EOp2,
    ESlice,
    ETuple,
    EVar,
    FunctionDeclaration,
    FunctionType,
    Hole,
    Identifier,
    # expressions
    InjectedExpression,
    ListType,
    LiteralType,
    MixedType,
    Program,
    RangeType,
    RecordType,
    ReturnStatement,
    SCase,
    Scope,
    SFor,
    SIf,
    SMatch,
    TBool,
    TComplex,
    TFloat,
    TInt,
    TStr,
    TupleType,
    TypeDeclaration,
    # types
    TypeRef,
    VariableDeclaration,
)
from .utility import UnexpectedValueError


class HoleCleaner:
    def __init__(self, program: Program = None):
        self.selected_hole: Optional[Hole] = None
        self.holes: list[Hole] = []
        self.program = program

    def mark_scope_active(self, scope: Scope | None):
        """Walks up the scope chain and marks it. This is used for the `empty` rule:
        if a branch has been activated (e.g., by destruct, if, or match), then `empty` may be allowed later."""
        while scope:
            scope.has_destruct_child = True
            scope = scope.parent

    # Recursive function for cleaning
    def clean_node(self, node: Any, current_scope: Scope = None) -> Any:  # scope wird damit gegeben
        match node:
            case Hole():
                # Regardless of whether the hole is filled or not, set node.scope to the current scope.
                # This ensures that during fill/let/return the interpreter knows which variables are in scope.
                node.scope = current_scope
                # If this is a list hole, clean its elements (they may contain expression holes)
                if getattr(node, "kind", "normal") == "list":
                    node.list_elements = [self.clean_node(e, current_scope) for e in (node.list_elements or [])]

                # Filled hole: remove the hole, replace it with the filler, and fix the selection if necessary.
                # Open hole: add the hole to the hole list, assign it an index, and possibly mark it as the selected hole.
                if node.filler is not None:
                    # (This applies specifically to intro holes.)
                    # The variable is immediately registered with its type in the correct scope so the system knows it exists.
                    if isinstance(node.filler, Identifier) and node.type is not None and isinstance(current_scope, Scope):
                        current_scope.add(node.filler, node.type)
                    # Now it has been filled, so it is no longer a hole but replaced by its content.
                    if node is self.selected_hole:
                        self.selected_hole = None

                    # Once a hole is filled, it should no longer appear as a hole in the AST.
                    # The AST should instead look as if the filler was originally placed there.
                    return self.clean_node(node.filler, current_scope)
                # No selected hole? -> choose the first opened hole
                if self.selected_hole is None:
                    self.selected_hole = node
                # Initially set everything to False because the cleaner first collects all holes.
                # The final selected hole will later be marked as True (in clean_holes).
                node.selected = False
                node.index = len(self.holes)
                self.holes.append(node)
                # As the hole is still open, it remains in the AST.
                return node

            case TypeRef():
                return node

            case EFunCall(func_expr, arg_exprs):
                func_expr = self.clean_node(func_expr, current_scope)
                arg_exprs = [self.clean_node(a, current_scope) for a in arg_exprs]
                return EFunCall(func_expr, arg_exprs)

            case EOp1(op, operand):
                operand = self.clean_node(operand, current_scope)
                return EOp1(op, operand)

            case EOp2(left, op, right):
                left = self.clean_node(left, current_scope)
                right = self.clean_node(right, current_scope)
                return EOp2(left, op, right)

            case EBoolOp(op, left, right):
                left = self.clean_node(left, current_scope)
                right = self.clean_node(right, current_scope)
                return EBoolOp(op, left, right)

            case EIf(test, body, orelse):
                test = self.clean_node(test, current_scope)
                body = self.clean_node(body, current_scope)
                orelse = self.clean_node(orelse, current_scope)
                return EIf(test, body, orelse)

            case ETuple(elts):
                elts = [self.clean_node(e, current_scope) for e in elts]
                return ETuple(elts)
            case EList(elts, element_type):
                elts = [self.clean_node(e, current_scope) for e in elts]
                element_type = self.clean_node(element_type, current_scope)
                return EList(elts, element_type)
            case RangeType(element_type):
                element_type = self.clean_node(element_type, current_scope)
                return RangeType(element_type)

            # Indexing
            case EIndex(seq, index):
                seq = self.clean_node(seq, current_scope)
                index = self.clean_node(index, current_scope)
                return EIndex(seq, index)
            # Slicing
            case ESlice(seq, lower, upper):
                seq = self.clean_node(seq, current_scope)
                lower = self.clean_node(lower, current_scope) if lower is not None else None
                upper = self.clean_node(upper, current_scope) if upper is not None else None
                return ESlice(seq, lower, upper)

            # Leave it as it is
            case InjectedExpression() | EConst() | EVar():
                return node

            # Leave it as it is
            case Identifier():
                return node
            # If the RecordType contains fields that may include Holes, clean them recursively.
            case RecordType():
                for k, v in node.fields.items():
                    node.fields[k] = self.clean_node(v, current_scope)
                return node

            case ListType(element_type):
                element_type = self.clean_node(element_type, current_scope)
                return ListType(element_type)

            # Leave it as it is
            case TInt() | TBool() | TFloat() | TComplex() | TStr():
                return node

            case FunctionType(parameter_types, return_type):
                parameter_types = [self.clean_node(p, current_scope) for p in parameter_types]
                return_type = self.clean_node(return_type, current_scope)
                return FunctionType(parameter_types, return_type)
            # Leave it as it is
            case EmptyStatement() | DescriptionStatement():
                return node

            case CompositeStatement(first, second):
                first = self.clean_node(first, current_scope)
                second = self.clean_node(second, current_scope)
                return CompositeStatement(first, second)

            case FunctionDeclaration(name, function_type, parameters, statement):
                name = self.clean_node(name, current_scope)
                function_type = self.clean_node(function_type, current_scope)
                parameters = [self.clean_node(p, current_scope) for p in parameters]

                func_scope = Scope(parent=current_scope)
                statement = self.clean_node(statement, func_scope)
                return FunctionDeclaration(name, function_type, parameters, statement)

            case DataDeclaration(name, parameters):
                name = self.clean_node(name, current_scope)
                cleaned_params = {k: self.clean_node(v, current_scope) for k, v in parameters.items()}
                self.program.defined_types[name.value] = cleaned_params
                return DataDeclaration(name, cleaned_params)

            case VariableDeclaration(name, type_, expression):
                # An if, else, or match scope is no longer considered empty once it contains a variable
                self.mark_scope_active(current_scope)
                name = self.clean_node(name, current_scope)
                type_ = self.clean_node(type_, current_scope)
                # Clean the initializer first so that assignments like "c = d" work if d was already defined
                expression = self.clean_node(expression, current_scope)
                # Add the variable to the current scope
                if isinstance(current_scope, Scope) and isinstance(name, Identifier):
                    current_scope.add(name, type_)
                return VariableDeclaration(name, type_, expression)

            case ReturnStatement(expression):
                expression = self.clean_node(expression, current_scope)
                return ReturnStatement(expression)
            case TupleType() as tt:
                tt.element_types = [self.clean_node(t, current_scope) for t in tt.element_types]
                return TupleType(element_types=tt.element_types)

            case LiteralType() as lit:
                lit.cases = [self.clean_node(c, current_scope) for c in lit.cases]
                return LiteralType(cases=lit.cases, name=lit.name)

            case MixedType() as mt:
                # Recursively clean all alternatives (cases), in case they contain Holes, RecordTypes, etc.
                mt.cases = [self.clean_node(c, current_scope) for c in mt.cases]
                return MixedType(cases=mt.cases, name=mt.name)

            case SMatch(expr, cases):
                # Mark the scope as non-empty (used for the empty rule)
                self.mark_scope_active(current_scope)
                expr = self.clean_node(expr, current_scope)
                # frozen_parent represents a snapshot of the scope up to this point.
                frozen_parent = current_scope.freeze() if current_scope else None
                new_cases = []
                for c in cases:
                    body_scope = c.scope if isinstance(getattr(c, "scope", None), Scope) else Scope(parent=frozen_parent)

                    the_pattern_holes = []
                    for h in getattr(c, "pattern_values", []) or []:
                        cleaned_hole = self.clean_node(h, body_scope)
                        the_pattern_holes.append(cleaned_hole)

                    body = IList([self.clean_node(stmt, body_scope) for stmt in c.body])

                    new_case = SCase(c.pattern, body, scope=body_scope)
                    if the_pattern_holes:
                        new_case.pattern_values = the_pattern_holes
                    new_cases.append(new_case)

                return SMatch(expr, new_cases)

            case SFor(var, iterable, body, scope=stored_scope):
                iterable = self.clean_node(iterable, current_scope)

                frozen_parent = current_scope.freeze() if current_scope else None

                # reuse the stored loop scope if present
                for_scope = stored_scope if isinstance(stored_scope, Scope) else Scope(parent=frozen_parent)

                var = self.clean_node(var, for_scope)
                new_body = IList([self.clean_node(stmt, for_scope) for stmt in body])

                return SFor(var, iterable, new_body, scope=for_scope)

            case SIf(test, body, orelse):
                # The first three steps are the same as for SMatch
                self.mark_scope_active(current_scope)
                test = self.clean_node(test, current_scope)
                frozen_parent = current_scope.freeze() if current_scope else None
                # The if body has its own scope
                body_scope = Scope(parent=frozen_parent)
                new_body = IList([self.clean_node(stmt, body_scope) for stmt in body])
                # The else branch uses a separate scope and does not inherit variables from the if branch.
                orelse_scope = Scope(parent=frozen_parent)
                new_orelse = IList([self.clean_node(stmt, orelse_scope) for stmt in orelse])
                return SIf(test, new_body, new_orelse)
            case ConstantType(_):
                return node
            case TypeDeclaration(name, type_):
                name = self.clean_node(name, current_scope)
                type_ = self.clean_node(type_, current_scope)
                return TypeDeclaration(name, type_)
            case _:
                raise UnexpectedValueError(node)

    # Cleans up the entire program after each change
    def clean_holes(self, program: Program) -> None:
        # The program maintains the currently selected hole (e.g., after a switch), which the cleaner uses as its starting point.
        self.selected_hole = self.program.selected_hole
        self.holes = []
        # This is the top-level scope for the entire program.
        root_scope = Scope(parent=None)
        self.program.statement = self.clean_node(self.program.statement, current_scope=root_scope)

        if self.selected_hole is None and self.holes:
            # take the last opened hole
            self.selected_hole = self.holes[-1]
        if self.selected_hole:
            self.selected_hole.selected = True

        self.program.selected_hole = self.selected_hole
        self.program.holes = self.holes
