# Handoff: Agentic SRE Team - next session

## Prompt to start the next session with

> The design for `/agentic-sre-team` is approved (spec v1.3). Invoke the
> superpowers:writing-plans skill and produce the phased implementation plan
> from `agentic-sre-team/docs/superpowers/specs/2026-07-11-agentic-sre-team-design.md`
> and the wireframes at `agentic-sre-team/docs/design/wireframes-v1.html`
> (published: https://claude.ai/code/artifact/0c38c752-bc27-4de2-a9f8-7e827cdea8c6).
> Read both plus this handoff before planning. Do not re-litigate approved
> decisions.

## State

- Spec approved through v1.3 (commit `ddcc419`), including three revision
  rounds driven by user feedback: DevSecOps/GitHub+GitLab, Spectre/HolmesGPT/
  LangSmith, and chat surface/Robusta review.
- Wireframes approved (same commit, same review).
- No implementation code exists yet. Next step is the implementation plan,
  then build.

## Approved decisions (do not reopen)

1. **Runtime**: LangGraph 1.x as a library inside FastAPI (no LangGraph
   Server). One case = one thread, AsyncPostgresSaver. Air-gap portable.
2. **SUT**: the user's existing Spectre stack at `~/Code/spectre` (Keycloak,
   Kong, OpenSearch, Alloy -> Grafana Cloud, GitHub Actions). We add chaos
   only: env-gated Express middleware PR to spectre + docker-level chaos
   scripts here. No dummy demo app.
3. **Evidence engine**: HolmesGPT server mode as a pinned Docker sidecar
   (`/api/chat`, SSE tool events, per-request model). Thin LangGraph workers
   delegate scoped asks; Holmes toolsets = prometheus, loki, docker, github,
   gitlab, opensearch, postgres (config in git = evidence-layer manifest).
4. **Models**: tiers in `models.yaml` - Gemini 2.5 Flash (small/medium),
   Claude on Vertex (frontier); air-gap = LiteLLM -> MiniMax on vLLM. Holmes
   is LiteLLM-based so the same swap covers it.
5. **Tracing**: LangSmith cloud free plan, env-gated, off in air-gap.
6. **Case kinds**: `incident` and `pipeline_failure` (GitHub Actions +
   GitLab CI), unified `ScmProvider`. Optional gated draft-MR publish
   (`scm_draft_mr`, off by default) - a gateway publish action, never an
   agent tool.
7. **Graph**: triage -> plan -> parallel evidence workers (Send API, effort
   scaled) -> synthesize (bounded rounds) -> rca -> verify-citations ->
   gate 1 -> remediate -> gate 2 -> publish/close. Hypothesis board in
   state; case learnings written at close and retrieved at triage.
8. **Intake**: Grafana webhook + poller; Telegram long polling; GitHub/GitLab
   pipeline webhooks + poller; chat kickoff (thread promoted to case).
   Noise control includes cross-signature correlation grouping.
9. **UI**: React + Vite ops console per wireframes - case queue (with
   activity timeline strip), case detail (ledger / hypothesis board /
   evidence), artifact review (citations + outcome-preview approvals),
   governance, and the chat surface (ad-hoc, case-context, workflow-kickoff;
   budget-capped; cannot approve gates).
10. **Governance**: per-agent YAML manifests (default-deny), budget envelopes
    checked between nodes, append-only audit, global pause. HITL at both
    gates, from UI or Telegram inline buttons.

## User's working preferences observed this project

- Research-first before design decisions; cite sources.
- Approval gates before each phase transition; AskUserQuestion works well.
- Conventional commits, no agent co-author line, plain dashes (no em dash).
- Spec + wireframes live in `agentic-sre-team/docs/`; update artifacts in
  place at the same URL.

## Plan-shaping hints for writing-plans (suggestions, not decisions)

- Phase the build so every phase ends demoable: scaffold + compose + intake
  -> case graph with fake model/fake Holmes -> real Holmes + Grafana Cloud ->
  UI screens -> Telegram + gates e2e -> pipeline-failure kind -> chat
  surface -> chaos + provisioning + acceptance demos.
- The fake-Holmes fixture server and scripted fake chat model are the
  backbone of graph tests - build them early.
- The Spectre chaos middleware is a separate small PR in `~/Code/spectre`
  (its own repo, gitflow, conventional commits).
