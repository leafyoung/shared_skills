# What `marimo convert` actually does (observed on 0.24.x)

Know these before reading a converted file or writing any fix-up tooling. Every
item below was verified empirically on a 23-notebook quant corpus; the two
"gotcha" items cost real debugging time when missed.

## The cell mechanism

Each code cell becomes

```python
@app.cell
def _(df, pd):        # parameters = the cell's references
    ...
    return (df_1,)    # scaffolding; may be bare `return`
```

Cross-cell name reuse is expressed through **parameters**, not globals. Read a
converted cell as: "my inputs arrive as arguments".

Markdown cells become code cells of their own — `@app.cell(hide_code=True)`
containing `mo.md(r"""...""")` (raw string, so backslashes survive) — and the
file gains one `import marimo as mo` boilerplate cell that has **no `.ipynb`
counterpart**. Extraction/comparison tooling must skip both shapes.

## How the converter resolves conflicts (do not re-fix these)

- **Version-renames rebinding chains.** `df = df.sort_values(...)` in a later
  cell becomes `df_1 = df.sort_values(...)` with a notebook-wide counter
  (`df_1`, `df_2`, ...), and every downstream load is rewritten to the newest
  version. The chain is semantically correct — **for direct loads**. Trailing-
  digit suffixes are never cosmetic.

  **Corollary (late binding breaks function bodies).** The rewrite does not
  reach inside functions defined earlier. A cell-1 objective that reads
  `event_times` as a global resolves that name *at call time*; if the original
  notebook rebinds `event_times` in cell 2 before calling the fitter, Jupyter's
  shared namespace makes it work. After conversion cell 2's binding is
  `event_times_1`, the closure still resolves cell 1's `event_times`, and the
  fit silently uses the wrong data — plausible output, no error, static gates
  pass. Only a Layer-3 output diff exposes it. Fix: pass the data as arguments
  (SKILL.md §6).
- **Privatizes display-only names.** Variables (and function defs) that only
  exist to be looked at may be renamed `name` -> `_name`, making them
  cell-private. Duplicate `_`-prefixed names across cells are **legal**.
- **Subscript/attribute assignment is a mutation, not a redefinition.**
  `df['col'] = ...` does NOT define `df`; marimo treats it as mutating the
  object that arrived via the parameter. Any tool that walks an assignment
  target tree and treats every `Name` under it as a bind will misread these
  cells, "fix" them, and corrupt a valid conversion. (This happened: an AST
  fixer renamed loads into `NameError`s on files that were already correct.
  The fixer was discarded and the files restored from backup.)

  **Corollary: don't write a preemptive renamer/fixer.** Convert's output for
  redefinition-heavy notebooks is usually already valid. Convert everything,
  run the gates, and only then consider hand edits — with a backup taken
  first and a diff-review of anything a tool changed.

## Imports are redefinitions too

`marimo check` / `app.run()` raise `MultipleDefinitionError` when two cells
bind the same name — **including identical `import pandas as pd` lines**
(verified on 0.24.2; older lore says imports are exempt — they are not).
The converter deletes redundant re-imports (keeping the earliest); if you
split or merge cells afterwards, re-run the check.

## Semantics cheat sheet (all verified on 0.24.2)

| Pattern | Result |
|---|---|
| public name bound in 2 cells | `MultipleDefinitionError` (static) |
| same import in 2 cells | `MultipleDefinitionError` (static) |
| **for-loop targets bound in 2 cells** (`for name, data in ...:`) | `MultipleDefinitionError` — loop targets are cell-level definitions, not temporaries (verified 0.24.2; hit in practice on four cells iterating the same way). In hand-written/hand-fixed cells use `_`-prefixed loop variables — cell-local, may repeat legally |
| duplicate `_`-private defs across cells | legal |
| `_x` bound in cell A, loaded in cell B | passes static gates, **NameError at runtime** (error hints at the mangled `_cell_XXXX_x`) |
| `_x = _x.f()` first thing in a cell, `_x` from previous cell | **UnboundLocalError at runtime** |
| `df['col'] = x` in a cell that receives `df` as param | fine (mutation) |
| `xs = []` in cell A, `xs.append(x)` in cell B | legal (mutation), but re-running B *appends again* — move the init into the loop cell so re-runs start fresh |
| Series built by a functional rewrite loses its `.name` | cosmetic but user-visible: statsmodels/arch summaries print the Series name as `Dep. Variable:`. Chaining `df['x']...` assignments into `np.log(df['price']/...).dropna()` renames the series to `price`; restore with `.rename('log_return')` (caught by output diff in practice) |
| bare `display(df)` (no IPython import) | survives conversion with `display` unbound — **NameError at runtime**, static gates pass (Jupyter auto-injects the builtin; the converter only rewrites the explicit-import form). Replace with `print(df)` (verified 0.24.2) |
| cell-1 function body references a global that cell 2 rebinds (converter renames cell 2's binding) | closure keeps resolving cell 1's version — **silently operates on stale data** (late binding + version rename, see the corollary above; bit in practice on a Hawkes MLE) |
| `app.run(defs={"x": v})` override | skips the ENTIRE cell defining `x` — data loading / RNG seeding sharing that cell is skipped too. Prefer env-driven flags (`os.environ.get(...)`) for config that lives in a data-loading cell |

The runtime-error rows above are why `marimo check` passing is *necessary but
not sufficient* — see `verification.md` Layer 1b, which also runs the
private-flow scan.

## AST-level rewrites to expect in diffs (all semantics-preserving)

- string quotes normalized (`"x"` -> `'x'`, including f-strings)
- float repr normalized (`1e-8` -> `1e-08`, `0.80` -> `0.8`, `0.00002` -> `2e-05`)
- redundant parentheses dropped
- augmented assignment expanded: `total += x` -> `total = total + x`
- comments re-anchored — section banners can land mid-cell and comment blocks
  get folded (see the comment-restoration pass in SKILL.md §4)
- `!pip` / magic lines commented out or dropped
- `from IPython.display import display` is dropped and `display` becomes a
  cell parameter (marimo supplies it) — check what the converter generated
  before hand-adding IPython imports

## What the converter does NOT do

- It does not run code or verify semantics — `marimo check` passing is a
  static gate only.
- It does not consolidate first-time imports into cell 0; it only deletes
  redundant repeats.
- It does not invent arbitrary renames. Every rename is either
  `name -> name_N` (versioning) or `name -> _name` (privatization). Any other
  identifier change in a diff is a red flag.
- It does not rewrite bare `display()` calls into something resolvable, and it
  does not fix closure-over-global dataflow when it renames a rebound global —
  both require the hand fixes in SKILL.md §3 and §6.
