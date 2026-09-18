# End-to-End Verification

Three layers, in order. All must pass before the original `.ipynb` files are
removed. Each layer catches different conversion damage:

1. **Structural** — code was not lost or reordered.
2. **Behavioral** — the conversion still computes the same results.
3. **Execution** — both formats run cleanly today.

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

## Layer 2 — behavioral equivalence

Successful execution is not enough — compare the printed results.

1. Run the conversion headlessly and keep the log (prints land on stderr/stdout):

   ```bash
   uv run marimo export html <notebook.py> -o out.html > /dev/null 2> run.log
   ```

2. Extract `label: value` metric lines from the `.ipynb` stored outputs
   (cell outputs of type `stream`) and from the run log; compare positionally in
   order of appearance, with a small relative tolerance (~1%) for data drift.
3. Fallbacks for output without `label: value` lines: compare *all* extracted
   numbers positionally, or compare non-empty output lines exactly (whitespace-normalized).
4. **Baseline nondeterminism before blaming the conversion.** Run the *same*
   notebook twice (or compare two days' runs). Model training and iterative
   optimizers are not bit-stable: if the notebook does not reproduce itself,
   drift in its metrics is inherent noise, not conversion damage.

Verdict per notebook: PASS when all deterministic metrics match and any remaining
deltas are covered by the notebook's own noise floor.

## Layer 3 — execution

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
  PASS/FAIL markers in the log.

## Removal protocol (only after all layers pass)

1. Archive originals: `mkdir -p /tmp/<backup>/ipynb && cp *.ipynb /tmp/<backup>/ipynb/`
   (ephemeral — say so out loud).
2. `rm *.ipynb`.
3. Update docs that describe the layout: README conversion section (note the
   verification + removal date), AGENTS/CLAUDE-style agent docs (headless-run
   commands move from nbconvert to `uv run marimo export html`), and any
   agent-memory notes that claim `.ipynb` files still exist.
4. Leave the registered Jupyter kernel in place if one exists — harmless, and the
   environment may still serve non-notebook Jupyter use.

## Pre-flight checks worth running after convert

- Magics scan: `grep -nE "get_ipython|^\s*[!%][a-zA-Z%]" X.py` (see `magics.md`).
- `uv run marimo check X.py` — catches duplicate top-level global definitions
  (underscore-prefixed names are cell-scoped and may legally repeat).
- Empty-cell check: comments-only source cells become empty marimo cells; that's
  fine, but their comments are dropped — the comment-restoration pass recovers
  the ones that belong to statements.
