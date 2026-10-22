---
name: visualize
description: >-
  Add ONE correct, minimal visual — a diagram or geometric picture — when an idea is genuinely clearer as a picture: dependency graph, system/flow, sequence, state machine, tree, comparison, or spatial/geometric content (coordinate geometry, number lines, vectors, plots, physical layouts). Outsources authoring+rendering to a maker subagent (mermaid-maker / svg-maker) that verifies the image by looking at it, then you embed the returned file in a lesson, doc, or chat reply.
---

# Visualize

A picture earns its place only when it shows something words can't — shape, structure, direction, relationship, geometry. This skill produces ONE such picture, guaranteed **correct** (the maker renders it and looks at it before returning), and embeds it where the reader will see it.

You are the **creative director**. You decide the exact idea and distill it to its fewest carrying elements. A **maker subagent** does the authoring, rendering, visual verification, and saving, then returns a filename. You embed that file.

## When to visualize (and when not to)

Reach for one when:

- The idea is a **structure or relationship**: dependencies, a system with parts and arrows, a flow/pipeline, a sequence of exchanges, a state machine, a tree/hierarchy, a comparison, containment.
- The idea is **spatial or geometric**: coordinate geometry, a number line, vectors, a function's shape, a physical arrangement.

Do NOT visualize when prose or a single equation already carries it. A decorative diagram that just restates the sentence next to it adds noise and a chance to be wrong. When in doubt, don't — a missing visual is cheaper than a false one.

## Choose the maker

Two makers, discovered from `~/.pi/agent/extensions/subagents/agents/`:

- **`mermaid-maker`** — structural/relational visuals: dependency graphs, flowcharts, sequence/state/ER/class diagrams, trees, mindmaps, timelines. The default; renders via mermaid-cli.
- **`svg-maker`** — spatial/geometric visuals Mermaid can't lay out: exact coordinates, geometry figures, number lines, vectors, plots, custom shapes. Renders via `rsvg-convert`.

Rule of thumb: *nodes-and-edges / relationships* → mermaid-maker. *positions-and-shapes / geometry* → svg-maker.

## Brief the maker well: one idea, fewest elements

The most common failure is **cramming** — every extra label makes the picture harder to read AND harder to lay out correctly. Prune to the fewest elements that carry the idea; for each ask *"if I delete this, is the idea still clear?"* If yes, delete it.

Give the maker the concept AND the concrete elements — not a vague topic, not a long checklist:

- BAD: "make a diagram about how TCP works"
- GOOD: "graph TD: node 'packet' at top; arrows down to 'ordering' and 'retransmit on loss'; both into 'reliable stream'. No title. Show that reliability is built FROM packets, not alongside them."

If your brief lists more than ~5–7 elements, cut it first. The PNG publishes into the session's working directory under `viz/` with a unique name — for a lesson workspace, dispatch from the workspace root so `viz/` lands there.

## Invoke

Dispatch with the `subagent` tool:

```
subagent(agent="mermaid-maker", task="<minimal, concrete brief>")
subagent(agent="svg-maker", task="<minimal, concrete brief>")
```

The maker has purpose-built tools (`write_*` / `edit_*` / `render_*`): it authors the source, renders a PNG that is returned **inline so it can look at it**, iterates until correct and clean, then publishes via `save_as: <short-kebab-slug>` into `<cwd>/viz/viz-<slug>-<timestamp>.png` and returns:

```
RESULT:
filename: <slug>.png
path: <absolute path>
```

If it returns `RESULT FAILED:`, it couldn't make a correct picture of the brief — simplify or rethink, or decide the visual isn't worth it. Never hand-author or fake a diagram yourself; correctness depends on the maker's render-and-inspect loop.

## Embed it

- In a Quarto/Typst lesson or any markdown doc: standard embed with the returned path relative to the project root — `![caption](viz/viz-<slug>-<timestamp>.png)`; control size with Quarto's `{width=...}` attribute when needed.
- In a chat reply: give the path so the user can open it.

Introduce the visual in one sentence, then let it carry the idea — don't narrate every element back in prose.

## Why this is reliable

- The maker never returns a picture it hasn't **looked at**, so "renders fine but says something false" is caught before it reaches the reader.
- PNG embed means what the maker verified is pixel-identical to what the reader sees — no re-render drift.
