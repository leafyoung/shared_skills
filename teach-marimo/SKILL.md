---
name: teach-marimo
description: >-
  Build and verify marimo companion notebooks for teaching workspaces: an
  interactive app that runs the lesson's or lecture's central artifact - the
  algorithm being taught, the worked example, the visualization of a
  phenomenon, the concept made manipulable. Use when creating a marimo
  notebook for a lesson or course, deciding whether a course or unit gets
  companion notebooks, wiring a workspace's editor to open notebooks in
  marimo, or verifying a marimo notebook by executing it (the
  run_marimo_notebook.py headless verifier). Used by the teach skill (and its
  video-teach / slides-teach source pipelines) whenever a teaching workspace
  calls for a notebook. Not for pedagogy (teach), workspace layout (teach),
  or book-building mechanics (mdbook-authoring).
---

# Teach-marimo: companion notebooks for teaching workspaces

Notebooks are **marimo, never Jupyter** (user preference: reactive cells, no
hidden state, stored as plain Python). This skill owns three things: whether a
course gets notebooks, how they are built, and how they are verified.

## Whether to build notebooks

Decide once per course (or per tutoring workspace), record the decision in
`NOTES`, and apply it to every unit:

1. **Default: build.** A marimo notebook is generally a good way to explain
   concepts and put up interactive examples - for any teaching topic, including
   non-programming ones (a finance formula the user can drag a slider on, a
   statistics phenomenon visualized, a geometry construction). When the subject
   is not a programming language, notebooks are an explanation tool; use them
   liberally.
2. **Build when the course teaches Python or already uses Python in its
   content.** The notebook then doubles as worked code the learner reads and
   reruns - it is part of the subject matter, not just an illustration.
3. **Skip when the course teaches a non-Python programming language** (VBA, R,
   C++, ...). A marimo notebook is a Python program; building one would put a
   second language between the learner and the subject. Exercises and worked
   artifacts live in the course's own language instead - under the language's
   own tooling (scripts, spreadsheets, the REPL), verified the same way.

Edge case: a mixed course (e.g. finance concepts with Python worked examples)
follows rule 2. A course that merely *mentions* code in passing follows rule 1.

## Building a notebook

Each unit's notebook lives at `<unit>/notebooks/<slug>.py` (tutoring
workspaces: beside the lesson under `lessons/`-adjacent `notebooks/` or in
`./notebooks/`, consistently) - an interactive companion that runs the
central artifact: the algorithm being taught, the worked example, the
visualization of the phenomenon, the spreadsheet model made live.

- marimo app with `app_title`, `hide_code` markdown cells explaining each
  section, LaTeX via `$...$`/`$$...$$` in `mo.md`, interactive controls
  (`mo.ui.slider`, `mo.ui.text`) wherever a parameter is pedagogically
  interesting.
- Self-contained: synthetic data or tiny bundled samples by default. If it
  needs a download, cache into `<unit>/data/` and degrade gracefully offline;
  for spreadsheet sources bundle the real sheet as a small CSV when it is
  small enough to commit, else generate a faithful synthetic stand-in and say
  so.
- One known structural requirement: **put `import marimo as mo` alone in its
  own cell** - bundling it with the notebook's other imports interacts badly
  with the verifier's `mo` injection (marimo prunes the cell and every later
  cell orphans; see below).
- Reference the notebook from the unit's overview chapter and the relevant
  lessons (repo-relative path in prose).

## Verifying a notebook

**Verify by execution:**

```bash
uv run python ~/.agents/skills/teach-marimo/scripts/run_marimo_notebook.py \
    <unit>/notebooks/<slug>.py
```

It imports the module, runs every cell via `app.run(defs={"mo": marimo})`,
and detects a raised cell by diffing the notebook's statically declared cell
outputs against the definitions the run actually produced. Any failure exits
nonzero.

Why this harness exists - neither naive check works:

- On current marimo (verified 0.25.0), a cell that raises does **not**
  propagate its exception through `app.run()` - the run completes silently
  with that cell's definitions missing.
- Plain `marimo export html` is **not a verifier**: it exits 0 on broken
  cells AND wrongly exits 1 on correct mo-using notebooks.

So the runner parses the notebook's AST for every name a cell declares in its
`return` tuple and diffs that against the definitions the run produced: any
missing definition means a cell raised, and the missing names are reported.
Exceptions that do propagate (marimo semantic errors) also exit nonzero - and
`IncompleteRefsError` almost always means the bundled-`import marimo as mo`
problem above; the runner prints that fix when it sees the error.

Also run `ruff` and `marimo check` on each touched notebook as part of the
workspace's verification bar (teach, "Mirrors, sync, and verification").

## Editor wiring

Add a root `.vscode/settings.json` so unit notebooks open as marimo while
`assets/*.py` figure scripts and any `src/` package keep the default editor -
the ipynb-to-marimo skill's `workbench.editorAssociations` pattern (narrower
`"default"` overrides first, the notebook glob last):

```json
{
  "workbench.editorAssociations": {
    "**/unit*_*/notebooks/*.py": "marimo-notebook"
  }
}
```

(video-course layout: glob `**/ep*_*/notebooks/*.py`.)
