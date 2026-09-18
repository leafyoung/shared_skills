# Pi Agent Skills

Shared [Pi coding agent](https://github.com/mariozechner/pi-coding-agent) skills for batch processing, automation pipelines, and agent architecture patterns — plus other cross-project, agent-agnostic utilities kept here for sharing.

## Skills

| Skill | Description |
|---|---|
| [`agent-design-for-batch`](agent-design-for-batch/SKILL.md) | Architectural patterns for building robust batch processing systems with the Pi agent SDK — worker pools, stall detection, graceful shutdown, parallel prompt architectures. |
| [`ai-code-review`](ai-code-review/SKILL.md) | Writing code for LLM maintainability and setting up AI-assisted code review. |
| [`cpp-runtime-audit`](cpp-runtime-audit/SKILL.md) | Benchmark, profile, and audit compiled C++ programs (peak RSS, threading, runtime gotchas). |
| [`critical-research`](critical-research/SKILL.md) | Develop, deepen, or stress-test research or ideas with critical analysis. |
| [`manim-math-tutor`](manim-math-tutor/SKILL.md) | 一对一数学辅导：解答数学题，生成 HTML 讲解文档和带配音的 Manim 动画视频. |
| [`markitdown`](markitdown/SKILL.md) | Convert PDF, Word, and other documents to Markdown. |
| [`mental-models`](mental-models/SKILL.md) | Mental models and thinking frameworks (fs.blog collection) for reasoning about problems. |
| [`mean-reversion-testing`](mean-reversion-testing/SKILL.md) | Test for mean reversion in a series (ADF test, stationarity checks). |
| [`visualize`](visualize/SKILL.md) | Add one correct, minimal visual (diagram / geometric picture) when an idea is genuinely clearer as a picture. |
| [`notebook-output-dedup`](notebook-output-dedup/SKILL.md) | Deduplicate repeated output in Jupyter notebooks (e.g. charts rendered twice). |
| [`rust-harden`](rust-harden/SKILL.md) | Harden Rust code for production. |
| [`rust-runtime-audit`](rust-runtime-audit/SKILL.md) | Benchmark, profile, and audit compiled Rust programs. |
| [`teach`](teach/SKILL.md) | Teach the user a new skill or concept within the workspace. |

## Usage

Skills follow the standard Pi skill format (SKILL.md with YAML frontmatter). Install by copying the skill directory into your Pi skills directory; in this workspace they are symlinked from `../skills/` so agents discover them in place.

## License

MIT
