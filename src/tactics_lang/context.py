from typing import Any, TypeAlias

from .helper_functions import find_parent_statement, find_parent_variable_declaration, prefix_before
from .program import (
    CompositeStatement,
    EIndex,
    ESlice,
    # Expressions
    Expression,
    FunctionDeclaration,
    Hole,
    Identifier,
    ListType,
    Program,
    Scope,
    SIf,
    SMatch,
    # Statements
    Statement,
    TInt,
    # Types
    Type,
    TypeDeclaration,
    VariableDeclaration,
)
from .type_checker import check_type_equal, type_check_expr
from .utility import TypeCheckerError

TCtx: TypeAlias = dict[str, Type]


def check_ctx_equal(ctx1: TCtx, ctx2: TCtx, es: Expression | Statement, program) -> None:
    """Ensures that variables shared by two contexts have compatible types."""
    for x in ctx1.keys():
        if x in ctx2:
            check_type_equal(ctx1[x], ctx2[x], es, program)


# ********************************************************************************************
def ctx_from_program(program: Program, len_ctx: dict[str, int | None] | None = None) -> dict[str, Type]:
    """ Builds a type context from a Program object"""
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
                for stmt in body or []:
                    collect(stmt)
                for stmt in orelse or []:
                    collect(stmt)
            case SMatch(expr, cases):
                collect(expr)
                for c in cases or []:
                    if c is None:
                        continue
                    for h in getattr(c, "pattern_values", []) or []:
                        if h is not None:
                            collect(h)
                    for stmt in c.body or []:
                        if stmt is not None:
                            collect(stmt)

            case EIndex(seq, index):
                t_seq = type_check_expr(ctx, seq, program, len_ctx=len_ctx)
                t_i = type_check_expr(ctx, index, program, len_ctx=len_ctx)
                check_type_equal(t_i, TInt(), index, program)

                if not isinstance(t_seq, ListType):
                    raise TypeCheckerError("❌ Indexing only allowed on list[T]")

                return t_seq.element_type

            case ESlice(seq, lower, upper):
                t_seq = type_check_expr(ctx, seq, program, len_ctx=len_ctx)

                if not isinstance(t_seq, ListType):
                    raise TypeCheckerError("❌ Slicing only allowed on list[T]")

                if lower is not None:
                    check_type_equal(
                        type_check_expr(ctx, lower, program, len_ctx=len_ctx),
                        TInt(),
                        lower,
                        program,
                    )
                if upper is not None:
                    check_type_equal(
                        type_check_expr(ctx, upper, program, len_ctx=len_ctx),
                        TInt(),
                        upper,
                        program,
                    )

                return ListType(t_seq.element_type)

            case TypeDeclaration(_, _):
                pass
            case _:
                pass

    collect(program.statement)
    return ctx


# **************************************************************************************
def normalize_keys(d: dict) -> dict[str, Type]:
    return {(k.value if isinstance(k, Identifier) else str(k)): v for k, v in d.items()}


def build_full_scope(interpreter, hole: Hole) -> Scope:
    parent_stmt = find_parent_statement(interpreter, hole)
    full_scope = Scope(hole.scope) if hole.scope else Scope()
    # Collect all parent variables.
    # Traverse upward and gather the names from parent scopes.
    while parent_stmt:
        # If there is a `let` expression somewhere above this node in the AST,
        # the variable is visible here. Therefore, add it to the full_scope.
        if isinstance(parent_stmt, VariableDeclaration):
            full_scope.add(parent_stmt.name, parent_stmt.type_)
        # This is related to the program's main function
        elif isinstance(parent_stmt, FunctionDeclaration):
            for param, ptype in zip(parent_stmt.parameters, parent_stmt.function_type.parameter_types):
                if isinstance(param, Identifier):
                    full_scope.add(param, ptype)

        parent_stmt = find_parent_statement(interpreter, parent_stmt)
    full_scope.vars.update(interpreter.program.variables)
    full_scope.vars.update(interpreter.global_scope.copy_all())
    return full_scope


def make_ctx_for_typecheck(interpreter, hole):
    parent_decl = find_parent_variable_declaration(interpreter, hole)

    ctx: dict[str, Type] = {}
    if isinstance(hole.scope, Scope):
        if parent_decl is not None:
            decl_name = parent_decl.name.value if isinstance(parent_decl.name, Identifier) else str(parent_decl.name)
            if hole.scope.parent:
                ctx.update(normalize_keys(hole.scope.parent.copy_all()))
            ctx.update(prefix_before(interpreter, hole.scope.vars, decl_name))
        else:
            ctx.update(normalize_keys(hole.scope.copy_all()))
    else:
        ctx.update(normalize_keys(interpreter.global_scope.copy_all()))

    ctx.update(normalize_keys(interpreter.program.variables))
    return parent_decl, ctx
