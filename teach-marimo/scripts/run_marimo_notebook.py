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
    Returns belonging to functions (or lambdas) *nested inside* a cell are
    the nested scope's own, not cell-level state — descend no further than
    the cell's own body (a nested `def helper(): return a, b` must not
    register a, b as cell outputs).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    def is_cell(node: ast.AST) -> bool:
        return any(
            (isinstance(d, ast.Attribute) and d.attr == "cell")
            or (isinstance(d, ast.Name) and d.id == "cell")
            for d in node.decorator_list
        )

    def walk_own_scope(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # nested scope — its returns are not cell-level state
            if isinstance(child, ast.Return) and isinstance(child.value, ast.Tuple):
                names.update(e.id for e in child.value.elts if isinstance(e, ast.Name))
            walk_own_scope(child)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_cell(node):
            walk_own_scope(node)
    return names


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("notebook_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        outputs, defs = mod.app.run(defs={"mo": marimo})
    except Exception as e:  # marimo semantic errors DO propagate (unlike cell raises)
        if "IncompleteRefsError" in type(e).__name__ + str(e):
            print(
                f"FAILED: {path} — marimo IncompleteRefsError: {e}\n"
                "Known cause: this runner injects `mo` via defs, which makes marimo prune "
                "a cell that bundles `import marimo as mo` together with the notebook's "
                "other imports, orphaning those imports for every later cell. "
                "Fix: put `import marimo as mo` alone in its own cell.",
                file=sys.stderr,
            )
            return 1
        raise
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
