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
  spinning up a workspace.
---

The user has asked you to teach them something. If it grows into a
multi-session effort — a teaching workspace — the request is stateful: you
maintain the mission, learning records, and the book across sessions. For
quick one-off explanations, apply the two principles below and skip the
workspace machinery.

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

## Output Formats

A teaching workspace authors its lessons in **one format — mdbook by default**. **Ask the user only to confirm when starting a new workspace** — unless they already named a format or explicitly want print-first lessons, do not push quarto. If they defer ("whatever", "you choose"), fall back to mdbook. Record the choice in `NOTES`; in an existing workspace, read it from `NOTES` or infer it from disk (`lessons_md*/` or `./mdbook/` → mdbook; `lessons/*.qmd` with no book dir → quarto) and don't re-ask.

- **mdbook (default)** — the whole course as a navigable, searchable web book (`book.toml` + `src/` + built `book/`). Best in practice: it is the format every active curriculum here converged on, the user browses it continuously, and a translated course is simply two mirror books under one convention.
- **quarto** — per-lesson `./lessons/*.qmd` rendered to PDF via Typst. Reserve for genuinely print-first deliverables.

**Where state documents live (decide once per workspace, never straddle).** Canonical in an mdBook workspace: MISSION/NOTES/RESOURCES/GLOSSARY/learning-records live **inside the book** as `src/*.md` (layout in [MDBOOK.md](./MDBOOK.md)). One exception is the **linkage route** — a workspace whose other artifacts (reference-doc PDFs, notebook headers) link into rendered root documents keeps GLOSSARY/MISSION/NOTES/RESOURCES as root Quarto docs, rendered from a root `_quarto.yml` that no longer lists lessons, with their lesson links pointing into the built book. A third sanctioned flavor is the **video-course workspace** (the video-teach skill): root `.qmd` state docs kept as editor-readable ledgers — deliberately never rendered, no root `_quarto.yml` — because the book's `about.md` carries the in-book summary. Pick one flavor, record it in `NOTES`, don't straddle: two living copies of a state document is how mirror drift happens.

**Never maintain the same lessons in two formats.** Dual sources drift: retiring one curriculum's qmd lesson tree required a full normalized-diff audit of all twenty lesson pairs to prove nothing was lost (2026-09-26). All three curricula in `argus-teach` have since retired their qmd lesson trees; Quarto survives only for print-first courses and, on the linkage route, the root reference docs. If a workspace has both, convert (Route B), prove sync, retire the qmd lessons, and record the retirement in `NOTES`.

The teaching rules are identical under both; only the authoring format and build differ. All mdBook mechanics — the pinned toolchain (mdbook + admonish + katex + mermaid — exact versions matter), **Route A: create an mdBook from scratch**, **Route B: convert an existing qmd course** (with the construct-by-construct mapping), and the style to use for each content type (callouts, math, diagrams, captioned figures, cross-references, …) — live in the shared **mdbook-authoring** skill (`~/.agents/skills/mdbook-authoring/`, also used by video-teach and slides-teach). [MDBOOK.md](./MDBOOK.md) keeps only teach's flavor deltas: the state-doc layout, route couplings, and the qmd-retirement policy.

## First session

1. **Probe.** If no mission document exists yet (`MISSION.qmd` in a Quarto workspace, `mission.md` in the book's `src/`), interview the user on why they want to learn this (`ask_user_question`) — interrogate the goal until it's concrete. Write it before authoring any teaching content (scaffold the directory shell first if the document lives inside the book). Also probe their current level: bracket the edge of what they know (see [Zone Of Proximal Development](#zone-of-proximal-development)). In the same question round, **confirm the output format** (mdbook by default; quarto only for print-first — see [Output Formats](#output-formats)) unless the user already specified one, and record the answer in `NOTES` before authoring content (in the default mdBook flavor that means scaffolding the book's `src/` shell first — `NOTES` lives inside it).
2. **Plan.** Scope the field from research, never from memory alone. Present the plan in chat before any teaching: the approach in prose, plus a small mermaid dependency map — unconditional truths at the roots, each node hanging off what it depends on, the user's goal as the sink. Stress-test the roots: if a "foundational" node itself derives from something simpler the user would accept at face value, push it down. Then stop and wait for the user's go-ahead before authoring (resource *acquisition* may run during planning; authoring waits). Search for high-trust sources (books, articles, courses, communities) and populate `RESOURCES` (`RESOURCES.qmd`, or `resources.md` in the book's `src/`). Every entry is downloaded on the spot (see [Knowledge](#knowledge) — Acquisition): a `RESOURCES` entry without a local copy or an explicit streaming-only/paywalled note is not fully acquired.
3. **Build one lesson.** Format per [Output Formats](#output-formats). mdBook (default): scaffold the book from the mdbook-authoring skill's bundled template (`~/.agents/skills/mdbook-authoring/assets/book.toml`) and follow that skill's **Route A** — or **Route B** if the workspace already has `.qmd` lessons to convert. Quarto (print-first only): create a single self-contained lesson in `./lessons/0001-...qmd` (rendered to PDF via Typst) tied to the mission; ensure the workspace has a `_quarto.yml` at its root, bootstrapped from the skill's bundled template [`assets/_quarto.yml`](./assets/_quarto.yml) — this is the shared styling every lesson inherits.
4. **Record.** Write a learning record if the user demonstrated understanding or disclosed prior knowledge.

Future sessions: read `learning-records/` and `NOTES` (`NOTES.md` in the book's `src/`, or `NOTES.qmd` in a Quarto workspace) to pick the next thing in their zone of proximal development.

## Teaching Workspace

Treat the current directory as a teaching workspace. The state of their learning is captured in this directory in several files (paths below are the Quarto flavor; in the mdBook default everything lives inside the book's `src/` with `.md` extensions — `mission.md`, `reference/`, `resources.md`, `NOTES.md`, `lessons/` — per the canonical layout in [MDBOOK.md](./MDBOOK.md). The book dir may sit at the workspace root under a name like `lessons_md/`, and a translated course is one book per language (`lessons_md/`, `lessons_md_zh/`) kept as full mirrors, with shared state documents maintained **once**, in the primary-language book — see [MDBOOK.md](./MDBOOK.md) and [Output Formats](#output-formats) for the linkage exception):

- `MISSION.qmd`: A document capturing the _reason_ the user is interested in the topic. This should be used to ground all teaching. Use the format in [MISSION-FORMAT.md](./MISSION-FORMAT.md).
- `./reference/*.qmd`: Reference materials (Quarto/Typst) — compressed cheat sheets, algorithms, syntax references, glossaries. Designed for quick reference and printing. `GLOSSARY.qmd` at workspace root tracks canonical terminology and cross-references these files (format: [GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md)).
- `RESOURCES.qmd`: A list of resources which can be explored to ground your teaching in contextual knowledge, or to acquire knowledge and wisdom. Use the format in [RESOURCES-FORMAT.md](./RESOURCES-FORMAT.md).
- `./learning-records/*.md`: A directory of learning records, which capture what the user has learned. These are loosely equivalent to architectural decision records in software development - they capture non-obvious lessons and key insights that may need to be revised later, or drive future sessions. These should be used to calculate the zone of proximal development. They are titled `0001-<dash-case-name>.md`, where the number increments each time. Use the format in [LEARNING-RECORD-FORMAT.md](./LEARNING-RECORD-FORMAT.md).
- `./lessons/` — a directory of lessons. A **lesson** is a single, self-contained document that teaches one tightly-scoped thing tied to the mission. This is the primary unit of teaching in this workspace. Quarto format: `lessons/*.qmd` rendered to PDF via Typst. mdBook format: `<book-dir>/src/lessons/*.md` built into the course book (see [MDBOOK.md](./MDBOOK.md)).
- `./assets/*`: Reusable **components** shared across lessons (Typst template partials, reusable markdown includes, diagram helpers). See [Assets](#assets).
- `NOTES.qmd`: A Quarto scratchpad for you to jot down user preferences, or working notes. Give it a `title` header so it renders like the rest.

## Philosophy

To learn at a deep level, the user needs three things:

- **Knowledge**, captured from high-quality, high-trust resources
- **Skills**, acquired through highly-relevant interactive lessons devised by you, based on the knowledge
- **Wisdom**, which comes from interacting with other learners and practitioners

Before the `RESOURCES.qmd` is well-populated, your focus should be to find high-quality resources which will help the user acquire knowledge. Never trust your parametric knowledge. The moment you are even slightly unsure of any fact, name, date, formula, or definition, stop and verify (web search or a researcher subagent) before saying it — one confidently-delivered hallucination poisons the trust everything else rests on. If a check corrects what you were about to teach, say so plainly.

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

A lesson is the main thing you produce — the unit in which knowledge and skills reach the user. Each lesson is one self-contained document in the workspace's chosen format (see [Output Formats](#output-formats)), saved under the lessons directory (Quarto: `lessons/0001-<dash-case-name>.qmd`; mdBook: `<book-dir>/src/lessons/`) where the number increments each time. Quarto lessons carry a minimal YAML header (a `title` is enough) and inherit everything else from the workspace `_quarto.yml`; the body is markdown rendered to PDF by Typst. mdBook lessons are plain markdown chapters (H1 title, no front matter) registered in `src/SUMMARY.md`.

**Mirrors, sync, and verification.** A translated course is two full mirror books: every lesson change lands in all languages *and* the companion notebooks in the same session — never "I'll translate it later". Shared state (mission, NOTES, RESOURCES, learning-records) is maintained **once**, in the primary-language book; the mirror carries only translated teaching content. Sync is proven, not assumed: normalized-diff the language pairs after stripping the known per-format differences (frontmatter vs H1, figure syntax, escaped `\$`, path depth, tag forms) — use [`assets/scripts/normalized_diff.py`](./assets/scripts/normalized_diff.py), don't hand-roll the stripping: `--digest` proves the structural lockstep (heading levels, figures, tags, math, tables — the proof for language mirrors, since every word legitimately differs), the default full-text diff is for same-language checks (qmd → mdBook). Figure convention: the Chinese variant of a figure is `name-zh.svg` beside the English original (the normalizer strips the suffix when pairing trees); errata caveat wording follows the book's language (a 修正 note is fully Chinese, caveat included). The verification bar for any session that touched lessons or notebooks: `ruff` + `marimo check` on each touched notebook, then the execution bar — `marimo export html` (it runs every cell and fails loudly) in ordinary workspaces, or the video-teach skill's `run_marimo_notebook.py` in video-course workspaces (it injects `mo` explicitly; headless export can silently skip that injection), `mdbook build` per book with zero warnings, `quarto render` only for the root reference docs. If other artifacts link into the built `book/` (reference-doc PDFs, notebook headers), commit the rebuilt output as part of the change — where the book output is tracked (linkage commits its `book/`; neg-bal-abuse gitignores both books'; gitignored books just rebuild).

**Errata discipline.** A defect found in a source spec or resource is folded into the lesson at the exact point the wrong figure appears — a red **ERRATA** (English book) / **修正** (Chinese book) tag, then the note, always preserving the caveat "flagged, not yet confirmed with the source's owner". No standalone root-level errata source: that was tried and deleted in both curricula that had one (2026-09-26) — an entry at point-of-use is what survives review, and it stops the bad figure being restated as authoritative. A per-book `errata.md` ledger page inside each book's `src/` is fine (neg-bal-abuse keeps one) — maintained directly in the books, never mirrored from a root document.

A lesson should be **beautiful** — clean, readable typography and layout — since the user will return to these later to review. Think Tufte, in the medium the reader actually gets: lean on the book template's shared defaults (mdBook's `book.toml` + CSS, Quarto's `_quarto.yml`) rather than restyling each lesson.

The lesson should be short, and completable very quickly. Learners' working memory is very small, and we need to stay within it. But each lesson should give the user a single tangible win that they can build on. It should be directly tied to the mission, and should be in the user's zone of proximal development.

If possible, build and open the lesson for the user by running a CLI command. mdBook: `mdbook build <book-dir>` then open `<book-dir>/book/index.html`, or `mdbook serve <book-dir>` for a live-reloading preview at `localhost:3000` — binaries live in `~/.cargo/bin` (toolchain pinning: mdbook-authoring skill). Quarto: `quarto render ./lessons/0001-....qmd`, then open the resulting PDF (`open` on macOS, `xdg-open` on Linux) — requires the `quarto` CLI.

Each lesson should link via standard markdown links to other lessons and reference documents (mdBook: relative paths within `src/`; Quarto resolves these across the project).

Each lesson should recommend a primary source for the user to read or watch. This should be the most high-quality, high-trust resource you found on the topic.

Each lesson should contain a reminder to ask followup questions to the agent. The agent is their teacher, and can assist with anything that's unclear.

Structure each concept in a lesson as a **node** in the dependency map, and teach every node the same way — foundational or derived:

1. **Motivate** — why *this* node, right now. Applies to unconditional truths too, not just derived steps.
2. **Establish** — foundational truths stated plainly, at face value, no caveats; derived steps built up via a motivated discovery path (Socratic or expository), answering "how could I have discovered this?".
3. **Connect** — make the dependency edge explicit: show how this node hangs off what's already established, so it's understood, not memorized.
4. **Check** — confirm the node landed (exercise or in-chat question) before building anything on it. An unconfirmed foundation is exactly as dangerous as an unconfirmed derived fact. Any mid-lesson unconditional truth goes through the same loop.

Math renders as LaTeX in both formats — write `$f(x) = x^2$`, never plain-text approximations. If LaTeX can be used, it should be. (Quarto renders it via Typst; mdBook via KaTeX — plain LaTeX in both, never Typst-native math syntax.) In mdBook, KaTeX pins `\tag` at the right margin without reflowing content, so a display equation too wide for the column is silently overlapped by its own tag — keep tagged equations narrow (one tag per source equation; `aligned`-break long ones) — full gotcha list in the mdbook-authoring skill.

Diagrams: use the `mermaid-maker` subagent for relational diagrams (flowcharts, dependency graphs) and `svg-maker` for spatial/geometric figures (function plots, vectors, number lines, layouts) — embed the resulting figure in the lesson (mermaid output embeds directly as a ` ```mermaid ` block under mdBook; in a Quarto lesson use a ` ```{mermaid} ` chunk, no `%%|` options). If neither subagent is available, hand-build the figure (raw SVG, or a small matplotlib/plotting script) — but never as a one-off: see [Assets](#assets) below, every figure's generation code is a first-class, saved component, not scratch work.

## Assets

Lessons are built from reusable **components**, stored in `./assets/`: Typst template partials, reusable markdown includes, diagram helpers, code snippets — anything a second lesson could reuse.

Reuse is the default, not the exception. Before authoring a lesson, read `./assets/` and build from the components already there. When a lesson needs something new and reusable, write it as a component in `./assets/` and reference it — never inline content a future lesson would duplicate.

**Every figure is regenerable, not just embeddable.** When a lesson figure is produced by code (a hand-built SVG, a matplotlib/plotting script — anything that isn't a static export from `mermaid-maker`/`svg-maker`), save the generation script itself into `./assets/` alongside the rendered image, named to match (`lessonNNNN-topic.py` generating `lessonNNNN-topic.svg`/`.png`). The script must run standalone from the workspace root with a one-line invocation (document it in a short module docstring), and must regenerate the exact figure already embedded — a figure with no saved script is a dead end the moment a number in the lesson needs to change. This is why the image is a build artifact of the script, not the other way around: edit the script and re-run it, don't hand-patch the image.

A shared `_quarto.yml` at the workspace root is the first component every Quarto workspace earns, bootstrapped from the skill's bundled template [`assets/_quarto.yml`](./assets/_quarto.yml). It sets the Typst `format` defaults — page, margins, fonts, accent colour — so every lesson renders as one consistent course rather than a pile of one-offs. mdBook workspaces earn the equivalent: the mdbook-authoring skill's bundled `assets/book.toml` (callouts, KaTeX math and the text-fix preprocessor pre-wired — see that skill's gotchas). As the workspace grows, so should the component library.

Figure scripts earn the same treatment: bootstrap `assets/scripts/svgutil.py` from [`assets/scripts/svgutil.py`](./assets/scripts/svgutil.py) into any workspace that hand-builds SVG figures, rather than re-typing `line`/`rect`/`text`/`circle`/`polyline`/`write_svg` tag-formatting per script. It includes `FONT_EN`/`FONT_ZH` and `lang_from_argv()` for a script that renders both an English and a Chinese label variant from one file (`python3 scriptname.py zh`). Copy it in once per workspace (not a cross-project import) so each course stays self-contained. (The bundled copy's `FONT_ZH` note is a starting point — re-verify CJK font availability on each new workstation.)

## The Mission

Every lesson should be tied into the mission - the reason that the user is interested in learning about the topic.

If the user is unclear about the mission, or the mission document (`MISSION.qmd` / `mission.md`) is not populated, your first job should be to question the user on why they want to learn this.

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

Knowledge should first be gathered from trusted resources. Use `RESOURCES.qmd` to keep track of them. Lessons should be littered with citations - links to external resources to back up any claim made. This increases the trustworthiness of the lesson.

If web search does not work (errors, timeouts, empty, or spam results), **notify the user immediately** — do not silently fall back to parametric knowledge or pretend sources were verified. State what failed, mark affected resources as unverified in `RESOURCES.qmd`, and retry when search is available again.

### Acquisition: download every resource, immediately

Every resource added to `RESOURCES.qmd` is **downloaded into the workspace at the moment it is added** — all of them, not only the ones the current lesson cites. `RESOURCES.qmd` is an acquisition ledger, not a bookmark list: an entry without a local copy is unfinished. Record the local path in `RESOURCES.qmd`. Lessons must not depend on external links staying alive:

- **PDFs, datasets, slides, code archives** — save verbatim into `resources/`.
- **Web pages** — snapshot to a local `.qmd` under `resources/web/` (mdBook workspaces: `.md`): a YAML `title`, a provenance blockquote (source URL, fetch date, license/© note), then the page's content converted to markdown. Trim site navigation, keep the substance.
- **Paywalled or unobtainable full texts** — say so plainly in `RESOURCES.qmd`; snapshot the abstract/landing page as a `.qmd`, and hunt an open-access substitute (author mirrors, `.edu` lecture notes, working-paper repositories, the Wayback Machine) rather than relying on the dead link.
- **Streaming or interactive media** (video lectures, courses, forums) — don't mass-download video; snapshot the landing page as a `.qmd` under `resources/web/`, mark the entry *streaming-only* in `RESOURCES.qmd`, and note the offline substitute where one exists (e.g. the same course's textbook as a PDF).

Before finishing any session that touched `RESOURCES.qmd`, re-scan it: every entry carries a local path or an explicit streaming-only/paywalled note. Fix the gaps while you're still in the session.

For acquiring knowledge, difficulty is the enemy. It eats working memory you need for understanding.

## Skills

If knowledge is all about acquisition, skills are about durability and flexibility. Make the knowledge stick.

For skill acquisition, difficulty is the tool. Effortful retrieval is what builds storage strength. Skills are taught through exercises embedded in the lesson (printed in the PDF under Quarto; as `## Exercises`/`## Answers` sections in the book under mdBook). There are several tools at your disposal:

- **Self-check exercises** printed in the lesson — multiple-choice questions, fill-in-the-blanks, short prompts to answer in writing.
- **Real-world tasks** the lesson walks the user through step by step (for instance, yoga poses, or running a command and observing the output).

Each of these should be based on a **feedback loop**. Because the output is static (a PDF, or a built book), automatic feedback is not possible — so make the loop tight another way: print the answers (or a marking rubric) under a clearly delimited "Answers" heading at the end of the lesson, and always invite the user to bring their attempt back to the agent for review. The agent is the feedback channel.

**Answers are not optional.** Every exercise printed in a lesson — multiple-choice, fill-in-the-blank, short prompt, real-world task — must have its answer or expected outcome (rubric) printed in the same lesson file, under the "Answers" heading. A lesson rendered with an unanswered exercise is incomplete and must not ship. (2026-09-15: lesson 0001 shipped with unanswered Skills questions and the user had to ask for the key — the exact failure mode this rule prevents.)

**Notebook preference:** the user prefers **marimo** notebooks over Jupyter for lesson-created notebooks and exercises (reactive cells, no hidden state, stored as plain Python — see marimo.new); record the preference in each new workspace's `NOTES`. In an existing Jupyter-based workspace, engage with its notebooks as they are — don't convert wholesale unless asked. Wire the workspace's `.vscode/settings.json` so notebook files open in the marimo editor and every other `.py` file (figure/asset scripts, helper modules) keeps the default Python editor — see the `ipynb-to-marimo` skill's `workbench.editorAssociations` pattern (narrower `"default"` overrides first, the notebook glob last).

For printed multiple-choice questions (and in-chat options), construct the set so evenness is automatic — don't audit after the fact:

- Every option is a bare claim — no justification anywhere. All reasoning goes in the answer key / explanation revealed after the user answers. The #1 tell is the correct option carrying its own "because…" while distractors stay bare.
- Write the correct claim first, then mutate it into each distractor: one specific misconception or easily-confused neighbour per distractor, in the same skeleton, grain size, and register as the correct claim.
- Each distractor must be a real error the user might actually make (so which one they pick is diagnostic), yet unambiguously wrong — tempting, not tricky.
- No asymmetric bolding, and keep options near the same length (and characters, if possible).

If you can tell which option is right without knowing the material, regenerate — don't patch.

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

Glossaries, in particular, are an essential reference. Once one is created, it should be adhered to in every lesson.

## `NOTES`

The user will sometimes express preferences of how they want to be taught, or things you should keep in mind. This is the place to record those preferences, so you can refer back to them when designing lessons or working with the user. (Quarto flavor: `NOTES.qmd` with a `title` header so it renders like the rest; mdBook flavor: `NOTES.md` in the book's `src/`.)
