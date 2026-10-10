---
name: video-teach
description: >-
  Build a full study course from a list of YouTube lecture videos, laid out as
  one workspace: one git repo, one `uv` project, one folder per
  episode (`epN_<slug>/`) holding the downloaded-and-cleaned transcript, extracted
  slide captures with an authoritative slides/README.md index, qmd resource
  snapshots, marimo notebooks, and teach-skill lessons authored into an mdBook at
  the repo root. Use when the user asks to "build a course from these videos",
  "turn these lectures into lessons/episodes", "set up a course workspace for a
  YouTube playlist", or otherwise wants the video→transcript→slides→lessons→
  notebooks pipeline over one or more lecture URLs. Pairs with the `teach` skill
  (pedagogy, workspace layout, lessons into the book, resources, verification
  gates), the `teach-marimo` skill (companion notebooks), the `mdbook-authoring`
  skill (book mechanics), and the `transcribe-video` skill (transcription).
---

# Build a video course workspace

**Definitive pipeline** (one episode; the steps below are the full contract):

1. **Step 1** — `transcribe-video` (URL or local media in) →
   `transcript/<slug>.raw.vtt` (timing kept) + canonical `<slug>.clean.md`
   (overrides: no `.clean.zh.md`, glossary handed over, intermediates kept).
2. **Step 2** — slide extraction + OCR → `slides/slideK_<slug>_<MmSSs>.png`,
   `slides/README.md`, `slides/slides_ocr.json`.
3. **Step 3** — transcript foundation → `<slug>.verbal.md`, term-corrected
   `.clean.md` (slide refs + index), tagged `.clean.srt`,
   `correction_brief.md`/`corrections.json`.
4. **Steps 4–7** — lessons (mdBook) → resources → marimo notebook → wrap:
   per the **teach** skill, with this course's parameters (below).

Turn a list of YouTube lecture videos into a **teaching workspace**: one git repo
whose per-episode folders hold every primary source (transcript, slide captures,
resource snapshots, notebook, lessons), and one mdBook that teaches the course.
The workspace structure, state-doc flavor, book layout, resource rules, and the
exit gate are the **teach** skill's course flavor with
these parameters: unit folder `epN_<slug>/`, join key `MmSSs` timestamps on the
raw video timeline, authoring inputs the slides index + corrected transcript,
root extras `MEDIA.md` (pointer to the gitignored video cache) and the kept
transcript intermediates. Companion notebooks follow the **teach-marimo**
skill's when-to-build rule (built by default for these courses; skipped when
the lecture series teaches a non-Python language). The pipeline per episode:

```
video/URL ──transcribe-video──► transcript/<slug>.raw.vtt + .clean.md   (Step 1;
  │                             intermediates kept: video/audio + .transcript.* + .srt)
  └──ffmpeg frames──► slides/slideK_*.png + slides_ocr.json             (Step 2;
                                       │            timestamps join keys)
                     ┌─────────────────┴──────────────────┐
                     ▼                                    ▼
  transcript_layers: .verbal.md + slide-tagged .clean.srt + corrected .clean.md
                     (Step 3)
                                       │
                     ┌─────────────────┴──────────────────┐
                     ▼                                    ▼
        mdbook lessons (teach skill)             epN/notebooks/*.py (marimo,
        + epN/resources/*.qmd snapshots          per teach-marimo) + episode README
```

The video content itself is **ground truth**: never teach from parametric memory
when a transcript or slide says otherwise. Web-search only for things the video
implies but doesn't state (links, paper citations, published course materials).

**The transcript is the narration layer here** - a first-class input per
teach's authoritative-index contract, not a byproduct of Step 2: the
lecturer's ordering, motivation, and emphasis are the course's pedagogy.
Author from the transcript outward (teach's rule: end-to-end read before
writing). This flavor's precedence tail: the image outranks the spoken word on
formulas and numbers (ASR garbles exactly those), the transcript outranks the
slide on reasoning and motivation.

## Episode pipeline

**Step 0 — teach first-session flow (new course only).** Run teach's mandatory
first-session steps before authoring: mission interview, format confirmation
(mdbook here), research + dependency-map plan, then stop and wait for the
user's go-ahead. Steps 1–3 below are mechanical (transcribe / slides + OCR / transcript layers)
and may run while that interview and planning happen; no lesson authoring
before the go-ahead.

Work episodes in watch order. The pipeline splits into two phases with a handover
gate between them: **Phase A — data** (Steps 1–3, plus the official deck PDF, which
is ground truth for the index) collects everything the lessons will cite; **Phase B —
lessons** (Steps 4–7, per teach) authors from it. Phase A for one episode may
run while an earlier episode is in Phase B, but an episode does not enter Phase B
until its Phase A exit checklist (end of this file) passes — it is the handover
contract between the two phases. The reason the gate is strict: lessons cite the slide index
and the corrected transcript as ground truth, so a mislabeled capture, a missed
slide, or a garbled name that reaches Phase B propagates into prose, exercises, and
figures silently — no build warning will ever catch it.

### Step 1 — Transcribe (via the `transcribe-video` skill)

One step covers download + transcription: invoke the transcribe-video skill and
follow it exactly, passing the **YouTube URL** or a **local video/audio file**.
For YouTube URLs pass `--best-video` — the tool's default is an audio-only
download, and Step 2 needs the video file for slide extraction (with
`--best-video` the binary also downloads a separate audio track and
transcribes from that, so transcription quality is unchanged). Course-specific
points:

- **The video intermediary is kept** (standing override: callers skip the
  skill's move-and-cleanup) — Step 2 needs the same video file for slide
  extraction, and a shared file guarantees slide timestamps align with
  transcript timestamps. Move it into the media cache (`$MEDIA_DIR`, recorded
  in `MEDIA.md`) if the skill left it elsewhere.
- Standing overrides: **no `.clean.zh.md`**; hand over any known proper-noun
  list (course-level terms from prior episodes). A raw `.vtt`/`.srt` from an
  earlier pass may be supplied instead (the skill's Step 1b mode, skipping
  Groq). The slide-OCR-grounded term pass runs in Step 3, after Step 2's OCR
  exists.
- **Leave the timing file as `transcript/<slug>.raw.vtt`**: copy (not move)
  the skill's `<name>.transcript.srt` — or the caller-supplied
  `.vtt`/`.srt` — to that name. Step 3's commands read exactly this file.
- **Retrofit (episode has no raw timing file** — courses that predate the
  pipeline): rebuild it from YouTube's auto-captions, subtitle-only. A
  fallback layer, a notch below Groq (punctuation-less, coarser stamps): fine
  for the verbal layer + correction cues, but don't expect cue-level alignment
  against a clean.md made from a different transcription. Recipe + caveats:
  `references/transcript-foundation.md` § "Retrofit"; in brief —

  ```bash
  yt-dlp --skip-download --write-auto-subs --sub-langs en --sub-format vtt \
        -o transcript/<slug>.raw https://www.youtube.com/watch?v=<id>
  python3 ~/.agents/skills/video-teach/scripts/fetch_raw_captions.py \
         transcript/<slug>.raw.en.vtt --out transcript/<slug>.raw.vtt
  ```

  The caption endpoint 429s after a burst (~8–10 rapid fetches) — when batching
  episodes, retry the failures minutes apart, not immediately.
- Pass `--language-code en` (or the actual language) and
  `--output-dir <episode>/transcript --output-name <slug>` so outputs land with
  the right names on the first pass. On `HTTP 403`/`HTTP 500` (SABR/client
  problem): retry with `--extractor-args "youtube:player_client=visionos"`.
- **Native-caption skip defeats `--best-video`:** if the tool logs
  "Native-language subtitles available — transcription skipped", it used YouTube's
  auto-captions and never ran Whisper, even with `--best-video` (seen 2026-10 on a
  3h freeCodeCamp lecture). For course-grade quality: extract the audio from the
  downloaded video (`ffmpeg -i video -vn -c:a copy out.audio.webm`) and transcribe
  the local file with the same `--output-name`/`--output-dir` — the Whisper pass is
  the raw layer a course wants.
- `--best-video` downloads may be `.webm` **without stream duration metadata**
  (live-stream recordings): `extract_slides.py` fails on `ffprobe duration=N/A`.
  Remux first: `ffmpeg -i in.webm -c copy out.mp4`, keep the mp4 in the media
  cache, and record the remux in `MEDIA.md`.
- Fetch `%(title)s`/`%(channel)s`/`%(duration_string)s` first to pick the
  episode `<slug>` (lowercase, descriptive, one separator style per course).
- **Timestamps are the join key** for everything downstream — slide files, the
  slides index, and lesson citations all reference `MmSSs` positions on the raw
  video timeline. Everything stays aligned to it.

### Step 2 — Extract slides and OCR them

Run the skill's extractor on the video from Step 1, then review and index:

```bash
cd ep<N>_<slug> && python3 ~/.agents/skills/video-teach/scripts/extract_slides.py "$VIDEO" \
  [--scene-threshold 0.25] [--sample-interval 20]
```

It writes `slides_raw/chosen/sNN_<MmSSs>.png` (one full-res frame per distinct
slide window, captured late in the window), a
`slides_raw/contact_sheet.jpg` for fast review, and `slides_raw/candidates.tsv`. Then:

1. **Review every candidate** with the Read tool (contact sheet first, then
   full-res frames). Drop non-slides: webcam cutaways, terminal demos, transition
   blurs. Lower `--scene-threshold` and re-run if slide changes were missed;
   extract a missed frame manually with `ffmpeg -ss <t> -i video -frames:v 1`.
2. Move keepers to `ep<N>_<slug>/slides/`, renamed `slideK_<slug>_<MmSSs>.png`
   (K = 1..count in first-appearance order; `MmSSs` = the capture timestamp).
3. Write `slides/README.md` — the **authoritative index**, per teach's
   authoritative-index contract (one row per slide: file, on-screen title,
   dense summary, formulas as text, verified against the image), plus this
   flavor's header (source video URL/title, slide count) and per-row transcript
   section (timestamp range). Note slide callbacks (presenter flips back to an
   earlier slide) in the header prose, not as new slides.
   The transcript-section column is **narration-aligned, not screen-window-aligned**:
   speakers routinely discuss a slide's content minutes before advancing to it (and
   this deck-lag is often heavier in the back half of a talk), so a section range
   legitimately starts before its slide's on-screen window. Verify each row's range
   against the transcript's narration transitions (verbal-layer stamps / SRT), not
   by mechanically matching OCR windows.
4. **OCR the kept slides** — `python3 ~/.agents/skills/video-teach/scripts/slide_ocr.py
   slides/ --duration <video-seconds>` writes `slides/slides_ocr.json` (+ `.md`
   index): per slide, its OCR text and on-screen time window. This is the ground
   truth consumed by Step 3's correction pass. The script also flags
   **possible duplicate captures** (consecutive slides with near-identical OCR):
   the deck advanced mid-window, so the earlier of the pair is likely the *next*
   slide and one in between was missed — never ignore that warning (seen in
   practice: a capture named for slide 3 that showed slide 4).
5. Delete `slides_raw/` once indexed.

Expect roughly one slide per 2–6 lecture minutes; wildly more candidates means the
threshold is too low or the lecture is whiteboard-style (then capture *boards*
state-by-state, same naming).

**Slide re-index — run whenever review contradicts the index.** The recurring defect
class (seen on 5 of 9 episodes of one real course): scene detection labels a capture
with the wrong slide (off-by-one across near-identical builds), misses a slide
entirely, keeps a zero-length duplicate, or numbers captures out of
first-appearance order. The index and the transcript inherit whatever is wrong, so
fix the set before anything downstream consumes it:

1. Cross-check **every** filename against its image or `slides_ocr.json` text —
   not just counts. Titles and deck-page footers in the OCR settle most cases;
   Read suspicious PNGs for the rest.
2. Recover missed slides with `ffmpeg -ss <t> -i video -frames:v 1`, probing late
   in the on-screen window (decks build bullets progressively — capture fully
   built states). Rename mislabeled files to match their content, drop true
   duplicates (keep the later / fully built capture), and renumber K into
   first-appearance order.
3. Re-run `slide_ocr.py` — its keys are filenames, so it is stale after any
   rename. Fix the affected `slides/README.md` rows (and header note), then
   regenerate downstream: strip the transcript's old `## Slide index` and re-run
   `--fix-clean --assemble`; re-run `--clean-srt` (its tags are time-based, so
   pure renames usually leave them valid). Note the fix in the episode README.

### Step 3 — Two-layer transcript with slide-assisted correction
With `slides/slides_ocr.json` from Step 2, run the transcript-foundation
pipeline (`scripts/transcript_layers.py`) against
`transcript/<slug>.raw.vtt`: derive the verbatim `<slug>.verbal.md`, correct
the canonical `.clean.md` against slide OCR via a correction brief →
`corrections.json` → `--fix-clean --assemble` (term fixes in place, slide
index appended), and tag the `.clean.srt` with `[Slide K]`. Because these
courses are technical, the slides' OCR is the ground truth for exactly the
words ASR garbles — named methods, library calls, linearized formulas,
numbers.

Full commands, artifact definitions, and the precedence rules:
`references/transcript-foundation.md`. Outputs the Phase A gate expects:
`transcript/<slug>.verbal.md`, the corrected `transcript/<slug>.clean.md`
(slide index appended), the slide-tagged `transcript/<slug>.clean.srt`, and
`correction_brief.md`/`corrections.json` for provenance.

The correction pass may consult **other episodes' slide OCR** — proper nouns recur
across a course (TA rosters, benchmark names, model names, paper names), and a term
this episode's slides never spell out may be attested on an earlier or later
episode's deck. Cite the attesting slide in `corrections.json`'s notes; leave
anything still unattested as `[as heard]` rather than guessing. A
verification-only pass (empty `replacements`) is a legitimate outcome — record
what was checked and why in `notes`, because that field is the handover narrative
Phase B reads first.

Two retrofit notes (full detail: `references/transcript-foundation.md`):
when the raw layer is rebuilt from YouTube auto-captions while `.clean.md`
predates it from a better ASR, the brief's cues are **context, not alignment** —
correct at the term level against slide OCR, never cue-by-cue. And if the course
keeps a `.clean.zh.md` translation mirror: apply `corrections.json` to it too
(only replacements that literally match will land — hand-mirror the rest of the
fixed sentences), and append the translated slide index via
`--fix-clean <slug>.clean.zh.md --assemble --zh-index <translated-index.md>`
(bullets under `## 幻灯片索引`).

### Steps 4–7 — lessons, resources, notebook, wrap (teach, notebooks per teach-marimo)

Author per the teach skill with this course's parameters: authoring inputs are
`slides/README.md` (densest source) and the corrected `transcript/*.clean.md`
(narrated derivations, joined by timestamp) — the lecture tells you *what to
teach and in what order*. Lesson cadence: 2–4 lessons per lecture hour. The
lecture's own deck PDF is a Phase A artifact (it verifies the slide index), so
it is pulled into `resources/` before the A-exit gate even though resources
formally belong to Step 5. Cite the lecture by video timestamp + transcript
section. Everything else - book structure, figures, copyright posture,
wrap-up and the exit gate - is the teach skill's; companion notebooks are the
teach-marimo skill's (built by default here; skipped for non-Python-language
lecture series).
Lesson language: the course's language; per-language mirror books only when
the user explicitly requests a translated course.

**Episode metadata is authoritative per episode**: video URLs, titles, and
durations come from that episode's `slides/README.md` (or a live `yt-dlp
--print`), never from chat context or another episode's README — cross-episode
URL scrambles are easy to make and are caught only downstream.

## Conventions

- **Timestamps as the join key** across slide filenames, slides/README.md, SRT, and
  lesson citations — never assume section headers line up 1:1 with slides.
- **Formulas are transcribed as text** in transcripts and the slides index
  (teach's authoritative-index rule); this flavor's precedence tail: the slide
  image outranks the spoken formula when they disagree.
- **New session in an existing course**: follow teach's resume order;
  Step 1–3 end states are defined by the Phase A gate below, Steps 4–7 by the
  teach exit gate.

## Verification checklists — the Phase A → B handover gate

**Phase A exit — the data handover.** Every item is checkable; do not enter Phase B
on failures. Presence checks alone are not enough: the gate's core is the
cross-artifact consistency pass (index ↔ images ↔ OCR ↔ transcript), which is what
catches mislabeled captures and garbled names that presence checks never will.

- [ ] transcript inputs present: `<slug>.raw.vtt` (or caller-supplied timing file),
      `.verbal.md`, `.clean.md`; the verbal layer reads as non-duplicated prose —
      spot-read its opening lines (a rolling YouTube auto-caption fed in raw doubles
      every phrase; `parse_timing` auto-dedups with a stderr notice, and
      `fetch_raw_captions.py` normalizes at the source)
- [ ] slide set sane: count vs lecture length (~1 slide / 2–6 min); every PNG named
      `slideK_<slug>_<MmSSs>.png` with K in first-appearance order; **every
      filename's content verified against its image or OCR text**; no zero-length
      windows; no duplicates; missed captures recovered (slide re-index, Step 2)
- [ ] `slides_ocr.json` regenerated after the last rename (its keys are filenames)
- [ ] `slides/README.md` re-verified last, against the images — including the
      on-screen title and deck-page columns, not just the row count
- [ ] deck PDF in `resources/` (the index is verified against it)
- [ ] correction pass complete: `correction_brief.md` worked;
      `corrections.json` accounts for every brief finding — explicitly including
      verification-only passes, with what was checked and what stays `[as heard]`
      recorded in `notes`
- [ ] handover state assembled: `.clean.md` carries the assembled slide index;
      `.clean.srt` is `[Slide K]`-tagged; the zh decision (default no-zh unless the
      course overrides) is recorded

**Phase B uses the teach exit gate, plus these video-specific items:**

- [ ] lessons cite the corrected layers (timestamps, slide numbers), not the
      raw transcript
- [ ] if a Phase A defect was found *during* Phase B: re-run every A-gate item the
      fix touches (renames → re-OCR → re-assemble index → re-tag SRT) before
      committing, so the committed set is consistent end to end
