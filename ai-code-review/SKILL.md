---
name: ai-code-review
description: This skill should be used when the user asks to "write code for LLM maintainability", "set up an AI-first codebase", "optimize code for LLM reasoning", "apply AI-first coding principles", "make code easy to regenerate", "write code that LLMs can maintain", "structure code for AI agents", "refactor for maintainability", "simplify architecture for AI agents", or "apply LLM-friendly coding guidelines". Make sure to use this skill whenever the user wants code, structure, logging, naming, configuration, documentation, or refactoring choices optimized for explicitness, predictability, regenerability, or maintenance by future LLMs, even if they do not mention LLMs explicitly. Do not use this skill for ordinary bug fixes, feature additions, styling work, or performance tuning unless the user also wants maintainability or agent-friendly restructuring.
---

# AI Coding

Produce code that is predictable, debuggable, and easy for future LLMs to rewrite or extend. Optimize for model reasoning, regeneration, and debugging rather than human cleverness.

## Default Mode

Assume the next maintainer is another LLM with no memory of the current session. Prefer flat structure, explicit state, declarative configuration, and structured logs.

## Activation Boundary

Use this skill when the task is mainly about maintainability strategy, architecture simplification, explicit state, declarative configuration, structured logging policy, repo instructions, or refactoring code so future LLMs can reason about it quickly.

Do not use this skill for routine bug fixes, isolated feature delivery, cosmetic cleanup, or pure performance work unless the user explicitly asks for those changes to be done in an LLM-first or maintainability-first way.

For example trigger decisions, see `references/activation-examples.md`.

## Workflow Rules

### Rule 1: Work one discrete unit at a time
- Prefer delegating each significant unit of work to a subagent (e.g. the `subagent` tool).
- If subagents are unavailable, keep the main session scoped to one discrete unit at a time.
- Finish the unit, verify it, record any durable repo-wide rule, then move on.

**Exception:** Handle a trivial one-file fix directly when delegation would add more overhead than clarity.

### Rule 2: Read current documentation before using non-trivial technology
- Read current documentation before using a non-trivial language feature, framework, library, or external API.
- Use the documentation tools available in the environment, such as web search or page fetch tools.
- Confirm the current API and idioms before implementing.
- If current docs are unavailable, say so explicitly and proceed with conservative assumptions.

**Exception:** Skip external doc lookup for simple repo-local patterns or stable language basics already visible in the codebase.

### Rule 3: Update instruction files only with durable rules
- Update existing `.github/copilot-instructions.md`, `AGENTS.md`, `agent.md`, or `CLAUDE.md` files when a task reveals a durable repo-wide rule, workflow, dependency, or verification requirement.
- Keep living documentation accurate.
- Do not add one-off local quirks or temporary investigation notes.

**Exception:** Leave instruction files unchanged when the work teaches nothing reusable outside the current edit.

### Rule 4: Verify before handoff
- Run the strongest available automated test or check.
- Verify build, lint, or type-check steps when applicable.
- Confirm observable behavior matches intent.
- If full verification is not possible, state exactly what was checked and what remains unverified.

**Exception:** For documentation-only changes, verify by rereading the edited content and checking internal consistency.

### Rule 5: Keep terminal state clean
- Reuse existing terminals where possible.
- Close terminals that are no longer needed.

## Code Rules

### Rule 1: Prefer predictable structure
- Use a consistent, obvious layout.
- Group code by feature, screen, or workflow.
- Keep shared utilities minimal and easy to locate.
- Identify shared structure before scaffolding repeated files.
- Treat duplication that requires the same fix in multiple places as a problem.

**Exception:** Keep a small amount of duplication when an abstraction would hide behavior or tightly couple unrelated modules.

### Rule 2: Prefer flat, explicit architecture
- Prefer flat code over deep hierarchies.
- Avoid clever patterns, metaprogramming, and unnecessary indirection.
- Minimize coupling so one file or module can be regenerated without cascading breakage.

**Exception:** Use framework-native composition or a thin shared wrapper when it clearly removes repeated boilerplate without hiding control flow.

### Rule 3: Keep functions linear and state explicit
- Keep top-level control flow linear.
- Use small-to-medium functions.
- Pass state explicitly.
- Avoid hidden globals and import-time side effects.

**Exception:** Extract a helper or wrapper when it removes repeated risky I/O, validation, or error-handling logic.

### Rule 4: Use names and comments that survive context loss
- Use descriptive, simple names.
- Write comments only for invariants, assumptions, external requirements, or non-obvious constraints.
- Do not narrate obvious code.

**Exception:** Add a short orienting comment at the start of a dense workflow when the code is otherwise easy to misread.

### Rule 5: Log at boundaries, not everywhere
- Emit structured logs at a medium level.
- Log workflow boundaries, wrappers around external I/O, retries, failures, and explicit state transitions.
- Prefer stable fields such as `event`, `module`, `function`, `status`, `duration_ms`, `entity_id`, and `attempt`.
- Make errors explicit: state what failed, where it failed, and the safe identifier or value involved when safe to log.

**Exception:** Avoid logging inside small pure helper functions unless they wrap risky or opaque behavior. Avoid trace noise and payload dumps.

### Rule 6: Optimize for regenerability
- Write each file so it can be rewritten from scratch without surprising the rest of the system.
- Prefer declarative configuration such as JSON or YAML where practical.
- Avoid hidden setup during import or initialization.

**Exception:** Use imperative setup when the platform requires it, but keep the setup local, explicit, and easy to replace.

### Rule 7: Use platform conventions directly
- Use the platform's standard routing, configuration, state, and library patterns.
- Avoid abstractions that merely rename platform primitives.

**Exception:** Add a thin adapter only when it isolates unstable external APIs or removes repeated error-prone glue code.

### Rule 8: Modify code in proportion to the change
- Follow existing local patterns unless those patterns cause the problem.
- Rewrite a small cohesive file when behavior or structure changes substantially.
- Use targeted edits for isolated fixes so small changes stay small.

**Exception:** Preserve a slightly imperfect local pattern when changing it would force a wide unrelated rewrite.

### Rule 9: Test observable behavior
- Favor deterministic behavior.
- Keep tests simple and focused on inputs and outputs.
- Avoid tests that lock in implementation details.

**Exception:** Test an implementation detail only when it is itself the public contract, such as a required log schema or serialization format.

## OOP / Object-Oriented Design Guidance

When working in a language that supports OOP (Python, C++, Java, Rust, etc.), apply classes only where they reduce total code by consolidating state that multiple functions already thread through. Do **not** introduce classes to wrap stateless logic.

### When a class is worth it

Introduce a class when **all three** conditions hold:

1. **Shared state** — two or more functions receive the same 3+ arguments (a dataset, a config dict, a schema) on every call.
2. **Lifecycle** — the state is prepared once (validated, constructed) then consumed by multiple operations.
3. **Net line-count reduction** — replacing the repeated argument passing + standalone dataclass with a class that owns its methods produces fewer total lines.

Typical good candidates:
- A `TaskModel` that binds (dataset, feature_table, task_definition) and exposes `.predict_loo()`, `.predict_grouped()`, `.metrics` — replacing a dataclass + 5 functions that all take the dataclass as their first argument.
- A `Project` that owns a root path and provides `.load_master()`, `.load_features()`, `.paths.figures_dir` — replacing 15 module-level path constants + 7 free functions.
- A result object (e.g. `TaskPrediction`) with computed properties (`.rmse`, `.r2`, `.mae`) and a serialization method (`.as_dict()`) — replacing a dict with inconsistent key names across call sites.

### When a class is NOT worth it

- **Pure data transforms** — functions that take data in, return data out, and share no mutable state. Keep these as free functions.
- **Single-use wrappers** — a class instantiated and called once, where a function with explicit arguments is equally clear.
- **"Manager" / "Handler" / "Service" objects with no real state** — these are just namespaces. Use a module instead.
- **Replacing a dict** — if the dict is consumed by one caller and never validates its shape, a TypedDict or dataclass is lighter than a class with methods.

### Concrete anti-patterns to avoid

| Anti-pattern | Why it bloats | What to do instead |
|---|---|---|
| Abstract base class for one implementation | Adds 20+ lines of indirection for zero polymorphism | Use a concrete class; add the ABC later if a second implementation appears |
| Builder / fluent API for a 3-argument constructor | Hides what's actually required behind chained calls | Plain `__init__` or a `classmethod` factory |
| Strategy pattern via class hierarchy for 2 model types | Spreads 30 lines across 3 files for a simple `if/elif` | A registry dict mapping name → constructor kwargs |
| DTO → Entity → Service layered architecture for a CLI script | Triple the files, same behavior | One module with functions, or one class if the state-sharing test passes |

### Checklist before adding a class

- [ ] At least 2 functions currently pass the same 3+ arguments on every call
- [ ] The class replaces more lines than it adds (count functions eliminated vs methods added)
- [ ] No abstract base class unless a second concrete subclass already exists
- [ ] The class has real mutable or prepared state — not just a namespace for related functions
- [ ] Existing callers (scripts, notebooks, tests) can migrate with minimal import changes

### Relationship to existing rules

- This refines **Code Rule 2 (flat, explicit architecture)**: a class that eliminates repeated argument passing is *more* explicit than threading the same 4 arguments through 5 functions. But a class that adds layers without removing duplication is a hierarchy that should stay flat.
- This refines **Code Rule 6 (optimize for regenerability)**: a well-scoped class with a clear constructor and a few methods is easy to regenerate. A deep inheritance tree or an over-factored composition root is not.

## Refactor Audit

To audit a codebase for LLM alignment, use `references/refactor-audit-prompt.md`. The audit should:
1. load these principles,
2. search the full codebase,
3. produce prioritized findings grouped as High / Medium / Lower,
4. save the result to `llm-refactor-plan.md` in the project root.

## Quick Checklist

Before submitting any code:

- [ ] The task was handled as one discrete unit, or the split between units is explicit
- [ ] Top-level control flow is linear and helper logic stays shallow
- [ ] State and configuration are explicit; no hidden globals or import-time side effects
- [ ] Each file or module can be understood and regenerated in isolation
- [ ] Structured logs exist at workflow boundaries, external I/O, retries, failures, and state transitions
- [ ] Helper functions are not cluttered with trace-level logging or payload dumps
- [ ] Errors state what failed, where it failed, and the safe identifier or value involved
- [ ] Current docs were checked for non-trivial external technology, or missing docs were called out explicitly
- [ ] Declarative configuration is used where practical instead of imperative setup
- [ ] The strongest available verification was run, and any remaining gaps are stated plainly
- [ ] Project instruction files were updated only for durable repo-wide rules
- [ ] Classes introduced only where they replace scattered argument threading and reduce total line count (see OOP Guidance section)
