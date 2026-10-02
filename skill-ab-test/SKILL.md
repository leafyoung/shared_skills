---
name: skill-ab-test
description: >-
  A/B test a skill version by regenerating its artifacts fresh and comparing
  against artifacts made by the older version. Use when the user asks to
  "A/B test this skill", "regenerate with the new skill and compare against
  the old outputs", "check whether the skill rewrite improved or regressed",
  "validate a skill refactor against real outputs", or wants to turn
  old-vs-new artifact differences into concrete skill edits. The artifact is
  anything a skill produces end to end (a course, a document set, a codebase
  scaffold); the reference instance is a teach-skill A/B over three study
  courses. Not for reviewing the skill text itself (use a meta-review for
  that) - this skill measures outputs.
---

# Skill A/B test: regenerate fresh, compare, improve the skill

Measure whether the current version of an artifact-producing skill produces
better work than an older version did, and convert the deltas into skill edits.
The design goal is a fair experiment: **same control inputs, different skill**,
with the generating agents never knowing they are in a test.

## Phase 0 - Ground truth (orchestrator only)

1. Pick 2-3 **small** existing artifacts made by the old skill version. Size
   them first (disk, unit counts); verify provenance (they really came from the
   old version) and that each is self-contained enough to regenerate.
2. For each, extract the **control inputs** - the brief the artifact was built
   from (mission, spec, requirements) and its **vehicle** (external material
   the work anchors on: a codebase, a dataset, a source document). The
   orchestrator is the ONLY one who reads the old artifact from here on.
3. Note **input asymmetries** honestly (e.g. the old run had session-history
   material the new run cannot have). Record them as threats to validity in the
   final report - never patch them by leaking extra context to the new run.
4. Snapshot nothing over the originals: they stay untouched as the A side.

## Phase 1 - Hermetic regeneration (parallel subagents)

One subagent per artifact, dispatched in parallel. Each prompt contains:

- **The task as a first-time task.** "Follow the current skill exactly: read
  `<skill path>/SKILL.md`, then everything it directs." Never mention the old
  version, the comparison, A/B, v1/v2, or that this is a test. Keep neutral
  workspace names - no `redo`, `v2`, `compare` in any path the agent sees.
- **The control inputs**, verbatim or near-verbatim (same inputs the old run
  had, minus documented asymmetries).
- **One-go constraint.** The complete deliverable in this single session:
  full artifact, built/verified per the skill's own bar, committed.
- **Access restrictions (hard).** Enumerate forbidden roots (the old artifacts'
  directories) and the allowlist (own workspace, the skill files, the vehicle,
  the web). Seed **copies** of any vehicle that lives inside a forbidden root
  into the new workspace, so the restriction needs no exceptions.
- **No interactivity.** Forbid `ask_user_question` and waiting; require an
  assumptions ledger. Note: this constraint is itself a test surface - if the
  skill has no autonomous-mode provision, the agent will improvise one, and
  that improvisation gap is a finding.
- A final-report format (deliverable inventory, counts, verification results,
  rules applied, assumptions) so the three runs are comparable before reading
  a single artifact.

## Phase 2 - Comparison (read-only agents, fixed rubric)

One comparison agent per old/new pair - contamination no longer matters. It
reads both artifacts in full and reports, evidence-cited (file:line):

1. **Inventory table** - units, sizes, structure, state/meta files, build
   health, both sides.
2. **Conformance audit** against the CURRENT skill's own rules, scored for
   each side separately (this shows whether the old artifact violated rules
   the new one now enforces, and whether the new one actually follows them).
3. **Quality dimensions specific to the artifact type** - for each, a
   definition up front.
4. **Paired-sample depth check** - the 2 most comparable units (same topic
   both sides), compared for depth, clarity, grounding; one short quoted
   excerpt per side as evidence. Verify disputed technical claims against the
   underlying source.
5. **What the old does better** - candidate regressions to repair.
6. **What the new does better** - confirmations of the current skill.
7. **Ranked skill-edit candidates** - each with evidence, proposed wording,
   the section it belongs in, and severity.

## Phase 3 - Improve the skill

- **Convergent findings first** (same gap seen in 2+ pairs): these become
  rules. Single-pair findings: apply by judgement, note the source.
- **Mode findings are not rules.** Deltas caused by the generation mode
  itself (interactive multi-session vs autonomous one-go: session-driven
  discoveries, ZPD calibration, user-steered scope) cannot be fixed by
  wording alone - they become a *mode/shape option* in the skill, or a
  constraint on what one mode may claim.
- Apply edits with verified anchors; after any multi-edit script, re-verify
  EVERY edit site individually (a mid-script failure plus an eager commit has
  shipped partial rule sets). One commit for the improvement set, message
  naming the findings.
- Threats to validity go in the final report next to the findings they
  affect: model/thinking-level parity, input asymmetries, artifact-pair
  sample size.

## Pitfalls (all encountered in practice)

- The generator's own report is not conformance evidence - it claims the
  rules it believes it followed; only the comparison audit checks the
  artifact.
- Comparison agents find fabricated content (an invented answer-key
  explanation contradicting the quoted source) - verify their disputed-claim
  citations yourself before writing rules from them.
- Excluding a deliverable class from comparison (e.g. notebooks when the
  generation mode differs) is fine - say so in both the generator prompt and
  the comparison rubric so neither side optimizes for it.
- The orchestrator reading old artifacts for briefs is the one sanctioned
  leak; keep the brief to control inputs only - never the old artifact's
  structure, lesson list, or content decisions.

## Reference instance

2026-10-03, teach skill: three study courses (async Rust, RL for portfolio
optimization, limit-order-book engines in three languages) regenerated in one
autonomous go by hermetic subagents at neutral paths, compared by three rubric
agents, distilled into 11 teach edits (autonomous mode, verification pass,
vehicle probing, retrieval cadence, MCQ mechanics, ephemeral-context
harvesting, ...) plus a course-shape option (planned vs session-driven) for
the delta that was structural to the generation mode. Findings reused here:
attempt-first Socratic prompts, one-go completion, assumptions ledgers,
forbidden-root access lists, paired-depth samples with source verification.
