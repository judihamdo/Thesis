from .context import build_full_scope
from .helper_functions import (
    _resolve_ref,
    _resolve_ref_deep,
    find_parent_statement,
    find_parent_variable_declaration,
    is_parameter_hole,
    mixed_needs_new,
    resolve_all_defined_types,
    resolve_types_in_ast,
    types_ready_for_signature,
)
from .immutable_list import IList
from .parser import (
    parse_data_type,
    parse_expression,
    parse_identifier,
    parse_integer,
    parse_literal,
    parse_mixed_type,
    parse_type,
)
from .program import (
    CompositeStatement,
    DataDeclaration,
    DescriptionStatement,
    EConst,
    EIndex,
    EList,
    EmptyStatement,
    EOp1,
    ESlice,
    ETuple,
    EVar,
    Expression,
    FunctionDeclaration,
    FunctionType,
    Hole,
    Identifier,
    ListType,
    LiteralType,
    MixedType,
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
    Type,
    TypeDeclaration,
    TypeRef,
    VariableDeclaration,
)
from .repl import print_program
from .type_checker import check_type_equal, type_check_expr
from .utility import TacticError, TerminationException, TypeCheckerError
from .visualise import pretty_type


def _tactic_description(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No description specified")
    description = data.strip()
    interpreter.fill_selected_hole(CompositeStatement(DescriptionStatement(description), Hole({"signature", "type", "data"})))
    print_program(interpreter, "Added description")


def _tactic_comment(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌No comment specified")

    selected_hole = interpreter.get_selected_hole()

    # Allow comments only in statement holes (not in expression holes).
    if not selected_hole.tactics.isdisjoint({"fill", "new", "nil", "cons"}) or selected_hole.tactics == {"intro"}:
        raise TacticError("❌ comment is not allowed in expression holes")

    # Important: the hole remains open afterward, with the same tactics and the same scope.
    interpreter.fill_selected_hole(
        CompositeStatement(
            DescriptionStatement(data.strip()),
            Hole(selected_hole.tactics, scope=selected_hole.scope),
        )
    )
    print_program(interpreter, "Added comment")


def _tactic_type(interpreter, data: str) -> None:
    data = data.strip()
    if data == "empty":
        interpreter.fill_selected_hole(CompositeStatement(EmptyStatement(), Hole({"signature", "data"})))
        print_program(interpreter, "Added a new type")
        return
    if "=" not in data:
        raise TacticError("❌ Missing '=' after type name")
    name_str, rhs = data.split("=", 1)
    my_identifier = parse_identifier(name_str.strip())

    rhs = rhs.strip()
    # Literal[...]
    if rhs.startswith("Literal"):
        my_type = parse_literal(rhs)
        my_type.name = my_identifier.value
    # MixedType with '|'
    elif "|" in rhs:
        my_type = parse_mixed_type(
            rhs,
            name=my_identifier.value,
            custom_types=interpreter.program.defined_types,
        )
    # MixedType consisting of a single element.
    else:
        my_type = parse_type(rhs, custom_types=interpreter.program.defined_types)
    # register type in the üprogram
    interpreter.program.defined_types[my_identifier.value] = my_type
    interpreter.used_variables_names.add(my_identifier)

    my_hole = Hole({"type", "signature", "data"})
    interpreter.fill_selected_hole(CompositeStatement(TypeDeclaration(my_identifier, my_type), my_hole))
    print_program(interpreter, "Added a new type")
    resolve_all_defined_types(interpreter)
    resolve_types_in_ast(interpreter)


def _tactic_signature(interpreter, data: str) -> None:
    ready, msg = types_ready_for_signature(interpreter)
    if not ready:
        raise TacticError(msg or "❌ Types are not ready for signature yet.")

    if data.strip() == "":
        raise TacticError("❌ No signature name specified")

    if ":" not in data:
        raise TacticError("❌ Missing ':' after signature name")

    # Separate between Name und type of the Function
    name, function_type_str = data.split(":", 1)
    identifier = parse_identifier(name)

    if function_type_str.strip() == "":
        raise TacticError("❌ No function type specified")

    # Parse the function type using the already defined types (e.g. Pet).
    function_type: FunctionType = parse_type(function_type_str, custom_types=interpreter.program.defined_types)

    if not isinstance(function_type, FunctionType):
        raise TacticError("❌ Only function types are allowed for the signature")
    parameter_holes = []

    for t in function_type.parameter_types:
        if isinstance(t, LiteralType):
            # Named LiteralType (e.g. Pet) or unnamed literal directly.
            if t.name is not None and t.name in interpreter.program.defined_types:
                # Hole takes den named Typ from defined_types
                param_type = interpreter.program.defined_types[t.name]
            else:
                # Unnamed LiteralType remains unchanged
                param_type = t
            parameter_holes.append(Hole({"intro"}, type=param_type))
        else:
            # Normal types wie TInt, TBool, etc.
            parameter_holes.append(Hole({"intro"}, type=t))
    # Add function
    interpreter.fill_selected_hole(
        FunctionDeclaration(
            name=identifier,
            function_type=function_type,
            parameters=parameter_holes,
            statement=Hole({"let", "return", "destruct"}),
        )
    )
    interpreter.return_type = function_type.return_type
    print_program(interpreter, "Added signature")


def _tactic_intro(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No variable names specified")
    identifier = parse_identifier(data)

    # Check not only program.variables, but everything that is visible
    # (global variables + scoped variables).
    selected_hole = interpreter.program.selected_hole
    if not selected_hole:
        raise TacticError("❌ No hole selected to fill")

    visible: dict[str, Type] = {}

    # If we are inside a branch/case: collect everything visible from this scope.
    if isinstance(selected_hole.scope, Scope):
        visible.update(selected_hole.scope.copy_all())

    # Global / program-wide variables.
    # program.variables may have keys as str or Identifier → normalize them.
    for k, v in interpreter.program.variables.items():
        kk = k.value if isinstance(k, Identifier) else str(k)
        visible[kk] = v

    # global scope (function-wide)
    if hasattr(interpreter, "global_scope") and isinstance(interpreter.global_scope, Scope):
        visible.update(interpreter.global_scope.copy_all())

    # Prevent collisions: the name must NOT match any existing variable.
    if identifier.value in visible:
        raise TacticError("❌ it already exists variable with this name")
    if identifier.value in interpreter.program.variables or identifier.value in interpreter.used_variables_names:
        raise TacticError("❌ it already exists variable with this name")
    if identifier in interpreter.program.variables or identifier in interpreter.used_variables_names:
        raise TacticError("❌ it already exists variable with this name")
    # Take the type directly from the hole.
    if selected_hole.type is not None:
        parentt = find_parent_statement(interpreter, selected_hole)
        # Is it in the intro holes of the main program?
        if is_parameter_hole(interpreter, selected_hole):
            if parentt is None:
                interpreter.program.variables[identifier.value] = selected_hole.type
            interpreter.used_variables_names.add(identifier.value)
        else:
            if isinstance(selected_hole.scope, Scope):
                selected_hole.scope.add(identifier, selected_hole.type)
            if parentt is None:
                interpreter.program.variables[identifier.value] = selected_hole.type
            interpreter.used_variables_names.add(identifier.value)
    else:
        raise TacticError("❌ Selected hole has no type info")
    interpreter.fill_selected_hole(identifier)
    print_program(interpreter, "Introduced name")


def _tactic_let(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No variable name specified")
    if ":" not in data:
        raise TacticError("❌ Missing ':' after variable name")
    name_str, type_str = data.split(":", 1)
    name = parse_identifier(name_str)
    if type_str.strip() == "":
        raise TacticError("❌ No variable type specified")
    type_ = parse_type(type_str, custom_types=interpreter.program.defined_types)
    selected_hole = interpreter.get_selected_hole()
    # Must be globally unique
    if name.value in interpreter.used_variables_names:
        raise TacticError(f"❌Variable '{name.value}' was already introduced by a let")

    if selected_hole.scope is None:
        scope_to_use = interpreter.global_scope
    else:
        scope_to_use = selected_hole.scope

    # A name must not appear more than once in the same branch.
    if scope_to_use.get(name.value) is not None:
        raise TacticError(f"❌ Variable '{name.value}' already exists in this scope/branch")
    scope_to_use.add(name, type_)
    # Remember name
    interpreter.used_variables_names.add(name.value)
    # Both new holes must have the same Scope
    init_scope = scope_to_use
    rest_scope = scope_to_use
    is_record = isinstance(type_, RecordType)  # (works only if parse_type returns RecordType)
    is_mixed = mixed_needs_new(interpreter, type_)

    def decide_mixed_type(t: Type, visiting: set[int] | None = None) -> bool:
        """
        True iff t is (or contains anywhere inside) a RecordType/ListType/TupleType.
        Assumes no TypeRef at this stage.
        Uses 'visiting' as recursion stack to avoid infinite recursion on real cycles.
        """
        if visiting is None:
            visiting = set()

        # direct constructibles
        if isinstance(t, (RecordType, ListType, TupleType)):
            return True

        # Only container types can create cycles -> guard them with visiting stack
        oid = id(t)
        if oid in visiting:
            return False

        if isinstance(t, MixedType):
            visiting.add(oid)
            ok = any(decide_mixed_type(c, visiting) for c in (t.cases or []))
            visiting.remove(oid)
            return ok

        if isinstance(t, RecordType):
            visiting.add(oid)
            ok = any(decide_mixed_type(ft, visiting) for ft in t.fields.values())
            visiting.remove(oid)
            return ok

        if isinstance(t, ListType):
            visiting.add(oid)
            ok = decide_mixed_type(t.element_type, visiting)
            visiting.remove(oid)
            return ok

        if isinstance(t, TupleType):
            visiting.add(oid)
            ok = any(decide_mixed_type(x, visiting) for x in t.element_types)
            visiting.remove(oid)
            return ok

        return False

    is_list = isinstance(type_, ListType)
    if isinstance(type_, ListType):
        interpreter.program.list_lengths[name.value] = 0
    else:
        interpreter.program.list_lengths[name.value] = None

    if is_record or is_mixed or isinstance(type_, TupleType) or is_list:
        chosen_hole = Hole({"new", "fill"}, scope=init_scope)
    else:
        chosen_hole = Hole({"fill"}, scope=init_scope)

    interpreter.fill_selected_hole(
        CompositeStatement(
            VariableDeclaration(name, type_, chosen_hole),
            Hole(selected_hole.tactics, scope=rest_scope),
        )
    )
    print_program(interpreter, "Added variable declaration")


def _tactic_data(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No expression specified")
    # Parsen
    data_name, parameters = parse_data_type(
        data,
        custom_types=interpreter.program.defined_types,
    )
    data_decl = DataDeclaration(name=data_name, parameters=parameters)
    if data_decl.name in interpreter.program.defined_types or data_decl.name in interpreter.used_variables_names:
        raise TacticError("❌ The name is taken")
    selected_hole = interpreter.get_selected_hole()
    # Firstly save the type
    interpreter.program.defined_types[data_decl.name.value] = data_decl.parameters
    interpreter.used_variables_names.add(data_decl.name.value)
    # Then fill hole
    interpreter.fill_selected_hole(CompositeStatement(data_decl, Hole(selected_hole.tactics, scope=selected_hole.scope)))
    resolve_all_defined_types(interpreter)
    resolve_types_in_ast(interpreter)
    print_program(interpreter, "Added Data")


def _tactic_fill(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No expression specified")

    expression = parse_expression(data.strip())
    selected_hole = interpreter.get_selected_hole()

    # Only care about the case: fill: <single name>
    if isinstance(expression, EVar) and isinstance(expression.name, Identifier):
        name = expression.name.value

        # 1) Is it a variable in visible scope/program/global? -> allowed
        visible: set[str] = set()

        if isinstance(selected_hole.scope, Scope):
            visible |= set(selected_hole.scope.copy_all().keys())

        # program.variables keys can be str or Identifier
        for k in interpreter.program.variables.keys():
            visible.add(k.value if isinstance(k, Identifier) else str(k))

        if isinstance(interpreter.global_scope, Scope):
            visible |= set(interpreter.global_scope.copy_all().keys())

        if name not in visible:
            # 2) Not a variable. If it's a data/record constructor name -> forbid fill, require new
            dt = interpreter.program.defined_types.get(name)
            if isinstance(dt, (dict, RecordType)):
                raise TacticError(f"❌ '{name}' is a constructor name, not a value. Use `new: {name}`.")

    interpreter.fill_selected_hole(expression)
    print_program(interpreter, "Added expression")


def _tactic_new(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No expression specified")
    selected_hole = interpreter.get_selected_hole()
    selected_hole._used_new = True
    ctor_name = data.strip()
    expected_ty = selected_hole.type
    parent_decl = find_parent_variable_declaration(interpreter, selected_hole)
    if expected_ty is None and parent_decl is not None:
        expected_ty = parent_decl.type_

    # list[...] Konstruktion ---
    if isinstance(expected_ty, ListType):
        # data must be "list[T]"
        try:
            ty = parse_type(data.strip(), custom_types=interpreter.program.defined_types)
        except TacticError as e:
            raise TacticError(f"❌ Invalid list type in new: {e}")

        if not isinstance(ty, ListType):
            raise TacticError("❌ For list construction use: new: list[T].")

        # The inner type must match.
        check_type_equal(
            ty.element_type,
            expected_ty.element_type,
            interpreter.get_selected_hole(),
            interpreter.program,
        )

        # *** The List_hole ***
        list_hole = Hole(
            tactics={"cons", "nil"},  # Only these operations
            kind="list",
            type=expected_ty,
            scope=interpreter.get_selected_hole().scope,
        )
        # Build Metadaten for List
        list_hole.list_element_type = expected_ty.element_type  # <<< hinzufügen
        list_hole.list_elements = []  # vorhandene Elemente
        list_hole.length = 0  # <<< NEU
        list_hole.owner = parent_decl.name.value if parent_decl else None
        if parent_decl is not None and isinstance(parent_decl.name, Identifier):
            list_hole.owner = parent_decl.name.value
            interpreter.program.list_lengths[list_hole.owner] = 0
        else:
            list_hole.owner = None

        # fill the actual expression-hole direct with the list_hole
        interpreter.fill_selected_hole(list_hole)
        print_program(interpreter, "Created list hole")
        return

    # tuple[...] Konstruktion
    elif isinstance(expected_ty, TupleType):
        try:
            ty = parse_type(data.strip(), custom_types=interpreter.program.defined_types)
        except TacticError as e:
            raise TacticError(f"❌ Invalid tuple type in new: {e}")

        if not isinstance(ty, TupleType):
            raise TacticError("❌ For tuple construction use: new: tuple[...].")

        # Check that the arity matches.
        # For example, if tuple[int, str] is expected (2 elements), the user must not provide tuple[int].
        if len(ty.element_types) != len(expected_ty.element_types):
            raise TacticError("❌ Tuple arity does not match expected type")

        # Element types must match.
        for have, exp in zip(ty.element_types, expected_ty.element_types):
            # benutzt deinen vorhandenen Type-Vergleich inkl. Promotion/MixedType
            check_type_equal(have, exp, interpreter.get_selected_hole(), interpreter.program)

        # Create a tuple expression: ([0], [1], [2]) with typed fill holes.
        # In other words, construct the tuple AST immediately.
        # e.g: ETuple([Hole(fill,type=t1), Hole(fill,type=t2), ...])
        el_holes = [Hole(tactics={"fill"}, type=t, scope=interpreter.get_selected_hole().scope) for t in expected_ty.element_types]

        # When we have ETuple
        interpreter.fill_selected_hole(ETuple(el_holes))
        print_program(interpreter, "Added tuple expression")
        return

    # If this is a return hole and the type is missing, use interpreter.return_type.
    if expected_ty is None and getattr(selected_hole, "is_return_hole", False):
        expected_ty = getattr(interpreter, "return_type", None)
    parent_decl = find_parent_variable_declaration(interpreter, selected_hole)
    if expected_ty is None and parent_decl is not None:
        expected_ty = parent_decl.type_
    if expected_ty is None:
        raise TacticError("❌ Cannot use 'new' here (no expected type information)")

    # Case: MixedType and RecordType.
    # Helper: checks whether ctor_name is allowed as an alternative in expected_ty.
    def ctor_allowed(expected: Type, ctor: str, visiting: set[int] | None = None) -> bool:
        if visiting is None:
            visiting = set()

        # resolve TypeRef
        while isinstance(expected, TypeRef) and expected.name in interpreter.program.defined_types:
            real = interpreter.program.defined_types[expected.name]
            expected = RecordType(real, expected.name) if isinstance(real, dict) else real

        # direct record
        if isinstance(expected, RecordType):
            return ctor == expected.name

        oid = id(expected)
        if oid in visiting:
            return False
        visiting.add(oid)

        # union: search inside
        if isinstance(expected, MixedType):
            for c in expected.cases:
                if ctor_allowed(c, ctor, visiting):
                    visiting.remove(oid)
                    return True

        visiting.remove(oid)
        return False

    if not ctor_allowed(expected_ty, ctor_name):
        raise TacticError(f"❌ '{ctor_name}' is not a valid constructor")
    # parse_expression("Dillo") -> EVar(Identifier("Dillo"))
    expression = parse_expression(ctor_name)
    interpreter.fill_selected_hole(expression)
    print_program(interpreter, "Added expression")


def _tactic_nil(interpreter, data: str) -> None:
    selected_hole = interpreter.get_selected_hole()
    if getattr(selected_hole, "kind", "normal") != "list":
        raise TacticError("❌ nil can only be used on a list hole")

    # All elements must be Expressions (No open Holes)
    elts: list[Expression] = []
    for e in selected_hole.list_elements or []:
        if isinstance(e, Hole):
            if e.filler is None:
                raise TacticError("❌ You must fill all list element holes before closing the list with nil")
            if isinstance(e.filler, Expression):
                elts.append(e.filler)
            else:
                raise TacticError("❌ List element is not an expression")
        elif isinstance(e, Expression):
            elts.append(e)
        else:
            raise TacticError("❌ Invalid list element")

    # Replace List_hole with real List_Expression
    if not isinstance(selected_hole.type, ListType):
        raise TacticError("❌ List hole has no element type")

    selected_hole.filler = EList(elts, element_type=selected_hole.type.element_type)
    selected_hole.kind = "normal"

    # -------------------------------
    # length tracking beim nil + nested lengths
    # -------------------------------
    owner = getattr(selected_hole, "owner", None)
    if isinstance(owner, str):
        interpreter.program.list_lengths[owner] = len(elts)

        def _const_int(x: Expression | None) -> int | None:
            if x is None:
                return None
            if isinstance(x, EConst) and isinstance(x.value, int) and not isinstance(x.value, bool):
                return x.value
            if isinstance(x, EOp1) and x.op == "-" and isinstance(x.operand, EConst):
                v = x.operand.value
                if isinstance(v, int) and not isinstance(v, bool):
                    return -v
            return None

        def infer_list_len(expr: Expression) -> int | None:
            if isinstance(expr, EVar) and isinstance(expr.name, Identifier):
                n = interpreter.program.list_lengths.get(expr.name.value)
                return n if isinstance(n, int) else None
            if isinstance(expr, EList):
                return len(expr.elts)
            if isinstance(expr, ESlice):
                a = _const_int(expr.lower)
                b = _const_int(expr.upper)
                if a is None or b is None:
                    return None
                return (b - a) if a <= b else None
            if isinstance(expr, EIndex) and isinstance(expr.seq, EVar) and isinstance(expr.seq.name, Identifier):
                i = _const_int(expr.index)
                if i is None:
                    return None
                return interpreter.program.nested_list_lengths.get((expr.seq.name.value, i))
            return None

        # store nested lengths with path
        def store_under(owner_name: str, path: tuple[int, ...], expr: Expression):
            n = infer_list_len(expr)
            if isinstance(n, int):
                interpreter.program.nested_list_lengths[(owner_name, path)] = n

            # if expr is a concrete list literal, go deeper
            if isinstance(expr, EList):
                for j, sub in enumerate(expr.elts):
                    store_under(owner_name, path + (j,), sub)

            # if expr is an alias to another list variable, copy its known nested map
            if isinstance(expr, EVar) and isinstance(expr.name, Identifier):
                src = expr.name.value
                src_len = interpreter.program.list_lengths.get(src)
                if isinstance(src_len, int):
                    interpreter.program.nested_list_lengths[(owner_name, path)] = src_len
                for (base, p), ln in list(interpreter.program.nested_list_lengths.items()):
                    if base == src:
                        interpreter.program.nested_list_lengths[(owner_name, path + p)] = ln

        for i, e in enumerate(elts):
            store_under(owner, (i,), e)

    # Clean + print
    interpreter.hole_cleaner.clean_holes(interpreter.program)
    print_program(interpreter, "Closed list with nil")


def _tactic_cons(interpreter, data: str) -> None:
    selected_hole = interpreter.get_selected_hole()
    if getattr(selected_hole, "kind", "normal") != "list":
        raise TacticError("❌ cons can only be used on a list hole")

    if not isinstance(selected_hole.type, ListType):
        raise TacticError("❌ List hole has no element type")
    T = selected_hole.type.element_type

    # Element hole of type T (expression hole).
    # If T is a RecordType or MixedType, `new` may also be allowed.
    allow_new = (
        isinstance(T, RecordType)
        or (isinstance(T, MixedType) and any(isinstance(c, RecordType) for c in T.cases))
        or isinstance(T, TupleType)
        or isinstance(T, ListType)
    )
    elem_tactics = {"fill", "new"} if allow_new else {"fill"}

    elem_hole = Hole(tactics=elem_tactics, type=T, scope=selected_hole.scope)

    selected_hole.list_elements.append(elem_hole)
    interpreter.hole_cleaner.clean_holes(interpreter.program)
    print_program(interpreter, "Added list element (cons)")
    selected_hole.length += 1
    if selected_hole.owner is not None:
        interpreter.program.list_lengths[selected_hole.owner] = selected_hole.length


def _tactic_return(interpreter, data: str) -> None:
    selected_hole = interpreter.get_selected_hole()
    if not selected_hole:
        raise TacticError("❌ No hole selected to fill")
    # Collect all visible variables as a dictionary for the type checker.
    branch_scope_dict: dict = {}
    if selected_hole.scope:
        branch_scope_dict.update(selected_hole.scope.copy_all())
    branch_scope_dict.update(interpreter.program.variables)

    def return_supports_new(rt: Type) -> bool:
        # `new` should also work for list/tuple types, since holes can be generated from them.
        if isinstance(rt, (RecordType, ListType, TupleType)):
            return True
        if isinstance(rt, MixedType):
            return any(isinstance(_resolve_ref_deep(interpreter, c), (RecordType, ListType, TupleType)) for c in rt.cases)
        return False

    rt = _resolve_ref_deep(interpreter, interpreter.return_type)
    the_tactics = {"fill", "new"} if return_supports_new(rt) or mixed_needs_new(interpreter, rt) else {"fill"}
    # Create a return hole; data types or classes could be added here.
    return_hole = Hole(
        the_tactics,
        type=interpreter.return_type,
        is_return_hole=True,
        scope=selected_hole.scope,
    )
    interpreter.fill_selected_hole(ReturnStatement(return_hole, expected_type=interpreter.return_type))
    print_program(interpreter, "Added return statement")


def _tactic_switch(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No index specified")
    index = parse_integer(data)
    interpreter.select_hole(index)
    print_program(interpreter, "Switched hole")


def _tactic_destruct_bool_expression(interpreter, data: str, expr, selected_hole, hole_tactics, parent_scope) -> None:
    # Boolean Expression
    if_stmt = SIf(
        test=expr,
        body=IList([Hole(hole_tactics, scope=Scope(parent_scope))]),
        orelse=IList([Hole(hole_tactics, scope=Scope(parent_scope))]),
    )
    interpreter.fill_selected_hole(CompositeStatement(if_stmt, Hole(hole_tactics, scope=selected_hole.scope)))


def _tactic_destruct_Literal(interpreter, data: str, expr_type, expr, parent_scope, selected_hole, hole_tactics) -> None:
    cases_list = []
    for literal in expr_type.cases:
        # pro Case One Scope
        # Create new scope for case
        case_scope = Scope(parent_scope)

        hole_type = expr_type.type_of(literal)  # TInt/TStr/...
        case_body_hole = Hole(tactics=hole_tactics, scope=case_scope, type=hole_type)

        cases_list.append(
            SCase(
                pattern=str(literal.value),
                body=IList([case_body_hole]),
                scope=case_scope,
                # pattern_values are in RecordType not empty
                pattern_values=[],
            )
        )
    # create new scope for match
    match_stmt = SMatch(expr=expr, cases=cases_list, scope=Scope(parent_scope))

    next_hole = Hole(hole_tactics, scope=selected_hole.scope)

    interpreter.fill_selected_hole(CompositeStatement(match_stmt, next_hole))


def _tactic_destruct_Record(interpreter, data: str, parent_scope, expr_type, hole_tactics, expr, selected_hole) -> None:
    case_scope = Scope(parent_scope)
    field_holes = []
    for field_name, field_type in expr_type.fields.items():
        # save key as string e.g. ram: int
        case_scope.add(field_name, field_type)
        # Create one intro hole for each field.
        field_holes.append(Hole(tactics={"intro"}, type=field_type, scope=case_scope))

    body_hole = Hole(hole_tactics, scope=case_scope)
    case_stmt = SMatch(
        expr=expr,
        cases=[
            # Only one case: e.g. case Computer([], [])..
            SCase(
                pattern=expr_type.name,
                body=IList([body_hole]),
                scope=case_scope,
                pattern_values=field_holes,
            )
        ],
        scope=Scope(parent_scope),
    )
    # Remain in the main scope as usual.
    next_hole = Hole(hole_tactics, scope=selected_hole.scope)

    interpreter.fill_selected_hole(CompositeStatement(case_stmt, next_hole))


def _tactic_destruct_Tuple(interpreter, data, expr_type, expr, selected_hole, hole_tactics, parent_scope) -> None:
    case_scope = Scope(parent_scope)

    # Intro holes for tuple components; the switch is added automatically in get_allowed_tactics.
    pat_holes = [Hole(tactics={"intro"}, type=t, scope=case_scope) for t in expr_type.element_types]

    body_hole = Hole(hole_tactics, scope=case_scope)
    # Body: the checker expects `pass` directly inside.
    cases_list = [
        SCase(
            pattern="",
            body=IList([body_hole]),
            scope=case_scope,
            pattern_values=pat_holes,
        )
    ]
    match_stmt = SMatch(expr=expr, cases=cases_list, scope=Scope(parent_scope))
    next_hole = Hole(hole_tactics, scope=selected_hole.scope)
    interpreter.fill_selected_hole(CompositeStatement(match_stmt, next_hole))


def _tactic_destruct_List(interpreter, data, expr_type, expr, full_scope, selected_hole, hole_tactics) -> None:
    parent_scope = Scope(full_scope)
    for_scope = Scope(parent_scope)

    var_hole = Hole(tactics={"intro"}, type=expr_type.element_type, scope=for_scope)
    body_hole = Hole(hole_tactics, scope=for_scope)

    for_stmt = SFor(var=var_hole, iterable=expr, body=IList([body_hole]), scope=for_scope)

    next_hole = Hole(hole_tactics, scope=selected_hole.scope)

    interpreter.fill_selected_hole(CompositeStatement(for_stmt, next_hole))


def _tactic_destruct_Mixed(interpreter, data, parent_scope, expr_type, expr, selected_hole, hole_tactics) -> None:
    cases_list: list[SCase] = []

    for alt in expr_type.cases:
        # Convert TypeRef alternatives into actual types.
        alt = _resolve_ref(interpreter, alt)
        # If it is still a TypeRef, the definition is missing → raise a clear error.
        if isinstance(alt, TypeRef):
            raise TacticError(
                f"❌ Cannot destruct MixedType: alternative '{alt.name}' is not defined yet. "
                f"Add a 'data:' or 'type:' definition for it before using destruct."
            )

        # pro Alternative eigener Case-Scope
        case_scope = Scope(parent_scope)

        # Alternative ist RecordType (data)
        if isinstance(alt, RecordType):
            field_holes: list[Hole] = []
            for field_name, field_type in alt.fields.items():
                field_holes.append(Hole(tactics={"intro"}, type=field_type, scope=case_scope))

            body_hole = Hole(hole_tactics, scope=case_scope)

            cases_list.append(
                SCase(
                    pattern=alt.name,
                    body=IList([body_hole]),
                    scope=case_scope,
                    pattern_values=field_holes,
                )
            )

        # Alternative ist LiteralType
        elif isinstance(alt, LiteralType):
            for lit in alt.cases:
                lit_body_hole = Hole(
                    tactics=hole_tactics,
                    scope=case_scope,
                    type=alt.type_of(lit),  # TInt/TStr/...
                )
                cases_list.append(
                    SCase(
                        pattern=str(lit.value),
                        body=IList([lit_body_hole]),
                        scope=case_scope,
                        pattern_values=[],
                    )
                )
        # Alternative ist ListType
        elif isinstance(alt, ListType):
            # xs binds the whole list → its type remains the original type (list[T]).
            xs_hole = Hole(tactics={"intro"}, type=alt, scope=case_scope)

            body_hole = Hole(hole_tactics, scope=case_scope)

            cases_list.append(
                SCase(
                    pattern="list",
                    body=IList([body_hole]),
                    scope=case_scope,
                    pattern_values=[xs_hole],
                )
            )
        # Alternative ist TupleType
        elif isinstance(alt, TupleType):
            # Bind the components: create one intro-hole per element.
            pat_holes = [Hole(tactics={"intro"}, type=t, scope=case_scope) for t in alt.element_types]

            body_hole = Hole(hole_tactics, scope=case_scope)

            cases_list.append(
                SCase(
                    pattern="",
                    body=IList([body_hole]),
                    scope=case_scope,
                    pattern_values=pat_holes,
                )
            )

        # Alternative is primitive type
        elif isinstance(alt, (TInt, TBool, TFloat, TComplex, TStr)):
            prim_label = pretty_type(alt)

            pv = Hole(tactics={"intro"}, type=alt, scope=case_scope)
            body_hole = Hole(hole_tactics, scope=case_scope)

            cases_list.append(
                SCase(
                    pattern=prim_label,
                    body=IList([body_hole]),
                    scope=case_scope,
                    pattern_values=[pv],
                )
            )

        else:
            raise TacticError(f"❌ Cannot destruct MixedType alternative {alt}")

    match_stmt = SMatch(expr=expr, cases=cases_list, scope=Scope(parent_scope))

    next_hole = Hole(hole_tactics, scope=selected_hole.scope)

    interpreter.fill_selected_hole(CompositeStatement(match_stmt, next_hole))


def _tactic_destruct(interpreter, data: str) -> None:
    if data.strip() == "":
        raise TacticError("❌ No expression specified")
    selected_hole = interpreter.get_selected_hole()

    full_scope = build_full_scope(interpreter, selected_hole)
    # Parse expression
    try:
        expr = parse_expression(data.strip())
    except TacticError as e:
        raise TacticError(f"❌ Invalid expression: {e}")
    # Determine the type of the expression
    try:
        # Keys always string not identifier
        ctx_for_tc: dict[str, Type] = {(k.value if isinstance(k, Identifier) else str(k)): v for k, v in full_scope.copy_all().items()}
        expr_type = type_check_expr(ctx_for_tc, expr, interpreter.program)

    except TypeCheckerError as e:
        raise TacticError(f"❌ Type error in destruct expression: {e}")

    hole_tactics = selected_hole.tactics
    # Parent scope for the new holes.
    # We need the parent so it can be placed in the scope: Scope(parent).
    parent_scope = Scope(full_scope)
    if isinstance(expr_type, TBool):
        _tactic_destruct_bool_expression(interpreter, data, expr, selected_hole, hole_tactics, parent_scope)

    # RecordType, data: Computer(ram:int, ...)
    elif isinstance(expr_type, RecordType):
        _tactic_destruct_Record(interpreter, data, parent_scope, expr_type, hole_tactics, expr, selected_hole)

    # LiteralType Pet=Literal['cat','dog',  ..]
    elif isinstance(expr_type, LiteralType):
        _tactic_destruct_Literal(interpreter, data, expr_type, expr, parent_scope, selected_hole, hole_tactics)

    elif isinstance(expr_type, TupleType):
        _tactic_destruct_Tuple(interpreter, data, expr_type, expr, selected_hole, hole_tactics, parent_scope)

    elif isinstance(expr_type, ListType) or isinstance(expr_type, RangeType):
        _tactic_destruct_List(interpreter, data, expr_type, expr, full_scope, selected_hole, hole_tactics)

    # Apply destruct to a MixedType.
    elif isinstance(expr_type, MixedType):
        _tactic_destruct_Mixed(interpreter, data, parent_scope, expr_type, expr, selected_hole, hole_tactics)
    else:
        raise TacticError(f"❌ Cannot destruct expression of type {pretty_type(expr_type)}")
    print_program(interpreter, "Added destruct")


def _tactic_pass(interpreter, data: str) -> None:
    selected_hole = interpreter.get_selected_hole()
    # Expression Hole is not allowed to be empty
    if ("fill" in selected_hole.tactics) or ("new" in selected_hole.tactics):
        raise TacticError("pass is not allowed in expression holes")
    # fill hole (normal statement-Hole)
    selected_hole.filler = EmptyStatement()
    interpreter.hole_cleaner.clean_holes(interpreter.program)
    print_program(interpreter, "Filled with pass")


def _tactic_finish(interpreter, data: str) -> None:
    if len(interpreter.program.holes) > 0:
        raise TacticError("❌ There are still unfilled holes")
    print_program(interpreter, "Finished the program", False)
    raise TerminationException
