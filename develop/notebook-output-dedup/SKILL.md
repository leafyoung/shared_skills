---
name: notebook-output-dedup
description: This skill should be used when output in a Jupyter notebook appears more than once - "the chart renders twice", "duplicate figures", "my plot shows up twice", "the widget renders twice", "the tab shows six copies", "output keeps stacking", "output accumulates when I move the slider", "clear_output isn't clearing", "the notebook file is huge", "committed .ipynb doubled in size" - or when building ipywidgets Output/Tab/interact UIs, matplotlib-in-notebook cells, or any refresh-on-control-change pattern where a stale render could survive. Also use when verifying that an executed .ipynb contains exactly one copy of each output, or when notebook size is being investigated. Do not use for ordinary notebook authoring with no duplication concern, or for duplicated *source* cells.
---

# Notebook Output De-duplication

Duplicated notebook output has four distinct causes with four different fixes. They look
identical in the browser, so **diagnose before editing**. Each one is measurable in the
`.ipynb` JSON, and none of them require a human to eyeball the rendering.

## Diagnostic first

Never guess which cause it is. Execute headlessly and count what actually landed:

```bash
jupyter nbconvert --to notebook --execute --inplace nb.ipynb
```

Then run `references/audit_notebook.py` (see that file) to report, per cell and per widget
Output: image count, stream count, duplicate widget views, and total notebook bytes.

Two counting rules that matter:

- A cell holding **two byte-identical `image/png`** outputs, one `execute_result` and one
  `display_data`, is cause 1.
- A cell holding **both a `display_data` and an `execute_result` whose data is
  `application/vnd.jupyter.widget-view+json`** is cause 2.

## Cause 1 — bare `fig` at the end of a cell that also leaves the figure open

The last expression is displayed as the cell's `execute_result` (via the figure's PNG
repr) **and** the inline backend flushes the still-open figure as `display_data`. Two
copies of every chart, doubling the committed size.

```python
fig, ax = plt.subplots()      # WRONG: stores the PNG twice
ax.plot(x, y)
fig
```

Fix with one helper used everywhere, so the rule is enforced rather than remembered:

```python
def show(figure) -> None:
    """Display a figure exactly once."""
    from IPython.display import display
    import matplotlib.pyplot as plt
    display(figure)
    plt.close(figure)
```

## Cause 2 — a helper that both displays a widget and returns it

`display(w)` inside the helper produces `display_data`; returning `w` makes the cell's
return value render a **second full copy**.

Do not fix this at the call site with `_ = build_ui(...)`. That is a convention every
future caller must remember, and it will be forgotten at the second call site. Make the
helper return `None`:

```python
def build_ui(...) -> None:
    ...
    display(widget)
    # Returns nothing on purpose: displaying *and* returning renders a second copy.
```

## Cause 3 — clearing an Output instead of replacing it (the stacking one)

This is the cause behind "six copies in one tab". Both clearing idioms can leave the
previous render in place:

| strategy | behaviour under rapid refreshes |
|---|---|
| `output.clear_output(wait=True)` | Clear is **deferred** until the next output arrives. Survives simple cases; the live-session failure mode. |
| `output.outputs = ()` | Clears what already flushed, but **already-buffered appends still land after it**. Measured: 6 report blocks and 6 figures per tab after 6 rapid refreshes. |
| build a fresh `Output` and swap it in | Correct under every timing. Late output lands on a widget that is no longer displayed. |

So do not clear. Rebuild and swap:

```python
def refresh(_change=None):
    fresh = []
    for kind in kinds:
        output = widgets.Output()
        with output:
            render(kind)          # print / display into the new widget
        fresh.append(output)
    tabs.children = tuple(fresh)  # nothing can accumulate on a discarded widget
```

Preserve `selected_index` and re-apply `set_title` after swapping, or the user is thrown
back to the first tab on every refresh.

## Cause 4 — observer handlers stacking across cell re-runs

If a control **outlives** the cell that registers the handler (defined in an earlier
cell, or the widget is module-level), each re-run adds another handler, so one change
fires the render N times. Drop prior handlers on the trait you are about to observe:

```python
control.unobserve_all(name="value")
control.observe(refresh, names="value")
```

Add a re-entrancy guard too, so dragging a control cannot interleave two renders into
one Output:

```python
rendering = False
def refresh(_change=None):
    nonlocal rendering
    if rendering:
        return
    rendering = True
    try:
        ...
    finally:
        rendering = False
```

## Verification rules

- **A clean `nbconvert` exit proves nothing.** A widget cell that renders nothing still
  "passes". Assert on counts from the JSON, not on the exit code.
- Counts read **inside the same cell** that triggered a refresh are misleading: freshly
  created `Output` widgets flush asynchronously, so `len(o.outputs)` reads 0. Read them
  in a **later cell**.
- To reproduce a live-session bug headlessly, drive the widget under a real kernel: run
  a probe notebook that calls `refresh()` several times in one cell, then counts in the
  next. `references/probe_widget_dedup.py` generates one.
- Some duplication is **deliberate**: a static fallback cell rendering the same figure as
  a widget tab exists because GitHub does not render ipywidgets. Do not "fix" that.

## References

- `references/audit_notebook.py` — count duplication in executed notebooks; exits
  non-zero on any finding, so it can gate a commit. Verified against a notebook
  committing all three detectable causes: it reports each one and exits 1.
- `references/probe_widget_dedup.py` — build and execute a probe notebook comparing the
  three clearing strategies under a real kernel. Reproduces the table above.
- `references/canonical_helpers.py` — copy-ready `show()` and `kind_tabs()`. Put them in
  a module the notebooks import, not in a cell: notebook JSON is un-greppable and
  un-testable, so a rule living in a cell gets re-derived differently next time.

## Reporting

State which of the four causes it was and the measured counts before and after. If you
could not reproduce the user's symptom headlessly, say so and say why the chosen fix is
timing-independent rather than implying you observed the failure.
