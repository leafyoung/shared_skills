---
name: ipynb-to-marimo
description: Convert Jupyter notebooks (.ipynb) to marimo notebooks (.py) and verify the conversion end-to-end. Use when asked to convert notebooks to marimo, when "move off Jupyter" or "marimo conversion" comes up, when a converted file raises NameError or has scattered comments or duplicate definitions, when deciding whether magic commands like %timeit or %%timeit survive conversion, or when verifying a conversion is faithful before deleting the originals. Covers uv project setup (ruff per-file-ignores, VS Code editor associations), magic-command handling, and three-layer verification (AST structural, behavioral metrics, end-to-end execution).
---

# Converting Jupyter Notebooks to Marimo

Convert, restore, verify, then clean up the project. **Do not delete the original
`.ipynb` until all three verification layers pass.**

## 1. Convert first

**Important:** Run the converter before you read the source notebook — the generated
file is the fastest way to see what needs attention.

```bash
uvx marimo convert <notebook.ipynb> -o <notebook.py>   # ad hoc
uv run  marimo convert <notebook.ipynb> -o <notebook.py>   # marimo already a project dep
```

Read the `.ipynb` only if conversion fails or the generated file omits required
information. Treat the generated file as a first draft. Then:

```bash
uvx marimo check <notebook.py>   # static validation; re-run after edits
```

Know what the converter does so you can spot real problems: it maps code cells 1:1
unless they conflict, renames cell-local helpers with a `_` prefix (duplicate
`_names` across cells are **legal** — they are cell-scoped; don't "fix" them),
deduplicates repeated imports into earlier cells, flattens code onto single lines,
and **misplaces the original cell comments** (section banners land mid-statement,
comment blocks get folded onto one line). See §4.

## 2. Project setup (uv)

Add marimo (and ruff if linting) to the uv project:

```bash
uv add marimo
uv add --dev ruff
```

Converted notebooks re-import per cell (by design), end cells with a bare `return`,
and may render a bare expression like `df`. Silence those rules for marimo files in
`pyproject.toml`:

```toml
[tool.ruff.lint.per-file-ignores]
"*.py" = ["F401", "B018", "PLR1711"]
```

`F401` unused import (cells re-import), `B018` useless expression (bare `df`
display cells), `PLR1711` useless return (marimo cells end with bare `return`).
If the repo also has non-marimo modules, narrow the glob (e.g. `"notebooks/*.py"`).

For editors, make numbered notebook files open as marimo notebooks via
`.vscode/settings.json`:

```json
{
  "workbench.editorAssociations": {
    "[0-9][0-9][0-9][0-9]_*.py": "marimo-notebook"
  }
}
```

Adjust the glob to the project's naming scheme.

## 3. Magic commands

The converter cannot execute or translate IPython magics — they break the generated
Python or survive as `get_ipython()` calls. Scan for them first:

```bash
grep -nE "get_ipython|^\s*[!%][a-zA-Z%]" <notebook.py>
```

General rules: delete environment magics, translate compute magics, and replace
shell escapes. `%timeit` and `%%timeit` become the `timeit` module:

```python
# %timeit -n 100 -r 10 f(x)            ->  best-of-r timing
import timeit
best = min(timeit.repeat(lambda: f(x), number=100, repeat=10))

# %%timeit over a cell body            ->  time a function wrapping the body
import timeit
def _bench():
    ...cell body...
print(f"{min(timeit.repeat(_bench, number=1, repeat=7)):.4f}s")
```

Full translation table: read [`references/magics.md`](references/magics.md).
Also add the explicit import when the notebook relies on IPython's auto-injected
`display` builtin (works in Jupyter, `NameError` in marimo): put
`from IPython.display import display` in the first cell that uses it and add
`display` to that cell's `return` tuple.

## 4. Restore comments and fix converter artifacts

Before verification, run the comment-restoration pass on all converted files — it
re-anchors every original comment to the statement it preceded (any nesting depth,
rename-tolerant) and asserts executable code is unchanged:

```bash
# dry run first, then --write
uv run python <skill-dir>/scripts/restore_comments.py --ipynb-dir . --py-dir .
uv run python <skill-dir>/scripts/restore_comments.py --ipynb-dir . --py-dir . --write
```

It also fixes: stale leading comment stacks above the first statement (trim), and
duplicate-definition fallout (converter renames are expected and safe; top-level
duplicate *global* definitions are not — `marimo check` reports those).

## 5. Verify end-to-end (all three layers)

**Layer 1 — structural equivalence.** Every original statement must exist in the
conversion, in order, rename-tolerant:

```bash
uv run python <skill-dir>/scripts/verify_structure.py --ipynb-dir . --py-dir .
```

PASS = no lost statements; report-only extras allowed (the added `display` import).

**Layer 2 — behavioral equivalence.** Compare printed results, not just successful
runs. Extract `label: value` metrics from the `.ipynb` stored outputs and from a
headless marimo run, compare positionally with a small tolerance:

```bash
uv run marimo export html <notebook.py> -o out.html 2> run.log   # log holds prints
```

Critical: **baseline nondeterminism before blaming the conversion.** Run the *same*
notebook twice (or across days). Training and optimizer runs are not bit-stable —
if the notebook doesn't reproduce itself, metric drift is not a conversion error.
For outputs without `label: value` lines, compare all extracted numbers or
non-empty lines positionally.

**Layer 3 — execution.** Execute every converted notebook headlessly (exit 0, no
failed cells), and execute the originals the same way (nbconvert) so both formats
are proven on the same day:

```bash
uvx --with nbconvert python -m nbconvert --to notebook --execute --inplace <notebook.ipynb> \
  --ExecutePreprocessor.timeout=1800 --ExecutePreprocessor.kernel_name=<kernel>
```

Details, edge cases, and the removal protocol: read
[`references/verification.md`](references/verification.md).

## 6. Review the conversion

- Verify all required packages in the PEP 723 metadata; the converter can miss some
  package-installation forms. Remove residual installation cells and stale install prose.
- Preserve the purpose and intended workflow of the source notebook; keep cell
  boundaries sensible (merge/split when they reduce clarity).
- Put the value to render in the final expression of each cell.
- Replace interactive input that waits for terminal input; gate expensive work or
  side effects with `mo.stop()` and a suitable UI element.
- Do not print, log, or save secrets.
- For ipywidgets, read [`references/widgets.md`](references/widgets.md).
- For LaTeX and MathJax, read [`references/latex.md`](references/latex.md).

## 7. Clean up

Only after all three layers pass: archive the originals somewhere ephemeral, delete
the `.ipynb` files, and update README/AGENTS-style docs (runtime commands move from
nbconvert to `uv run marimo export html`; editor associations now resolve).
