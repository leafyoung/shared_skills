"""Count what actually landed in an executed notebook.

Usage:
    python audit_notebook.py nb.ipynb [nb2.ipynb ...]

Reports, per notebook: duplicated figures, duplicated widget views, per-tab output
counts, and total bytes. Exits non-zero if any duplication is found, so it can gate a
commit. Deliberate duplication (a static fallback cell mirroring a widget tab) will
show up here too -- read the per-cell detail before "fixing" it.
"""

import json
import sys
from pathlib import Path

WIDGET_MIME = "application/vnd.jupyter.widget-view+json"


def audit(path: Path) -> int:
    nb = json.loads(path.read_text())
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    problems = 0

    print(f"\n{path}  ({path.stat().st_size:,} bytes)")

    unexecuted = sum(1 for c in code if c.get("execution_count") is None)
    errors = [o["ename"] for c in code for o in c.get("outputs", []) if o["output_type"] == "error"]
    print(f"  cells: {len(nb['cells'])} ({len(code)} code), unexecuted: {unexecuted}, errors: {errors or 'none'}")

    # Cause 1: one cell storing the same figure twice (execute_result + display_data).
    for i, cell in enumerate(code):
        images = [o for o in cell.get("outputs", []) if "image/png" in o.get("data", {})]
        if len(images) > 1:
            identical = len({o["data"]["image/png"][:200] for o in images}) == 1
            print(f"  CAUSE 1  cell {i}: {len(images)} figures"
                  f"{' (byte-identical -> bare `fig` with the figure left open)' if identical else ''}")
            problems += 1

    # Cause 2: a widget displayed and also returned.
    for i, cell in enumerate(code):
        views = [o["output_type"] for o in cell.get("outputs", []) if WIDGET_MIME in o.get("data", {})]
        if len(views) > 1:
            print(f"  CAUSE 2  cell {i}: {len(views)} widget views {views} -> helper displays and returns")
            problems += 1

    # Causes 3 and 4: stacked content inside widget Outputs.
    state = list(nb["metadata"].get("widgets", {}).values())
    outputs = [v for v in state[0]["state"].values() if v.get("model_name") == "OutputModel"] if state else []
    if outputs:
        counts = []
        for v in outputs:
            entries = v["state"].get("outputs", [])
            counts.append((sum(1 for x in entries if x.get("output_type") == "stream"),
                           sum(1 for x in entries if x.get("output_type") == "display_data")))
        print(f"  widget Outputs: {len(outputs)}, (stream, figure) each: {counts}")
        stacked = [c for c in counts if c[0] > 1 or c[1] > 1]
        if stacked:
            print(f"  CAUSE 3/4  {len(stacked)} Output(s) hold stacked renders: {stacked}")
            problems += len(stacked)
    else:
        print("  widget Outputs: none (no saved widget state)")

    print(f"  => {'clean' if not problems else f'{problems} duplication problem(s)'}")
    return problems


if __name__ == "__main__":
    paths = [Path(a) for a in sys.argv[1:]]
    if not paths:
        sys.exit("usage: python audit_notebook.py nb.ipynb [...]")
    sys.exit(1 if sum(audit(p) for p in paths) else 0)
