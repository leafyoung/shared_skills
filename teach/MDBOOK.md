# mdBook output format

Full guide for authoring the course as an **mdBook** — a navigable, searchable
web book. Read this whenever the workspace output format is `mdbook` (see
"Output Formats" in SKILL.md), whether starting fresh or converting from
Quarto. Everything in SKILL.md about teaching (mission, node structure,
Motivate/Establish/Connect/Check, exercises with answer keys, zone of
proximal development) applies unchanged — only the authoring format and
build differ.

## When to choose mdbook

- The user wants a **navigable website/book** ("a book", "a site", "mdbook",
  "something I can browse and search") rather than per-lesson PDFs.
- The course is long / non-linear enough that a sidebar + full-text search
  beats a pile of PDFs.
- Choose once per workspace and record the choice in `NOTES` (mdbook
  workspaces: `mdbook/src/NOTES.md`). Never mix formats inside one workspace.

Quarto stays the default for print-oriented, Tufte-style lessons.

## Toolchain — exact versions, no substitutions

Installed via `cargo` (binaries land in `~/.cargo/bin`):

```bash
cargo install mdbook@0.4.52 mdbook-admonish@1.20.0 mdbook-katex@0.9.0 mdbook-mermaid@0.16.0
```

| Crate | Version | Role |
| --- | --- | --- |
| mdbook | 0.4.52 | the builder |
| mdbook-admonish | 1.20.0 | callout boxes (` ```admonish ` blocks) |
| mdbook-katex | 0.9.0 | build-time math rendering (KaTeX) |
| mdbook-mermaid | 0.16.0 | ` ```mermaid ` diagrams |

These four are **mutually compatible — upgrade all-or-nothing**. mdbook-katex
0.10 and mdbook-mermaid 0.17 require mdbook 0.5, which mdbook-admonish 1.20
rejects (its preprocessor crashes on 0.5 with a config-parse error). Do not
mix new katex/mermaid with mdbook 0.4, and do not bump mdbook to 0.5 until a
0.5-compatible admonish exists.

## Workspace layout (mdbook flavor)

Same teaching content as the Quarto flavor, inside `./mdbook/`:

- `book.toml` — build config (start from [`assets/book.toml`](./assets/book.toml))
- `src/SUMMARY.md` — the table of contents; **every chapter file must be
  listed here or mdBook will not render it**
- `src/mission.md` — the mission (MISSION.qmd equivalent)
- `src/lessons/0001-<name>.md` — lessons, numbered in teaching order
  (match the naming style already in the workspace: this collection uses
  underscore-separated `000n_slug.md`)
- `src/reference/*.md`, `src/resources.md`, `src/NOTES.md`,
  `src/learning-records/*.md` — same roles as the Quarto flavor
- `src/assets/` — figures and their regeneration scripts (same rule as
  Quarto: every figure's generation code is a first-class component)
- `book/` — build output (add to `.gitignore`)

## book.toml and plugin wiring

Start from [`assets/book.toml`](./assets/book.toml). It wires, in order:
mdbook-admonish (callouts) → mdbook-katex (math) → the **text-fix
preprocessor** (see gotchas) → and optionally mdbook-mermaid once the course
has diagrams. Two wiring rules that are easy to get wrong:

1. **Plugin installers must run from inside the book directory**
   (`cd <book-dir> && mdbook-admonish install .`). They copy CSS/JS assets
   and write `additional-css`/`additional-js` paths relative to the *current
   directory* — run from the wrong cwd they silently corrupt `book.toml`.
2. **Custom preprocessors must exit 0 on the `supports <renderer>` probe.**
   mdBook calls `<command> supports html` (with no stdin) before deciding to
   run the preprocessor; a probe failure means mdBook silently never runs it.

## Route A — create an mdBook from scratch

1. Probe and plan exactly as in SKILL.md (mission interview, dependency-map
   plan, resource acquisition) — format changes nothing there.
2. Scaffold: `mkdir -p mdbook/src/lessons mdbook/src/reference` and write
   `book.toml` from [`assets/book.toml`](./assets/book.toml) (fill in the
   title; copy the text-fix preprocessor script next to the book or point
   `command` at its absolute path).
3. Wire plugins: from inside `mdbook/`, `mdbook-admonish install .` (and
   `mdbook-mermaid install .` only once a mermaid block exists). Re-check
   `book.toml` afterwards — the installers edit it.
4. Write `src/SUMMARY.md` first (Parts + chapter list), then the mission,
   then lessons one at a time. Every new lesson: create the `.md`, **add it
   to `SUMMARY.md` in the same edit**, link it from its predecessors.
5. Style content per the table below (callouts, math, figures, …).
6. Build and verify: `mdbook build` must complete with **zero warnings**;
   check every internal link resolves (build warnings catch broken `.md`
   links); open `book/index.html` or `mdbook serve` and eyeball the changed
   page — math renders, callouts are boxed, diagrams draw.
7. Record the learning record / update `NOTES.md` as usual.

## Route B — convert an existing Quarto (qmd) course to mdBook

Convert file-by-file with the mapping below, then rebuild the surrounding
structure. The `.qmd` sources stay untouched on disk (verification record);
the mdBook becomes the living format only if the user says so.

| Quarto construct | mdBook rewrite |
| --- | --- |
| YAML front matter | strip; the `title` becomes the `SUMMARY.md` entry |
| `::: {.callout-note/tip/important}` … `:::` | ` ```admonish note/tip/warning ` fenced block (body unchanged; `important` maps to `warning`) |
| `{{< pagebreak >}}` | `<div class="pagebreak"></div>` (inert on web, honored by print backends) |
| `{{< include x.qmd >}}` | inline the converted fragment |
| ` ```{mermaid} ` + `%%\|` chunk options | ` ```mermaid ` with the `%%|` lines dropped |
| `![caption](img)` | keep — alt text still shows on hover |
| `![caption](img){width=95%}` | `<img src="…" alt="" style="width:95%;">` + the caption as an italic line below (pandoc attributes are silently dropped otherwise) |
| `](other.qmd)` links | `](other.md)` — mdBook rewrites intra-book `.md` links to `.html` |
| `mission.qmd`, `glossary.qmd`, … | `mission.md`, `glossary.md`, … in `src/` per the layout above |

Math and currency need care (KaTeX pairing differs from pandoc):

- Math stays `$…$` / `$$…$$` LaTeX — it renders via mdbook-katex unchanged.
- **Literal/currency dollars** (`$100,000`, `\$100,000`) must be neutralized
  or mdbook-katex's scanner pairs them as math across paragraphs and
  headings: rewrite to `\$` (or `&dollar;`) outside math. Inside real math,
  `\$` is kept (KaTeX renders it as a dollar sign). Pairing rules follow
  pandoc's: opener `$`+non-space, closer non-space+`$` not followed by a
  digit; an invalid closer abandons the current opener and retries. When in
  doubt, verify a tricky paragraph against
  `pandoc -f markdown -t native` (quarto bundles pandoc).
- Strip `_`/`*` hazards per the gotcha below.

After conversion: write `SUMMARY.md` (titles from the old front matter),
wire plugins, build, and run the full verification bar. Then fix content
bugs in the **book** — do not regenerate from qmd unless the user asks.

## Style: what to use for each content type

| Content | mdBook style |
| --- | --- |
| Callouts, warnings, "ask the agent" notes | ` ```admonish note ` / `tip` / `warning` blocks (body is normal markdown, math included) |
| Math | LaTeX in `$…$` / `$$…$$`; display formulas on their own line; never Typst-native syntax |
| Relational diagrams (flowcharts, dependency maps) | ` ```mermaid ` block |
| Spatial/geometric figures | SVG/PNG embed `![](…)`; generation script lives in `src/assets/` |
| Captioned figures | image (or `<img … style="width:..%">` for sizing) + the caption as an *italic line below* — alt-text-only captions are invisible in mdBook |
| Page breaks | `<div class="pagebreak"></div>` (print/PDF backends only) |
| Shared fragments | inline them, or `{{#include file.md}}` |
| Cross-references between lessons | plain relative `.md` links — there is no auto-numbering or `@ref`; name the target in prose ("lesson 0003") |
| Collapsible answers / asides | `<details><summary>…</summary>` |
| Code | fenced ` ```python `/` ```sql ` blocks (highlighting + copy button built in) |
| Exercises + answer keys | same SKILL.md rules; `## Exercises` / `## Answers` headings, feedback loop via the agent |
| Tables | pipe tables only (no grid tables, no definition lists) |
| Footnotes | supported (`[^1]`) |
| Citations | manual — no citeproc; link the resource and cite `resources.md` |

## Gotchas (all encountered in practice — do not rediscover them)

- **`\_` in math**: mdbook-katex renders `\_` as a literal `_` character in
  its HTML output; mdBook's markdown parser then pairs those underscores into
  emphasis across the span tags → "unclosed `<span>`" build warnings and
  garbled nesting. The text-fix preprocessor (in `assets/book.toml`) escapes
  `_`/`*` in KaTeX text nodes — keep it wired, and keep its `supports`
  handling intact.
- **Preprocessor ordering**: the text-fix preprocessor must declare
  `after = ["katex"]`; mdBook otherwise sorts alphabetically and runs it
  *before* katex, where it is a no-op.
- **`README.md` in `src/`**: mdBook's index preprocessor hijacks it into
  `index.html` and breaks link rewriting. Name the page anything else
  (`about.md`).
- **`SUMMARY.md` completeness**: a source file not listed in `SUMMARY.md` is
  silently not rendered. Add the chapter and the summary entry in one edit.
- **`create-missing = false`**: keep it — it turns a missing chapter into a
  build error instead of a silent gap.
- **Verification bar for every session that touched the book**: zero
  warnings, every internal link/image resolves (spot-check the built
  `book/` HTML), and the changed page renders correctly (math, callouts,
  diagrams) via `mdbook serve` or `book/index.html`.
