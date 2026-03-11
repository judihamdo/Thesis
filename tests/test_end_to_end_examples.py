from __future__ import annotations

from pathlib import Path

import pytest

from src.tactics_lang.interpreter import Interpreter
from src.tactics_lang.repl import interpret_file
from src.tactics_lang.utility import TacticError, TerminationException

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _is_expected_failure(p: Path) -> bool:
    """Convention: filenames containing 'fail' or 'error' are expected to fail."""
    name = p.name.lower()
    return ("fail" in name) or ("error" in name)


def _run_example(path: Path) -> None:
    """Runs a test example. 'finish' counts as a successful completion."""
    itp = Interpreter()
    try:
        interpret_file(itp, path)
    except TerminationException:
        return


def _collect_examples() -> list[Path]:
    if not EXAMPLES_DIR.exists():
        return []
    return sorted(EXAMPLES_DIR.glob("*.txt"))


@pytest.mark.parametrize("example_path", _collect_examples())
def test_examples_end_to_end(example_path: Path):
    # When no examples avilable: do not evaluate Test as "fail"
    if not example_path.exists():
        pytest.skip(f"Example not found: {example_path}")

    if _is_expected_failure(example_path):
        with pytest.raises((TacticError, TypeError)):
            _run_example(example_path)
    else:
        _run_example(example_path)
