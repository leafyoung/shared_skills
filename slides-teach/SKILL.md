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
  skill (pedagogy, workspace layout, lessons into the book, resources,
  verification gates), the `teach-marimo` skill (companion notebooks), and the
  `mdbook-authoring` skill (book mechanics); the sibling for lecture-video
  sources is `video-teach`.
---

# Build a course workspace from slides or documents

Turn static source material — a slide deck, a report, a textbook chapter, a
workbook of spreadsheets — into a **teaching workspace**: one git repo whose
per-unit folders hold every primary source (page captures, per-page text,
speaker notes, resource snapshots, notebook, lessons), and one mdBook that
teaches the course. The workspace structure, state-doc flavor, book layout,
resource rules, and the exit gate are the **teach** skill's
course flavor with these parameters: unit folder `unitN_<slug>/`, join key the
source page number `pNNN`, authoring inputs the pages index + text layer +
speaker notes, and one unit per source document. Steps 3–6 (lessons into the
book, resources, marimo notebook, wrap) are the teach skill's (notebooks per
teach-marimo), with this course's content sources and citation rule noted
below. The pipeline per unit:

```
source file ──convert/ingest──► unit/source/ (original, committed)
  │
  ├──pdftoppm/pdftotext──► pages/pageK_<slug>_pNNN.png + pages/README.md
  │                        (page numbers are the join keys; text layer rides along)
  ├──pptx speaker notes──► notes.md   (the narration intent, when the format has it)
  │
  ▼
mdbook lessons (teach skill)              unit/notebooks/*.py (marimo,
+ unit/resources/*.qmd snapshots          per teach-marimo) + unit README
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

### Steps 3–6 — lessons, resources, notebook, wrap (teach, notebooks per teach-marimo)

Author per the teach skill with this course's parameters: authoring inputs are
`pages/README.md` (densest source), the text layer, and `notes.md`
(narration intent), joined by page number — the source tells you *what to
teach and in what order*. Lesson cadence: 2–4 lessons per substantial source
(say, per 30–40 content pages). Cite the source by page ("source p.12") with
a relative link to the kept page image and the `pages/README.md` row. The
source document itself enters `RESOURCES` marked *in-repo*, pointing at
`unitN_<slug>/source/`. Everything else - book structure, figures,
copyright posture, wrap-up and the exit gate - is the teach skill's;
companion notebooks are the teach-marimo skill's (built by default here;
skipped when the source teaches a non-Python language; the XLSX data-bundling
rule is teach-marimo's).

## Conventions

- **Page numbers as the join key** across page filenames, pages/README.md,
  notes.md, and lesson citations — cite `pNNN`, never "slide 12-ish".
- **Formulas are transcribed as text** in the index; the page image outranks
  the text layer on rendered formulas and layout; the text layer outranks the
  image on exact wording and numbers.
- **Errata in the source** get teach-skill ERRATA tags at the point of use
  (teach "Mirrors, sync, and verification").
- **New session in an existing course**: follow teach's resume order;
  Step 1–2 end state is `pages/README.md` present (and `notes.md` extracted
  for pptx, or marked "none"), the rest is the teach exit gate.
