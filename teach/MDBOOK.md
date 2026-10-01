# mdBook flavor notes for teach workspaces

mdBook **mechanics** — toolchain pinning, plugin wiring, Route A (create an
mdBook from scratch), Route B (convert a qmd course, with the
construct-by-construct mapping), the per-content-type style table, and every
gotcha — now live in the shared **mdbook-authoring** skill
(`~/.agents/skills/mdbook-authoring/`, one source used by teach,
video-teach, and slides-teach alike). Its bundled `assets/book.toml`,
`assets/scripts/katex_text_fix.py`, and `assets/scripts/check_links.py`
moved there too. **Follow that skill for all book building.**

Everything in SKILL.md about teaching (mission, node structure,
Motivate/Establish/Connect/Check, exercises with answer keys, zone of
proximal development) applies unchanged — only the authoring format and
build differ, and the format decision itself stays in SKILL.md "Output
Formats" (mdbook default; quarto print-first; never two living lesson
formats in one workspace).

This file keeps only what teach adds on top of the shared guide:

- **Canonical layout — state docs live inside the book.** Same teaching
  content as the Quarto flavor, inside `./mdbook/`: `src/mission.md`,
  `src/NOTES.md`, `src/resources.md`, `src/glossary.md`,
  `src/reference/*.md`, `src/learning-records/*.md`, lessons at
  `src/lessons/000N-<dash-case-name>.md` (dash-separated; underscores are
  the companion *notebook* files' convention, not the lessons'). The book
  dir may sit at the workspace root under a name like `lessons_md/`.
  Agent-facing state (`NOTES.md`, `learning-records/`) stays **out of
  `SUMMARY.md`** and unlinked from lessons — unlisted = silently
  unrendered, which is exactly what state wants. Each state doc's H1
  equals its Quarto-era front-matter `title` (what the normalizer pairs
  on).
- **Translated workspaces**: one full-mirror book per language
  (`lessons_md/` + `lessons_md_zh/`), kept in lockstep per SKILL.md
  "Mirrors, sync, and verification" — shared state (mission, NOTES,
  RESOURCES, learning records) maintained **once**, in the
  primary-language book. The teach skill's
  [`assets/scripts/normalized_diff.py`](./assets/scripts/normalized_diff.py)
  implements the sync proof (it stays bundled here, not in
  mdbook-authoring — mirror sync is teach's concern, not the book's).
- **Linkage-route exception**: a workspace whose other artifacts
  (reference-doc PDFs, notebook headers) link into rendered root documents
  keeps GLOSSARY/MISSION/NOTES/RESOURCES as root Quarto docs instead
  (SKILL.md "Output Formats"); the book then holds lessons, reference
  pages, and assets only.
- **Route couplings**: Route A step 1 (probe/plan) is teach's mandatory
  first-session flow — mission interview, dependency-map plan, user
  go-ahead before any authoring; Route A step 7 records learning records /
  `NOTES` updates as usual. Route B's end-state policy: after the
  normalized-diff proof, **retire the qmd lessons** — delete them (git
  history is the provenance record) and record the retirement in `NOTES`
  (first done 2026-09-26; keeping both is how mirror drift happens;
  retaining the qmd lessons is the one exception and a confirm-with-user
  decision — only if the user explicitly wants the print format maintained
  too, which decides whether the root `_quarto.yml` survives). After
  conversion, fix content bugs in the **book** — do not regenerate from
  qmd unless the user asks.
