---
name: ipynb-to-marimo
description: Convert Jupyter notebooks (.ipynb) to marimo notebooks (.py) in a uv + pyproject.toml project, and verify the conversion end-to-end before deleting the originals. Use when asked to convert notebooks to marimo or "move off Jupyter", when a converted file raises NameError/UnboundLocalError, has scattered comments or duplicate definitions, or produces plausible-but-wrong numbers after conversion, or when judging whether a converter rewrite (private-name prefixes, version suffixes, magic commands, display() calls, MultipleDefinitionError) is safe. Covers uv project setup (ruff per-file-ignores, VS Code editor associations), magic-command handling, what marimo convert rewrites internally, and four-layer verification (AST structural, def-chain/version correctness, behavioral output diffing, end-to-end execution).
---

# Converting Jupyter Notebooks to Marimo

Convert, restore, verify, then clean up the project. **Do not delete the original
`.ipynb` until all four verification layers pass.**

**Precondition: this skill assumes a `uv` + `pyproject.toml` project.** Every
command below is `uv run` / `uv add` against a project-local `.venv`. Check
first — `test -f pyproject.toml && command -v uv`. If either is missing, stop
and tell the user the project isn't uv-managed rather than improvising pip,
poetry, or conda equivalents; those need different dependency, script-running,
and environment-activation commands throughout, not just a substituted install
line.

## 1. Convert first

**Important:** Run the converter before you read the source notebook — the generated
file is the fastest way to see what needs attention.

```bash
uvx marimo convert <notebook.ipynb> -o <notebook.py>   # ad hoc
uv run  marimo convert <notebook.ipynb> -o <notebook.py>   # marimo already a project dep
```

Use the `-o` flag rather than a `>` redirect — sandbox hooks on some machines
block shell redirections that write source files, while programmatic `-o`
writes pass.

Read the `.ipynb` only if conversion fails or the generated file omits required
information. Treat the generated file as a first draft. Then:

```bash
uvx marimo check <notebook.py>   # static validation; re-run after edits
uv run marimo export script <notebook.py> -o /dev/null   # equivalent static gate
```

Both gates catch `MultipleDefinitionError` statically. They are
necessary-but-not-sufficient: `_`-private names loaded across cells pass them
and die at runtime — Layer 2 scans for those.

Calibrate the static gate once per environment before trusting it: feed `check`
a deliberately broken two-cell file (the same name defined twice) and confirm
it fails — a gate that has never been seen failing proves nothing. Also compare
shapes: original code-cell count vs `@app.cell` count in the conversion (1:1
plus one `import marimo` boilerplate cell means the converter merged nothing;
fewer cells means it merged redefinitions — read those merges line by line).

Know what the converter does so you can spot real problems. It maps code cells
1:1, turns each cell into a parameterized function (`def _(df, pd):` — the
params are the cell's inputs), resolves cross-cell redefinitions by
**version-renaming** (`df = df.sort_values(...)` becomes `df_1 = ...`, loads
rewritten to the newest version), **privatizes** display-only names
(`name` -> `_name`; duplicate `_names` across cells are legal — don't "fix"
them), deduplicates repeated imports (a repeated `import pandas as pd` is a
`MultipleDefinitionError` in marimo — imports are redefinitions too), expands
`x += 1` to `x = x + 1`, normalizes quotes/float formatting/parens, and
**misplaces the original cell comments** (section banners land mid-statement,
comment blocks get folded onto one line). `df['col'] = ...` is a mutation,
not a redefinition — cells that mutate a parameterized `df` are correct as
converted. Full table with the runtime traps: read
[`references/convert-behavior.md`](references/convert-behavior.md). See §4.
Two damage classes the converter never fixes for you: objective functions that
close over globals a later cell rebinds (§6 — silently fits stale data), and
bare `display(...)` calls (§3 — runtime `NameError`).

**Dangerous special case: a source variable named `mo`.** marimo's own convention
is `import marimo as mo`, so if the source notebook reuses `mo` for anything else
(a loop variable for "month" is a classic collision), the converter renames the
colliding definitions to `mo_1`, `mo_2`, … — safe on its own, like any other
renamed collision — but its markdown/display-cell rewriter can then bind the
wrong (locally-scoped, non-import) `mo_N` into a `mo_N.md(...)` call instead of
the real `mo` import. This produces `AttributeError`s like `'datetime.datetime'
object has no attribute 'md'` at *runtime*, not at `marimo check` time, so it
slips past static validation. After conversion, grep for `mo_\d+\.md\(` and
confirm every hit is a markdown cell that should be calling the real `mo`
import — rebind it and drop the now-unused `mo_N` from that cell's `return`
tuple.

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
The converter handles IPython's auto-injected `display` builtin only when the
source *imported* it explicitly: it drops `from IPython.display import display`
and gives cells a `display` parameter. Bare `display(df)` calls (no import —
Jupyter auto-injects the builtin) survive conversion with nothing named
`display` in scope and raise `NameError` at runtime; the static gates pass them.
Grep the converted file for `display(` and check each call site resolves to a
cell parameter or import; replace the rest with `print(df)` or the cell's last
expression — don't restructure cells just for previews (observed on 0.24.2).

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

**Do not write a preemptive renamer/fixer for redefinitions.** Convert's output
for redefinition-heavy notebooks is usually already valid (versioning +
parameterization handles it), and a naive AST fixer misreads
`df['col'] = ...` targets as rebinds of `df`, renames loads into `NameError`s,
and corrupts correct files — this has happened in practice. If a fixer ran and
something looks off, restore from the pre-fix backup and re-verify instead of
patching forward. Always `tar -czf /tmp/<project>-pre-fix-<date>.tar.gz <dir>`
before bulk tooling touches converted files.

## 5. Verify end-to-end (all four layers)

**Run every verification command via `uv run` from inside the target project
directory, never an ad hoc environment.** Layers 2 and 3 `importlib`-load and
execute the converted app for real, so they need the project's own runtime
dependencies (marimo, numpy, pandas, whatever the notebook imports) already
installed by `uv add`/`uv sync` in §2. Running them elsewhere fails with an
unrelated `ModuleNotFoundError` that looks like a conversion bug but isn't —
confirmed by hand: `uv run --with nbformat --with numpy python verify_outputs.py`
raised `ModuleNotFoundError: No module named 'marimo'` on a valid conversion,
while the identical command with `--with marimo` (or, better, just `uv run
python ...` inside the already-set-up project) passed.

**Layer 1 — structural equivalence.** Every original statement must exist in the
conversion, in order, rename-tolerant:

```bash
uv run python <skill-dir>/scripts/verify_structure.py --ipynb-dir . --py-dir .
```

PASS = no lost statements; report-only extras allowed (the added `display` import).

**Layer 2 — chain/version correctness.** Statement-presence diffs pass a
conversion that loads `df_1` where the original's dataflow implies `df_2`.
This layer labels every variable occurrence with its def-chain identity on
both sides and compares canonical dumps, so wrong-version references,
mis-privatized names, and duplicate-import regressions fail structurally. It
also scans for the runtime traps `marimo check` cannot see: `_`-private names
loaded across cells (runtime `NameError`) and `_x = _x.f()` reaching for the
previous cell's value (runtime `UnboundLocalError`).

```bash
uv run python <skill-dir>/scripts/verify_chains.py --ipynb-dir . --py-dir .
```

Every accepted rename is printed for review (legal shapes: `name_N` and
`_name`; anything else prints SUSPECT). Before trusting a verdict on a new
corpus, re-run under a few `PYTHONHASHSEED` values — flaky, seed-dependent
results mean id()-keyed AST bookkeeping is outliving its trees.

**Layer 3 — behavioral equivalence.** Compare printed results, not just successful
runs. The harness executes each converted app in-process (importlib load +
`app.run()` under captured stdout, cwd = the data dir, so relative paths work)
and diffs its text output against the `.ipynb` stored outputs after symmetric
normalization — renderer noise dropped from BOTH sides, floats rounded to 3
significant digits:

```bash
uv run python <skill-dir>/scripts/verify_outputs.py --ipynb-dir . --py-dir . --env FAST_RUN=1
```

Verdicts: `PASS` (exact), `PASS-STOCHASTIC` (identical skeleton — numbers
masked, whitespace collapsed, sorted line multisets), `DIFF` (unified-diff
excerpt), `EXEC-FAIL`. The manual alternative (`marimo export html` + metric
extraction), the noise-class table (progress bars, keras summary boxes, pandas
preview furniture, warning continuations, figure reprs, self-enumerated file
listings), and the input-freezing protocol: read
[`references/verification.md`](references/verification.md), Layer 3.

Critical: **baseline nondeterminism before blaming the conversion.** Run the
*same* notebook twice and diff its own outputs. Training and optimizer runs are
not bit-stable (unseeded model init, unseeded sampler draws) — if the notebook
doesn't reproduce itself, exact equality is unattainable: use the skeleton
verdict, and check the converted side's headline metrics sit inside the
original's run-to-run spread. If the notebook reads live or volatile data,
freeze it first (staging copy of the data dir, both sides pointed there, runs
back-to-back) — otherwise identical pipelines still differ on the day's fresh
download.

If both formats *are* individually reproducible but still disagree on a seeded
computation, suspect an RNG API swap before anything else: `np.random.seed(42)` +
`np.random.randn(...)` (legacy global `RandomState`, Mersenne Twister) and
`np.random.default_rng(42)` (modern `Generator`, PCG64) are different algorithms
that produce different streams from the *same* seed. Nothing in the converter
does this, but it's an easy "modernization" to introduce by hand while cleaning
up a cell — never substitute one API for the other during conversion; keep
whichever the source notebook used.

**Layer 4 — execution.** Execute every converted notebook headlessly (exit 0, no
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
- Hand-fix rules that preserve behavior (each one bit in practice):
  - **Closures over rebound globals silently fit stale data.** Jupyter cells
    share one namespace, so a notebook can define an objective that reads
    `event_times`/`T` as globals in one cell, then REBIND those names in a
    later cell before calling the fitter — Python's late binding makes the
    later call see the new data. `marimo convert` renames the later rebinding
    (`event_times_1`) to satisfy the no-redefinition rule, and the closure
    keeps resolving the FIRST binding: the fit runs on the wrong data with no
    error, static gates pass, and only the Layer-3 number diff exposes it (bit
    in practice: a likelihood-ratio statistic of −9216 where the original
    printed −0.0002). Detect: functions whose bodies reference names that are
    not their parameters AND are rebound in a later cell. Fix: pass the data
    explicitly — `minimize(lambda p: nll(p, event_times, T), ...)`.
  - **Config flags hard-coded in a cell: make them env-driven.** A notebook's
    `FAST_RUN = False` converts to a hard-coded `False`. Replace with
    `FAST_RUN = os.environ.get("FAST_RUN") == "1"` so the saved file always
    defaults to the full experiment and smoke runs persist nothing (pass
    `--env FAST_RUN=1` to the Layer-3 harness). Do NOT reach for
    `app.run(defs={"FAST_RUN": True})` instead — a defs override skips the
    ENTIRE defining cell, so any data loading or RNG seeding that shares the
    cell is silently skipped too.
  - **Loop variables are cell-level definitions.** When several cells iterate
    the same way (`for name, data in ...:`), the shared targets raise
    `MultipleDefinitionError`; use `_`-prefixed loop variables (cell-local,
    may repeat legally).
  - **Preserve Series/DataFrame names through functional rewrites.** Turning
    `df['col'] = ...` chains into `.assign()`/pipeline one-liners can change
    the Series `.name`, which library output echoes back (statsmodels/arch
    summaries show it as `Dep. Variable:`). Restore with `.rename(...)`.
  - **Move accumulator init into the loop cell.** `results = []` in one cell
    with `results.append(...)` in a later cell is legal, but re-running the
    loop cell duplicates entries; define the list where it is filled.
  - `plt.show()` is optional — marimo captures each cell's figures; keep or
    drop, output is equivalent.
- Put the value to render in the final expression of each cell.
- Replace interactive input that waits for terminal input; gate expensive work or
  side effects with `mo.stop()` and a suitable UI element.
- Do not print, log, or save secrets.
- **ipywidgets do not work in marimo — this is silent, not an error.** `import ipywidgets`
  succeeds (it's an ordinary pip package) and `Accordion`/`Tab`/`Output`/`interact`/`.observe()`
  all construct and execute without raising, so `marimo check`, Layers 1-4, and even a real
  headless `app.run()` all report success. But marimo's frontend has no Comm channel wired up
  for classic ipywidgets: containers print as inert text reprs
  (`interactive(children=(Dropdown(...), Output()), _dom_classes=(...))`) instead of rendering,
  and `.observe()`/`interact()` callbacks never fire — the "interactivity" is completely dead.
  None of the automated verification layers catch this because they check that code runs and
  outputs match, not that a widget is interactive. Treat any `import ipywidgets` (or
  `from ipywidgets import ...`) in the source as a required migration, not an optional cleanup:
  grep for it before declaring a notebook done, and read
  [`references/widgets.md`](references/widgets.md) for the mapping (prefer the native `mo.ui`/
  `mo.accordion`/`mo.ui.tabs` equivalent in the table there; fall back to
  `mo.ui.anywidget(...)` only for entries marked "no equivalent").
- For LaTeX and MathJax, read [`references/latex.md`](references/latex.md).

## 7. Clean up

Only after all four layers pass: archive the originals somewhere ephemeral, delete
the `.ipynb` files, and update README/AGENTS-style docs (runtime commands move from
nbconvert to `uv run marimo export html`; editor associations now resolve). Then:

```bash
grep -rn "ipynb" --include="*.md" --include="*.qmd" --include="*.toml" --include="*.yml" \
  --include="*.yaml" --include="*.py" --include="*.sh" --include="Dockerfile" \
  --include="Makefile" . | grep -v ".venv"    # stale filename references in lessons/prose/helper scripts/CI dangle after deletion
```

Also sweep for the old runner by name (helper scripts, CI, and lesson prose may
invoke it by filename: `grep -rn "run_notebooks\|nbconvert" --include="*.py"
--include="*.md" --include="*.sh" --include="*.yml" --include="*.yaml"
--include="Dockerfile" --include="Makefile" . | grep -v .venv`) and drop the
orphaned Jupyter dev dependencies (`uv remove --group dev jupyterlab ipykernel
nbconvert`). Full protocol:
[`references/verification.md`](references/verification.md), "Removal protocol".
