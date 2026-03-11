import argparse
from pathlib import Path

from .interpreter import Interpreter
from .repl import interpret_file, interpret_interactive


def run_all_examples_in_folder(folder="examples"):
    for p in sorted(Path(folder).glob("*.txt")):
        print("\n" + "=" * 80)
        print(f"RUNNING: {p}")
        print("=" * 80)
        interpreter = Interpreter()
        interpret_file(interpreter, p)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the tactic interpreter either in interactive mode or by executing a source file.")
    parser.add_argument(
        "--file",
        type=Path,
        metavar="PATH",
        help="Path to a file to interpret. If omitted, the interpreter starts in interactive mode.",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Run all example .txt files in the examples/ folder.",
    )
    args = parser.parse_args()
    interpreter = Interpreter()
    if args.examples:
        run_all_examples_in_folder("examples")
    elif args.file is None:
        interpret_interactive(interpreter)
    else:
        interpret_file(interpreter, args.file)
