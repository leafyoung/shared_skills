# DIAGRAMS.md — relationship diagrams in lessons: routing and the 45-type touch-point map

Teach-side companion to the **diagram-design** skill (when installed). That
skill owns diagram *craft*: type selection detail, semantic patterns, the
editorial design system, the complexity budget (≤9 nodes, target density 4/10),
templates, and export. This file adds only what is teach-domain: when a course
author reaches for a diagram, which of the 45 types fits, and how the output
becomes a regenerable lesson asset.

## Diagram vs illustration — the boundary

- **Illustration**: quantities or geometry carry the meaning (curve shape,
  distribution, ladder of stakes). *Evidence* — must show the lesson's own
  numbers → charting script, reproducible (Assets rule).
- **Diagram**: relationships between discrete ideas carry the meaning (depends
  on / flows to / contains / happens-after / positioned against). *Structure* —
  schematic values suffice → diagram-design when installed, else mermaid.
- **Straddle zone** (bar, line/scatter families, heatmap, treemap, waterfall,
  Sankey, quadrant, pyramid exist in both worlds): if the lesson's exact
  numbers must show, it is an illustration; if structure and style lead, it is
  a diagram.

## Routing

0. **Onboard once per project — after the first illustrations exist.** The
   chart scripts fix the course figure palette: sample paper (page
   background), ink (primary text), accent (the charts' primary series
   color), and muted (secondary) from the illustration constants or their
   rendered PNGs, then onboard diagram-design with its paste-tokens option
   (d): darken the accent until text roles clear 4.5:1 on paper, save it as
   a named profile (`~/.diagram-design/profiles/<slug>.md`) and write the
   project `.diagram-design` marker (mechanics: diagram-design's
   `references/profiles.md`). No illustrations yet → skip onboarding and
   keep the default editorial skin — never half-match a skin or edit the
   installed skill's own `style-guide.md`.
1. `diagram-design` skill installed in the session → invoke it for the diagram;
   follow its selection guide, complexity budget, and export scripts. In
   autonomous runs skip its confirm-before-drawing pause and note the
   assumptions beside the deliverable.
2. Not installed → `mermaid-maker` subagent (or a ```` ```mermaid ```` block:
   mdBook — wire `mdbook-mermaid`; Quarto — ```` ```{mermaid} ````).
3. Hand-build (svg-maker / figure script) only when neither applies.
4. In-chat planning artifacts (the plan-phase dependency map) stay mermaid —
   fast and throwaway. Reach for diagram-design when the figure becomes a
   keeper embedded in the book.

Embed mechanics: export PNG/SVG via the skill's export scripts into
`mdbook/src/assets/unitN/` (embed from there per the Assets rule); keep the
HTML source plus any brand profile in `<unit>/assets/` — the HTML is the
figure's regeneration source. After installing or updating the package:
`/reload`, and `pi update --extensions` pulls merged changes.

## The 45 types by teaching situation

### Course architecture and planning (keeper figures for plan pages, unit overviews)

| Type | Reach for it when the lesson teaches… |
| --- | --- |
| Dependency graph | the course's own node map as a keeper: what depends on what, fan-in, cycles a tree can't show |
| Tree | a taxonomy: parent → children decompositions (a language's construct families, a discipline's branches) |
| Nested | containment/scope: what sits inside a runtime, standard, permission scope, era |
| Org chart | ownership, reporting, routing, escalation: who owns what, where requests go |
| Timeline | history: discoveries, versions, standards events positioned in time |
| Gantt | a plan with durations and overlaps: course/project phases on a calendar |
| Story map | the planned course as a narrative backbone sliced into units, with the cut line (plan page) |

### Concept structure (the Connect move inside lessons)

| Type | Reach for it when the lesson teaches… |
| --- | --- |
| Flowchart | decision logic the learner must internalize (branch rules, classification procedures) |
| Sequence | protocols/handshakes between parties: request/response, negotiation, authentication |
| State machine | lifecycles with guards: order/process/connection states, phases, retries, cancellation |
| UML class | OOP lessons: classes, operations, inheritance, composition |
| ER / data model | conceptual entities + relationships (data modeling before SQL) |
| Database schema | physical tables: keys, types, constraints, indexes (SQL lessons) |
| Loop | reinforcing cycles: compounding, feedback loops, vicious/virtuous circles |
| Venn | overlap between two sets: shared properties of tools, schools, concepts |
| Quadrant | two-axis positioning/comparison: tools, strategies, trade-off spaces |
| Pyramid / funnel | ranked levels or drop-off: mastery tiers, conversion stages |
| Layer stack | stacked abstractions and "where does X sit" (network layers, storage tiers) |
| Fishbone | root-cause analysis of one observed effect (debugging, post-mortem lessons) |
| Wardley map | evolution against value chain: build/buy, what is commoditizing (strategy lessons) |

### Systems and processes (end-to-end "how it happens")

| Type | Reach for it when the lesson teaches… |
| --- | --- |
| Architecture | one-snapshot system: components + connections, including nested scopes |
| Architecture delta | a before/after topology change: migration, refactor, cutover |
| IT current-state | the legacy baseline a modernization story starts from |
| Deployment | where software runs: zones, hosts, artifacts, replicas, ports (infra lessons) |
| Process | a multi-stage sequential process with per-stage inputs/outputs and governance |
| Swimlane | cross-functional handoffs: who does what across stages |
| Data flow | role-scoped movement of data through a pipeline: who does what at each step |
| High-Level | the end-to-end stack snapshot (e.g., the modern data platform on one page) |
| Medallion | data-quality tiers with access policies (bronze/silver/gold) |
| DP integration | platform integration topology: sources → core → consumers |
| DP security matrix | who-can-access-what, per role or component |
| Kanban | work by state with WIP limits and blocked items (workflow/ops lessons) |

### Human-centered

| Type | Reach for it when the lesson teaches… |
| --- | --- |
| User journey | what a person does and feels across the stages of an experience |
| Service blueprint | frontstage vs backstage across stages, with the line of visibility |

### Physical and spatial

| Type | Reach for it when the lesson teaches… |
| --- | --- |
| Exploded axonometric | teardown/assembly of an artifact: parts pulled apart along one axis |
| Axonometric plan | a site/floor seen from above at an angle: rooms, buildings by phase |

### Quantitative-schematic (straddle zone — apply the boundary rule first)

| Type | Reach for it when the lesson teaches… |
| --- | --- |
| Bar chart | comparison of magnitude across categories |
| Waterfall | a start→end bridge by signed contributions (budget bridges, P&L walks) |
| Treemap | part-of-whole where relative size is the story |
| Heatmap | cross-tabulated intensity, fill encodes the value per cell |
| Line chart | trends over time; slopegraph (two states), ridgeline (distribution per series), bump (rank movement) |
| Scatter plot | two-variable correlation/distribution; bubble (three variables), beeswarm (dot per item) |
| Radar | a few entities scored across 3–5 criteria |
| Polar | one series across cyclic categories (hours, months) |
| Sankey | a quantity splitting and merging across stages, band width = amount |
