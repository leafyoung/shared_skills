---
name: mental-models
description: |
  This skill should be used when the user asks about "mental models",
  "fs.blog mental models", "thinking frameworks", "decision-making tools",
  "latticework of mental models", "how to think better", "cognitive toolbox",
  "mental model for [topic]", "teach mental models", "write about mental models",
  "apply mental model[s]", "Farnam Street models", "Charlie Munger models",
  "decision frameworks", "models from [discipline]", or wants to improve
  critical thinking, decision-making, writing, or teaching using proven
  cross-disciplinary frameworks.
version: 1.0.0
---

# Mental Models: The Great Mental Models Library

A mental model is a simplified explanation of how something works. Like a map,
mental models highlight key information while ignoring irrelevant details.
They're tools for compressing complexity into manageable chunks.

> *"If you want to be a good thinker, you must develop a mind that can jump the
> jurisdictional boundaries. You don't have to know it all. Just take in the best
> big ideas from all these disciplines."* — Charlie Munger

This library documents ~100 mental models drawn from Farnam Street (fs.blog),
organized into 8 disciplines. Each model includes its core idea, explanation,
pedagogical guidance, and writing application.

---

## Table of Contents

Each discipline has its own reference file. Load the relevant one when needed.

| # | Discipline | Models | Reference File |
|---|-----------|--------|----------------|
| 1 | **General Thinking Tools** | 9 meta-models for how to think about thinking | `references/general-thinking-tools.md` |
| 2 | **Physics, Chemistry & Biology** | 20 models from the natural sciences | `references/physics-chemistry-biology.md` |
| 3 | **Systems Thinking** | 11 models for understanding complex systems | `references/systems-thinking.md` |
| 4 | **Mathematics & Numeracy** | 7 models for probabilistic and numerical reasoning | `references/mathematics.md` |
| 5 | **Economics** | 12 models of scarcity, competition, and cooperation | `references/economics.md` |
| 6 | **Art & Storytelling** | 11 models of communication, perception, and narrative | `references/art-storytelling.md` |
| 7 | **Military & War** | 5 models of strategy and competition | `references/military-war.md` |
| 8 | **Human Nature & Judgment** | 23 models of cognitive biases and behavioral drivers | `references/human-nature-judgment.md` |

---

## Quick Reference by Application Need

| If you need to... | Start with these models | Full reference |
|---|---|---|
| Make a better decision | Inversion, Second-Order Thinking, Margin of Safety, Probabilistic Thinking | [General Thinking](references/general-thinking-tools.md) + [Systems](references/systems-thinking.md) |
| Understand why people act | Incentives, Bias from Incentives, Social Proof, Commitment and Consistency Bias | [Human Nature](references/human-nature-judgment.md) + [Bio](references/physics-chemistry-biology.md) |
| Write persuasively | Framing, Audience, Narrative Instinct, Plot, Contrast | [Art & Storytelling](references/art-storytelling.md) |
| Analyze a system | Feedback Loops, Bottlenecks, Ecosystems, Equilibrium, Scale | [Systems Thinking](references/systems-thinking.md) |
| Innovate / create | First Principles, Creative Destruction, Alloying, Thought Experiment | [General Thinking](references/general-thinking-tools.md) + [Economics](references/economics.md) |
| Avoid mistakes | Inversion, Hanlon's Razor, Confirmation Bias, Survivorship Bias | [General Thinking](references/general-thinking-tools.md) + [Human Nature](references/human-nature-judgment.md) |
| Teach effectively | Curiosity Instinct, Narrative, Contrast, Setting, Analogies | [Art](references/art-storytelling.md) + [Human Nature](references/human-nature-judgment.md) |
| Understand competition | Red Queen Effect, Niches, Asymmetric Warfare, Creative Destruction | [Bio](references/physics-chemistry-biology.md) + [Military](references/military-war.md) |
| Evaluate an argument | Map Is Not the Territory, Circle of Competence, Falsification | [General Thinking](references/general-thinking-tools.md) + [Human Nature](references/human-nature-judgment.md) |
| Plan under uncertainty | Probabilistic Thinking, Margin of Safety, Scenario Planning | [General Thinking](references/general-thinking-tools.md) + [Systems](references/systems-thinking.md) |

---

## Using This Skill

### Progressive Loading

This skill uses progressive disclosure. Load only what you need:

1. **SKILL.md** (this file) — Overview, table of contents, and quick-reference
   tables. Enough for basic use and navigation.
2. **`references/`** — Load the discipline-specific file when you need
   detailed explanations, pedagogical notes, and writing applications for
   models in that category.
3. **Cross-referencing** — Many problems benefit from combining models across
   disciplines. The quick-reference table above suggests which combinations
   are most useful for common tasks.

### How Each Model Is Structured

Every model in the reference files follows the same four-part format:

- **Core idea** — The essence in one sentence
- **Explanation** — Practical, teachable prose with concrete examples
- **Pedagogical use** — How to teach this model to others
- **Writing application** — How to use this model as a writer

### Teaching Mental Models

When introducing a model to students or readers:

1. State the **core idea** in one sentence
2. Give a **concrete example** from everyday life
3. Ask: "Where does this model **break down** or not apply?"
4. **Connect** it to other models — mental models work best in combination
5. Use **paired models** for deeper understanding:
   - Second-Order Thinking + Inversion
   - Confirmation Bias + Falsification
   - Leverage + Margin of Safety
   - Evolution + Red Queen Effect

### Combining Models

The real power of mental models comes from using them together. A few
powerful combinations:

- **Inversion + Margin of Safety + Second-Order Thinking** — Before any
  major decision, ask what would guarantee failure, build buffers, and trace
  ripple effects.
- **Incentives + Confirmation Bias + Availability Heuristic** — To understand
  why someone holds a belief, ask what they gain from it, what evidence they're
  ignoring, and what examples come most easily to mind.
- **Circle of Competence + First Principles + Thought Experiment** — When
  venturing outside your expertise, break problems down to fundamentals and
  test assumptions mentally before acting.

---

## References

The detailed content for each discipline is in separate reference files:

- [`references/general-thinking-tools.md`](references/general-thinking-tools.md)
  — 9 general thinking tools
- [`references/physics-chemistry-biology.md`](references/physics-chemistry-biology.md)
  — 20 natural science models
- [`references/systems-thinking.md`](references/systems-thinking.md)
  — 11 systems thinking models
- [`references/mathematics.md`](references/mathematics.md)
  — 7 numeracy models
- [`references/economics.md`](references/economics.md)
  — 12 economics models
- [`references/art-storytelling.md`](references/art-storytelling.md)
  — 11 art & storytelling models
- [`references/military-war.md`](references/military-war.md)
  — 5 military strategy models
- [`references/human-nature-judgment.md`](references/human-nature-judgment.md)
  — 23 human nature & judgment models

### Source Material

Most models are drawn from Farnam Street's Great Mental Models series:
[farnamstreetblog.com/mental-models](https://fs.blog/mental-models/)

Key reference works:
- *The Great Mental Models* (Volumes 1-4) — Shane Parrish & Rhiannon Beaubien
- *Poor Charlie's Almanack* — Charlie Munger
- *Thinking, Fast and Slow* — Daniel Kahneman
- *The Art of Thinking Clearly* — Rolf Dobelli
- *Influence* — Robert Cialdini
