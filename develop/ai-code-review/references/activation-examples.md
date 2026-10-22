# Activation Examples

Use this file to audit whether `ai-code-review` should trigger.

## Should trigger

| Prompt | Why |
| --- | --- |
| "Refactor this service so another AI agent can maintain it easily." | Explicit LLM-maintainability request. |
| "Simplify this architecture and remove hidden state." | Architecture simplification and explicit-state goals are core to the skill. |
| "Make this codebase easier to regenerate after future changes." | Regenerability is a primary trigger. |
| "Review this module for over-abstraction and improve naming and logging." | Requests maintainability-oriented structure, naming, and logging decisions together. |
| "Update AGENTS.md with the durable rules you discovered while refactoring." | Repo instruction hygiene is part of the workflow rules. |

## Should not trigger

| Prompt | Why not |
| --- | --- |
| "Fix this off-by-one bug in my loop." | Bug fix only; no maintainability or AI-agent requirement. |
| "Add a dark mode toggle to this page." | Feature delivery, not LLM-first design work. |
| "Speed up this SQL query." | Performance task with no maintainability constraint. |
| "Make this button blue and align it left." | Cosmetic styling only. |
| "Write a unit test for this helper." | Narrow testing task; no codebase-shaping or LLM-maintainability goal. |

## Borderline prompts

| Prompt | Default decision | Reason |
| --- | --- | --- |
| "Refactor this component for readability." | Usually no | Trigger only if the request expands into maintainability strategy, explicit state, architecture simplification, or agent-friendly structure. |
| "Improve naming in this file." | Usually no | Naming alone is too broad unless the user frames it as AI/agent maintainability or regeneration work. |
| "Add logging around this endpoint." | Usually no | Trigger only if the request is about structured logging policy or maintainability standards rather than just instrumentation. |
| "Clean up this repo." | Depends | Trigger if cleanup means simplifying structure, removing hidden state, or making the repo easier for future agents to modify. |
| "Document this module." | Depends | Trigger if the documentation is part of durable repo instructions or maintainability rules; otherwise treat it as a normal docs task. |
| "Refactor to OOP / add classes." | Depends | Trigger if the refactoring is about reducing scattered state and argument threading. Do not trigger if it is a mechanical wrap-everything-in-classes request with no maintainability goal. |

## Practical heuristic

Trigger this skill when the user is asking how code should be shaped for future change, future debugging, or future AI-agent maintenance.

Do not trigger this skill when the user is only asking what code should do right now.
