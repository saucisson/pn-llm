"""Check the size budgets of the code, beyond what ruff checks (docs/architecture.md, "Budgets").

Ruff limits the complexity of a function. These budgets keep modules and classes readable: a
module that outgrows its budget is split along a real concept, not along line numbers.
Used as a pre-commit hook and in CI.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = (ROOT / "api" / "app", ROOT / "engines" / "common")

MAX_MODULE_LINES = 700
MAX_FUNCTION_LINES = 130
MAX_METHODS_PER_CLASS = 40


def main() -> int:
    """Return 0 when every file is within its budgets, 1 otherwise."""
    problems: list[str] = []
    for source in SOURCES:
        for path in sorted(source.rglob("*.py")):
            text = path.read_text()
            name = path.relative_to(ROOT)
            lines = text.count("\n") + 1
            if lines > MAX_MODULE_LINES:
                problems.append(f"{name}: {lines} lines, budget {MAX_MODULE_LINES}")
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    length = (node.end_lineno or node.lineno) - node.lineno + 1
                    if length > MAX_FUNCTION_LINES:
                        problems.append(
                            f"{name}:{node.lineno} {node.name}: {length} lines, "
                            f"budget {MAX_FUNCTION_LINES}"
                        )
                elif isinstance(node, ast.ClassDef):
                    methods = sum(
                        isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                        for item in node.body
                    )
                    if methods > MAX_METHODS_PER_CLASS:
                        problems.append(
                            f"{name}:{node.lineno} {node.name}: {methods} methods, "
                            f"budget {MAX_METHODS_PER_CLASS}"
                        )
    for problem in problems:
        print(problem)  # noqa: T201  (hook output)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
