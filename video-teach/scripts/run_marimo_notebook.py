"""Verify a marimo notebook by executing all its cells headlessly.

Usage: python3 run_marimo_notebook.py NOTEBOOK.py
Imports the notebook module and calls app.run(), injecting `mo` explicitly
(some environments don't inject mo into headless cell execution).

Failure detection: on current marimo (verified 0.25.0), a cell that raises
does NOT propagate its exception through app.run() — the run completes
silently with the cell's definitions missing (and `marimo export html`
exits 0 too, while wrongly failing on correct mo-using notebooks). So
instead of relying on exceptions, this script parses the notebook's AST
for every name a cell declares in its `return` tuple (marimo requires
these statically) and diffs them against the definitions the run actually
produced. Any missing definition means a cell raised mid-body: nonzero
exit, with the missing names reported. Exceptions that DO propagate
(e.g. marimo semantic errors) also exit nonzero.

NOTEBOOK's third-party imports must be importable — run it inside the
course env (uv run python ...).
"""
import ast
import importlib.util
import sys
from pathlib import Path

import marimo


def declared_defs(path: Path) -> set[str]:
    """Union of names cells declare in their `return (...)` tuples.

    marimo requires each cell's return statement to list exactly the
    variables it defines, so this is the notebook's full declared state.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_cell = any(
            (isinstance(d, ast.Attribute) and d.attr == "cell")
            or (isinstance(d, ast.Name) and d.id == "cell")
            for d in node.decorator_list
        )
        if not is_cell:
            continue
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Tuple):
                names.update(e.id for e in stmt.value.elts if isinstance(e, ast.Name))
    return names


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("notebook_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    outputs, defs = mod.app.run(defs={"mo": marimo})
    missing = declared_defs(path) - set(defs)
    if missing:
        print(
            f"FAILED: {path} — cell(s) raised or did not complete; "
            f"missing definitions: {sorted(missing)} "
            f"(headless marimo swallows cell exceptions — check these cells)",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {path} executed; {len(defs)} definitions, {len(outputs)} cell outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
