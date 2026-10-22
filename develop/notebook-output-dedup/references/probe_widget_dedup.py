"""Reproduce widget-output stacking under a real kernel, and compare the three fixes.

Usage:
    python probe_widget_dedup.py            # writes and executes /tmp/probe_dedup.ipynb
    python probe_widget_dedup.py out.ipynb

Why a probe notebook rather than a plain script: ipywidgets `Output` only captures
output when a kernel is attached. Run the same code with plain `python` and prints leak
to stdout while `output.outputs` stays empty, so the bug cannot be observed at all.

Counting rule: the counts are read in a *later* cell than the refreshes, because freshly
created Output widgets flush asynchronously and read as empty within the same cell.
"""

import json
import subprocess
import sys
from pathlib import Path

SETUP = '''
import ipywidgets as widgets
import matplotlib.pyplot as plt
from IPython.display import display

KINDS = ["a", "b"]

def render(kind):
    print(f"report {kind}")
    fig, ax = plt.subplots()
    ax.plot([0, 1])
    display(fig)
    plt.close(fig)

def make(strategy):
    """strategy: 'wait' | 'assign' | 'swap'"""
    tabs = widgets.Tab(children=[widgets.Output() for _ in KINDS])
    for i, k in enumerate(KINDS):
        tabs.set_title(i, k)

    def refresh(_change=None):
        if strategy == "swap":
            fresh = []
            for kind in KINDS:
                out = widgets.Output()
                with out:
                    render(kind)
                fresh.append(out)
            selected = tabs.selected_index
            tabs.children = tuple(fresh)
            for i, k in enumerate(KINDS):
                tabs.set_title(i, k)
            tabs.selected_index = selected if selected is not None else 0
        else:
            for out, kind in zip(tabs.children, KINDS):
                if strategy == "wait":
                    out.clear_output(wait=True)
                else:
                    out.outputs = ()
                with out:
                    render(kind)

    return tabs, refresh
'''

REFRESH = '''
built = {}
for strategy in ("wait", "assign", "swap"):
    tabs, refresh = make(strategy)
    for _ in range(6):          # six rapid refreshes, as a control drag produces
        refresh()
    built[strategy] = tabs
print("six refreshes applied per strategy")
'''

COUNT = '''
# Read in a later cell so the buffered output above has flushed.
print(f"{"strategy":<9}{"(report blocks, figures) per tab"}")
for strategy, tabs in built.items():
    per_tab = [(sum(1 for x in o.outputs if x["output_type"] == "stream"),
                sum(1 for x in o.outputs if x["output_type"] == "display_data"))
               for o in tabs.children]
    verdict = "OK" if all(c == (1, 1) for c in per_tab) else "STACKED"
    print(f"{strategy:<9}{per_tab}   {verdict}")
'''


def build(path: Path) -> None:
    cells = [{"cell_type": "code", "id": f"p{i}", "execution_count": None, "metadata": {},
              "outputs": [], "source": src.strip().splitlines(keepends=True)}
             for i, src in enumerate((SETUP, REFRESH, COUNT))]
    path.write_text(json.dumps({
        "cells": cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python", "version": "3"}},
        "nbformat": 4, "nbformat_minor": 5}, indent=1))


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/probe_dedup.ipynb")
    build(path)
    subprocess.run(["jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", str(path)],
                   check=True, capture_output=True)
    nb = json.loads(path.read_text())
    for cell in nb["cells"]:
        for out in cell.get("outputs", []):
            if out["output_type"] == "stream":
                print("".join(out["text"]).rstrip())
            elif out["output_type"] == "error":
                print("ERROR", out["ename"], out["evalue"])


if __name__ == "__main__":
    main()
