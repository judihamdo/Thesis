from functools import partial
from typing import Any

from .context import make_ctx_for_typecheck
from .helper_functions import (
    _program_has_signature,
    all_paths_return,
    auto_close_unreachable,
    can_use_pass,
    collect_variables,
    find_parent_statement,
    is_directly_after_total_match,
    is_directly_after_total_return_stmt,
    is_parameter_hole,
    is_structural,
    is_top_level_in_function,
    is_within_destruct,
    postprocess_new,
    prefix_always_returns,
    types_ready_for_signature,
    update_list_lengths_after_fill,
)
from .hole_cleaner import HoleCleaner
from .program import (
    EVar,
    Hole,
    Identifier,
    Program,
    Scope,
)
from .repl import print_program
from .tactics import (
    _tactic_comment,
    _tactic_cons,
    _tactic_data,
    _tactic_description,
    _tactic_destruct,
    _tactic_fill,
    _tactic_finish,
    _tactic_intro,
    _tactic_let,
    _tactic_new,
    _tactic_nil,
    _tactic_pass,
    _tactic_return,
    _tactic_signature,
    _tactic_switch,
    _tactic_type,
)
from .type_checker import type_check, typecheck_filler
from .utility import TacticError

TACTICS = {
    "description",
    "signature",
    "intro",
    "let",
    "return",
    "fill",
    "new",
    "switch",
    "data",
    "finish",
    "type",
    "destruct",
    "pass",
    "cons",
    "nil",
    "comment",
}


class Interpreter:
    def __init__(self):
        self.program = Program(Hole({"description"}))
        self.hole_cleaner = HoleCleaner(self.program)
        self.hole_cleaner.clean_holes(self.program)
        self.global_scope = Scope()  # Root node for function-level variables
        print_program(self, "Initial program")
        self.used_variables_names: set[str] = set()
        self._tactic_handlers = {
            "description": partial(_tactic_description, self),
            "comment": partial(_tactic_comment, self),
            "type": partial(_tactic_type, self),
            "signature": partial(_tactic_signature, self),
            "intro": partial(_tactic_intro, self),
            "let": partial(_tactic_let, self),
            "data": partial(_tactic_data, self),
            "fill": partial(_tactic_fill, self),
            "new": partial(_tactic_new, self),
            "nil": partial(_tactic_nil, self),
            "cons": partial(_tactic_cons, self),
            "return": partial(_tactic_return, self),
            "switch": partial(_tactic_switch, self),
            "destruct": partial(_tactic_destruct, self),
            "pass": partial(_tactic_pass, self),
            "finish": partial(_tactic_finish, self),
        }

    def get_allowed_tactics(self) -> set[str]:
        """Assign the available tactics to each hole."""
        auto_close_unreachable(self)

        tactics: set[str] = set()
        if len(self.program.holes) == 0:
            return {"finish"}

        selected_hole = self.program.selected_hole
        if selected_hole is None:
            return {"finish"}

        if is_top_level_in_function(self, selected_hole) and prefix_always_returns(self, selected_hole):
            return {"finish"}

        elif is_directly_after_total_return_stmt(self, selected_hole):
            return {"pass"}

        # Allow comment only in Statement-Holes (not in expression holes / intro holes)
        if selected_hole.tactics.isdisjoint({"fill", "new", "cons", "nil"}) and selected_hole.tactics not in ({"intro"}, {"description"}):
            tactics.add("comment")

        if len(self.program.holes) > 1:
            tactics.add("switch")

        if self.program.selected_hole is None:
            return tactics

        # List_hole: Only cons/nil (+ switch when mutiple Holes)
        if getattr(selected_hole, "kind", "normal") == "list":
            t = {"cons", "nil"}
            if len(self.program.holes) > 1:
                t.add("switch")
            return t

        # tactics performs the union without duplicates
        tactics |= selected_hole.tactics
        # Parameter holes: only intro + switch
        if is_parameter_hole(self, selected_hole):
            tactics.discard("pass")
            tactics.discard("return")
            tactics.discard("destruct")
            return tactics

        parent_stmt = find_parent_statement(self, selected_hole)
        in_destruct = is_within_destruct(self, selected_hole)

        if in_destruct:
            tactics |= selected_hole.tactics

        # If all paths in the if-else return → only pass is allowed.
        if parent_stmt and all_paths_return(self, parent_stmt, inside_destruct=False):
            return {"pass"}

        # Expression holes (fill) must never offer `pass`.
        if "fill" in selected_hole.tactics or "new" in selected_hole.tactics or selected_hole.tactics == {"intro"}:
            tactics.discard("pass")
            return tactics
        want_empty = can_use_pass(self, selected_hole)

        # Top level: if previous code does not definitely return, `pass` is not allowed.
        if is_top_level_in_function(self, selected_hole) and not prefix_always_returns(self, selected_hole):
            want_empty = False

        # Top level only: do not allow `pass` directly after a match that guarantees a return.
        # This could be changed if a `case_` branch is introduced.
        if is_top_level_in_function(self, selected_hole):
            want_empty = False

        if is_directly_after_total_match(self, selected_hole):
            want_empty = True
            tactics = {"finish"}
            return tactics

        if want_empty:
            tactics.add("pass")
        else:
            tactics.discard("pass")

        # bevor signature is offered, check this
        ready, _msg = types_ready_for_signature(self)
        # signature ist nur erlaubt, wenn ready
        if "signature" in tactics and not ready:
            tactics.discard("signature")
        return tactics

    def get_selected_hole(self) -> Hole:
        """The hole currently being handled."""
        if self.program.selected_hole is None:
            raise TacticError("❌ No hole is selected")
        return self.program.selected_hole

    def fill_selected_hole(self, filler: Any) -> None:
        """Handle the filling of the selected hole."""
        hole = self.get_selected_hole()
        hole.filler = filler

        parent_decl, ctx = make_ctx_for_typecheck(self, hole)
        if not typecheck_filler(self, hole, parent_decl, ctx, filler):
            return

        auto_ctor = isinstance(filler, EVar) and isinstance(filler.name, Identifier)
        if getattr(hole, "_used_new", False) or auto_ctor:
            new_filler = postprocess_new(self, hole, parent_decl, filler)
            if new_filler is not None:
                filler = new_filler
                hole.filler = filler

        update_list_lengths_after_fill(self, parent_decl, filler)
        target_scope = hole.scope if isinstance(hole.scope, Scope) else self.global_scope
        if is_structural(filler):
            collect_variables(self, filler, target_scope)

        if _program_has_signature(self, self.program.statement) and is_structural(filler):
            type_check(self.program)

        self.hole_cleaner.clean_holes(self.program)

    def select_hole(self, index: int) -> None:
        """Which hole must be selected"""
        if index < 0 or index >= len(self.program.holes):
            raise TacticError(f"❌ There is no unfilled hole with the index {index!r}")
        if self.program.selected_hole is self.program.holes[index]:
            raise TacticError("❌ Hole is already selected")
        self.program.selected_hole = self.program.holes[index]
        self.hole_cleaner.clean_holes(self.program)

    def interpret_tactic(self, tactic: str) -> None:
        """Handle the received command."""
        tactic = tactic.strip()
        if tactic == "":
            raise TacticError("❌ No tactic specified")
        if ":" not in tactic:
            raise TacticError("❌ Missing ':' after tactic keyword")

        keyword, data = tactic.split(":", 1)
        keyword = keyword.strip()
        data = data
        if keyword not in TACTICS:
            raise TacticError(f"❌ Unknown tactic {keyword!r}")

        allowed = self.get_allowed_tactics()
        if keyword not in allowed:
            raise TacticError(f"❌ The tactic {keyword!r} can not be applied right now")
        # Use self._tactic_handlers; if it does not exist, initialize it as an empty dictionary.
        handler = getattr(self, "_tactic_handlers", {}).get(keyword)
        if handler is None:
            raise TacticError(f"❌ No handler implemented for tactic {keyword!r}")

        # Central execution: the handler performs the changes, then we print the result.
        handler(data)
