# CLAUDE.md

@AGENTS.md

## Claude Code Notes

- All project context, hard air-gap/OSS-only constraints, monorepo map, current build state, commands, and working conventions live in [`AGENTS.md`](AGENTS.md) so every agentic IDE/CLI shares one source of truth.
- For subagent/branch workflows in `agentic-sre-team/`, see `agentic-sre-team/docs/superpowers/HANDOFF.md`, noting that all laptop-specific paths (`~/Code/agentic-ons/...`, `~/.claude/projects/...`) are deprecated in favor of git-tracked docs (`AGENTS.md` and `docs/2026-11-research-and-architecture-review.md`).
- When completing a phase or changing an architectural decision, update `AGENTS.md` in git before finishing your session.
