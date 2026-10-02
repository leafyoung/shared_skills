# Teach skill family - validation protocol

Any session can re-validate the whole teach skill family from this file - after
any structural change to a family skill, or when something behaves oddly. It is
the stored version of the decomposition's architecture contract plus the
mechanical checks that prove the current files still implement it.

## The family and its locations

| Skill | Real files (git repo) | Owns |
|---|---|---|
| `teach` | `~/.agents/shared_skills/teach/` | pedagogy AND the workspace: layout, state docs, output formats, lessons into the book, resources, assets, mirrors/errata, verification bar, exit gates |
| `teach-marimo` | `~/.agents/shared_skills/teach-marimo/` | companion notebooks: whether to build, how, the `run_marimo_notebook.py` verifier, editor wiring |
| `video-teach` | `~/.agents/shared_skills/video-teach/` | video source pipeline: transcribe (Step 1), slides+OCR (Step 2), transcript layers (Step 3), Phase A handover gate |
| `slides-teach` | `~/.agents/shared_skills/slides-teach/` | static-source pipeline: ingest (Step 1), page extraction/index + speaker notes (Step 2) |
| `mdbook-authoring` | `~/.agents/shared_skills/mdbook-authoring/` | book mechanics: toolchain, Route A/B, style table (tracked in this repo like the family, but external to it: owned by its own skill, not restructured with it) |

`~/.agents/skills/<skill>` are symlinks to `../shared_skills/<skill>`; edit only
the real files under `shared_skills/`.

## The architecture contract

```
video-teach (Steps 1-3)      slides-teach (Steps 1-2)
            └─────────┬────────────┘
                      ▼
     teach  ──────►  teach-marimo (called up for notebooks)
  pedagogy + workspace
         └──────► mdbook-authoring (book mechanics, when building)
```

Call order is a handoff, top-down: a front-end (or a "teach me" session) does
its own phase, then hands to teach for workspace and lesson authoring, which
calls teach-marimo when a notebook is needed and mdbook-authoring when the book
is built. Each concern has exactly one home; cross-skill references are
pointers, never copies.

## Checks (all mechanical)

1. **Home uniqueness** - each concern appears in full in exactly one skill; the
   others carry at most a one-line pointer. Grep signals:
   - notebook conventions (`app_title`, `mo.ui.slider`, the verifier invocation)
     only in teach-marimo;
   - the course workspace layout tree and the exit-gate checklist only in teach;
   - the Phase A cross-artifact gate only in video-teach;
   - the page-index/notes.md extraction rules only in slides-teach;
   - `run_marimo_notebook.py` exists exactly once, at
     `teach-marimo/scripts/`, and compiles (`python3 -m py_compile`).
2. **Handoff pointers** - video-teach's Steps 4-7 and slides-teach's Steps 3-6
   point at teach; both point notebook questions at teach-marimo; teach points
   book building at mdbook-authoring and notebooks at teach-marimo. No file in
   the family references `teach-course` (removed 2026-10-03).
3. **Notebook policy** - teach-marimo carries the when-to-build rule (default
   build as concept explainer; build when the course teaches or uses Python;
   skip when the course teaches a non-Python programming language; decision
   recorded in `NOTES`), and teach's exit-gate notebook item is conditional on
   that rule rather than unconditional.
4. **Reference integrity** - every file path referenced by any family SKILL.md
   exists (test through the `~/.agents/skills/` symlink paths too); every
   internal markdown anchor resolves against its file's headings; frontmatter
   (`name:` + `description:`) parses in all four skills.
5. **Symlinks** - `~/.agents/skills/` contains `teach`, `teach-marimo`,
   `video-teach`, `slides-teach`, each resolving to `../shared_skills/<skill>`;
   no `teach-course` symlink remains.
6. **Regression spot-checks** - owned rules still present and attributed
   correctly: exercises-all-answered + multiple-choice construction (teach);
   acquisition-on-the-moment + the fetched-PDF truncation check + resources
   gitignore (teach); errata at point-of-use + mirror sync via
   `normalized_diff.py` + the authoritative-index contract (teach); deck PDF
   pulled forward + narration-aligned index columns (video-teach); notes.md
   extraction + XLSX inventory mode (slides-teach); XLSX CSV bundling
   (teach-marimo).
7. **Functional smoke test** (when a course workspace with a notebook is
   available): run `uv run python ~/.agents/skills/teach-marimo/scripts/run_marimo_notebook.py
   <notebook>.py` against one existing course notebook; expect exit 0 on a
   known-good one.

## Re-validation procedure

Read this file, run checks 1-6 by grep/Read (fast - no subagent needed), and 7
when a workspace is at hand. Findings are reported to the user - this repo
keeps no review log by design - and fixes land on the user's go-ahead, one
commit per fix. After fixing, re-run this protocol before reporting done.
