---
name: slides-teach
description: >-
  Build a full study course from static source material — slide decks (PDF,
  PPTX), documents (DOCX, PDF), or spreadsheets (XLSX) — laid out as one
  workspace: one git repo, one `uv` project, one folder per course unit
  (`unitN_<slug>/`) holding the original source, extracted page captures with
  an authoritative pages/README.md index (plus extracted speaker notes when
  the format has them), resource snapshots, marimo notebooks, and teach-skill
  lessons authored into an mdBook at the repo root. Use when the user asks to
  "build a course from these slides", "turn this deck/document into lessons",
  "make a course from this PDF/textbook chapter", or otherwise wants the
  slides→index→lessons→resources→notebooks pipeline over static files — no
  audio/video, hence no download or transcription step. Pairs with the `teach`
  skill (teaching rules; mdBook mechanics live in the `mdbook-authoring`
  skill); the video-course sibling for
  lecture-video sources is `video-teach`.
---

# Build a course workspace from slides or documents

Turn static source material — a slide deck, a report, a textbook chapter, a
workbook of spreadsheets — into a **teaching workspace**: one git repo whose
per-unit folders hold every primary source (page captures, per-page text,
speaker notes, resource snapshots, notebook, lessons), and one mdBook that
teaches the course. The pipeline per unit:

```
source file ──convert/ingest──► unit/source/ (original, committed)
  │
  ├──pdftoppm/pdftotext──► pages/pageK_<slug>_pNNN.png + pages/README.md
  │                        (page numbers are the join keys; text layer rides along)
  ├──pptx speaker notes──► notes.md   (the narration intent, when the format has it)
  │
  ▼
mdbook lessons (teach skill)            unit/notebooks/*.py (marimo)
+ unit/resources/*.qmd snapshots        + unit README + learning records
```

The document itself is **ground truth**: never teach from parametric memory
when the source says otherwise. Web-search only for things the source implies
but doesn't state (citations, cited papers, published course materials). If
the source has gaps — a deck that sketches what the lecture would have spoken
— say so in the unit README and teach only what the source supports.

**The text layer (and speaker notes) are first-class inputs to everything
downstream** — not a byproduct of extraction. Lessons take their structure,
derivations, and emphasis from the document's own order and its notes; the
page text carries the precise wording of formulas and claims; notebooks
implement what the document works through; the pages index captures what each
page shows. Author from the text outward: read it end-to-end for the
argument's shape before writing anything, then reconcile against the page
images where they disagree — the image outranks the text layer on layout,
figures, and rendered formulas; the text layer outranks the image on exact
wording and numbers (OCR/selection is exact; visual reading is not).

## Workspace layout (create once per course)

```
<course>/
├── AGENTS.md              # how to work here: layout + conventions (adapt on init)
├── MISSION.qmd            # teach-skill mission (root, canonical)
├── RESOURCES.qmd          # acquisition ledger (root, canonical; snapshots per-unit)
├── NOTES.qmd              # scratchpad (root, canonical)
├── pyproject.toml         # ONE uv project for the whole course (marimo — pin the
│                          #   version, pillow, pytest, ruff, python-pptx/pandas as needed)
├── .python-version        # 3.12 unless the course needs otherwise
├── .gitignore             # mdbook/book/, output/, __pycache__, caches
├── mdbook/                # the course book (teach-skill mdBook flavor)
│   ├── book.toml          #   scaffold per the mdbook-authoring skill's Route A
│   │                      #   (admonish+katex+text-fix)
│   ├── src/SUMMARY.md     #   one Part per unit; every file listed or it won't render
│   ├── src/about.md       #   course overview + progress table (the resume anchor;
│   │                      #   NOT mission.md — root MISSION.qmd is canonical)
│   ├── src/unitN-<slug>/  #   unit overview chapter + lessons/*.md for that unit
│   ├── src/reference/     #   cross-unit cheat sheets (glossary.md first)
│   └── src/assets/unitN/  #   copies of figures embedded in lessons (source in unitN/assets/)
└── unitN_<slug>/          # one folder per source document — everything else is per-unit
    ├── README.md          # source provenance, page count, topic map, what's built, gaps
    ├── source/            # the original file(s), committed (gitignore + note in NOTES
    │                      #   only if a file is genuinely huge, say >20 MB)
    ├── pages/pageK_<slug>_pNNN.png + README.md   # the authoritative page index
    ├── notes.md           # speaker notes extracted from pptx (empty if none)
    ├── notebooks/<slug>.py # marimo notebook(s)
    ├── resources/         # downloaded PDFs; web snapshots as resources/web/*.qmd
    ├── assets/            # lesson figure generation scripts + rendered images
    ├── output/            # marimo export artifacts (gitignored)
    └── learning-records/  # per-unit ZPD findings, per teach skill
```

**Canonical vs book.** MISSION/RESOURCES/NOTES stay `.qmd` at the root — the
same sanctioned **video-course flavor** of teach's state-doc rule (root `.qmd`
state docs kept as editor-readable ledgers, deliberately never rendered; see
teach "Output Formats"). The book's `about.md` is the in-book summary, not a
duplicate. Reference docs live in the book (it's the living format). Record
the flavor choice in `NOTES`. Every mdBook rule — toolchain pinning, plugin
wiring, SUMMARY completeness, zero-warning build bar, style table — is in the
**mdbook-authoring** skill (`~/.agents/skills/mdbook-authoring/`, shared by
teach/video-teach/slides-teach); follow it, starting from its bundled
`assets/book.toml`.

**Python code.** One root `pyproject.toml`, no per-unit files; add a
dependency once at the root when any unit needs it. Notebooks are **marimo,
never Jupyter** (user preference; also a teach-skill rule). Add a root
`.vscode/settings.json` so every `unitN_<slug>/notebooks/*.py` opens as a
marimo notebook while `assets/*.py` figure scripts and any `src/` package
keep the default Python editor (ipynb-to-marimo skill's
`workbench.editorAssociations` pattern — add an explicit `"default"`
override for any non-notebook `.py` that would otherwise fall inside the
notebook glob):

```json
{
  "workbench.editorAssociations": {
    "**/unit*_*/notebooks/*.py": "marimo-notebook"
  }
}
```

## Unit pipeline

Work units in course order. Steps 1–2 are mechanical and can run while you
author an earlier unit's lessons; authoring (Steps 3–5) is where the care
goes.

**Step 0 — teach first-session flow (new course only).** Run teach's
mandatory first-session steps before authoring: mission interview, format
confirmation (mdbook here), research + dependency-map plan, then stop and
wait for the user's go-ahead. Steps 1–2 may run while that interview and
planning happen; no lesson authoring before the go-ahead.

### Step 1 — Ingest the source

One source document per unit (`unitN_<slug>/source/`), named
`<slug>.<ext>`. Fetch remote sources with `curl -L -o`; ask the user for
files not on the web. Normalize for extraction:

```bash
# PPTX → PDF (LibreOffice; needed for page images — python-pptx alone can't render)
soffice --headless --convert-to pdf --outdir unit<N>_<slug>/source unit<N>_<slug>/source/<slug>.pptx
```

XLSX stays as-is (it is inspected, not rendered — Step 2). Keep the original
alongside the normalized copy. If a file is genuinely huge (>20 MB), gitignore
it, record its path in `NOTES`, and say so in the unit README.

### Step 2 — Extract, review, and index pages

Run the skill's extractor, then review and index:

```bash
cd unit<N>_<slug> && python3 ~/.agents/skills/slides-teach/scripts/extract_pages.py source/<slug>.pdf [--dpi 150]
```

It writes `pages_raw/p-NNN.png` (one full-res render per page), a per-page
text layer under `pages_raw/text/`, a `pages_raw/contact_sheet.jpg` for fast
review, and `pages_raw/index.tsv` (page number, image, title guess, text
volume — blank/boilerplate pages stand out). Then:

1. **Review the contact sheet** with the Read tool. Drop non-content pages:
   covers, repeated logos/footers, section dividers (fold their headings into
   the index prose instead), near-empty scans.
2. Move keepers to `unit<N>_<slug>/pages/`, renamed
   `pageK_<slug>_pNNN.png` (K = 1..count in reading order; `pNNN` = the
   source page number, zero-padded).
3. **PPTX speaker notes** (the narration intent): extract them per slide into
   `notes.md` with python-pptx (`slide.notes_slide.notes_text_frame.text`),
   one `## Slide K (pNNN)` section each. Empty file if the deck has none.
4. Write `pages/README.md` — the **authoritative index**: source file +
   provenance, page count, then one table row per kept page: file, on-page
   title, a dense summary of every formula, claim, figure, and number on the
   page (formulas as text, e.g. `M_t(n) = P_t − MA_t(n)`), verified against
   the image, not skimmed. Note cross-references ("continues the table from
   p7") in the header prose.
5. Delete `pages_raw/` once indexed. Keep the per-page text you actually used
   by pasting key passages into `pages/README.md` rows or `notes.md`.

For **XLSX sources**: skip page extraction. Dump each sheet's shape, header
row, dtypes, and a representative sample into `pages/README.md` (as an
inventory, same authoritativeness), and note derived fields worth teaching.

### Step 3 — Lessons (teach skill, mdBook flavor)

Author per the `teach` skill with output format **mdbook** — its teaching
rules (mission grounding, Motivate/Establish/Connect/Check per node,
unconditional truths first, exercises with answer keys, citations, ZPD) all
apply unchanged.

- Course content comes from `pages/README.md` (densest source), the text
  layer, and `notes.md` (narration intent), joined by page number. The source
  tells you *what to teach and in what order*; the teach rules tell you *how*.
- 2–4 lessons per substantial source (say, per 30–40 content pages), each
  tightly-scoped, self-contained, with a single tangible win and its
  `## Exercises`/`## Answers` sections. A lesson with unanswered exercises
  must not ship.
- Book structure: one Part per unit in `SUMMARY.md`; each Part opens with a
  unit overview chapter (what the source covers, link to the original,
  links to its notebook and resources) followed by the lessons. Add each
  chapter to `SUMMARY.md` in the same edit that creates it.
- Cite the source: by page ("source p.12") with a relative link to the kept
  page image in `mdbook/src/assets/unitN/`, and to the unit's `pages/README.md`
  row. Figures are regenerable — generation script in
  `unitN_<slug>/assets/lessonNNNN-<topic>.py`, rendered image beside it,
  **copy** the image into `mdbook/src/assets/unitN/` for embedding (re-copy
  after regenerating).
- Source page images may be embedded in lessons where the page IS the content
  (a key formula, a result table): copy into `mdbook/src/assets/unitN/`
  likewise, and keep a conservative copyright posture — brief excerpts for
  personal study are fine, wholesale re-publication is not.
- Build bar: `mdbook build` with zero warnings; math via KaTeX, callouts via
  admonish, per the mdbook-authoring skill's style table and gotchas (escape
  literal `$`, wire the text-fix preprocessor, no `README.md` in src/).

### Step 4 — Resources (download on the spot, as qmd)

`RESOURCES.qmd` at the root is the ledger; per the teach skill, **every entry
is acquired the moment it's added**, and in this workspace acquisition means:

- Papers / references / cited works → PDF verbatim into `unitN_<slug>/resources/`.
- Web pages (project sites, docs, course pages) → snapshot to
  `unitN_<slug>/resources/web/<slug>.qmd`: YAML `title`, a provenance
  blockquote (source URL, fetch date, license note), then the content as
  markdown.
- The source document itself → entry marked *in-repo* pointing at
  `unitN_<slug>/source/`.
- Find the official materials first (the deck's own course page, the paper's
  landing page, the workbook's companion site); they beat any third-party
  summary. Cite them from the unit's lessons.

Before finishing any session: every `RESOURCES.qmd` entry has a local path or
an explicit streaming-only/paywalled note.

### Step 5 — Marimo notebook

Each unit gets `unitN_<slug>/notebooks/<slug>.py` — an interactive companion
that runs the source's central artifact: the algorithm it teaches, the worked
example, the visualization of the phenomenon, the spreadsheet model made
live. Conventions:

- marimo app with `app_title`, `hide_code` markdown cells explaining each
  section, LaTeX via `$...$`/`$$...$$` in `mo.md`, interactive controls
  (`mo.ui.slider`, `mo.ui.text`) wherever a parameter is pedagogically
  interesting.
- Self-contained: synthetic data or tiny bundled samples by default; for XLSX
  sources, bundle the real sheet as a small CSV in `unitN_<slug>/data/` when
  it is small enough to commit, else generate a faithful synthetic stand-in
  and say so.
- **Verify by execution**: `uv run python
  ~/.agents/skills/slides-teach/scripts/run_marimo_notebook.py
  unitN_<slug>/notebooks/<slug>.py` — it imports the module, runs every cell
  via `app.run(defs={"mo": marimo})`, and detects a raised cell by diffing
  the notebook's statically declared cell outputs against the definitions the
  run actually produced (headless marimo swallows plain cell exceptions —
  verified on 0.25.0). Any failure exits nonzero. (Plain `marimo export html`
  is NOT a verifier here: it exits 0 on broken cells AND wrongly exits 1 on
  correct mo-using notebooks.) Reference the notebook from the unit overview
  chapter and the relevant lessons (repo-relative path in prose).

### Step 6 — Wrap the unit

1. `unitN_<slug>/README.md`: source provenance (origin, date, version), the
   page index summary, what was built (lessons, notebook, resources), open
   gaps (sketched-but-unexplained content, typos found in the source).
2. Learning records when the session surfaced something non-obvious (a ZPD
   finding, an extraction convention decision, an erratum in the source).
3. Update root `RESOURCES.qmd` / `NOTES.qmd`; bump the unit's row in the
   book's `about.md` progress table (keep this table — it is the resume
   anchor).
4. Commit at unit boundaries (`unit3: pages indexed, 2 lessons, notebook`); on
   a long unit, commit at pipeline-step boundaries too (`unit3: pages indexed`)
   — never leave hours of extraction/indexing work uncommitted.

## Conventions

- **Page numbers as the join key** across page filenames, pages/README.md,
  notes.md, and lesson citations — cite `pNNN`, never "slide 12-ish".
- **Formulas are transcribed as text** in the index; the page image outranks
  the text layer on rendered formulas and layout; the text layer outranks the
  image on exact wording and numbers.
- **Honest gaps**: if a notebook can't reproduce a claimed number (library
  drift, missing data), say so in the unit README with what was checked —
  never tune until it matches. Errata in the source get teach-skill ERRATA
  tags at the point of use, preserving the caveat "flagged, not yet confirmed
  with the source's owner".
- **Per-unit placement is not negotiable**: only AGENTS.md, MISSION/RESOURCES/
  NOTES, pyproject.toml, .python-version, .gitignore, and mdbook/ are
  root-level; everything else lives in `unitN_<slug>/`.
- **New session in an existing course**: read AGENTS.md → NOTES.qmd → the
  book's `about.md` progress table → `git log --oneline` + `git status` → the
  current unit's README.md, then resume the pipeline at its first incomplete
  step (the checklist below defines each step's end state: `source/` present
  = Step 1 done, `pages/README.md` present = Step 2 done, …).
- Skill-scripts and extractors are regenerable; never commit `.venv`, caches,
  build output.

## Verification checklist (per unit, before commit)

- [ ] source: original (and normalized PDF, if converted) in `unitN_<slug>/source/`
- [ ] pages: content pages kept as `pageK_<slug>_pNNN.png`; `pages/README.md`
      table covers every kept page with formulas verified against images; `pages_raw/` deleted
- [ ] notes.md extracted for pptx sources (or marked "none")
- [ ] book: new chapters in `SUMMARY.md`; `mdbook build` zero warnings; exercises all answered
- [ ] notebook: `run_marimo_notebook.py` exits 0 — the execution bar; headless
      `marimo export html` can silently skip `mo` injection AND exits 0 on
      broken cells (an HTML export into `output/` is optional); linked from the
      unit's book chapters
- [ ] resources: every RESOURCES.qmd entry added this session has a local path or
      streaming-only note
- [ ] unit README current; git commit(s) for the unit
