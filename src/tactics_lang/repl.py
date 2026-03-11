from pathlib import Path

from .utility import TacticError, TerminationException, UnexpectedValueError, pad_str
from .visualise import program_to_str


def print_program(interpreter, status: str, print_options: bool = True) -> None:
    print(f"{status}:")
    print(pad_str(program_to_str(interpreter.program), "| "))
    if print_options:
        tactics = interpreter.get_allowed_tactics()
        tactics_str = ", ".join(tactics) if len(tactics) > 0 else "None"
        print(pad_str(f"Options: {tactics_str}", "| "))


def interpret_file(interpreter, file_path: str | Path) -> None:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError("File not found")
    tactics = file_path.read_text()
    for tactic in tactics.split("\n\n"):
        print("\nInput a tactic:")
        print(pad_str(tactic + "\n", "| ") + "\n")
        try:
            interpreter.interpret_tactic(tactic)
        except TacticError as e:
            print(f"❌ Error: {e}")
        except TerminationException:
            return None


def interpret_interactive(interpreter) -> None:
    while True:
        tactic_lines = []
        print("\nInput a tactic:")
        while True:
            tactic_line = input("| ")
            if tactic_line == "":
                print()
                break
            tactic_lines.append(tactic_line)

        tactic = "\n".join(tactic_lines)

        try:
            interpreter.interpret_tactic(tactic)

        except TacticError as e:
            print(f"❌ Tactic-Fehler: {e}")

        except TypeError as e:
            print(f"❌ Typfehler: {e}")

        except UnexpectedValueError as e:
            print(f"❌ Nicht unterstützter Ausdruck: {e}")

        except TerminationException:
            return None
