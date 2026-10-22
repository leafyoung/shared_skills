# End-to-End Verification

Four layers, in order. All must pass before the original `.ipynb` files are
removed. Each layer catches different conversion damage:

1. **Structural** — code was not lost or reordered.
2. **Chain/version correctness** — every variable occurrence refers to the
   same def-chain version as in the original (and no runtime-private-name
   traps were introduced).
3. **Behavioral** — the conversion still computes the same results.
4. **Execution** — both formats run cleanly today.

## Layer 1 — structural equivalence

AST-based, rename-tolerant alignment of every original statement against the
converted file:

```bash
uv run python <skill-dir>/scripts/verify_structure.py --ipynb-dir <dir> --py-dir <dir>
```

The script reports, per notebook pair:

- `matched N (exact X, rename/fuzzy Y)` — statements present in order. Fuzzy
  matches are the converter's mechanical renames (`df` → `_df`); verify a sample
  by eye the first time.
- `converter-deduplicated at position, verified present elsewhere: N` — repeated
  imports the converter hoisted into an earlier cell; checked to exist elsewhere.
- `LOST ORIG STATEMENTS` — **FAIL**. Conversion dropped code. Fix before anything else.
- `marimo-only statements` — report-only (expected: an added `display` import).
- Cell-count comparison ignores comments-only cells (the converter folds them away).

## Layer 2 — chain/version correctness

Layer 1's fuzzy alignment can pass a conversion that loads `df_1` where the
original's dataflow implies `df_2` — both sides are "a df statement". This
layer closes that gap with a def-chain canonical comparison: both sides are
walked in evaluation order, every variable occurrence is labeled with its
def-chain identity (fresh id per rebinding, reused for loads of the live
version, idempotent for re-imports, name-keyed for externals), and canonical
statement dumps are compared per cell.

```bash
uv run python <skill-dir>/scripts/verify_chains.py --ipynb-dir <dir> --py-dir <dir>
```

- It inherently tolerates the converter's mechanical transforms (quotes,
  float repr, parens, `x += 1` expansion, version renames, privatization,
  dropped re-imports, dropped `IPython.display` imports) and prints every
  rename it accepted — all renames must be `name -> name_N` or
  `name -> _name`; anything else is printed as SUSPECT and reviewed by hand.
- It also scans for **runtime-private-name traps** that static gates pass:
  `_x` bound in one cell and loaded in another (runtime `NameError`), and
  `_x = _x.f()` reaching for the previous cell's value (runtime
  `UnboundLocalError`). `marimo check` does NOT catch these.
- **Determinism check:** run it under several `PYTHONHASHSEED` values before
  trusting a verdict on a new corpus:
  `for s in 0 1 42; do PYTHONHASHSEED=$s python verify_chains.py ...; done`
  Flaky, seed-dependent results mean an id()-keyed map in the tooling is
  outliving its AST — every id()-keyed dict (name marks, def marks, skip
  sets) must be scoped to a single cell, because dead AST nodes free their
  addresses and CPython id reuse silently relabels live nodes.
- Skip verdicts (`global`/`nonlocal`, `match`, star imports) need manual
  review; exit 1 only on FAIL.

## Layer 3 — behavioral equivalence

Successful execution is not enough — compare the printed results.

1. **Harness: normalized output diff.** `scripts/verify_outputs.py` executes
   each converted app in-process (importlib load + `app.run()` under redirected
   stdout/stderr, cwd set to the data dir so relative paths work) and diffs its
   text output against the `.ipynb` stored outputs (stream stdout +
   `display_data` `text/plain`, in cell order):

   ```bash
   uv run python <skill-dir>/scripts/verify_outputs.py --ipynb-dir . --py-dir . --env FAST_RUN=1
   ```

   Both sides are normalized symmetrically (noise classes below dropped from
   both, floats rounded to 3 significant digits) and compared as line lists.
   Verdicts: `PASS` (exact), `PASS-STOCHASTIC` (identical skeleton — item 5),
   `DIFF` (unified-diff excerpt), `EXEC-FAIL`. A failing or crashing pair is
   reported and the remaining pairs still run; exit 0 only when all pass.
   Calibrate the harness once on a tiny synthetic pair (identical → PASS,
   numbers-only change → PASS-STOCHASTIC, wording change → DIFF) so its
   verdicts mean something.

2. **Manual alternative** (no harness): `uv run marimo export html
   <notebook.py> -o out.html 2> run.log`, extract `label: value` metric lines
   from the stored outputs and the log, compare positionally with ~1%
   tolerance.

3. **Noise classes to drop from BOTH sides** (each observed in practice; the
   harness implements all of them — `--extra-noise REGEX` for project-specific
   stragglers):

   | Class | Examples / notes |
   |---|---|
   | progress bars | `%|`, `it/s`, `s/it`, `━`, `ETA`, backspace-erase lines (`\x08` runs emitted by keras bars) |
   | keras fit/summary chatter | `Epoch 1/40`, `382/382 [...]`; `model.summary()` renders as an ANSI-styled box table in Jupyter but a plain box headless — drop lines containing `\x1b` or box-drawing chars (`│┃├┼┤╒═…`) from both sides |
   | optimizer chatter | optuna `Trial N finished`, `Best is trial`; statsmodels/arch `Time:` wall-clock stamps |
   | warnings + continuations | `RuntimeWarning: ...` **and** the indented source-context line some warnings print after them (strip leading whitespace before matching) |
   | figure reprs | `<Figure size 1400x600 with 1 Axes>` — Jupyter turns figures into display_data reprs the headless side never prints |
   | pandas preview furniture | index-led data rows, header chunks, `...` ellipses, `\` wrap markers, `[N rows x M columns]` footers (footers exist only where the renderer truncated — their presence is layout, not data). Do NOT "fix" by setting `display.width`; filter symmetrically |
   | self-enumerated file listings | `- results_part2.csv` bullets from cells that list the output dir — which artifacts exist mid-run depends on cell execution order (notebook linear vs marimo topological) and prior runs |

4. **Stored `.ipynb` outputs can be days old.** If the notebook pulls live
   data, don't diff a fresh run against the stored outputs — diff fresh vs
   fresh (run the original too, Layer 4), or pin the data (item 6).

5. **Stochastic notebooks: prove nondeterminism, then compare skeletons.**
   Rerun the ORIGINAL twice and diff its own stored outputs. If it does not
   reproduce itself (unseeded model init, unseeded sampler draws), exact
   equality is unattainable — that is a property of the notebook, not the
   conversion. Compare skeletons instead: mask every number (`-?\d+(\.\d+)?...`
   → `#`, each mask its own token so `[[255` and `[[ 593` normalize equal),
   collapse internal whitespace, require equal line counts, then compare the
   SORTED line multisets. This tolerates the churn stochastic runs actually
   produce: alignment padding from digit-width changes in confusion matrices,
   sign flips on near-zero correlations, row swaps in tables sorted by a
   stochastic column. Finish by checking the converted side's headline metrics
   sit inside the original's run-to-run spread.

6. **Pin ALL inputs, not just downloads.** For live APIs, a replay cache beats
   tolerance: the first process to download persists each response; the second
   replays it (yfinance: ~10-line `sitecustomize.py` pickle cache on
   `PYTHONPATH`), making pairs exact. But data can also change under you
   without any download in the notebook: a background collector, teammate, or
   cron job writing to the data directory mid-verification turns later runs
   into a comparison against different input. Freeze the corpus: copy the data
   dir to a staging location (or generate known seeded data there) and point
   BOTH sides at it via cwd. Run pairs back-to-back to shrink the drift window.
   Diagnosis pattern: a deterministic pipeline that suddenly yields empty or
   degenerate output means the INPUT changed, not the code — check data-file
   sizes/mtimes before debugging the conversion (bit in practice: an hour of
   input data silently became 2 minutes mid-session and the "failure" was a
   window filter returning zero rows).

7. **Flat-script diff as the fallback shape.** When outputs are plain prints
   (no `label: value` metrics), extract both sides to runnable flat scripts
   and diff stdout directly: ipynb → concatenated code cells; marimo → the
   `@app.cell` function bodies via AST, skipping `mo.md` cells, `return`
   lines, and the `import marimo as mo` boilerplate cell. Require equal code-
   cell counts, run both with the same cwd/env (`MPLBACKEND=Agg`), compare
   exact for deterministic sources, skeleton/numeric-tolerant otherwise.
   Sandbox-hook caveat: on machines whose PreToolUse hooks block
   `subprocess`/`exec` inside submitted helper scripts, load apps with
   `importlib.util.spec_from_file_location` + `exec_module` (module loading,
   not `exec` of file text) and pass run-mode flags via environment variables
   the apps read — source-patching runners and argv-driven subprocess
   wrappers tend to trip injection heuristics.

Verdict per notebook: `PASS` when outputs match exactly after normalization;
`PASS-STOCHASTIC` when the notebook is proven nondeterministic and skeletons
match with headline metrics inside the original's noise floor; otherwise FAIL.

## Layer 4 — execution

- Converted notebooks: `uv run marimo export html X.py -o out.html` for each —
  require exit 0 and no "some cells failed to execute" in output.
- Originals, same day: nbconvert with the project kernel:

  ```bash
  uvx --with nbconvert python -m nbconvert --to notebook --execute --inplace X.ipynb \
    --ExecutePreprocessor.timeout=1800 --ExecutePreprocessor.kernel_name=<kernel>
  ```

  Back-to-back runs on the same day minimize data drift (online data sources
  revise history; fixed download windows reduce this but don't eliminate it).
- Budget: minutes per notebook; run sequentially in background with per-notebook
  PASS/FAIL markers in the log. Don't conclude a format is slow from one
  timing: the first run after dependency churn can be contention-slowed orders
  of magnitude (observed: 588 s under load vs 4 s standalone for the same
  notebook).

## Removal protocol (only after all layers pass)

1. Archive originals: `mkdir -p /tmp/<backup>/ipynb && cp *.ipynb /tmp/<backup>/ipynb/`
   (ephemeral — say so out loud).
2. `rm *.ipynb`.
3. Update docs that describe the layout: README conversion section (note the
   verification + removal date), AGENTS/CLAUDE-style agent docs (headless-run
   commands move from nbconvert to `uv run marimo export html`), and any
   agent-memory notes that claim `.ipynb` files still exist.
4. Sweep for stale references beyond the obvious docs: `grep -rn "ipynb"`
   over `*.md`, `*.qmd`, `*.toml`, `*.yml`, `*.py` (excluding `.venv`/build
   dirs) — lessons/tutorials/prose and helper scripts often cite notebooks or
   the old runner by filename and now dangle (verified in practice: lesson
   `.qmd` files referencing three deleted notebooks, and a figure script
   naming one in its docstring).
5. Drop now-orphaned Jupyter dev dependencies once the originals are gone:
   `uv remove --group dev jupyterlab ipykernel nbconvert` (adjust to the
   project's actual dev group). Empty `dev = []` group left behind is harmless.
6. Leave the registered Jupyter kernel in place if one exists — harmless, and the
   environment may still serve non-notebook Jupyter use.

## Pre-flight checks worth running after convert

- Calibrate the gates before trusting them: feed `marimo check` a deliberately
  broken two-cell file (same name defined twice) and confirm it fails; smoke
  `verify_outputs.py` on a synthetic pair expected to PASS, one expected
  PASS-STOCHASTIC, one expected DIFF. A gate that has never been seen failing
  proves nothing.
- Map shapes: original code-cell count vs `@app.cell` count in the conversion.
  1:1 (plus one `import marimo` boilerplate cell) means the converter merged
  nothing; fewer cells means it merged redefinitions — review those merges.
- Magics scan: `grep -nE "get_ipython|^\s*[!%][a-zA-Z%]" X.py` (see `magics.md`).
- `uv run marimo check X.py` — catches duplicate top-level global definitions
  (underscore-prefixed names are cell-scoped and may legally repeat) **and
  duplicate imports across cells** (imports are redefinitions in marimo; the
  converter deletes redundant ones, but hand edits can reintroduce them).
- `uv run marimo export script X.py -o /dev/null` — equivalent static gate;
  useful when `check` is unavailable.
- Empty-cell check: comments-only source cells become empty marimo cells; that's
  fine, but their comments are dropped — the comment-restoration pass recovers
  the ones that belong to statements.
- Before ANY bulk tooling runs on converted files: take a backup
  (`tar -czf /tmp/<project>-pre-fix-<date>.tar.gz <py-dir>`), and if a tool's
  output looks suspicious, restore and re-verify instead of patching forward.
