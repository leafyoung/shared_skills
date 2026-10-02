---
name: teach
description: >-
  Teach the user a new skill or concept, within this workspace. This skill
  should be used when the user asks to "teach me", "learn about", "I want to
  understand", "explain X", "help me learn", "give me a lesson", "tutorial
  on", "how does X work", or wants to learn any topic through structured
  lessons, interactive exercises, and reference materials within a dedicated
  workspace. Lessons are authored as an mdBook (navigable web book) by
  default, with Quarto (PDF via Typst) reserved for print-first courses; see
  "Output Formats". Make sure to use this skill whenever the user expresses a
  desire to learn something new over multiple sessions, even if they don't
  explicitly say "teach" — look for "walk me through", "can you show me how
  to", "I'd like to get into", etc. Also applies to quick explanations: apply
  the two teaching principles (see "How to Teach") so it locks in, without
  spinning up a workspace. Companion marimo notebooks are the teach-marimo
  skill's.
---

The user has asked you to teach them something. If it grows into a
multi-session effort — a teaching workspace — the request is stateful: you
maintain the mission, learning records, and the book across sessions. For
quick one-off explanations, apply the two principles below and skip the
workspace machinery.

**Division of labour across the teaching skills.** This skill owns the
pedagogy *and* the workspace: how to teach, how to plan, what to teach next,
plus the workspace itself — layout, state documents, output formats, lessons
in the book, resources, assets, verification bars and commit gates. Two
satellites: **mdbook-authoring** (`~/.agents/skills/mdbook-authoring/`) owns
the book mechanics — build every book with it. **teach-marimo**
(`~/.agents/skills/teach-marimo/`) owns companion marimo notebooks — whether
to build one, how, and how to verify it; call it up whenever a lesson or
course calls for a notebook. The source pipelines **video-teach** and
**slides-teach** turn raw material into a trustworthy index and then author
their lessons through this skill. Anything about *how to teach* and *how the
workspace is structured* lives here; book *mechanics* live in
mdbook-authoring and *notebooks* in teach-marimo — never copy them in.

## How to Teach

Two principles govern every explanation, from a one-liner to a deep dive. The goal is never "the user can recite the fact" — it is **understanding**: the fact is derivable from foundations the user already accepts, connected into their mental model. Connected knowledge is self-preserving; memorized facts rot. Aim for the *click* — the moment a pile of lonely facts collapses into a few generating ideas.

A key mechanism: the brain won't fully commit to a fact it isn't sure is safe to lock in. If something more fundamental might later contradict it, committing is risky. Both principles remove that risk.

### Principle i — Unconditional truths first

Lock in the core **always-true** unconditional truths before anything built on them. Not because bottom-up is the "correct" order — because unconditional truths are the easiest thing for the brain to accept: they're safe, commit instantly, and give the first solid ground to build from.

- An *unconditional truth* is accepted **as-is, at face value, no caveats or nuance** (a property of how it's held). An *axiom* follows from nothing else (where it sits in the graph). They overlap but aren't synonyms — say "unconditional truth" by default; reserve "axiom" for genuine roots.
- If a fact needs "well, usually…", it isn't unconditional yet — dig down further.
- Strong forms, when they exist: **universal statements** ("ALL X is done through {____}") and **real definitions** (genuine ones — a vague property list anchors nothing). Don't force either.
- **Confirm the foundation before building on it.** If a core truth doesn't feel rock-solid to the user, stop and fix it — don't build on sand.

### Principle ii — "How could I have discovered this?"

Facts feel arbitrary when there's no visible reason they *had* to be that way, and the brain won't commit to arbitrary info. Make it feel discovered, not decreed: walk through how the user **could have discovered it themselves**, with every step motivated — why are we even doing this? why try *this* formula? why manipulate the equation *this* way? 3Blue1Brown is the reference style: nothing appears from nowhere.

**Socratic vs expository — choose per topic and per the user's energy.** Socratic (pose the motivating problem, let them attempt the discovery first) is stronger and the default when they can plausibly reason their way there. Expository (narrate the motivated path yourself) when the topic is beyond cold-reasoning reach or the user is low-energy.

## Course parameters (fix once per workspace, record in NOTES)

This skill serves tutoring workspaces and course workspaces built from source
material. Fix the parameters at workspace creation:

| Parameter | video course | slides/documents course | tutoring workspace |
|---|---|---|---|
| Unit folder | `epN_<slug>/` | `unitN_<slug>/` | none (flat) |
| Join key | `MmSSs` timestamps | source page `pNNN` | - |
| Authoring inputs | `slides/README.md` + corrected transcript | `pages/README.md` + text layer + `notes.md` | research |
| Source gate | video-teach Phase A | slides-teach index review | - |
| Extras | `MEDIA.md` + gitignored media cache; deck PDF pulled forward | `source/` committed; `notes.md` speaker notes | - |

Everything below is written in terms of a **unit** - an episode, a unit, or a
lesson batch in a tutoring workspace.

## Output Formats

A teaching workspace authors its lessons in **one format — mdbook by default**. **Ask the user only to confirm when starting a new workspace** — unless they already named a format or explicitly want print-first lessons, do not push quarto. If they defer ("whatever", "you choose"), fall back to mdbook. Record the choice in `NOTES`; in an existing workspace, read it from `NOTES` or infer it from disk (`mdbook/` or `lessons_md*/` -> mdbook; `lessons/*.qmd` with no book dir -> quarto) and don't re-ask.

- **mdbook (default)** — the whole course as a navigable, searchable web book (`book.toml` + `src/` + built `book/`). Best in practice: it is the format every active curriculum here converged on, the user browses it continuously, and a translated course is simply two mirror books under one convention.
- **quarto** — per-lesson `./lessons/*.qmd` rendered to PDF via Typst. Reserve for genuinely print-first deliverables.

**Never maintain the same lessons in two formats.** Dual sources drift: retiring one curriculum's qmd lesson tree required a full normalized-diff audit of all twenty lesson pairs to prove nothing was lost (2026-09-26). If a workspace has both, convert (mdbook-authoring Route B), prove sync, retire the qmd lessons, and record the retirement in `NOTES`.

**State-doc flavor - decide once, never straddle.** Canonical in an mdBook workspace: MISSION/NOTES/RESOURCES/GLOSSARY/learning-records live **inside the book** as `src/*.md` (canonical layout: [MDBOOK.md](./MDBOOK.md)). Two sanctioned exceptions: the **linkage route** (artifacts link into rendered root documents, so state docs stay root Quarto docs rendered from a root `_quarto.yml` that no longer lists lessons) and the **ledger flavor** used by video and slides courses (root `.qmd` state docs kept as editor-readable ledgers - deliberately never rendered, no root `_quarto.yml` - because the book's `about.md` carries the in-book summary). Two living copies of a state document is how mirror drift happens.

The teaching rules are identical under both formats; only the authoring format and build differ. All mdBook mechanics - the pinned toolchain, Route A (create from scratch), Route B (convert a qmd course), and the per-content-type style - live in the shared **mdbook-authoring** skill. [MDBOOK.md](./MDBOOK.md) keeps this skill's flavor deltas: the state-doc layout, route couplings, and the qmd-retirement policy.

## First session

1. **Probe.** If no mission document exists yet, interview the user on why they want to learn this (`ask_user_question`) — interrogate the goal until it's concrete. Write it before authoring any teaching content (format: [MISSION-FORMAT.md](./MISSION-FORMAT.md); scaffold the directory shell first if the document lives inside the book). Also probe their current level: bracket the edge of what they know (see [Zone Of Proximal Development](#zone-of-proximal-development)). In the same question round, **confirm the output format** (see [Output Formats](#output-formats)) unless the user already specified one, and record the answer in `NOTES` before authoring content.
2. **Plan.** Scope the field from research, never from memory alone. Present the plan in chat before any teaching: the approach in prose, plus a small mermaid dependency map — unconditional truths at the roots, each node hanging off what it depends on, the user's goal as the sink. Stress-test the roots: if a "foundational" node itself derives from something simpler the user would accept at face value, push it down. Then stop and wait for the user's go-ahead before authoring (resource *acquisition* may run during planning; authoring waits). Search for high-trust sources (books, articles, courses, communities) and populate `RESOURCES` — every entry is downloaded on the spot (see [Resources](#resources-download-on-the-spot)).
3. **Build one lesson.** mdbook (default): scaffold the book from the mdbook-authoring skill's bundled template and follow its Route A. Quarto (print-first only): create a single self-contained lesson in `./lessons/0001-...qmd` rendered to PDF via Typst, with the workspace `_quarto.yml` bootstrapped from the bundled template [`assets/_quarto.yml`](./assets/_quarto.yml).
4. **Record.** Write a learning record if the user demonstrated understanding or disclosed prior knowledge.

Future sessions: read `learning-records/` and `NOTES` to pick the next thing in their zone of proximal development.

## Workspace Layout

**Tutoring workspace** (flat):

- `MISSION.qmd` - the reason the user is learning this ([MISSION-FORMAT.md](./MISSION-FORMAT.md)); mdBook flavor: `<book-dir>/src/mission.md`.
- `RESOURCES.qmd` - the acquisition ledger ([RESOURCES-FORMAT.md](./RESOURCES-FORMAT.md)); mdBook: `src/resources.md`.
- `GLOSSARY.qmd` - canonical terminology ([GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md)); mdBook: `src/glossary.md`.
- `./learning-records/*.md` - what the user has learned, `0001-<name>.md`, incrementing ([LEARNING-RECORD-FORMAT.md](./LEARNING-RECORD-FORMAT.md)); mdBook: `<book-dir>/src/learning-records/`.
- `./lessons/` - the lessons; `./assets/` - reusable components; `NOTES.qmd` - preferences and working notes (mdBook: `src/NOTES.md`).

**Course workspace** (one git repo, one `uv` project, one folder per unit):

```
<course>/
├── AGENTS.md              # how to work here: layout + conventions (adapt on init)
├── MISSION.qmd            # root, canonical (ledger flavor - never rendered)
├── RESOURCES.qmd          # acquisition ledger (root; snapshots live per-unit)
├── NOTES.qmd              # scratchpad (root, canonical)
├── pyproject.toml         # ONE uv project for the whole course
├── .python-version        # 3.12 unless the course needs otherwise
├── .gitignore             # mdbook/book/, output/, __pycache__, caches (+ video: media, transcript intermediates)
├── mdbook/                # the course book (mdbook-authoring Route A scaffold)
│   ├── src/SUMMARY.md     #   one Part per unit; every file listed or it won't render
│   ├── src/about.md       #   course overview + progress table (the resume anchor;
│   │                      #   NOT mission.md - root MISSION.qmd is canonical)
│   ├── src/unitN-<slug>/  #   unit overview chapter + lessons/*.md
│   ├── src/reference/     #   cross-unit cheat sheets (glossary.md first)
│   └── src/assets/unitN/  #   copies of figures embedded in lessons (source in unitN/assets/)
└── <unit>N_<slug>/        # one folder per unit - everything else is per-unit
    ├── README.md          # provenance, index summary, what's built, open gaps
    ├── notebooks/<slug>.py    # marimo companion notebook(s), per teach-marimo
    ├── resources/         # downloaded PDFs; web snapshots as resources/web/*.qmd
    ├── assets/            # lesson figure generation scripts + rendered images
    ├── output/            # marimo export artifacts (gitignored)
    └── learning-records/  # per-unit ZPD findings
```

plus the flavor's source artifacts (video: `transcript/`, `slides/`, `MEDIA.md` - see video-teach; slides: `source/`, `pages/`, `notes.md` - see slides-teach).

**Placement is not negotiable**: only `AGENTS.md`, the root state docs, `pyproject.toml`, `.python-version`, `.gitignore` (and the flavor's root extras: `MEDIA.md` for video) are root-level; everything else lives in the unit folder.

**Python code.** One root `pyproject.toml`, no per-unit files; add a dependency once at the root when any unit needs it (marimo - pin the version - pillow, pytest, ruff, plus format-specific extras). Notebook preference, editor wiring, and notebook verification are the **teach-marimo** skill's.

## Philosophy

To learn at a deep level, the user needs three things:

- **Knowledge**, captured from high-quality, high-trust resources
- **Skills**, acquired through highly-relevant interactive lessons devised by you, based on the knowledge
- **Wisdom**, which comes from interacting with other learners and practitioners

Before `RESOURCES` is well-populated, your focus should be to find high-quality resources which will help the user acquire knowledge. Never trust your parametric knowledge. The moment you are even slightly unsure of any fact, name, date, formula, or definition, stop and verify (web search or a researcher subagent) before saying it — one confidently-delivered hallucination poisons the trust everything else rests on. If a check corrects what you were about to teach, say so plainly.

Some topics may require more skills than knowledge. Learning more about theoretical physics might be more knowledge-based. For yoga, more skills-based.

### Fluency vs Storage Strength

You should be careful to split between two types of learning:

- **Fluency strength**: in-the-moment retrieval of knowledge
- **Storage strength**: long-term retention of knowledge

Fluency can give the user an illusory sense of mastery, but storage strength is the real goal. Try to design lessons which build long-term retention by desirable difficulty:

- Using retrieval practice (recall from memory)
- Spacing (distributing practice over time)
- Interleaving (mixing up different but related topics in practice - for skills practice only)

## Lessons

A lesson is the main thing you produce — the unit in which knowledge and skills reach the user. Each lesson is one self-contained document teaching one tightly-scoped thing tied to the mission, saved under the workspace's lessons directory (Quarto: `lessons/0001-<dash-case-name>.qmd`; mdBook: `<book-dir>/src/lessons/`) where the number increments each time.

A lesson should be **beautiful** — clean, readable typography and layout — since the user will return to these later to review. Think Tufte, in the medium the reader actually gets: lean on the shared template defaults rather than restyling each lesson.

The lesson should be short, and completable very quickly. Learners' working memory is very small, and we need to stay within it. But each lesson should give the user a single tangible win that they can build on. It should be directly tied to the mission, and should be in the user's zone of proximal development.

If possible, build and open the lesson for the user by running a CLI command (mdBook: `mdbook build` + open, or `mdbook serve` for a live-reloading preview; Quarto: `quarto render` + open the PDF).

Each lesson should link via standard markdown links to other lessons and reference documents.

Each lesson should recommend a primary source for the user to read or watch. This should be the most high-quality, high-trust resource you found on the topic.

Each lesson should contain a reminder to ask followup questions to the agent. The agent is their teacher, and can assist with anything that's unclear.

Structure each concept in a lesson as a **node** in the dependency map, and teach every node the same way — foundational or derived:

1. **Motivate** — why *this* node, right now. Applies to unconditional truths too, not just derived steps.
2. **Establish** — foundational truths stated plainly, at face value, no caveats; derived steps built up via a motivated discovery path (Socratic or expository), answering "how could I have discovered this?".
3. **Connect** — make the dependency edge explicit: show how this node hangs off what's already established, so it's understood, not memorized.
4. **Check** — confirm the node landed (exercise or in-chat question) before building anything on it. An unconfirmed foundation is exactly as dangerous as an unconfirmed derived fact. Any mid-lesson unconditional truth goes through the same loop.

Math renders as LaTeX — write `$f(x) = x^2$`, never plain-text approximations. If LaTeX can be used, it should be. (Rendering mechanics and per-format gotchas: mdbook-authoring.) Figures are regenerable components, not one-offs — see [Assets](#assets).

## Lessons in the book

Author per the teaching rules above - this section is only about where lessons land and what they must contain in a course workspace.

- Content comes from the unit's authoritative index and narration layer (see [Course parameters](#course-parameters-fix-once-per-workspace-record-in-notes)). The source tells you *what to teach and in what order*; the teach rules tell you *how*.
- Lesson language: the course's language - the user's stated preference, else the source's. Mirror books apply only when the user explicitly requests a translated course (see [Mirrors, sync, and verification](#mirrors-sync-and-verification)).
- 2-4 lessons per lecture hour (video) or per 30-40 content pages (slides), each tightly-scoped, self-contained, with a single tangible win and its `## Exercises`/`## Answers` sections. A lesson with unanswered exercises must not ship.
- Retrofit (absorbing pre-existing lessons): normalize their exercise headings to the book's convention (`## Exercises` / `## Answers`) and bring each chapter to the same bar - a numerical, chapter-computable exercise where the existing mix is conceptual-only.
- Book structure: one Part per unit in `SUMMARY.md`; each Part opens with a unit overview chapter (what the source covers, link to the original, links to its notebook and resources) followed by the lessons. Add each chapter to `SUMMARY.md` in the same edit that creates it.
- Cite the source: video courses link the video with a timestamp (`https://youtu.be/<id>?t=<s>`) plus the local transcript section; slides courses cite the page ("source p.12") with a relative link to the kept page image in `mdbook/src/assets/unitN/` and the `pages/README.md` row.
- Figures are regenerable - generation script in `<unit>/assets/lessonNNNN-<topic>.py`, rendered image beside it, **copy** the image into `mdbook/src/assets/unitN/` for embedding (re-copy after regenerating).
- Source images may be embedded where the source IS the content (a key formula, a result table): copy into `mdbook/src/assets/unitN/` likewise, and keep a conservative copyright posture - brief excerpts for personal study are fine, wholesale re-publication is not. An asset copied into `mdbook/src/assets/` must be embedded by a lesson in the same session - an unreferenced copy is dead weight that reads as already-used, and no build warning will flag it.
- Build bar: `mdbook build` with zero warnings; math via KaTeX, callouts via admonish, per the mdbook-authoring skill's style table and gotchas (escape literal `$`, wire the text-fix preprocessor, no `README.md` in src/).

## The Mission

Every lesson should be tied into the mission - the reason that the user is interested in learning about the topic.

If the user is unclear about the mission, or the mission document is not populated, your first job should be to question the user on why they want to learn this.

Failing to understand the mission will mean knowledge acquisition is not grounded in real-world goals. Lessons will feel too abstract. You will have no way of judging what the user should do next.

Missions may change as the user develops more skills and knowledge. This is normal - make sure to update the mission document and add a learning record to capture the change. Confirm with the user before changing the mission.

## Zone Of Proximal Development

Each lesson, the user should always feel as if they are being challenged 'just enough'.

The user may specify an exact thing they want to learn. If they don't, figure out their zone of proximal development from:

- their `learning-records`
- the mission — what would move them toward it now

…then teach the most relevant thing that fits inside that zone.

**The edge is only located when it's bracketed**: something at that level the user gets **right** (a floor) and something they get **wrong** or genuinely don't know (a ceiling). One side alone tells you almost nothing.

- All-correct is not "done" — the questions were too easy. Escalate sharply until something breaks; if they never miss, you never found the edge.
- **Binary-search the edge**: on a correct answer, jump difficulty up sharply; on a miss, narrow back in. One miss is a coordinate, not a verdict — probe around it to tell a careless slip from a systematic misconception (misconceptions must be dislodged, not topped up).
- Map every strand the lesson rests on, bounded by relevance to the goal.
- Ask via `ask_user_question` (multiple-choice options work); grade from their pick. On a miss, one follow-up ("why did you pick that?" or a near-miss variant) before moving on — a careless slip and a systematic misconception call for different responses, and misconceptions must be dislodged, not topped up.

## Knowledge

Lessons should be designed around a skill the user is going to learn. The knowledge in the lesson should be only what's required to acquire that skill. You teach the knowledge first, then get the user to practice the skills via an interactive feedback loop.

Knowledge should first be gathered from trusted resources. Use `RESOURCES` to keep track of them. Lessons should be littered with citations - links to external resources to back up any claim made. This increases the trustworthiness of the lesson.

If web search does not work (errors, timeouts, empty, or spam results), **notify the user immediately** — do not silently fall back to parametric knowledge or pretend sources were verified. State what failed, mark affected resources as unverified in `RESOURCES`, and retry when search is available again.

For acquiring knowledge, difficulty is the enemy. It eats working memory you need for understanding.

## Resources (download on the spot)

`RESOURCES` is the ledger; **every entry is acquired the moment it's added** — all of them, not only the ones the current lesson cites. It is an acquisition ledger, not a bookmark list: an entry without a local copy is unfinished. Record the local path in the ledger. Lessons must not depend on external links staying alive. In a course workspace acquisition means:

- Papers / references / slides / cited works -> PDF verbatim into `<unit>/resources/`. **Verify every fetched PDF**: page count + text extraction (`pdfinfo`/`pdftotext`), and prefer the largest of N archive captures - a truncated download parses as a valid PDF header but is worse than no local copy (seen in practice: a Wayback capture complete only to ~half its size). A truncated PDF must not be kept.
- Web pages (course site, docs, project pages) -> snapshot to `<unit>/resources/web/<slug>.qmd`: YAML `title`, a provenance blockquote (source URL, fetch date, license note), then the content as markdown (tutoring workspaces: under `resources/web/` likewise; mdBook flavor: `.md`).
- Paywalled or unobtainable full texts -> say so plainly in the ledger; snapshot the abstract/landing page, and hunt an open-access substitute (author mirrors, `.edu` lecture notes, working-paper repositories, the Wayback Machine) rather than relying on the dead link.
- Streaming or interactive media -> don't mass-download video; snapshot the landing page, mark the entry *streaming-only*, and note the offline substitute where one exists. In a video course the episode video is such an entry: *streaming* + the local cache path from `MEDIA.md` (never commit video). The course's own source document (slides courses) enters marked *in-repo*, pointing at `<unit>/source/`.
- Find the official materials first (the course's or deck's own published materials beat any third-party summary); record and cite them from the unit's lessons.

Before finishing any session: every ledger entry has a local path or an explicit streaming-only/paywalled note. Fix the gaps while you're still in the session.

Downloaded papers are copyrighted third-party material - **gitignore `<unit>/resources/*.pdf`** so the tracked `resources/web/*.qmd` snapshots carry the record while the binaries stay local.

## Skills

If knowledge is all about acquisition, skills are about durability and flexibility. Make the knowledge stick.

For skill acquisition, difficulty is the tool. Effortful retrieval is what builds storage strength. Skills are taught through exercises embedded in the lesson (printed in the PDF under Quarto; as `## Exercises`/`## Answers` sections in the book under mdBook). There are several tools at your disposal:

- **Self-check exercises** printed in the lesson — multiple-choice questions, fill-in-the-blanks, short prompts to answer in writing.
- **Real-world tasks** the lesson walks the user through step by step (for instance, yoga poses, or running a command and observing the output).

Each of these should be based on a **feedback loop**. Because the output is static (a PDF, or a built book), automatic feedback is not possible — so make the loop tight another way: print the answers (or a marking rubric) under a clearly delimited "Answers" heading at the end of the lesson, and always invite the user to bring their attempt back to the agent for review. The agent is the feedback channel.

**Answers are not optional.** Every exercise printed in a lesson — multiple-choice, fill-in-the-blank, short prompt, real-world task — must have its answer or expected outcome (rubric) printed in the same lesson file, under the "Answers" heading. A lesson rendered with an unanswered exercise is incomplete and must not ship. (2026-09-15: lesson 0001 shipped with unanswered Skills questions and the user had to ask for the key — the exact failure mode this rule prevents.)

**Notebook preference:** the user prefers **marimo** notebooks over Jupyter for lesson-created notebooks and exercises; whether to build one, how, and how to verify it are the **teach-marimo** skill's.

For printed multiple-choice questions (and in-chat options), construct the set so evenness is automatic — don't audit after the fact:

- Every option is a bare claim — no justification anywhere. All reasoning goes in the answer key / explanation revealed after the user answers. The #1 tell is the correct option carrying its own "because…" while distractors stay bare.
- Write the correct claim first, then mutate it into each distractor: one specific misconception or easily-confused neighbour per distractor, in the same skeleton, grain size, and register as the correct claim.
- Each distractor must be a real error the user might actually make (so which one they pick is diagnostic), yet unambiguously wrong — tempting, not tricky.
- No asymmetric bolding, and keep options near the same length (and characters, if possible).

If you can tell which option is right without knowing the material, regenerate — don't patch.

## Assets

Lessons are built from reusable **components**, stored in `<unit>/assets/` (or `./assets/` in a tutoring workspace): Typst template partials, reusable markdown includes, diagram helpers, code snippets — anything a second lesson could reuse.

Reuse is the default, not the exception. Before authoring a lesson, read `./assets/` and build from the components already there. When a lesson needs something new and reusable, write it as a component and reference it — never inline content a future lesson would duplicate.

**Every figure is regenerable, not just embeddable.** When a figure is produced by code, save the generation script itself, named to match (`lessonNNNN-topic.py` -> `lessonNNNN-topic.svg`/`.png`), runnable standalone from the workspace root with a one-line invocation (document it in a module docstring), regenerating the exact embedded figure. A figure with no saved script is a dead end the moment a number in the lesson needs to change. Edit the script and re-run; never hand-patch the image.

Bootstrap shared helpers once per workspace rather than re-typing them: the mdbook-authoring skill's bundled `assets/book.toml` (callouts, KaTeX, text-fix preprocessor pre-wired), this skill's bundled [`assets/_quarto.yml`](./assets/_quarto.yml) for print-first Quarto workspaces, and [`assets/scripts/svgutil.py`](./assets/scripts/svgutil.py) for hand-built SVG figures (includes `FONT_EN`/`FONT_ZH` and `lang_from_argv()` for dual-language variants; copy it in once per workspace, and re-verify CJK font availability per workstation).

Diagrams: use the `mermaid-maker` subagent for relational diagrams and `svg-maker` for spatial/geometric figures; embed the result (```` ```mermaid ```` block under mdBook, ```` ```{mermaid} ```` chunk in Quarto). If neither subagent is available, hand-build per the figure-script rule above.

## Mirrors, sync, and verification

A translated course is full mirror books (`lessons_md/` + `lessons_md_zh/`): every lesson change lands in all languages *and* the companion notebooks in the same session - never "I'll translate it later". Shared state (mission, NOTES, RESOURCES, learning-records) is maintained **once**, in the primary-language book; the mirror carries only translated teaching content. Sync is proven, not assumed: normalized-diff the language pairs after stripping the known per-format differences - use [`assets/scripts/normalized_diff.py`](./assets/scripts/normalized_diff.py), don't hand-roll the stripping: `--digest` proves the structural lockstep (the proof for language mirrors, since every word legitimately differs), the default full-text diff is for same-language conversions (qmd -> mdBook). Figure convention: the Chinese variant of a figure is `name-zh.svg` beside the English original; errata caveat wording follows the book's language.

**Errata discipline.** A defect found in a source is folded into the lesson at the exact point the wrong figure appears - a red **ERRATA** (English book) / **修正** (Chinese book) tag, then the note, always preserving the caveat "flagged, not yet confirmed with the source's owner". No standalone root-level errata source (tried and deleted 2026-09-26); a per-book `errata.md` ledger page inside `src/` is fine, maintained directly in the book.

**The verification bar for any session that touched lessons or notebooks**: `ruff` + `marimo check` on each touched notebook, then the notebook execution bar per **teach-marimo**; `mdbook build` per book with zero warnings; `quarto render` only for root reference docs. If other artifacts link into the built `book/` (reference-doc PDFs, notebook headers), commit the rebuilt output as part of the change - where the book output is tracked, linkage commits its `book/`; gitignored books just rebuild.

## Wrap and the exit gate

1. `<unit>/README.md`: source provenance (origin, date, version; video link + duration for episodes), the index summary, what was built (lessons, notebook, resources), open gaps.
2. Learning records when the session surfaced something non-obvious (a ZPD finding, a convention decision, a bug or erratum in the source material).
3. Update root `RESOURCES` / `NOTES`; bump the unit's row in the book's `about.md` progress table (keep this table - it is the resume anchor).
4. Commit at unit boundaries (`unit3: pages indexed, 2 lessons, notebook`); on a long unit, commit at pipeline-step boundaries too - never leave hours of transcript/extraction work uncommitted.

**Exit gate - all items before the unit commit:**

- [ ] book: new chapters in `SUMMARY.md` (added in the same edit that creates them); `mdbook build` zero warnings; exercises all answered
- [ ] lessons cite the source layers per the course's join key; every figure or source image copied into `mdbook/src/assets/` is embedded by a lesson
- [ ] notebooks (where this course builds them - teach-marimo's when-to-build rule): the teach-marimo verifier exits 0; linked from the unit's book chapters
- [ ] resources: every ledger entry added this session has a local path or a streaming-only note
- [ ] unit README current (including open gaps); commit(s) for the unit

Source pipelines add their own gates before this one (video-teach's Phase A handover gate runs when the unit's data phase completes; the pipeline's own checklist defines each upstream step's end state).

## Conventions

- **Honest gaps**: if a notebook can't reproduce a claimed number (library drift, missing data), say so in the unit README with what was checked - never tune until it matches.
- **New session in an existing workspace**: read `AGENTS.md` -> `NOTES` -> the book's `about.md` progress table -> `git log --oneline` + `git status` -> the current unit's `README.md`, then resume the pipeline at its first incomplete step (the source pipeline's gate defines the upstream steps' end states; the exit gate above defines the rest).
- **Running steps with subagents** (the judgment-heavy steps - correction passes, lesson authoring - parallelize well, with three rules learned the hard way): dispatch at most 2-3 concurrent workers (4-5 tripped a provider 5-hour usage cap twice on one course; solo dispatches kept working); **audit `git status` and diffs before re-dispatching a "failed" worker** - workers that time out or die writing their final report often leave all their file edits already on disk; and give each worker the unit's own paths and IDs in the prompt, so it never has to trust summary-level context.
- Skill scripts and extractors are regenerable; never commit `.venv`, caches, build output, or media.

## Acquiring Wisdom

Wisdom comes from true real-world interaction - testing your skills outside the learning environment.

When the user asks a question that appears to require wisdom, your default posture should be to attempt to answer - but to ultimately delegate to a **community**.

A community is a place (online or offline) where the user can test their skills in the real world. This might be a forum, a subreddit, a real-world class (budget permitting) or a local interest group.

You should attempt to find high-reputation communities the user can join. If the user expresses a preference that they don't want to join a community, respect it.

## Reference Documents

While creating lessons, you should also create reference documents. Lessons can reference these documents - they are useful for tracking raw units of knowledge useful across lessons.

Lessons are revisited while the course runs; reference documents are what survives it. They should be the compressed essence of the lesson, in a format designed for quick reference.

Some learning topics lend themselves to reference:

- Syntax and code snippets for programming
- Algorithms and flowcharts for processes
- Yoga poses and sequences for yoga
- Exercises and routines for fitness
- Glossaries for any topic with its own nomenclature

Glossaries, in particular, are an essential reference. Once one is created, it should be adhered to in every lesson (format: [GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md)).

## `NOTES`

The user will sometimes express preferences of how they want to be taught, or things you should keep in mind. This is the place to record those preferences, so you can refer back to them when designing lessons or working with the user. (Location per flavor: [Workspace Layout](#workspace-layout).)
