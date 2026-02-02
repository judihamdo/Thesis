from pathlib import Path
from typing import Any, Literal
from parser import *
from program import *
from utility import TerminationException, TacticError, UnexpectedValueError, pad_str
from hole_cleaner import HoleCleaner
from visualise import program_to_str, hole_to_str
from type_checker import *
import re

#regulaerer Ausdruck fuers LiteralType erkennen
TYPE_ASSIGN_RE = re.compile(r"""^\s*
(?P<name>[A-Za-z_][A-Za-z0-9_]*)       # Name der Type
    \s*=\s*
    Literal\s*\[(?P<cases>\s*                       (?:                              [A-Za-z_][A-Za-z0-9_]*      # Bezeichner
                |
                -?\d+(?:\.\d+)?             # Zahl
                |
                '(?:\\'|[^'])*'             # String in ''
                |
                "(?:\\"|[^"])*"             # String in ""
            )
            (?:\s*,\s*
                (?:[A-Za-z_][A-Za-z0-9_]*|-?\d+(?:\.\d+)?|'(?:\\'|[^'])*'|"(?:\\"|[^"])*")
            )*
        \s*)
    \]
    \s*$
    """,
    re.VERBOSE
)


TACTICS = {"description", "signature", "intro", "let", "return", "fill", "new", "switch",
           "data","finish", "type", "destruct", "pass"}

class Interpreter:
    def __init__(self):
        self.program = Program(Hole({"description"}))
        self.hole_cleaner = HoleCleaner(self.program)
        self.hole_cleaner.clean_holes(self.program)
        self.global_scope = Scope()   # Root für funktionsweite Variablen
        self.print_program("Initial program")
        self.used_variables_names: set[str] = set()
        
        
    def is_within_destruct(self, hole: Hole) -> bool:
        """Prüft rekursiv, ob das Hole innerhalb eines destruct-Holes/Statements liegt."""
        def search(node)->bool:
            match node:
                case Hole():
                    #Sobald das Ziel Hole gefunden wurde -> False.
                    if node is hole:
                        return False  #wir haben das Hole gefunden, wir sind nicht innerhalb von destruct
                    if getattr(node, "tactics", None) and "destruct" in node.tactics:
                        #wenn ein destruct Hole auf dem Weg liegt
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
        return search(self.program.statement)
    
    def has_previous_stmt_in_same_block(self, hole: Hole) -> bool:
        """Steht vor diesem Hole im selben Scope schon mindestens ein Statement?"""
        #Das parent ist das Statement, das das Hole direkt enthält
        parent = self.find_parent_statement(hole)
        #Hole ist in if-body oder else-body
        if isinstance(parent, SIf):
            for i, s in enumerate(parent.body):
                if s is hole:
                    return i > 0   #Es steht Statement davor
            for i, s in enumerate(parent.orelse):
                if s is hole:
                    return i > 0
            return False
        #Hole ist in match-case body
        if isinstance(parent, SCase):
            for i, s in enumerate(parent.body):
                if s is hole:
                    return i > 0
            return False
        #Hole ist second in CompositeStatement
        if isinstance(parent, CompositeStatement):
            return parent.second is hole
        return False
    
    def is_directly_after_total_match(self, hole: Hole) -> bool:
        """helper function, can also be helpful if we have decided to add case_"""
        parent = self.find_parent_statement(hole)
        return (isinstance(parent, CompositeStatement) and parent.second is hole and\
            isinstance(parent.first, SMatch) and does_stmt_always_return(parent.first))

    def prefix_always_returns(self, hole: Hole) -> bool:
        """
        True genau dann, wenn der Code direkt VOR diesem Hole (im selben CompositeStatement)
        auf allen Pfaden returnt. Dann ist das Hole unerreichbar -> pass wäre "harmlos".
        """
        parent = self.find_parent_statement(hole)
        if isinstance(parent, CompositeStatement) and parent.second is hole:
            return does_stmt_always_return(parent.first)
        return False

    def can_use_pass(self, hole: Hole) -> bool:
        scope = hole.scope
        #pass bitte nicht ausserhalb destruct verwenden
        if scope is None:
            return False
        return getattr(scope, "has_destruct_child", False) or self.has_previous_stmt_in_same_block(hole)

    def find_parent_statement(self, target: Any) -> Statement | None:
        """ Sucht rekursiv das Statement, in dem `target` steckt. target kann ein Hole oder irgendein Node sein, der im AST vorkommt.
            Gibt None zurück, wenn target direkt im Program-Statement hängt (Root).
            if-Body -> SIf,  else-Body -> SIf, case-Body -> SCase
            direkt nach einem Statement -> CompositeStatement, direkt im Funktionsrumpf(Root) -> None """
        def search(node: Any, parent:Statement|None = None) -> Statement | None:
            #Wenn der aktuelle Knoten genau target ist-> gib den Parent zurück.
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

                #Match/Case 
                case SMatch(expr, cases):
                    #zuerst im Match Ausdruck suchen
                    res = search(expr, node)
                    if res is not None:
                        return res

                    # dann in jedem Case:
                    for c in cases:
                        # pattern_values (z.B. Record-Feld-Holes)
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
        return search(self.program.statement)

    def all_paths_return(self, stmt: Statement | Hole, inside_destruct = False) -> bool:
        """nuetzlich fuer if-else wenn man ueberall return hat, dann nur finish tactic muss zur Wahl stehen"""  
        match stmt:
            case ReturnStatement():
                return True
            case CompositeStatement(first, second):
                first_ret = self.all_paths_return(first, inside_destruct)
                #Wenn erstes Teil(Mutter) schon return liefert dann zweites Teil ist irrelevant
                if first_ret:
                    return True
                return self.all_paths_return(second, inside_destruct)
            #for match brauchen wir das nicht, nur fuer if-else
            case SIf(_, body, orelse):
                #Für SIf gilt:Pfad returnt, wenn jeder Branch return liefert
                body_all = all(self.all_paths_return(s, inside_destruct) for s in body)
                orelse_all = all(self.all_paths_return(s, inside_destruct) for s in orelse)
                return body_all and orelse_all
            case Hole():
                return False  #noch nicht gefüllt also kein Return
            case EmptyStatement():
                return False
            case _:
                return False

    def is_top_level_in_function(self, hole: Hole) -> bool:
        """True nur dann, wenn das Hole NICHT innerhalb eines Branch-Blocks (if/match-case) liegt.
        Wir prüfen die ganze Ahnenkette, nicht nur den direkten Parent."""
        node: Any = hole
        while True:
            parent = self.find_parent_statement(node)
            if parent is None:
                return True  #Root erreicht -> top-level
            if isinstance(parent, (SIf, SCase)):
                return False  #irgendwo in einem Branch
            node = parent
            
    def is_hole_directly_after_match(self, hole: Hole) -> bool:
        parent = self.find_parent_statement(hole)
        return (isinstance(parent, CompositeStatement) and parent.second is hole and\
                isinstance(parent.first, SMatch))

    def is_parameter_hole(self, hole: Hole) -> bool:
        """ intro holes merken """
        parent = self.find_parent_statement(hole)
        return parent is None and hole.type is not None and hole.tactics == {"intro"}
    
    def is_directly_after_total_return_stmt(self, hole: Hole) -> bool:
        parent = self.find_parent_statement(hole)
        return (isinstance(parent, CompositeStatement) and parent.second is hole and\
                 isinstance(parent.first, SIf)  and does_stmt_always_return(parent.first))
    
    def auto_close_unreachable(self) -> None:
        changed = False
        for h in list(self.program.holes):
            if self.prefix_always_returns(h):   # davor returnt sicher (if/match/...)
                h.filler = EmptyStatement()
                changed = True
        if changed:
            self.hole_cleaner.clean_holes(self.program)


    def get_allowed_tactics(self) -> set[str]:
        self.auto_close_unreachable()

        tactics: set[str] = set()
        if len(self.program.holes) == 0:
            return {"finish"}

        selected_hole = self.program.selected_hole
        if selected_hole is None:
            return {"finish"}  # sicherheit

        if self.is_top_level_in_function(selected_hole) and self.prefix_always_returns(selected_hole):
            return {"finish"}

        elif self.is_directly_after_total_return_stmt(selected_hole):
            return {"pass"}
                
        if len(self.program.holes) > 1:
            tactics.add("switch")

        if self.program.selected_hole is None:
            return tactics
        
        #tactics übernimmt die Vereinigung ohne Duplikaten 
        tactics |= selected_hole.tactics
        # Parameter holes: nur intro + switch
        if self.is_parameter_hole(selected_hole):
            tactics.discard("pass")
            tactics.discard("return")
            tactics.discard("destruct")
            return tactics

        parent_stmt = self.find_parent_statement(selected_hole)
        in_destruct = self.is_within_destruct(selected_hole)

        if in_destruct:
            tactics |= selected_hole.tactics

        #Wenn alle Pfade nahc if-else return haben -> nur pass
        if parent_stmt and self.all_paths_return(parent_stmt, inside_destruct=False):
            return {"pass"}

        #Expression-Holes (fill) dürfen NIE pass anbieten
        if "fill" in selected_hole.tactics or "new" in selected_hole.tactics or selected_hole.tactics == {"intro"}:
            tactics.discard("pass")
            return tactics 
        want_empty = self.can_use_pass(selected_hole)

        #Top-Level:wenn davor NICHT sicher returnt, dann kein pass
        if self.is_top_level_in_function(selected_hole) and not self.prefix_always_returns(selected_hole):
            want_empty = False

        #nur Top-Level: direkt nach einem total-return match kein pass, könnte geändert werden wenn mna sich fuer case_ entscheidet
        if self.is_top_level_in_function(selected_hole):
            want_empty = False

        if self.is_directly_after_total_match(selected_hole):
            want_empty = True
            tactics = {"finish"}
            return tactics
            
        if want_empty:
            tactics.add("pass")
        else:
            tactics.discard("pass")

        return tactics

    def print_program(self, status: str, print_options: bool = True) -> None:
        print(f"{status}:")
        print(pad_str(program_to_str(self.program), "| "))
        if print_options:
            tactics = self.get_allowed_tactics()
            tactics_str = ", ".join(tactics) if len(tactics) > 0 else "None"
            print(pad_str(f"Options: {tactics_str}", "| "))
            
    def find_parent_variable_declaration(self, target: Any) -> VariableDeclaration | None:
        """Findet die VariableDeclaration, deren expression-slot (oder Subtree) target enthält.
            Funktioniert auch innerhalb von SMatch / SCase (pattern_values + body)."""
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
                    # target kann direkt expr sein oder darin verschachtelt
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

                #match/case
                case SMatch(expr, cases):
                    # im match-Ausdruck suchen
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
        return search(self.program.statement)

    def get_selected_hole(self) -> Hole:
        if self.program.selected_hole is None:
            raise TacticError(f"No hole is selected")
        return self.program.selected_hole

    def short_dict(d: dict, name):
        n = d.get(name)
        if not isinstance(n, int):
            return {}
        return dict(list(d.items())[n:])
    
    def prefix_before(self, d: dict[str, Type], stop_name: str) -> dict[str, Type]:
        out: dict[str, Type] = {}
        for k, v in d.items():
            if k == stop_name:
                break
            out[k] = v
        return out

    
    def fill_selected_hole(self, filler: Any) -> None:
        hole = self.get_selected_hole()
        hole.filler = filler
        
        #Kontext aufbauen:dict[str, Type]
        ctx: dict[str, Type] = {}

        def normalize_keys(d: dict) -> dict[str, Type]:
            return {(k.value if isinstance(k, Identifier) else str(k)): v for k, v in d.items()}

        # Kontext aufbauen
        ctx: dict[str, Type] = {}
        parent_decl = self.find_parent_variable_declaration(hole)
        if isinstance(hole.scope, Scope):
            # Dieses Teil ist sehr wichtig damit die variables die nur danach kommen, erlaubt sind als assignment
            if parent_decl is not None:
                decl_name = parent_decl.name.value if isinstance(parent_decl.name, Identifier) else str(parent_decl.name)
                if hole.scope.parent:
                    ctx.update(normalize_keys(hole.scope.parent.copy_all()))
                ctx.update(self.prefix_before(hole.scope.vars, decl_name))

            else:
                ctx.update(normalize_keys(hole.scope.copy_all()))
        else:
            ctx.update(normalize_keys(self.global_scope.copy_all()))
        ctx.update(normalize_keys(self.program.variables))
        # Return-Hole typprüfen
        if getattr(hole, "is_return_hole", False):
            try:
                ctx_ret: dict[str, Type] = {}

                if isinstance(hole.scope, Scope):
                    ctx_ret.update(normalize_keys(hole.scope.copy_all()))
                else:
                    ctx_ret.update(normalize_keys(self.global_scope.copy_all()))

                ctx_ret.update(normalize_keys(self.program.variables))
                ctx_ret.update(normalize_keys(self.global_scope.copy_all()))

                expr_type = type_check_expr(ctx_ret, filler, self.program)
                check_type_equal(expr_type, self.return_type, filler)
            except TypeError as e:
                print(f"Typfehler beim Return: {e}")
                hole.filler = None
                return

        #Typ_checking for Data_Type(classes holes)
        #(wie Argument-Löcher aus new: Mobile -> Mobile([0],[1],[2]))
        elif hole.type is not None and ("fill" in hole.tactics or "new" in hole.tactics):
            try:
                t_expr = type_check_expr(ctx, filler, self.program)
                check_type_equal(t_expr, hole.type, filler)
            except TypeError as e:
                print(f"Typfehler: {e}")
                hole.filler = None
                return

        #VariableDeclaration initializer typprüfen (Fallback)
        else:
            parent_decl = self.find_parent_variable_declaration(hole)
            if parent_decl is not None:
                try:
                    expr_type = type_check_expr(ctx, filler, self.program)
                    check_type_equal(expr_type, parent_decl.type_, filler)
                except TypeError as e:
                    print(f"Typfehler: {e}")
                    hole.filler = None
                    return 

        if "new" in hole.tactics:
            if getattr(hole, "is_return_hole", False):
                decl_ty = self.return_type
            else:
                decl_ty = parent_decl.type_
            #Falls der Typ als Identifier kam dann auflösen über defined_types
            if isinstance(decl_ty, Identifier) and decl_ty.value in self.program.defined_types:
                dt = self.program.defined_types[decl_ty.value]
                if isinstance(dt, dict):
                    decl_ty = RecordType(fields=dt, name=decl_ty.value)
                elif isinstance(dt, Type):
                    decl_ty = dt

            if isinstance(decl_ty, RecordType):
                ctor_name = None
                if isinstance(filler, EVar) and isinstance(filler.name, Identifier):
                    ctor_name = filler.name.value

                if ctor_name == decl_ty.name:
                    arg_holes: list[Hole] = []
                    for field_name, field_type in decl_ty.fields.items():
                        arg_holes.append(
                            Hole(
                                    tactics={"fill"},
                                    type=field_type,   # wichtig fuer später in Typcheck
                                    scope=hole.scope  
                                )
                            )

                    #filler ersetzen: Handy([0],[1],...)
                    filler = EFunCall(EVar(Identifier(decl_ty.name)), arg_holes)
                    hole.filler = filler

            elif isinstance(decl_ty, MixedType):
                ctor_name = None
                if isinstance(filler, EVar) and isinstance(filler.name, Identifier):
                    ctor_name = filler.name.value

                #wir suchen passenden RecordType-Fall im MixedType
                chosen_rec: RecordType | None = None
                for c in decl_ty.cases:
                    if isinstance(c, RecordType) and c.name == ctor_name:
                        chosen_rec = c
                        break

                if chosen_rec is not None:
                    arg_holes: list[Hole] = []
                    for field_name, field_type in chosen_rec.fields.items():
                        arg_holes.append(
                            Hole(
                                tactics={"fill"},
                                type=field_type,
                                scope=hole.scope
                            )
                        )
                    filler = EFunCall(EVar(Identifier(chosen_rec.name)), arg_holes)
                    hole.filler = filler


        #Variablen eintragen (Identifier als Key)
        def collect_variables(node: Any, current_scope: Scope | None = None) -> None:
            if isinstance(node, VariableDeclaration):
                var_id = node.name if isinstance(node.name, Identifier) else Identifier(str(node.name))

                if current_scope is not None:
                    current_scope.add(var_id, node.type_)
                else:
                    self.program.variables[var_id] = node.type_

            elif isinstance(node, CompositeStatement):
                collect_variables(node.first, current_scope)
                collect_variables(node.second, current_scope)

            elif isinstance(node, FunctionDeclaration):
                for param, ptype in zip(node.parameters, node.function_type.parameter_types):
                    if isinstance(param, Identifier):
                        self.program.variables[param] = ptype
                collect_variables(node.statement, current_scope)

            elif isinstance(node, TypeDeclaration):
                if not hasattr(self.program, "defined_types"):
                    self.program.defined_types = {}
                self.program.defined_types[node.name.value] = node.type_
            elif isinstance(node, Hole) and node.filler is not None:
                collect_variables(node.filler, current_scope)

        target_scope = hole.scope if isinstance(hole.scope, Scope) else self.global_scope
        collect_variables(filler, target_scope)
        print("Those are there", self.get_selected_hole().scope.copy_all())
        #Typ-check und Holes aufräumen
        type_check(self.program)
        self.hole_cleaner.clean_holes(self.program)

    def select_hole(self, index: int) -> None:
        if index < 0 or index >= len(self.program.holes):
            raise TacticError(f"There is no unfilled hole with the index {index!r}")
        if self.program.selected_hole is self.program.holes[index]:
            raise TacticError(f"Hole is already selected")
        self.program.selected_hole = self.program.holes[index]
        self.hole_cleaner.clean_holes(self.program)

    def interprete_tactic(self, tactic: str) -> None:
        m = TYPE_ASSIGN_RE.match(tactic.strip())
        if m:
            if "type" not in self.get_allowed_tactics():
                raise TacticError("You cannot define a type here yet.")
            name_str = m.group("name")
            cases_str = m.group("cases")

            my_identifier = parse_identifier(name_str)
            my_literal = parse_literal(f"Literal[{cases_str}]")
            my_literal.name = my_identifier.value

            self.fill_selected_hole(
                CompositeStatement(
                    TypeDeclaration(my_identifier, my_literal),
                    Hole({"signature", "type"})
                )
            )
            self.print_program("Added a new type")
        else:
            if tactic.strip() == "":
                raise TacticError(f"No tactic specified")
            if ":" not in tactic:
                raise TacticError("Missing ':' after tactic keyword")
            keyword, data = tactic.split(":", 1)
            keyword = keyword.strip()
            if keyword not in TACTICS:
                raise TacticError(f"Unknown tactic {keyword!r}")
            if keyword not in self.get_allowed_tactics():
                raise TacticError(f"The tactic {keyword!r} can not be applied right now")

            match keyword:
                case "description":
                    if data.strip() == "":
                        raise TacticError(f"No description specified")
                    description = data.strip()
                    self.fill_selected_hole(
                        CompositeStatement(
                            DescriptionStatement(description),
                            Hole({"signature", "type", "data"})
                        )
                    )
                    self.print_program(f"Added description")

                case "type":
                    data = data.strip()

                    if data == "empty":
                        self.fill_selected_hole(
                            CompositeStatement(
                                EmptyStatement(),
                                Hole({"signature", "data"})
                            )
                        )
                        self.print_program("Added a new type")
                        return
                    if "=" not in data:
                        raise TacticError("Missing '=' after type name")
                    name_str, rhs = data.split("=", 1)
                    my_identifier = parse_identifier(name_str.strip())
                    rhs = rhs.strip()
                    #Literal[...]
                    if rhs.startswith("Literal"):
                        my_type = parse_literal(rhs)
                        my_type.name = my_identifier.value
                    #MixedType mit '|'
                    elif "|" in rhs:
                        my_type = parse_mixed_type(
                            rhs,
                            name=my_identifier.value,
                            custom_types=self.program.defined_types
                        )
                    else:
                        my_type = parse_type(rhs, custom_types=self.program.defined_types)
                    # Type im Programm registrieren (wichtig für spätere parse_type-Aufrufe)
                    self.program.defined_types[my_identifier.value] = my_type
                    self.used_variables_names.add(my_identifier) #wichtig damit keine WIEDERHOLUNDEN in Namen erlaubt sind

                    self.fill_selected_hole(
                        CompositeStatement(
                            TypeDeclaration(my_identifier, my_type),
                            Hole({"type", "signature", "data"})
                        )
                    )
                    self.print_program("Added a new type")


                case "signature":
                    if data.strip() == "":
                        raise TacticError(f"No signature name specified")

                    if ":" not in data:
                        raise TacticError("Missing ':' after signature name")

                    # Name und Typ der Funktion trennen
                    name, function_type_str = data.split(":", 1)
                    identifier = parse_identifier(name)

                    if function_type_str.strip() == "":
                        raise TacticError(f"No function type specified")

                    # Parse function type mit den bereits definierten Typen (z.B. Pet)
                    function_type: FunctionType = parse_type(
                        function_type_str,
                        custom_types=self.program.defined_types
                    )

                    if not isinstance(function_type, FunctionType):
                        raise TacticError("Only function types are allowed for the signature")
                    parameter_holes = []

                    for t in function_type.parameter_types:
                        if isinstance(t, LiteralType):
                            #Benannter LiteralType (z.B. Pet) oder unbenannter Literal direkt
                            if t.name is not None and t.name in self.program.defined_types:
                                # Hole nimmt den benannten Typ aus defined_types
                                param_type = self.program.defined_types[t.name]
                            else:
                                #unbenannter LiteralType bleibt unverändert
                                param_type = t
                            parameter_holes.append(Hole({"intro"}, type=param_type))
                        else:
                            #Normale Typen wie TInt, TBool, etc.
                            parameter_holes.append(Hole({"intro"}, type=t))

                    # Funktion einfügen
                    self.fill_selected_hole(
                        FunctionDeclaration(
                            name=identifier,
                            function_type=function_type,
                            parameters=parameter_holes,
                            statement=Hole({"let", "return", "destruct"})
                        )
                    )
                    self.return_type = function_type.return_type
                    self.print_program(f"Added signature")



                # die war sehr nice
                case "intro":
                    if data.strip() == "":
                        raise TacticError(f"No variable names specified")
                    identifier = parse_identifier(data)

                    #nicht nur program.variables prüfen, sondern alles Sichtbare (global + scopes)
                    selected_hole = self.program.selected_hole
                    if not selected_hole:
                        raise TacticError("No hole selected to fill")

                    visible: dict[str, Type] = {}

                    #Falls wir in einem Branch/Case sind: alles Sichtbare aus diesem Scope
                    if isinstance(selected_hole.scope, Scope):
                        visible.update(selected_hole.scope.copy_all())

                    #globale / programmweite Variablen
                    # program.variables kann keys als str oder Identifier haben -> normalize
                    for k, v in self.program.variables.items():
                        kk = k.value if isinstance(k, Identifier) else str(k)
                        visible[kk] = v

                    #global_scope (funktionsweit)
                    if hasattr(self, "global_scope") and isinstance(self.global_scope, Scope):
                        visible.update(self.global_scope.copy_all())

                    #Kollision verhindern: darf NICHT denselben Namen wie irgendeine bekannte Variable haben
                    if identifier.value in visible:
                        raise TacticError(f"it already exists variable with this name")
                    if identifier in self.program.variables or identifier in self.used_variables_names:
                        raise TacticError(f"it already exists variable with this name")
                    #Typ direkt aus dem Hole nehmen
                    if selected_hole.type is not None:
                        parentt = self.find_parent_statement(selected_hole)
                        if self.is_parameter_hole(selected_hole):
                            if parentt is None:
                                self.program.variables[identifier.value] = selected_hole.type
                            self.used_variables_names.add(identifier.value)
                        else:
                            if isinstance(selected_hole.scope, Scope):
                                selected_hole.scope.add(identifier, selected_hole.type)
                                if not hasattr(selected_hole.scope, "case_bindings"):
                                    selected_hole.scope.case_bindings = set()
                                selected_hole.scope.case_bindings.add(identifier.value)
                            if parentt is None:
                                self.program.variables[identifier.value] = selected_hole.type
                            self.used_variables_names.add(identifier.value)
                    else:
                        raise TacticError("Selected hole has no type info")
                    self.fill_selected_hole(identifier)
                    self.print_program(f"Introduced name")
                    

                case "let":
                    if data.strip() == "":
                        raise TacticError("No variable name specified")
                    if ":" not in data:
                        raise TacticError("Missing ':' after variable name")
                    name_str, type_str = data.split(":", 1)
                    name = parse_identifier(name_str)
                    if type_str.strip() == "":
                        raise TacticError("No variable type specified")
                    type_ = parse_type(type_str, custom_types=self.program.defined_types)
                    selected_hole = self.get_selected_hole()
                    # global eindeutig
                    if name.value in self.used_variables_names:
                        raise TacticError(
                            f"Variable '{name.value}' was already introduced by a let"
                        )
                    # funktionsweiter Scope: wenn None dann global_scope benutzen
                    if selected_hole.scope is None:
                        scope_to_use = self.global_scope
                    else:
                        scope_to_use = selected_hole.scope
                    # lokal im gleichen Branch darf Name nicht doppelt sein
                    if scope_to_use.get(name.value) is not None:
                        raise TacticError(f"Variable '{name.value}' already exists in this scope/branch")
                    scope_to_use.add(name, type_) 
                    # Name merken
                    self.used_variables_names.add(name.value)
                    # Beide neuen Holes müssen denselben Scope bekommen
                    init_scope = scope_to_use
                    rest_scope = scope_to_use
                    is_record = isinstance(type_, RecordType)   # (works only if parse_type returns RecordType)
                    is_mixed = isinstance(type_, MixedType) and any(isinstance(c, RecordType) for c in type_.cases)

                    if is_record or is_mixed:
                        chosen_hole = Hole({"new", "fill"}, scope=init_scope)
                    else:
                        chosen_hole = Hole({"fill"}, scope=init_scope)

                    self.fill_selected_hole(
                        CompositeStatement(
                            VariableDeclaration(
                                name,
                                type_,
                                chosen_hole
                            ),
                            Hole(selected_hole.tactics, scope=rest_scope)
                        )
                    )

                    self.print_program("Added variable declaration")

                case "data":
                    if data.strip() == "":
                        raise TacticError(f"No expression specified")
                    #parsen
                    data_name, parameters = parse_data_type(
                        data,
                        custom_types=self.program.defined_types
                    )
                    #den ganzen String an parse_data_type übergeben
                    data_decl = DataDeclaration(
                        name=data_name,
                        parameters=parameters
                        )
                    if data_decl.name in self.program.defined_types or data_decl.name in self.used_variables_names:
                        raise TacticError(f"The name is taken")
                    selected_hole = self.get_selected_hole()
                    # zuerst Typ speichern
                    self.program.defined_types[data_decl.name.value] = data_decl.parameters
                    self.used_variables_names.add(data_decl.name.value)
                    # dann Hole füllen
                    self.fill_selected_hole(
                        CompositeStatement(
                            data_decl,
                            Hole(selected_hole.tactics, scope=selected_hole.scope)
                        )
                    )
                    self.print_program(f"Added Data")

                case "fill":
                    if data.strip() == "":
                        raise TacticError(f"No expression specified")
                    expression = parse_expression(data.strip())
                    self.fill_selected_hole(expression)
                    self.print_program(f"Added expression")
                case "new":
                    if data.strip() == "":
                        raise TacticError("No expression specified")

                    selected_hole = self.get_selected_hole()
                    ctor_name = data.strip()
                    expected_ty = selected_hole.type
                    # Falls es ein Return-Hole ist und type fehlt dann nimm self.return_type
                    if expected_ty is None and getattr(selected_hole, "is_return_hole", False):
                        expected_ty = getattr(self, "return_type", None)
                    parent_decl = self.find_parent_variable_declaration(selected_hole)
                    if expected_ty is None and parent_decl is not None:
                        expected_ty = parent_decl.type_
                    if expected_ty is None:
                        raise TacticError("Cannot use 'new' here (no expected type information)")
                    #helper: prüft, ob ctor_name als Alternative in expected_ty erlaubt ist
                    def ctor_allowed(expected: Type, ctor: str) -> bool:
                        # direkter RecordType
                        if isinstance(expected, RecordType):
                            return ctor == expected.name
                        #MixedType: ctor muss ein RecordType-Alternativname sein
                        if isinstance(expected, MixedType):
                            for c in expected.cases:
                                if isinstance(c, RecordType) and c.name == ctor:
                                    return True
                            return False
                        return False
                    if not ctor_allowed(expected_ty, ctor_name):
                        raise TacticError(f"'{ctor_name}' is not a valid constructor")
                    #parse_expression("Dillo") -> EVar(Identifier("Dillo"))
                    expression = parse_expression(ctor_name)
                    self.fill_selected_hole(expression)
                    self.print_program("Added expression")
                case "return":
                    selected_hole = self.get_selected_hole()
                    if not selected_hole:
                        raise TacticError("No hole selected to fill")
                    #Hole alle sichtbaren Variablen als dict für TypeChecker
                    branch_scope_dict: dict = {}
                    if selected_hole.scope:
                        branch_scope_dict.update(selected_hole.scope.copy_all())
                    branch_scope_dict.update(self.program.variables)
                    def return_supports_new(rt: Type) -> bool:
                        if isinstance(rt, RecordType):
                            return True
                        if isinstance(rt, MixedType):
                            return any(isinstance(c, RecordType) for c in rt.cases)
                        return False
                    the_tactics = {"fill", "new"} if return_supports_new(self.return_type) else {"fill"}
                    #return-Hole erstellen, soll man hier data bzw. klassen hinzufügen
                    return_hole = Hole(
                        the_tactics, 
                        type=self.return_type, 
                        is_return_hole=True,
                        scope=selected_hole.scope  # Scope direkt speichern für spätere Fills
                    )
                    #Typcheck wenn filler schon existiert
                    try:
                        if return_hole.filler:
                            expr_type = type_check_expr(branch_scope_dict, return_hole.filler, expr_type)  # dict an TypeChecker
                            check_type_equal(expr_type, self.return_type, return_hole.filler)
                    except TypeError as e:
                        print(f"Typfehler beim Return: {e}")
                        return_hole.filler = None
                        return
                    # Hole füllen
                    self.fill_selected_hole(ReturnStatement(return_hole, expected_type=self.return_type))
                    self.print_program("Added return statement")
                    
                case "switch":
                    if data.strip() == "":
                        raise TacticError(f"No index specified")
                    index = parse_integer(data)
                    self.select_hole(index)
                    self.print_program(f"Switched hole")

                case "destruct":
                    if data.strip() == "":
                        raise TacticError("No expression specified")
                    selected_hole = self.get_selected_hole()
                    #Eltern scope zusammenbauen
                    def build_full_scope(hole: Hole) -> Scope:
                        # Hole scope + vater Holes + funktionsparameter
                        parent_stmt = self.find_parent_statement(hole)
                        full_scope = Scope(hole.scope) if hole.scope else Scope()
                        #Alle übergeordneten Variablen sammeln
                        while parent_stmt:
                            if isinstance(parent_stmt, VariableDeclaration):
                                n = parent_stmt.name.value if isinstance(parent_stmt.name, Identifier) else parent_stmt.name
                                full_scope.add(parent_stmt.name, parent_stmt.type_) 

                            elif isinstance(parent_stmt, FunctionDeclaration):
                                for param, ptype in zip(parent_stmt.parameters, parent_stmt.function_type.parameter_types):
                                    if isinstance(param, Identifier):
                                        full_scope.add(param, ptype) 
                                        
                            parent_stmt = self.find_parent_statement(parent_stmt)
                        #Danach globale Variablen hinzufügen         
                        full_scope.vars.update(self.program.variables)
                        full_scope.vars.update(self.global_scope.copy_all())
                        return full_scope
                    full_scope = build_full_scope(selected_hole)
                    #Ausdruck parsen
                    try:
                        expr = parse_expr(data.strip())
                    except Exception as e:
                        raise TacticError(f"Invalid expression: {e}")
                    #Typ des Ausdrucks bestimmen
                    try:
                        #Keys immer str nihct identifier
                        ctx_for_tc: dict[str, Type] = {
                            (k.value if isinstance(k, Identifier) else str(k)): v
                            for k, v in full_scope.copy_all().items()
                        }
                        expr_type = type_check_expr(ctx_for_tc, expr, self.program)

                    except TypeError as e:
                        raise TacticError(f"Type error in destruct expression: {e}")
                    
                    hole_tactics = selected_hole.tactics
                    #Eltern scope für die neuen Holes
                    parent_scope = Scope(full_scope)

                    #Boolescher Ausdruck
                    if isinstance(expr_type, TBool):
                        if_stmt = SIf(
                            test=expr,
                            body=IList([Hole(hole_tactics, scope=Scope(parent_scope))]),
                            orelse=IList([Hole(hole_tactics, scope=Scope(parent_scope))])
                        )

                        self.fill_selected_hole(
                            CompositeStatement(
                                if_stmt,
                                Hole(hole_tactics, scope=selected_hole.scope)
                            )
                        )

                    #RecordType, data: Computer(ram:int, ...)
                    elif isinstance(expr_type, RecordType):
                        case_scope = Scope(parent_scope)

                        field_holes = []
                        for field_name, field_type in expr_type.fields.items():
                            # Key als str speichern
                            case_scope.add(field_name, field_type)

                            field_holes.append(
                                Hole(
                                    tactics={"intro"},
                                    type=field_type,
                                    scope=case_scope
                                )
                            )

                        body_hole = Hole(hole_tactics, scope=case_scope)

                        case_stmt = SMatch(
                            expr=expr,
                            cases=[
                                SCase(
                                    pattern=expr_type.name,
                                    body=IList([body_hole]),
                                    scope=case_scope,
                                    pattern_values=field_holes
                                )
                            ],
                            scope=Scope(parent_scope)
                        )

                        next_hole = Hole(hole_tactics, scope=selected_hole.scope)

                        self.fill_selected_hole(
                            CompositeStatement(
                                case_stmt,
                                next_hole
                            )
                        )
                    #LiteralType Pet=Literal['cat','dog',  ..]
                    elif isinstance(expr_type, LiteralType):
                        cases_list = []

                        for literal in expr_type.cases:
                            # pro Case eigener Scope
                            case_scope = Scope(parent_scope)

                            hole_type = expr_type.type_of(literal)  # TInt/TStr/...
                            case_body_hole = Hole(
                                tactics=hole_tactics,
                                scope=case_scope,
                                type=hole_type
                            )

                            cases_list.append(
                                SCase(
                                    pattern=str(literal.value),
                                    body=IList([case_body_hole]),
                                    scope=case_scope,
                                    pattern_values=[]
                                )
                            )

                        match_stmt = SMatch(
                            expr=expr,
                            cases=cases_list,
                            scope=Scope(parent_scope)
                        )

                        next_hole = Hole(hole_tactics, scope=selected_hole.scope)

                        self.fill_selected_hole(
                            CompositeStatement(
                                match_stmt,
                                next_hole
                            )
                        )
                    #destruct angewendet auf MixedType
                    elif isinstance(expr_type, MixedType):
                        cases_list: list[SCase] = []
                        for alt in expr_type.cases:
                            # pro Alternative eigener Case-Scope
                            case_scope = Scope(parent_scope)
                            #Alternative ist von RecordType
                            if isinstance(alt, RecordType):
                                field_holes: list[Hole] = []
                                for field_name, field_type in alt.fields.items():
                                    # intro-hole für das Feld
                                    field_holes.append(
                                        Hole(
                                            tactics={"intro"},
                                            type=field_type,
                                            scope=case_scope
                                        )
                                    )
                                body_hole = Hole(hole_tactics, scope=case_scope)

                                cases_list.append(
                                    SCase(
                                        pattern=alt.name,
                                        body=IList([body_hole]),
                                        scope=case_scope,
                                        pattern_values=field_holes
                                    )
                                )

                            #Alternative ist von LiteralType
                            elif isinstance(alt, LiteralType):
                                for lit in alt.cases:
                                    lit_body_hole = Hole(
                                        tactics=hole_tactics,
                                        scope=case_scope,
                                        type=alt.type_of(lit)  # TInt/TStr/...
                                    )
                                    cases_list.append(
                                        SCase(
                                            pattern=str(lit.value),
                                            body=IList([lit_body_hole]),
                                            scope=case_scope,
                                            pattern_values=[]
                                        )
                                    )

                            #Alternative ist von primitiver Typ
                            elif isinstance(alt, (TInt, TBool, TFloat, TComplex, TStr)):
                                prim_label = pretty_type(alt)  # "int", "bool', ..
                                prim_body_hole = Hole(hole_tactics, scope=case_scope, type=alt)
                                cases_list.append(
                                    SCase(
                                        pattern=prim_label,
                                        body=IList([prim_body_hole]),
                                        scope=case_scope,
                                        pattern_values=[]
                                    )
                                )

                            else:
                                raise TacticError(f"Cannot destruct MixedType alternative {alt}")

                        match_stmt = SMatch(
                            expr=expr,
                            cases=cases_list,
                            scope=Scope(parent_scope)
                        )

                        next_hole = Hole(hole_tactics, scope=selected_hole.scope)

                        self.fill_selected_hole(
                            CompositeStatement(
                                match_stmt,
                                next_hole
                            )
                        )

                    else:
                        raise TacticError(f"Cannot destruct expression of type {pretty_type(expr_type)}")
                    self.print_program("Added destruct")

                case "pass":
                    selected_hole = self.get_selected_hole()
                    #Expression Hole darf nicht leer sein
                    if ("fill" in selected_hole.tactics) or ("new" in selected_hole.tactics):
                        raise TacticError("pass is not allowed in expression holes")
                    #Hole füllen (normaler Statement-Hole)
                    selected_hole.filler = EmptyStatement()
                    self.hole_cleaner.clean_holes(self.program)
                    self.print_program("Filled with pass")

                case "finish":
                    if len(self.program.holes) > 0:
                        raise TacticError(f"There are still unfilled holes")
                    self.print_program(f"Finished the program", False)
                    raise TerminationException
                case _:
                    raise UnexpectedValueError(keyword)
        
    def interprete_file(self, file_path: str | Path) -> None:
        file_path = Path(file_path)
        if not file_path.is_file():
            raise FileNotFoundError("File not found")
        tactics = file_path.read_text()
        for tactic in tactics.split("\n\n"):
            print(f"\nInput a tactic:")
            print(pad_str(tactic + "\n", "| ") + "\n")
            try:
                self.interprete_tactic(tactic)
            except TacticError as e:
                print(f"Error: {e}")
            except TerminationException:
                return None
    
    def interprete_interactive(self) -> None:
        while True:
            tactic_lines = []
            print(f"\nInput a tactic:")
            while True:
                tactic_line = input("| ")
                if tactic_line == "":
                    print()
                    break
                tactic_lines.append(tactic_line)

            tactic = "\n".join(tactic_lines)

            try:
                self.interprete_tactic(tactic)

            except TacticError as e:
                print(f"❌ Tactic-Fehler: {e}")

            except TypeError as e:
                print(f"❌ Typfehler: {e}")

            except UnexpectedValueError as e:
                print(f"❌ Nicht unterstützter Ausdruck: {e}")

            except TerminationException:
                return None
