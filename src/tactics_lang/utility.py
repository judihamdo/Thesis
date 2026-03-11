import ast
from dataclasses import dataclass
from typing import Any


# Error classes
# ----------------------
class UnexpectedValueError(Exception):
    def __init__(self, value: Any):
        super().__init__(f"Got unexpected value {value!r}")
        self.value = value


class TacticError(Exception):
    pass


@dataclass
class TypeCheckerError(TacticError):
    msg: str


class TerminationException(Exception):
    pass


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


# helper function
def pad_str(string: str, padding: str = "    ") -> str:
    """pad_str takes a multi-line string, prefixes each line with the given padding (default: four spaces), and returns the indented string again."""
    lines = [f"{padding}{line}" for line in string.split("\n")]
    return "\n".join(lines)
