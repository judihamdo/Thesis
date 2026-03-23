from typing import Any

from .immutable_list import IList
from .program import (
    CompositeStatement,
    DescriptionStatement,
    DataDeclaration,
    EConst,
    EFunCall,
    EIndex,
    EList,
    EmptyStatement,
    EOp1,
    ESlice,
    EVar,
    Expression,
    FunctionDeclaration,
    FunctionType,
    Hole,
    Identifier,
    ListType,
    LiteralType,
    MixedType,
    RecordType,
    ReturnStatement,
    SCase,
    Scope,
    SFor,
    SIf,
    SMatch,
    Statement,
    TupleType,
    Type,
    TypeDeclaration,
    TypeRef,
    VariableDeclaration,
)
from .type_checker import does_stmt_always_return

# This file may contain mixed types of helper functions, to prevent any importing cycle


def is_within_destruct(interpreter, hole: Hole) -> bool:
    """Recursively checks whether the hole is located inside a destruct hole/statement."""

    def search(node) -> bool:
        match node:
            case Hole():
                # As soon as the target hole is found → return False.
                if node is hole:
                    return False  # The hole was found, and we are not inside a destruct context.
                if getattr(node, "tactics", None) and "destruct" in node.tactics:
                    # If a destruct hole appears along the path
                    return True
                return False
            case CompositeStatement(first, second):
                return search(first) or search(second)
            case FunctionDeclaration(_, _, _, stmt):
                return search(stmt)
            case VariableDeclaration(_, _, expr):
                return search(expr)
            case SIf(_, body, orelse):
                return any(search(s) for s in body) or any(search(s) for s in orelse)
            case _:
                return False

    return search(interpreter.program.statement)

def has_previous_stmt_in_same_block(interpreter, hole: Hole) -> bool:
    #Checks whether there is at least one statement before this hole in the same scope.
    #The parent is the statement that directly contains the hole.
    parent = find_parent_statement(interpreter, hole)
    # Hole is in if-body oder else-body
    if isinstance(parent, SIf):
        for i, s in enumerate(parent.body):
            if s is hole:
                return any(not isinstance(prev, DescriptionStatement) for prev in parent.body[:i])
        for i, s in enumerate(parent.orelse):
            if s is hole:
                return any(not isinstance(prev, DescriptionStatement) for prev in parent.body[:i])
        return False
    # Hole is in match-case body
    if isinstance(parent, SCase):
        for i, s in enumerate(parent.body):
            if s is hole:
                return any(not isinstance(prev, DescriptionStatement) for prev in parent.body[:i])
        return False

    # Hole is in for-body
    if isinstance(parent, SFor):
        for i, s in enumerate(parent.body):
            if s is hole:
                return any(not isinstance(prev, DescriptionStatement) for prev in parent.body[:i])
        return False

    # Hole is in second in CompositeStatement
    if isinstance(parent, CompositeStatement):
        return parent.second is hole and not isinstance(parent.first, DescriptionStatement)
    return False


"""def has_previous_stmt_in_same_block(interpreter, hole: Hole) -> bool:
    #Checks whether there is at least one statement before this hole in the same scope.
    #The parent is the statement that directly contains the hole.
    parent = find_parent_statement(interpreter, hole)
    # Hole is in if-body oder else-body
    if isinstance(parent, SIf):
        for i, s in enumerate(parent.body):
            if s is hole:
                return i > 0  # There is a statement before it
        for i, s in enumerate(parent.orelse):
            if s is hole:
                return i > 0
        return False
    # Hole is in match-case body
    if isinstance(parent, SCase):
        for i, s in enumerate(parent.body):
            if s is hole:
                return i > 0
        return False

    # Hole is in for-body
    if isinstance(parent, SFor):
        for i, s in enumerate(parent.body):
            if s is hole:
                return i > 0
        return False

    # Hole is in second in CompositeStatement
    if isinstance(parent, CompositeStatement):
        return parent.second is hole
    return False"""


def is_directly_after_total_match(interpreter, hole: Hole) -> bool:
    """helper function, can also be helpful if we have decided to add case_"""
    parent = find_parent_statement(interpreter, hole)
    return (
        isinstance(parent, CompositeStatement)
        and parent.second is hole
        and isinstance(parent.first, SMatch)
        and does_stmt_always_return(parent.first)
    )


def prefix_always_returns(interpreter, hole: Hole) -> bool:
    """
    True exactly when the code immediately before this hole (in the same CompositeStatement)
    returns on all paths. In that case, the hole is unreachable, so `pass` would be harmless.
    """
    parent = find_parent_statement(interpreter, hole)
    if isinstance(parent, CompositeStatement) and parent.second is hole:
        return does_stmt_always_return(parent.first)
    return False


def can_use_pass(interpreter, hole: Hole) -> bool:
    scope = hole.scope
    # Do not allow `pass` outside of a destruct context
    if scope is None:
        return False
    return getattr(scope, "has_destruct_child", False) or has_previous_stmt_in_same_block(interpreter, hole)


def find_parent_statement(interpreter, target: Any) -> Statement | None:
    """
    Recursively searches for the statement that contains `target`. `target` can be a Hole or any AST node.
    Returns None if `target` is directly attached to the program root statement.
    if-body -> SIf, else-body -> SIf, case-body -> SCase
    directly after a statement -> CompositeStatement, directly in the function body (root) -> None
    """

    def search(node: Any, parent: Statement | None = None) -> Statement | None:
        # Wenn der aktuelle Knoten genau target ist-> gib den Parent zurück.
        if node is target:
            return parent
        match node:
            case CompositeStatement(first, second):
                res = search(first, node)
                if res is not None:
                    return res
                return search(second, node)

            case FunctionDeclaration(_, _, _, stmt):
                return search(stmt, node)

            case VariableDeclaration(_, _, expr):
                return search(expr, node)

            case SIf(_, body, orelse):
                for s in body:
                    res = search(s, node)
                    if res is not None:
                        return res
                for s in orelse:
                    res = search(s, node)
                    if res is not None:
                        return res
                return None
            case SFor(var, iterable, body):
                res = search(var, node)
                if res is not None:
                    return res
                res = search(iterable, node)
                if res is not None:
                    return res
                for s in body:
                    res = search(s, node)
                    if res is not None:
                        return res
                return None

            # Match/Case
            case SMatch(expr, cases):
                # firstly search in im Match Expression
                res = search(expr, node)
                if res is not None:
                    return res

                # then in every case:
                for c in cases:
                    # pattern_values (e.g. Record-Feld-Holes)
                    for pat_val in getattr(c, "pattern_values", []) or []:
                        res = search(pat_val, c)
                        if res is not None:
                            return res

                    # body statements
                    for s in c.body:
                        res = search(s, c)
                        if res is not None:
                            return res
                return None
            case _:
                return None

    return search(interpreter.program.statement)


def all_paths_return(interpreter, stmt: Statement | Hole, inside_destruct=False) -> bool:
    """Useful for if/else: if all branches return, then only the `finish` tactic should be available."""
    match stmt:
        case ReturnStatement():
            return True
        case CompositeStatement(first, second):
            first_ret = all_paths_return(interpreter, first, inside_destruct)
            # If the first part already guarantees a return, the second part is irrelevant
            if first_ret:
                return True
            return all_paths_return(interpreter, second, inside_destruct)
        # for match we do not need this, just for if-else
        case SIf(_, body, orelse):
            # For SIf: the path returns only if every branch returns.
            body_all = all(all_paths_return(interpreter, s, inside_destruct) for s in body)
            orelse_all = all(all_paths_return(interpreter, s, inside_destruct) for s in orelse)
            return body_all and orelse_all
        case Hole():
            return False  # still not filled -> no return
        case EmptyStatement():
            return False
        case _:
            return False


def is_top_level_in_function(interpreter, hole: Hole) -> bool:
    """
    True only if the hole is NOT inside a branch block (if/match-case).
    We check the entire ancestor chain, not just the direct parent.
    """
    node: Any = hole
    while True:
        parent = find_parent_statement(interpreter, node)
        if parent is None:
            return True  # Root arrived -> top-level
        if isinstance(parent, (SIf, SCase, SFor)):
            return False  # somewhere in a Branch
        node = parent


def is_hole_directly_after_match(interpreter, hole: Hole) -> bool:
    parent = find_parent_statement(interpreter, hole)
    return isinstance(parent, CompositeStatement) and parent.second is hole and isinstance(parent.first, SMatch)


def is_directly_after_total_return_stmt(interpreter, hole: Hole) -> bool:
    parent = find_parent_statement(interpreter, hole)
    return (
        isinstance(parent, CompositeStatement) and parent.second is hole and isinstance(parent.first, SIf) and does_stmt_always_return(parent.first)
    )


def is_parameter_hole(interpreter, hole: Hole) -> bool:
    """remember intro-holes"""
    parent = find_parent_statement(interpreter, hole)
    return parent is None and hole.type is not None and hole.tactics == {"intro"}


def auto_close_unreachable(interpreter) -> None:
    """Automatically closes holes that are unreachable because previous code already guarantees a return."""
    changed = False
    for h in list(interpreter.program.holes):
        ## The code before it definitely returns (if/match/...)
        if prefix_always_returns(interpreter, h):
            h.filler = EmptyStatement()
            changed = True
    if changed:
        interpreter.hole_cleaner.clean_holes(interpreter.program)


def _type_refs_in_type(interpreter, t: Type) -> set[str]:
    """
    Returns all type names that occur as TypeRef("X") anywhere inside a type.
    Mini example:
    type: A = tuple[B, int] → the type contains TypeRef("B") → returns {"B"}.
    """
    out: set[str] = set()

    def walk(x: Any):
        if isinstance(x, TypeRef):
            out.add(x.name)
        elif isinstance(x, FunctionType):
            for p in x.parameter_types:
                walk(p)
            walk(x.return_type)
        elif isinstance(x, TupleType):
            for e in x.element_types:
                walk(e)
        elif isinstance(x, MixedType):
            for c in x.cases:
                walk(c)
        elif isinstance(x, LiteralType):
            # Literal contains no TypeRefs in cases(just ConstantType)
            return
        elif isinstance(x, RecordType):
            for ft in x.fields.values():
                walk(ft)
        # ignore TInt/TBool/.../ConstantType

    walk(t)
    return out


def _is_data_type_def(interpreter, name: str) -> bool:
    """Return whether the given type name refers to a data type definition in the program."""
    v = interpreter.program.defined_types.get(name)
    # In our system, `data` is currently often stored as a dict or a RecordType
    return isinstance(v, (dict, RecordType))


def _build_type_graph(interpreter) -> dict[str, set[str]]:
    """
    Builds a dependency graph:
    type name -> set of type names it depends on (only via TypeRef).

    Example:
    If we have: data: Predator(pos: Pos)
                type: Animal = Predator | Prey
    then the graph could be:
    Predator -> {"Pos"}, and Animal -> {"Predator", "Prey"} (if cases are stored as TypeRef).
    """
    graph: dict[str, set[str]] = {}
    for name, val in interpreter.program.defined_types.items():
        deps: set[str] = set()
        # data: Name(...) -> val is dict oder RecordType
        if isinstance(val, dict):
            for ft in val.values():
                deps |= _type_refs_in_type(interpreter, ft)
        elif isinstance(val, RecordType):
            for ft in val.fields.values():
                deps |= _type_refs_in_type(interpreter, ft)
        elif isinstance(val, Type):
            deps |= _type_refs_in_type(interpreter, val)
        graph[name] = deps
    return graph


def _missing_type_definitions(interpreter) -> set[str]:
    """
    This function is used in types_ready_for_signature() to block `signature` until everything is defined.
    Example: data: Predator(pos: Pos) but Pos was never defined → missing = {"Pos"}.
    """
    graph = _build_type_graph(interpreter)
    known = set(interpreter.program.defined_types.keys())
    missing = set()
    for deps in graph.values():
        for d in deps:
            if d not in known:
                missing.add(d)
    return missing


def _sccs(interpreter, graph: dict[str, set[str]]) -> list[set[str]]:
    """
    Purpose: Find the strongly connected components (SCCs) of a graph.
    An SCC is a group of nodes that can all reach each other. Such groups
    represent cycles in the graph, including both multi-node cycles
    (e.g., A → B → C → A) and self-loops (A → A).
    Why SCCs are needed:
    They allow detection of both direct and indirect cycles in the graph.
    For example, A → B → C → A forms a single SCC {A, B, C}, while a
    self-loop A → A also forms an SCC (typically {A}).
    Input:
        graph: dict[str, set[str]]
            Adjacency list representation of the graph.
            graph["A"] = {"B", "C"} means there are edges A → B and A → C.
    Output:
        list[set[str]]
            A list of components, where each component is a set of node names.
    Example: graph = {"A": {"B"}, "B": {"C"}, "C": {"A"}, "D": {"C"}} → [{"A", "B", "C"}, {"D"}]
    """
    index = 0  # Tarjan assigns a running number for DFS discovery:
    # the first visited node gets index 0, the next one 1, and so on.

    stack: list[str] = []  # stack stores the current DFS path / active nodes
    onstack: set[str] = set()  # onstack allows a quick check: “is this node currently active?”
    idx: dict[str, int] = {}  # when was v first visited? (discovery index)
    low: dict[str, int] = {}  # the smallest idx value that v can reach via any edges,
    # but only within the current DFS context
    comps: list[set[str]] = []  # here we collect the SCCs

    def strong(v: str):
        nonlocal index  # `nonlocal` means that `index` is taken from the enclosing scope and updated here.
        idx[v] = index
        low[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)

        # With which nodes is A connected?
        for w in graph.get(v, set()):  # For each edge v → w: iterate over all neighbors w.
            if w not in graph:
                continue  # Unknown dependencies are handled separately using the `missing`.
            # 2) If w has not been visited yet → continue the DFS
            if w not in idx:
                strong(w)
                low[v] = min(low[v], low[w])
            # 3) w has already been visited and is still on the stack → this is a back edge, indicating a cycle
            elif w in onstack:
                low[v] = min(low[v], idx[w])

        if low[v] == idx[v]:
            comp = set()
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp.add(w)
                if w == v:
                    break
            comps.append(comp)

    for v in graph.keys():
        if v not in idx:
            strong(v)
    return comps


def _cycles_ok(interpreter) -> bool:
    """
    Purpose: Checks whether cycles in the type graph are allowed according to our defined rules.
    Rules:
    1. If a cycle contains more than one type (e.g., A ↔ B or A → B → A), it is only valid if
    at least one of the types in the cycle is a data type.
    2. If a self-loop exists (A → A), it is only valid if A is a data type.
    """
    graph = _build_type_graph(interpreter)
    for comp in _sccs(interpreter, graph):
        # Case 1: Cycle with multiple types: if the SCC contains no data type → illegal.
        if len(comp) > 1:
            if not any(_is_data_type_def(interpreter, n) for n in comp):
                return False
        # Case 2: SCC with a single node (self-loop).
        # If the type refers to itself and it is not a data type → illegal.
        # Example: type: A = A
        else:
            n = next(iter(comp))
            # interpreter-loop?
            if n in graph.get(n, set()):
                if not _is_data_type_def(interpreter, n):
                    return False
    return True


def types_ready_for_signature(interpreter) -> tuple[bool, str | None]:
    """Check whether all types are fully defined and legally usable before allowing a function signature."""
    missing = _missing_type_definitions(interpreter)
    if missing:
        return False, f"Missing type definitions: {', '.join(sorted(missing))}"
    if not _cycles_ok(interpreter):
        return (
            False,
            "Illegal cyclic type dependency: every cycle must contain at least one `data` type.",
        )
    return True, None


def find_parent_variable_declaration(interpreter, target: Any) -> VariableDeclaration | None:
    """
    Finds the VariableDeclaration whose expression slot (or subtree) contains the target.
    Works also inside SMatch / SCase (pattern_values + body).
    """

    def search(node: Any, parent: Any = None) -> VariableDeclaration | None:
        if node is target:
            return parent if isinstance(parent, VariableDeclaration) else None
        match node:
            case CompositeStatement(first, second):
                res = search(first, node)
                if res is not None:
                    return res
                return search(second, node)

            case FunctionDeclaration(_, _, _, stmt):
                return search(stmt, node)

            case VariableDeclaration(_, _, expr):
                # The target may be the expression itself or nested within it.
                if expr is target:
                    return node
                return search(expr, node)

            case SIf(_, body, orelse):
                for s in body:
                    res = search(s, node)
                    if res is not None:
                        return res
                for s in orelse:
                    res = search(s, node)
                    if res is not None:
                        return res
                return None
            case SFor(var, iterable, body):
                res = search(var, node)
                if res is not None:
                    return res
                res = search(iterable, node)
                if res is not None:
                    return res
                for s in body:
                    res = search(s, node)
                    if res is not None:
                        return res
                return None

            # match/case
            case SMatch(expr, cases):
                # search in im match-Expression
                res = search(expr, node)
                if res is not None:
                    return res

                # in allen cases suchen
                for c in cases:
                    # pattern_values (intro-holes in RecordType)
                    for pv in getattr(c, "pattern_values", []) or []:
                        res = search(pv, c)
                        if res is not None:
                            return res

                    # body statements
                    for s in c.body:
                        res = search(s, c)
                        if res is not None:
                            return res
                return None

    return search(interpreter.program.statement)


def prefix_before(interpreter, d: dict[str, Type], stop_name: str) -> dict[str, Type]:
    """Return a dictionary containing the entries of the input dictionary up to the given name."""
    out: dict[str, Type] = {}
    for k, v in d.items():
        if k == stop_name:
            out[k] = v
            break
        out[k] = v
    return out


def _program_has_signature(interpreter, node: Any) -> bool:
    """Recursively check whether the program AST already contains a function signature."""
    match node:
        case FunctionDeclaration():
            return True
        case CompositeStatement(a, b):
            return _program_has_signature(interpreter, a) or _program_has_signature(interpreter, b)
        case Hole() as h:
            return _program_has_signature(interpreter, h.filler) if h.filler is not None else False
        case _:
            return False


def _resolve_ref(interpreter, t: Type) -> Type:
    """Recursively resolve TypeRef until it is no longer a TypeRef."""
    while isinstance(t, TypeRef):
        name = t.name
        if name not in interpreter.program.defined_types:
            return t  # Forward reference remains (should not occur before signature resolution).
        real = interpreter.program.defined_types[name]
        if isinstance(real, dict):
            t = RecordType(fields=real, name=name)
        else:
            t = real
    return t


def _resolve_type_refs(interpreter, t: Type, visiting: set[str]) -> Type:
    """
    Takes a type t (e.g., TypeRef("Animal"), FunctionType(...), RecordType(...), MixedType(...))
    and replaces all TypeRef(...) occurrences that are defined in defined_types with their
    actual types.

    In other words, it traverses a type tree (a Type object) and replaces every TypeRef("X")
    with the corresponding definition from program.defined_types as far as possible.
    The visiting set prevents infinite recursion in the presence of cycles (e.g., A → B → A).
    """

    # If a type currently being expanded (e.g., Animal) is encountered again,
    # stop the expansion and return TypeRef("Animal") to avoid infinite recursion.
    if isinstance(t, MixedType) and t.name is not None and t.name in visiting:
        return TypeRef(t.name)

    if isinstance(t, RecordType) and t.name in visiting:
        return TypeRef(t.name)

    # Resolve TypeRef if it is defined.
    # This is the core logic: if a cycle is detected, return TypeRef(name) and stop.
    # If the definition is missing, keep the TypeRef as is (forward reference).
    # In general, visiting.add(...) and visiting.remove(...) are used to prevent cycles.
    if isinstance(t, TypeRef):
        name = t.name
        if name in visiting:
            return t  # Cycle detected → do not expand further
        if name not in interpreter.program.defined_types:
            return t  # Not yet defined → keep as TypeRef

        visiting.add(name)
        real = interpreter.program.defined_types[name]

        # If data is stored as a dict, convert it to a RecordType
        if isinstance(real, dict):
            real_t: Type = RecordType(fields=real, name=name)
        else:
            real_t = real

        resolved = _resolve_type_refs(interpreter, real_t, visiting)
        visiting.remove(name)
        return resolved

    # Recursively process composite types
    if isinstance(t, FunctionType):
        ps = [_resolve_type_refs(interpreter, p, visiting) for p in t.parameter_types]
        rt = _resolve_type_refs(interpreter, t.return_type, visiting)
        return FunctionType(ps, rt)

    if isinstance(t, TupleType):
        return TupleType([_resolve_type_refs(interpreter, x, visiting) for x in t.element_types])
    # If Animal appears again in its own definition, stop.
    if isinstance(t, MixedType):
        if t.name is not None:
            if t.name in visiting:
                return TypeRef(t.name)
            visiting.add(t.name)
            # Cases are normalized recursively so that the MixedType later contains actual type objects.
            # In other words, each case is not only normalized, but also handled properly in the same way as the parent case.
            cases = [_resolve_type_refs(interpreter, c, visiting) for c in t.cases]
            visiting.remove(t.name)
            return MixedType(cases, name=t.name)
        # No separate cycle detection via t.name is needed here,
        # because there is no name that could be tracked as a type node.
        return MixedType([_resolve_type_refs(interpreter, c, visiting) for c in t.cases], name=None)

    if isinstance(t, RecordType):
        if t.name in visiting:
            return TypeRef(t.name)
        visiting.add(t.name)
        new_fields = {k: _resolve_type_refs(interpreter, v, visiting) for k, v in t.fields.items()}
        visiting.remove(t.name)
        return RecordType(fields=new_fields, name=t.name)
    # Literal types and primitive types remain unchanged.
    return t


def resolve_all_defined_types(interpreter) -> None:
    """
    Iterate over all defined types (interpreter.program.defined_types) and
    resolve TypeRefs where possible.

    A new dictionary is created, and in the end program.defined_types is
    replaced with this updated dictionary.
    """
    new_map: dict[str, Type] = {}
    for name, val in interpreter.program.defined_types.items():
        # If a data type is stored as a dict, convert it to a RecordType
        # so that the representation remains consistent everywhere.
        if isinstance(val, dict):
            # Before: "Predator" -> {"x": TInt(), "y": TInt()}
            # After:  "Predator" -> RecordType(fields={...}, name="Predator")
            base: Type = RecordType(fields=val, name=name)
        else:
            base = val
        # _resolve_type_refs(...) recursively traverses base.
        # If it encounters TypeRef("Something") and "Something" exists in
        # defined_types, it replaces it with the actual definition.
        # visiting=set() is the safeguard against cycles:
        # if types reference each other (A → B → A), the process stops
        # safely and keeps a TypeRef instead of expanding indefinitely.
        new_map[name] = _resolve_type_refs(interpreter, base, visiting=set())
    interpreter.program.defined_types = new_map


def resolve_types_in_ast(interpreter) -> None:
    """
    Purpose: Traverse the entire AST of the program (including holes, declarations,
    ReturnStatements, DataDeclarations, TypeDeclarations, match cases, etc.)
    and resolve all stored type fields by calling _resolve_type_refs(...).

    This ensures that the AST contains actual type objects wherever possible,
    instead of unresolved TypeRefs.
    """

    def rt(t: Type) -> Type:
        return _resolve_type_refs(interpreter, t, visiting=set())

    def walk_stmt(s: Any) -> Any:
        match s:
            case Hole() as h:
                # If the hole has an expected type (h.type), it is resolved.
                if h.type is not None:
                    h.type = rt(h.type)
                # If the hole is already filled (h.filler), traverse into its contents.
                if h.filler is not None:
                    h.filler = walk_stmt(h.filler)
                return h

            case FunctionDeclaration(name, ftype, params, body):
                # Fix the function type
                ftype = rt(ftype)
                # Fix Parameter holes/identifiers.. type
                new_params = []
                for p in params:
                    if isinstance(p, Hole) and p.type is not None:
                        p.type = rt(p.type)
                    new_params.append(p)
                body = walk_stmt(body)
                return FunctionDeclaration(name, ftype, new_params, body)

            case VariableDeclaration(name, type_, expr):
                type_ = rt(type_)
                expr = walk_stmt(expr)
                return VariableDeclaration(name, type_, expr)

            case ReturnStatement(val, expected_type=et):
                if et is not None:
                    et = rt(et)
                val = walk_stmt(val)
                return ReturnStatement(val, expected_type=et)

            case DataDeclaration(name, params):
                new_params = {k: rt(v) for k, v in params.items()}
                return DataDeclaration(name, new_params)

            case TypeDeclaration(name, type_):
                return TypeDeclaration(name, rt(type_))

            case CompositeStatement(a, b):
                return CompositeStatement(walk_stmt(a), walk_stmt(b))

            case SIf(test, body, orelse):
                new_body = IList([walk_stmt(x) for x in body])
                new_orelse = IList([walk_stmt(x) for x in orelse])
                return SIf(test, new_body, new_orelse)

            case SMatch(expr, cases):
                new_cases = []
                for c in cases:
                    pvals = []
                    for pv in c.pattern_values or []:
                        pvals.append(walk_stmt(pv))
                    new_body = IList([walk_stmt(x) for x in c.body])
                    nc = SCase(c.pattern, new_body, pattern_values=pvals, scope=c.scope)
                    new_cases.append(nc)
                return SMatch(expr, new_cases, scope=s.scope)

            case _:
                return s

    interpreter.program.statement = walk_stmt(interpreter.program.statement)


def mixed_needs_new(interpreter, t: Type, visiting: set[int] | None = None) -> bool:
    """Return whether a type is or contains a constructible case that requires or allows the `new` tactic."""
    t = _resolve_ref_deep(interpreter, t)

    if visiting is None:
        visiting = set()

    # direct constructibles
    if isinstance(t, (RecordType, ListType, TupleType)):
        return True

    oid = id(t)
    if oid in visiting:
        return False
    visiting.add(oid)

    if isinstance(t, MixedType):
        ok = any(mixed_needs_new(interpreter, _resolve_ref_deep(interpreter, c), visiting) for c in (t.cases or []))
        visiting.remove(oid)
        return ok

    visiting.remove(oid)
    return False


def _resolve_ref_deep(interpreter, t: Type) -> Type:
    """repeatedly resolve TypeRef if possible"""
    while isinstance(t, TypeRef) and t.name in interpreter.program.defined_types:
        real = interpreter.program.defined_types[t.name]
        if isinstance(real, dict):
            t = RecordType(fields=real, name=t.name)
        else:
            t = real
    return t


def find_record_ctor(interpreter, t: Type, ctor: str) -> RecordType | None:
    """resolve TypeRef if any still exists"""
    t = _resolve_ref(interpreter, t)

    if isinstance(t, RecordType):
        return t if t.name == ctor else None

    if isinstance(t, MixedType):
        for alt in t.cases or []:
            r = find_record_ctor(interpreter, alt, ctor)
            if r is not None:
                return r

    return None


def _const_int(x: Expression | None) -> int | None:
    """helper: const int (inkl. -1 als EOp1("-", EConst(1)))"""
    if x is None:
        return None
    if isinstance(x, EConst) and isinstance(x.value, int) and not isinstance(x.value, bool):
        return x.value
    if isinstance(x, EOp1) and x.op == "-" and isinstance(x.operand, EConst):
        v = x.operand.value
        if isinstance(v, int) and not isinstance(v, bool):
            return -v
    return None


def infer_list_len(interpreter, expr: Expression) -> int | None:
    """Rekursiv Listenlänge inferieren"""
    # xs
    if isinstance(expr, EVar) and isinstance(expr.name, Identifier):
        n = interpreter.program.list_lengths.get(expr.name.value)
        return n if isinstance(n, int) else None

    # [a,b,c]
    if isinstance(expr, EList):
        return len(expr.elts)

    # xs[a:b]
    if isinstance(expr, ESlice):
        a = _const_int(expr.lower)
        b = _const_int(expr.upper)
        if a is None or b is None:
            return None
        if a <= b:
            return b - a
        return None

    # my_li[0] -> inner length
    if isinstance(expr, EIndex) and isinstance(expr.seq, EVar) and isinstance(expr.seq.name, Identifier):
        i = _const_int(expr.index)
        if i is None:
            return None
        return interpreter.program.nested_list_lengths.get((expr.seq.name.value, i))

    return None


# ------------------------------------------------------------
def is_structural(node: Any) -> bool:
    """Used to avoid running collect_variables repeatedly.
    Structural nodes are those that can introduce new statements, scopes or declarations"""
    return isinstance(
        node,
        (
            Statement,
            CompositeStatement,
            FunctionDeclaration,
            VariableDeclaration,
            TypeDeclaration,
            DataDeclaration,
            SIf,
            SMatch,
            SFor,
        ),
    )


# ------------------------------------------------------------
def collect_variables(interpreter, node: Any, current_scope: Scope | None = None) -> None:
    """This function does the following: Collect Variables/Types + Type_check + Holes cleaning"""
    if isinstance(node, VariableDeclaration):
        var_id = node.name if isinstance(node.name, Identifier) else Identifier(str(node.name))
        if current_scope is not None:
            current_scope.add(var_id, node.type_)
        else:
            interpreter.program.variables[var_id] = node.type_

    elif isinstance(node, CompositeStatement):
        collect_variables(interpreter, node.first, current_scope)
        collect_variables(interpreter, node.second, current_scope)

    elif isinstance(node, FunctionDeclaration):
        for param, ptype in zip(node.parameters, node.function_type.parameter_types):
            if isinstance(param, Identifier):
                interpreter.program.variables[param] = ptype
        collect_variables(interpreter, node.statement, current_scope)

    elif isinstance(node, TypeDeclaration):
        if not hasattr(interpreter.program, "defined_types"):
            interpreter.program.defined_types = {}
        interpreter.program.defined_types[node.name.value] = node.type_

    elif isinstance(node, Hole) and node.filler is not None:
        collect_variables(interpreter, node.filler, current_scope)


def update_list_lengths_after_fill(interp, parent_decl, filler) -> None:
    """Update stored length information for a filled list variable, including known lengths of nested sublists."""
    if not (parent_decl is not None and isinstance(parent_decl.name, Identifier) and isinstance(parent_decl.type_, ListType)):
        return

    dst = parent_decl.name.value

    if isinstance(filler, Expression):
        interp.program.list_lengths[dst] = infer_list_len(interp, filler)

    if isinstance(parent_decl.type_.element_type, ListType) and isinstance(filler, EList):
        for i, elt in enumerate(filler.elts):
            if isinstance(elt, Expression):
                inner_n = infer_list_len(interp, elt)
                if isinstance(inner_n, int):
                    interp.program.nested_list_lengths[(dst, i)] = inner_n


def postprocess_new(interp, hole, parent_decl, filler) -> Any:
    """Determine decl_ty without performing another parent_decl lookup."""
    if getattr(hole, "is_return_hole", False):
        decl_ty = interp.return_type
    elif parent_decl is not None and getattr(parent_decl, "type_", None) is not None:
        decl_ty = parent_decl.type_
    else:
        decl_ty = hole.type
    # If decl_ty is only a name, resolve the TypeRef/identifier.
    if isinstance(decl_ty, Identifier) and decl_ty.value in interp.program.defined_types:
        dt = interp.program.defined_types[decl_ty.value]
        # If defined_types["Predator"] is a dict (as produced by data:),
        # convert it to RecordType(fields=..., name=...).
        # LiteralType and MixedType are not stored as dictionaries in defined_types.
        if isinstance(dt, dict):
            decl_ty = RecordType(fields=dt, name=decl_ty.value)
        # If defined_types["X"] is already a Type (e.g. MixedType, LiteralType, alias, etc.), use it directly.
        elif isinstance(dt, Type):
            decl_ty = dt

    # after decl_ty is determined...
    if isinstance(decl_ty, TypeRef):
        dt = interp.program.defined_types.get(decl_ty.name)
        if isinstance(dt, dict):
            decl_ty = RecordType(fields=dt, name=decl_ty.name)
        elif isinstance(dt, Type):
            decl_ty = dt

    # RecordType: expand constructor name into a function call with field holes.
    # If the expected type is a RecordType and the filler only contains the
    # constructor name (e.g. Mobile), it is automatically expanded into a
    # constructor call with field holes:
    # Mobile → Mobile([0*], [1*], ...) (an EFunCall with one fill hole per field).
    # Example: new:Mobile()
    if isinstance(decl_ty, RecordType):
        # ctor = Constructor
        ctor_name = None
        # If the filler is only Mobile (EVar("Mobile")), then ctor_name = "Mobile".
        if isinstance(filler, EVar) and isinstance(filler.name, Identifier):
            ctor_name = filler.name.value
        # Only if the correct constructor was actually selected.
        if ctor_name == decl_ty.name:
            arg_holes: list[Hole] = []
            for _field_name, field_type in decl_ty.fields.items():
                arg_holes.append(
                    Hole(
                        tactics={"fill"},
                        type=field_type,
                        scope=hole.scope,
                    )
                )
            filler = EFunCall(EVar(Identifier(decl_ty.name)), arg_holes)
            hole.filler = filler

    # MixedType: the constructor must match a RecordType case -> expand it into a function call with field holes.
    elif isinstance(decl_ty, MixedType):
        ctor_name = None
        if isinstance(filler, EVar) and isinstance(filler.name, Identifier):
            ctor_name = filler.name.value

        if ctor_name is not None:
            chosen_rec = find_record_ctor(interp, decl_ty, ctor_name)

            if chosen_rec is not None:
                arg_holes: list[Hole] = [Hole(tactics={"fill"}, type=ft, scope=hole.scope) for ft in chosen_rec.fields.values()]
                hole.filler = EFunCall(EVar(Identifier(chosen_rec.name)), arg_holes)
    return hole.filler if hole.filler is not None else filler
