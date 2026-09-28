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

mdbook 0.5 changed the preprocessor protocol (RenderContext format).
mdbook-katex >=0.10 and mdbook-mermaid >=0.17 were updated upstream for it
(they now build against `mdbook-preprocessor 0.5.x`) and install fine from
crates.io. **mdbook-admonish has not been updated upstream as of writing**
(crates.io still ships 1.20.0, which predates the protocol change and
crashes on mdbook 0.5 with `invalid type: null, expected any valid TOML
value`) — track https://github.com/tommilligan/mdbook-admonish/issues/233.
Until that lands, admonish must be built from the `tixena/mdbook-admonish`
fork, which already supports 0.5:

```bash
cargo install mdbook mdbook-katex mdbook-mermaid
cargo install --git https://github.com/tixena/mdbook-admonish mdbook-admonish --force
```

| Crate | Source | Role |
| --- | --- | --- |
| mdbook | crates.io, latest (0.5.x) | the builder |
| mdbook-admonish | **git fork** `tixena/mdbook-admonish` — crates.io 1.20.0 is 0.4-only | callout boxes (` ```admonish ` blocks) |
| mdbook-katex | crates.io, latest (>=0.10.0) | build-time math rendering (KaTeX) |
| mdbook-mermaid | crates.io, latest (>=0.17.0) | ` ```mermaid ` diagrams |

Verified working combo (2026-09-26): mdbook 0.5.4 + mdbook-katex 0.10.0 + mdbook-mermaid
0.17.1, with both preprocessors rebuilt against `mdbook-preprocessor` 0.5.4 (zero
warnings). mdbook 0.5 changed the **preprocessor protocol** (details in the gotchas):
stdin is `[context, book]` with `book = {"items": [...]}` (0.4 used `sections`), but the
preprocessor must output **only the book object** — echoing `[context, book]` back fails
with `invalid type: map, expected a sequence`.

**Version-skew warnings ("built against 0.5.1/0.5.3, called from 0.5.4")** mean the
plugin binary was compiled against an older `mdbook-preprocessor` than the `mdbook`
you run. Cause: `cargo install --git` (and crates.io installs) honor the repo's
committed `Cargo.lock`, which can pin an older preprocessor than the `Cargo.toml`
requirement allows. Fix — clone, refresh the lockfile, install from the clone
(confirmed zero warnings for both mdbook-katex and the tixena admonish fork,
2026-09-26):

```bash
git clone --depth 1 <repo-url> /tmp/crate && cd /tmp/crate
cargo update -p mdbook-preprocessor   # -p mdbook too, if it depends on it
cargo install --path . --force
```

The git-fork install isn't tracked by `cargo install --list` version bumps
or `cargo update` — rerun the procedure above to pick up fork commits.
Switch admonish back to the crates.io release once #233 merges upstream
(check `cargo install mdbook-admonish` picks up a version newer than
1.20.0, or that its Cargo.toml depends on `mdbook-preprocessor` — the tell
that it's a mdbook-0.5-compatible release).

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

Math and currency need care (KaTeX pairing differs from pandoc — empirically verified
against mdbook-katex 0.10 / mdbook 0.5.4, contradicting older assumptions):

- Math stays `$…$` / `$$…$$` LaTeX — it renders via mdbook-katex unchanged.
- **Literal/currency dollars** (`$100,000`, `\$100,000`) must be escaped to `\$`, and this
  is *more* urgent than it looks: mdbook-katex's scanner pairs a bare `$` opener with the
  **next bare `$` by simple alternation** — it does NOT implement pandoc's closer-validity
  rules ("follows pandoc" is what this guide used to claim, and it is wrong for 0.10). The
  closer needs neither non-space before it nor a non-digit after it (`The $45 basis … the
  $95 level` renders "45 basis … the" as math), and the scan **continues across blank lines
  and headings**, so one unescaped literal `$` garbles a cascade of real math downstream.
  A `$` left unpaired at EOF can swallow the *next* paragraph.
- **Auditing an existing course: pair with pandoc's rules, not katex's.** Quarto-era sources
  are pandoc-correct (pandoc's closer validity — non-space before, next char not a digit,
  invalid closer abandons and retries, per block — recovers from literal currency). Scan the
  document per block (pandoc math never crosses blank lines/headings), skipping fenced code,
  inline code, and `$$…$$` display regions; escape every bare `$` that is NOT part of a
  pandoc math pair. With those escaped, katex's simpler alternation pairs the remaining `$`s
  exactly as pandoc did — no cascade. Do NOT chase katex's cascade with escape-everything
  logic: that escapes real math and re-inverts parity downstream.
- **`$$…$$` display blocks need a blank line after the closing `$$`**: mdbook-katex replaces
  the block with one very long HTML line, and prose directly following is swallowed as a
  CommonMark HTML block ("unexpected HTML end tag" warnings, silently unrendered markdown).
  Insert blank lines around display-math fences when converting.
- Strip `_`/`*` hazards per the gotcha below.

Pipeline notes from a 72-lesson / 11-episode conversion (do these mechanically, they all
broke once):

- Do the per-file transforms with a **script, not by hand**: YAML strip, link rewrites,
  image-path rewrites + PNG copying, dollar audit, display-math normalization — deterministic
  and re-runnable until the build is clean. Keep the script as the conversion's provenance
  record even after the sources are deleted. Per-file judgment calls that the script can't
  make (e.g. a source typo that makes `$…$` intent ambiguous) go in a documented `REPAIRS`
  list inside the script so the whole pipeline stays reproducible.
- Link rewrite map for a chapter at `src/lessons/<ep>/<file>.md`: intra-episode
  `](NNNN-x.qmd)` → `.md`; cross-episode `](../../epY/lesson/NNNN.qmd)` →
  `](../epY/NNNN.md)`; images `](../assets/X.png)` → `](../../assets/X.png)`; links to repo
  files outside the book (episode `src/`, `tests/`, `paper/`, figure scripts) → disk paths
  (`../../../../<ep>/…`, climbing from the built page to the repo root). See gotchas for the
  `.md`-suffix rule.
- **Out-of-book `.md` targets (episode READMEs, AGENTS.md, learning records): link the
  containing directory, never the `.md` file** — mdbook rewrites every `.md`-suffixed href to
  `.html`, *including* raw-HTML `<a href>` anchors, silently breaking disk targets. A
  directory target (`../../../../<ep>/`) is never rewritten and opens fine from the
  filesystem. These disk links work when browsing `book/index.html` directly but 404 under
  `mdbook serve` (which only serves `book/`) — state the intended reading mode.
- **Verify image basenames are unique across all source episodes before copying them into a
  shared `src/assets/`** (lesson numbers collide across episodes; here the `lessonNNNN-`
  prefix made them globally unique — check, don't assume). Record the regeneration flow:
  scripts stay per-episode, the book embeds copies, re-copy after regenerating.
- **Cross-episode links go stale when a target episode renames its lessons** (slugs change,
  numbers usually don't). Check every cross-episode link target *exists*; on a miss, fall
  back to the same-numbered lesson in the target episode and log the repair.
- **Order `SUMMARY.md` parts numerically, not lexically** — plain string sort puts Episode
  10 and 11 between 1 and 2.
- Links to gitignored fetch-time artifacts (e.g. `paper/*.pdf` restored by the episode's
  `download.py`) are legitimate; whitelist them in the link checker rather than deleting the
  links.

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
  garbled nesting. The text-fix preprocessor (in `assets/book.toml`, script at
  `assets/scripts/katex_text_fix.py`) escapes `_`/`*` in KaTeX text nodes —
  keep it wired, and keep its `supports` handling intact. It only ever fires
  on raw `_`/`*` at token edges inside KaTeX's output; ordinary subscripts
  (`x_1`) never emit raw underscores.
- **Preprocessor ordering**: the text-fix preprocessor must declare
  `after = ["katex"]`; mdBook otherwise sorts alphabetically and runs it
  *before* katex, where it is a no-op.
- **Preprocessor protocol (mdbook 0.5)**: stdin is the 2-element JSON
  `[context, book]` with `book = {"items": [...]}` (0.4 used `sections`);
  stdout must be **only the book object**. Echoing the input array back fails
  with `invalid type: map, expected a sequence` — mdbook deserializes the
  output directly as the Book struct. A custom preprocessor must also exit 0
  on the `supports <renderer>` probe (stdin is absent then) or mdbook
  silently never runs it.
- **An infinite loop lurks in span-scanning preprocessors**: KaTeX chunks can
  contain non-`<span>` tags (e.g. MathML `<math>…</math>`). Depth-scanning
  from `<` to the next `<` makes zero progress on a non-span tag whose `<` is
  at the scan position — always advance past a non-matching `<` explicitly.
- **`$$…$$` display blocks need a blank line after them**: the preprocessed
  KaTeX HTML is one long line; prose immediately following is swallowed as a
  CommonMark HTML block ("unexpected HTML end tag" warnings). Keep a blank
  line on both sides of every display-math fence.
- **Never leave a `.md` suffix in any href — including raw-HTML anchors**:
  mdbook rewrites every `.md`-suffixed link target to `.html` and adjusts its
  path, silently, even for targets that don't exist inside the book. Links to
  repo files outside the book (source code, READMEs, PDFs) must therefore end
  in something else — a non-md extension (`.py`, `.pdf` pass through) or a
  directory target.
- **Out-of-book disk links don't resolve under `mdbook serve`**: the serve
  process only serves `book/`. `file://` browsing of `book/index.html`
  resolves them fine — state the intended reading mode when such links exist.
- **`README.md` in `src/`**: mdBook's index preprocessor hijacks it into
  `index.html` and breaks link rewriting. Name the page anything else
  (`about.md`).
- **`SUMMARY.md` completeness**: a source file not listed in `SUMMARY.md` is
  silently not rendered. Add the chapter and the summary entry in one edit.
  Sort part/chapter ordering numerically when names embed numbers — a lexical
  sort puts item 10 and 11 between 1 and 2.
- **`create-missing = false`**: keep it — it turns a missing chapter into a
  build error instead of a silent gap.
- **Offline math (no CDN)**: mdbook-katex injects a CDN `<link>` to
  `katex.min.css` by default. To self-host: download `katex.min.css` + its
  `fonts/` (jsdelivr), put the css at `src/katex.min.css` and the fonts at
  `src/fonts/`, set `[preprocessor.katex] no-css = true`, and wire
  `additional-css = ["src/katex.min.css"]`. mdbook emits a second,
  depth-adjusted hashed copy of the css under `book/src/` that pages actually
  reference — its relative `fonts/` refs resolve to `book/src/fonts/`, so
  mirror the fonts at `src/src/fonts/` too. Verify a font actually loads
  (screenshot a math-heavy page with the network disconnected) before
  trusting the wiring.
- **Verification bar for every session that touched the book**: zero
  warnings, every internal link/image resolves (spot-check the built
  `book/` HTML), and the changed page renders correctly (math, callouts,
  diagrams) via `mdbook serve` or `book/index.html`. A tiny `check_links.py`
  (walk every built `.html`, resolve each `href`/`src` against the book tree
  or the repo on disk, whitelist fetch-time artifacts) makes the link half
  mechanical; render the riskiest pages to PNG (headless chromium
  `--headless --screenshot`) and eyeball math/dollars/figures before calling
  a conversion or content change done.
