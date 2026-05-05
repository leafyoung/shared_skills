# Pi Agent Skills

Shared [Pi coding agent](https://github.com/mariozechner/pi-coding-agent) skills for batch processing, automation pipelines, and agent architecture patterns.

## Skills

| Skill | Description |
|---|---|
| [`agent-design-for-batch`](agent-design-for-batch/SKILL.md) | Architectural patterns for building robust batch processing systems with the Pi agent SDK — worker pools, stall detection, graceful shutdown, parallel prompt architectures. |

## Usage

Skills follow the standard Pi skill format (SKILL.md with YAML frontmatter). Install by copying the skill directory into your Pi skills directory.

### Keeping in sync

If you maintain these skills locally, use the sync script to pull the latest versions:

```bash
./sync.sh agent-design-for-batch
```

This copies the skill from your local `../skills/` directory into the repo, ready to commit and push.

## License

MIT
