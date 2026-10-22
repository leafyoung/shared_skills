"""Copy-ready helpers that make notebook output duplication structurally impossible.

Put these in a project module the notebooks import -- not in the notebooks. Notebook
JSON is un-greppable and un-testable, so a rule that lives in a cell gets re-derived
(differently) in the next notebook. These are the shapes that measured clean under a
real kernel; see probe_widget_dedup.py for the measurement.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence


def show(figure) -> None:
    """Display a matplotlib figure exactly once.

    A bare `fig` at the end of a cell stores the PNG twice: once as the cell's
    execute_result repr, once when the inline backend flushes the still-open figure.
    """
    import matplotlib.pyplot as plt
    from IPython.display import display

    display(figure)
    plt.close(figure)


def kind_tabs(
    kinds: Iterable[str],
    render: Callable[[str], None],
    controls: Sequence = (),
) -> None:
    """Display one tab per kind, re-rendered when any control changes.

    `render(kind)` prints and/or displays; it is called inside that tab's Output.

    Three deliberate choices, each closing a duplication path:

    1. Each refresh builds *new* Output widgets and swaps them in rather than clearing
       the existing ones. `clear_output(wait=True)` defers the clear until the next
       output arrives, and `output.outputs = ()` lets already-buffered appends land
       after it -- measured at 6 stacked reports and 6 figures per tab after 6 rapid
       refreshes. Late output landing on a discarded widget is harmless.
    2. A re-entrancy guard, so dragging a control cannot interleave two renders into
       one Output.
    3. `unobserve_all` before observing, so a control that outlives a cell re-run does
       not accumulate one handler per run (which makes one change render N times).

    Returns None on purpose: displaying *and* returning the widget makes the cell's
    return value render a second copy of the whole tab strip, and then every call site
    has to remember `_ = kind_tabs(...)`.
    """
    import ipywidgets as widgets
    from IPython.display import display

    kinds = list(kinds)
    tabs = widgets.Tab()
    rendering = False

    def refresh(_change=None) -> None:
        nonlocal rendering
        if rendering:
            return
        rendering = True
        try:
            selected = tabs.selected_index
            fresh = []
            for kind in kinds:
                output = widgets.Output()
                with output:
                    render(kind)
                fresh.append(output)
            tabs.children = tuple(fresh)
            for position, kind in enumerate(kinds):
                tabs.set_title(position, kind)
            # Swapping children resets this, which would throw the reader back to tab 1
            # on every refresh.
            tabs.selected_index = selected if selected is not None else 0
        finally:
            rendering = False

    for control in controls:
        control.unobserve_all(name="value")
        control.observe(refresh, names="value")
    refresh()
    display(widgets.VBox([widgets.HBox(list(controls)), tabs]) if controls else tabs)
