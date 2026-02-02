from typing import Any, Optional
from utility import UnexpectedValueError
from program import *
from immutable_list import IList

class HoleCleaner:
    def __init__(self, program: Program = None):
        self.selected_hole: Optional[Hole] = None
        self.holes: list[Hole] = []
        self.program = program
        
    def mark_scope_active(self, scope: Scope | None):
        """ Geht nach oben durch die Scope-Kette. Das ist ein Marker für die empty-Regel:Wenn ein Branch aktiv war
        (z.B. durch destruct/if/match/), dann kann später empty erlaubt werden. """
        while scope:
            scope.has_destruct_child = True 
            scope = scope.parent
    # Rekursive Funktion zum Cleanen
    def clean_node(self, node: Any, current_scope: Scope = None) -> Any:#scope wird damit gegeben
        match node:
            case Hole():
                #Egal ob gefüllt oder nicht: node.scope wird auf den aktuellen Scope gesetzt.
                #Damit weiß später der Interpreter beim fill/let/return welche Variablen sichtbar sind.
                node.scope = current_scope
                #Gefülltes Hole: Entferne Hole, ersetze durch filler, und repariere selection falls nötig
                #Offenes Hole: Nimm Hole in die hole-Liste auf, gib ihm index, evtl. mach es zum selected hole
                if node.filler is not None:
                    #(Das ist speziell für intro Holes).
                    #Die Variable wird sofort mit Typ im richtigen Scope gespeichert,damit das System weiß, dass sie existiert.
                    if isinstance(node.filler, Identifier) and node.type is not None and isinstance(current_scope, Scope):
                        current_scope.add(node.filler, node.type)
                    #Jetzt ist es aber gefüllt worden, kein Hole mehr, sondern wurde durch seinen Inhalt ersetzt.
                    if node is self.selected_hole:
                        self.selected_hole = None

                    #Wenn ein Hole gefüllt ist dann soll es nicht mehr als Hole im AST stehen.Stattdessen soll der AST so aussehen, als wäre der Filler direkt dort.
                    return self.clean_node(node.filler, current_scope)
                #kein selected hole -> erste offene Loch waehlen
                if self.selected_hole is None:
                    self.selected_hole = node
                #Hier wird erstmal alles auf False gesetzt, weil: der Cleaner sammelt erstmal alle Holes
                #das finale selected hole wird später (in clean_holes) auf True gesetzt
                node.selected = False
                node.index = len(self.holes)
                self.holes.append(node)
                #Da das Hole offen ist, bleibt es im AST erhalten.
                return node
            #lass es wie es ist
            #case InjectedExpression() | EConst() | EVar() | EOp1() | EOp2() | EFunCall() | EIf() | EBoolOp():
            #    return node
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

            case InjectedExpression() | EConst() | EVar():
                return node

            #lass es wie es ist
            case Identifier():
                return node
            #Falls RecordType Felder hat, die wiederum Holes enthalten könnten, werden sie gereinigt.
            case RecordType():
                for k, v in node.fields.items():
                    node.fields[k] = self.clean_node(v, current_scope)
                return node
            #lass es wie es ist
            case TInt() | TBool() | TFloat() | TComplex() | TStr():
                return node

            case FunctionType(parameter_types, return_type):
                parameter_types = [self.clean_node(p, current_scope) for p in parameter_types]
                return_type = self.clean_node(return_type, current_scope)
                return FunctionType(parameter_types, return_type)
            #lass es wie es ist
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
                #Eine if, else, match scope... ist nicht mehr leer wenn eine variable drin ist
                self.mark_scope_active(current_scope)
                name = self.clean_node(name, current_scope)
                type_ = self.clean_node(type_, current_scope)
                # initializer zuerst cleanen (damit "c = d" geht, weil d schon vorher added wurde)
                expression = self.clean_node(expression, current_scope)
                # Variable im aktuellen Scope registrieren
                if isinstance(current_scope, Scope) and isinstance(name, Identifier):
                    current_scope.add(name, type_)
                return VariableDeclaration(name, type_, expression)

            case ReturnStatement(expression):
                expression = self.clean_node(expression, current_scope)
                return ReturnStatement(expression)

            case LiteralType() as lit:
                lit.cases = [self.clean_node(c, current_scope) for c in lit.cases]
                return LiteralType(cases=lit.cases, name=lit.name)
            
            case MixedType() as mt:
                # Alle Alternativen (cases) rekursiv cleanen (falls dort Holes/RecordTypes/etc. drin sind)
                mt.cases = [self.clean_node(c, current_scope) for c in mt.cases]
                return MixedType(cases=mt.cases, name=mt.name)


            case SMatch(expr, cases):
                #fuer empty, also mein scope ist nicht leer
                self.mark_scope_active(current_scope)
                expr = self.clean_node(expr, current_scope)
                #frozen_parent ist eine Kopie des Scopes bis hierhin.
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

            case SIf(test, body, orelse):
                #erste 3 genau wie bei Smatch
                self.mark_scope_active(current_scope)
                test = self.clean_node(test, current_scope)
                frozen_parent = current_scope.freeze() if current_scope else None
                #eigener Scope für if-body
                body_scope = Scope(parent=frozen_parent)
                new_body = IList([self.clean_node(stmt, body_scope) for stmt in body])
                #else-branch hat seinen eigenen Scope, er sieht nicht die Variablen aus if-branch
                orelse_scope = Scope(parent=frozen_parent)
                new_orelse = IList([self.clean_node(stmt, orelse_scope) for stmt in orelse])
                return SIf(test, new_body, new_orelse)

            case ConstantType(value):
                return node

            case TypeDeclaration(name, type_):
                name = self.clean_node(name, current_scope)
                type_ = self.clean_node(type_, current_scope)
                return TypeDeclaration(name, type_)
            case _:
                raise UnexpectedValueError(node)

    #räumt das ganze Programm nach jeder Änderung auf
    def clean_holes(self, program: Program) -> None:
        #Das Programm merkt sich bereits ein ausgewähltes Hole (z.B.nach switch) und der Cleaner übernimmt das als Startwert.
        self.selected_hole = self.program.selected_hole
        self.holes = []
        #Das ist der oberste Scope fürs gesamte Program.
        root_scope = Scope(parent=None)
        self.program.statement = self.clean_node(self.program.statement, current_scope=root_scope)

        if self.selected_hole is None and self.holes:
            #Nimm letzte offene Loch
            self.selected_hole = self.holes[-1]
        if self.selected_hole:
            self.selected_hole.selected = True

        self.program.selected_hole = self.selected_hole
        self.program.holes = self.holes

