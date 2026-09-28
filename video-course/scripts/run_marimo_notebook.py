"""Verify a marimo notebook by executing all its cells headlessly.

Usage: python3 run_marimo_notebook.py NOTEBOOK.py
Imports the notebook module and calls app.run(), injecting `mo` explicitly
(some environments don't inject mo into headless cell execution). Any cell
exception propagates — nonzero exit means the notebook is broken.
"""
import importlib.util
import sys

import marimo


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    spec = importlib.util.spec_from_file_location("notebook_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    outputs, defs = mod.app.run(defs={"mo": marimo})
    print(f"OK: {path} executed; {len(defs)} definitions, {len(outputs)} cell outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
