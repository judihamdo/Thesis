# Taktische Sprache für Python

This project implements a small tactic-based programming interpreter whose goal is to help beginners construct programs in a structured, guided, and sensible way.

Instead of writing a complete program at once, users build programs step by step by applying tactics. Each tactic performs a well-defined transformation on the program and guides the user toward a complete and well-formed result.

---

# Approach

The main approach is to represent a program as an abstract syntax tree (AST) that may contain **holes**.

Holes represent incomplete parts of the program that still need to be filled.

- Each hole knows which tactics are allowed at that position.
- Tactics fill a hole by replacing it with a concrete subtree, often introducing new holes.
- At any time, only one hole is selected and can be manipulated.
- The program is considered complete once all holes are filled.

This approach encourages users to follow a meaningful construction order (e.g. for functions:  
`description → signature → arguments → ... → return`) instead of writing arbitrary code.

---

# Architecture

## Program Model

The program is stored as an AST containing **statements**, **expressions**, and **holes**.

## Holes

Holes represent missing program fragments and restrict which tactics may be applied.  
Currently, filled holes are not removed but act as a proxy for their filler value.

## Tactics

Tactics are textual commands (for example `let: x: int` or `fill: y + 1`) that:

- check whether they are allowed for the currently selected hole
- replace that hole with a concrete AST fragment
- possibly introduce new holes

## Hole Cleaner

After each tactic, the program structure is updated:

- filled holes are removed
- the next unfilled hole is selected if necessary
- the next valid tactics are determined
- the current program state is printed if no error occurred

## Interpreter

The interpreter reads tactics (from a file or interactively), validates them, applies them to the program, and terminates successfully once no holes remain.

---

# Tactic Syntax

A detailed description of the available tactics and their syntax can be found in:

`syntax_übersicht.md`

---


## Requirements

Python 3.12 or newer

Install required tools:

pip install pytest ruff

## Running the Project

First, navigate to the project root directory.

### 1. Show all available examples

Run:

python -m src.tactics_lang --examples

### 2. Run all example tests (end-to-end)

This runs all example programs without showing their internal execution steps.

python -m pytest tests/test_end_to_end_examples.py

### 3. Run a specific example

To run a single example file, use:

python -m src.tactics_lang --file examples/file_name.txt

### 4. Run parser tests

python -m pytest tests/ParserTest.py

### 5. Run type checker tests

python -m pytest tests/TypeCheckerTest.py

### 6. Start the interactive mode

python -m src.tactics_lang

### 7. Exit the interactive mode

Press **Ctrl + C**.

---

## Code Style

### Format the code

python -m ruff format .

### Check and automatically fix style issues

python -m ruff check . --fix