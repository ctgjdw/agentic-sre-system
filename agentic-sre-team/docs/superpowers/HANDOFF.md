# Handoff: Agentic SRE Team - implementation sessions

## Prompt to start the next session with

> The implementation plan for `/agentic-sre-team` is approved and committed
> (`f2abb3c`). Execute
> `agentic-sre-team/docs/superpowers/plans/2026-07-11-agentic-sre-team-implementation.md`
> using superpowers:subagent-driven-development (or superpowers:executing-plans
> for inline), starting at Phase 0. Read the plan header (Global Constraints,
> Locked implementation decisions, Execution conventions) plus this handoff
> before dispatching the first task. Do not re-litigate approved decisions and
> do not re-review the plan - it already passed an independent review.

## State (2026-07-12)

- Spec v1.3 approved (`docs/superpowers/specs/2026-07-11-agentic-sre-team-design.md`).
- Wireframes approved (`docs/design/wireframes-v1.html`).
- Implementation plan complete: 10 phases, 50 TDD tasks, committed `f2abb3c`.
  Reviewed by a separate fresh Fable agent; all findings fixed in the committed
  version (incl. a round-bounding off-by-one - the plan node now owns the round
  counter and a two-round graph test guards it).
- No implementation code exists yet. Phase 0 (walking skeleton) is next.

## How to execute

- One phase = one PR: branch `feat/sre-team-p<N>-<slug>` off `main`, merge
  before the next phase starts. Tasks within a phase run in order; every task
  ends with the full gateway suite green (`uv run pytest -q && uv run ruff
  check .`), not just its own tests.
- Use superpowers:using-git-worktrees if isolation from the working tree is
  needed before executing.
- Check in with the user at phase boundaries (their approval-gate preference);
  within a phase, run autonomously.
- Docs-check steps in the plan are load-bearing (HolmesGPT contract in Task 23,
  langchain-google kwargs in Task 25, Grafana provisioning in Task 48). Use
  Context7 / the plan's reference-docs table; if the real API drifts, fix the
  client AND the fake fixtures in the same commit - the fake profile is the
  regression net.
- Test fixtures (`deps`, `deps_two_rounds`, `client`, `pipeline_deps`,
  `chat_service`) accrete in `gateway/tests/conftest.py` - never copied per
  file. DB tests use testcontainers (local Docker required).
- Task 46 (chaos middleware) is a separate PR in `~/Code/spectre` - that
  repo's conventions, branched per its CONTRIBUTING.md. Merge it before the
  error-storm acceptance demo so the changes worker can find the origin commit.

## Environment prerequisites by phase

- Phases 0-3 and 5: nothing external - the fake profile (scripted model + fake
  Holmes) covers everything, `make smoke` proves it.
- Phase 4+: Grafana Cloud stack + SA token, Vertex project (Gemini + Claude in
  Model Garden; `make live-check` verifies), pinned HolmesGPT image, optional
  LangSmith key. Phase 6: Telegram bot + group + allowed user ids. Phase 7:
  GitHub token (+ GitLab token and the `spectre-mirror` repo for the live
  GitLab path). Fill `.env` from `.env.example`; never commit `.env`.

## Approved decisions (do not reopen)

Unchanged from the design phase - the plan's Global Constraints section
restates them; the ten-item list lives in git history of this file and in
`docs/superpowers/specs/2026-07-11-agentic-sre-team-design.md`. Headlines:
LangGraph 1.x as a library in FastAPI (no LangGraph Server), Spectre as the
reference SUT (chaos-only changes; the SUT itself is config-described - see
the amendment below), HolmesGPT pinned sidecar as the evidence engine,
models.yaml tiers (Gemini Flash small/medium, Claude-on-Vertex frontier,
air-gap via LiteLLM), LangSmith env-gated, GitHub+GitLab behind one
ScmProvider, `scm_draft_mr` off by default and never an agent tool, the
triage->plan->parallel-workers->synthesize->rca->verify->gate1->remediate->
gate2->publish graph with budgets between nodes, Telegram-only channel,
default-deny manifests, append-only audit.

2026-07-12 amendment (user direction; plan locked decisions 15-16): the system
is generic - `config/environment.yaml` describes the target environment and
every SUT-aware prompt renders from it, so Spectre is only the shipped example
(chaos scripts + alert rules are reference-SUT demo assets). The Holmes
evidence layer additionally uses the Grafana MCP server (`mcp_servers` entry),
`grafana/tempo` (comparative fast/slow trace sampling), and
`elasticsearch/data` + `elasticsearch/cluster` replacing the notional
`opensearch` key (OpenSearch-compatible; the cluster toolset is explicitly for
cluster-health and query-latency investigation), with `openshift/*` flipped on
- as a reviewed git change - for OpenShift-platform targets.

## User's working preferences observed this project

- Research-first before decisions; cite sources. Approval gates between
  phases; AskUserQuestion works well.
- Major planning artifacts get a cold review by a separate Opus-class agent
  before commit; findings verified (not blindly applied) first.
- Conventional commits, scope `sre-team` for code / `agentic-sre-team` for
  docs, no agent co-author line, plain dashes (no em dash).
- Pre-existing dirty file `agentic-sre-framework/docs/llm-ops-spec/...` in the
  monorepo is unrelated - never stage it.
