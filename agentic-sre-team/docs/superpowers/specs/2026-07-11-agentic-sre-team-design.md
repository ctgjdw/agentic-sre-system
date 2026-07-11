# Agentic SRE Team - Design Specification

> **Status:** Approved
> **Date:** 2026-07-11
> **Location:** `/agentic-sre-team` (new top-level directory in this monorepo)
> **Relationship to siblings:** Implements the incident slice of the
> `agentic-sre-framework` docs (agents 0, 1, 2, 2a, 2b) as a runnable system.
> `open-sre-agents` remains the AWS-native reference MVP; this system is the
> local-Docker / on-prem-portable successor.

## 1. What this is

A production-grade agentic system that acts as a functional SRE/DevSecOps
team. It handles two case kinds through one pipeline:

1. **Incidents** - ingests events (Grafana alerts, human reports via
   Telegram), triages them, runs a hypothesis-driven root cause analysis
   pulling evidence from code, the observability layer (Grafana Cloud /
   LGTM), and the infrastructure layer (Docker, optionally Kubernetes), and
   proposes fixes as runbook artifacts.
2. **Pipeline failures (DevSecOps)** - ingests failed CI/CD pipeline events
   from GitHub Actions and GitLab CI, investigates (job logs, pipeline
   config, triggering diff, run history), classifies the failure (code /
   test / config / dependency / infra-runner / flaky / permissions), produces
   an RCA, and proposes fixes as runbook artifacts with concrete patches.

Source code and IaC live on GitHub and GitLab; both are supported behind one
SCM adapter interface. Humans approve every published artifact. Agents never
execute state-changing actions; the only write the system can perform at all
is opening a draft MR/PR for an approved fix, and only after explicit human
approval with the feature enabled (see the remediate node).

Deployment target for v1: the operator's local Docker environment, using
Grafana Cloud for observability and Google Vertex AI for models. The system
under test is **Spectre** (`~/Code/spectre`), the operator's existing IAM
admin console stack (Keycloak, Postgres, Express admin-server, React
admin-ui, Kong, OpenSearch, Fluent Bit, Alloy shipping to Grafana Cloud,
GitHub Actions CI) - already dockerized and instrumented; this project only
adds chaos injection. Evidence gathering is powered by **HolmesGPT** (CNCF
sandbox) running as a sidecar container, whose built-in toolsets cover the
operator's integrations (Docker, OpenShift, GitHub, GitLab, Prometheus,
Loki/Tempo/Grafana, OpenSearch, Postgres). Agent runs are traced to
**LangSmith cloud** (free plan, env-gated).

The architecture is fully portable to an air-gapped on-prem environment by
swapping adapters (LiteLLM/vLLM for models - HolmesGPT is LiteLLM-based so
the same swap covers it, self-hosted LGTM for observability, Mattermost for
channels, tracing disabled or self-hosted); every external dependency sits
behind a swappable adapter.

### Goals

- Prove the full loop locally: chaos event -> Grafana Cloud alert -> triage ->
  parallel evidence gathering -> evidence-cited RCA -> runbook draft -> human
  approval -> published to Telegram and visible in the ops UI.
- Prove the DevSecOps loop: failed GitHub Actions / GitLab CI pipeline ->
  triage + failure classification -> RCA citing job logs, config, and diff ->
  fix proposal (runbook + patch) -> human approval -> published.
- Honor the framework's governance pillars: human-in-command, deterministic
  routing, budgets, permission manifests, append-only audit.
- Modern agentic UI: live-streaming investigation timeline, hypothesis board,
  evidence viewer with citations, approval gates.

### Non-goals (v1)

- Executing remediations (drafts only, always).
- The non-incident agents from the framework roster (SysAdmin Drafter,
  Security Triage, Compliance Evidence, Postmortem Scribe, Observability
  Engineer). The data model leaves room for them.
- Mattermost/Slack adapters (Telegram only; channel adapter interface keeps
  the seam).
- Multi-tenant / RBAC in the UI.

## 2. Research grounding

Design decisions below trace to:

- **Google SRE practice** (IMAG): mitigate before root-causing; living
  incident document; communications-lead status updates; playbooks accelerate
  response.
- **Commercial AI SREs** (Traversal, Cleric, Datadog Bits AI, Rootly):
  hypothesis-driven parallel investigation; causally consistent diagnosis with
  ranked alternatives; recent-change correlation as the highest-value signal;
  read-only agentless integration; confidence scores with visible reasoning.
- **HolmesGPT (CNCF) / OpenDerisk**: config-gated read-only toolsets (MCP
  supported); evidence-centric reasoning to reduce hallucination; causal
  chain and timeline visualization. HolmesGPT is adopted directly as the
  evidence-gathering engine: its server mode exposes `/api/chat` with
  per-request model selection, structured `response_format`, SSE
  tool-execution events, and a complete `tool_calls` transcript per
  response.
- **Anthropic multi-agent lessons**: orchestrator-worker with parallel
  subagents only where work decomposes; effort scaled to complexity;
  a separate cheap citation-verification pass.
- **GitLab Duo Root Cause Analysis / Fix Pipeline flow**: pipeline-failure
  RCA follows summarize -> analyze -> propose-fix over four evidence sources
  (failed job logs with exit codes, pipeline config, merge-request diff,
  repository contents); run history distinguishes flaky from deterministic
  failures.

## 3. Architecture

Docker Compose on a single host. Services:

| Service | Image / stack | Purpose |
|---|---|---|
| `gateway` | Python 3.12, FastAPI, LangGraph 1.x, uv | Intake, noise control, case store, the case graph (library mode), REST + SSE API, Telegram bot (long polling), budget + audit |
| `ui` | React 18 + Vite + TypeScript, served by nginx | Ops console |
| `postgres` | postgres:16 | Case store + LangGraph checkpoints (AsyncPostgresSaver) |
| `holmes` | HolmesGPT server (pinned image) | Evidence-gathering engine: HTTP `/api/chat` with SSE tool events; toolsets configured for Grafana Cloud (Prometheus/Loki/Tempo), Docker (read-only socket), GitHub, GitLab, OpenSearch, Postgres |
| `provision` | one-shot Python container | Creates Grafana Cloud alert rules (matched to Spectre failure modes) + webhook contact point via HTTP API; idempotent |

The system under test is not part of this compose stack: **Spectre runs from
its own repo's `docker-compose.yml`**, unchanged except for the added chaos
capability (section 9). Both stacks join a shared external Docker network so
the Holmes docker toolset can observe Spectre's containers by name.

The gateway runs LangGraph as a library inside FastAPI (no LangGraph
Server). One case = one LangGraph thread, checkpointed in Postgres,
resumable across restarts. **LangSmith tracing** (cloud free plan) is
enabled via standard env vars (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`) and
covers the whole LangGraph plane - every node, prompt, and token count per
case. HolmesGPT's internal LLM loop is not LangSmith-traced; its complete
tool-call transcript is captured into the case's evidence and audit records
instead, so no investigative step is unrecorded. Tracing is optional and off
in air-gapped profiles.

**Why HolmesGPT as a sidecar (server mode) rather than the Python SDK:**
dependency isolation (Holmes ships its own LiteLLM-based stack), pinned
independent upgrades, per-request `model` selection that preserves the tier
config, and SSE tool events that relay directly into the live progress
ledger. The SDK path would couple two heavy dependency trees inside the
gateway for no functional gain.

### Intake paths

1. **Grafana webhook** - `POST /webhooks/grafana`, standard Grafana alerting
   JSON payload, HMAC-SHA256 verified. Used as-is on-prem where Grafana can
   reach the gateway.
2. **Grafana poller** - background task polling the Grafana Cloud alerting API
   for firing alert instances. Default for local laptops (no public URL or
   tunnel needed). Deduplicates against webhook intake by alert fingerprint.
3. **Telegram reports** - bot via long polling. Messages in the configured
   group/DM become human-report signals. The bot also carries outbound
   notifications and approval buttons.
4. **Pipeline failures** - GitHub `workflow_run` webhooks (conclusion:
   failure) and GitLab pipeline-event webhooks (status: failed), both
   signature-verified, for environments where the SCM can reach the gateway;
   plus a poller against the GitHub Actions / GitLab pipelines APIs for
   configured repositories (default for local laptops). Normalized by the
   SCM adapter into the same `Signal` envelope with `kind:
   pipeline_failure`.

All intake normalizes to a `Signal` envelope (source, reporter, received_at,
payload, fingerprint) per the framework spec, then passes noise control:
fingerprint dedup within a rolling window (attach to existing open case),
debounce, burst suppression (N similar signals in M seconds collapse to one
case), and a cheap incident-likelihood score for chat messages so low-value
chatter gets a canned reply and no agent spend. Suppression events are
audit-logged and counted on the governance page.

## 4. The case graph

One durable `StateGraph` encodes the case lifecycle. Deterministic edges own
all routing; LLMs decide only within nodes. Model tiers per node come from
`models.yaml` (section 7).

```
signal -> [triage] -> [plan] -> fan-out via Send:
                                  [metrics worker]
                                  [logs worker]      -> [synthesize] --loop?-->
                                  [infra worker]          |            (bounded)
                                  [changes/code worker]   v
                              <------------------------- [rca] -> [verify citations]
                                                                        |
                                                            HITL gate 1 (RCA)
                                                                        |
                                                                  [remediate]
                                                                        |
                                                            HITL gate 2 (runbook)
                                                                        |
                                                              [publish + close]
```

**triage** (small tier). Classifies the signal, proposes severity, checks
dedup context, searches the runbook index, seeds the hypothesis board
(3-6 candidate explanations), picks the effort level, and posts an
acknowledgment to Telegram. Very-low-confidence non-incidents end here with a
canned response.

**plan** (deterministic). Maps effort level to workers: low severity -> one
sequential worker chosen by signal type; medium/high -> parallel fan-out of
all four workers via the `Send` API. Rounds are bounded (max 2 investigation
rounds).

**Evidence workers** (medium tier, one per domain, parallel). Each worker is
a thin LangGraph node that delegates to the **HolmesGPT sidecar** via
`POST /api/chat`: a domain-scoped investigation prompt carrying the current
hypothesis board, a `response_format` JSON schema for hypothesis-tagged
findings, and the tier-appropriate `model`. Holmes runs the tool loop
against its configured toolsets; the worker streams Holmes's SSE tool events
into the case's live ledger and maps every `tool_calls` entry into an
`Evidence` record (toolset, invocation, raw result excerpt, timestamp,
hypothesis links). Worker domains and their Holmes toolsets:

- *metrics*: Prometheus toolset against Grafana Cloud (PromQL, alert rules).
- *logs*: Loki + OpenSearch toolsets (Spectre's audit and app logs land in
  both Grafana Cloud Loki and local OpenSearch).
- *infra*: Docker toolset over the read-only socket (Spectre's containers:
  keycloak, admin-server, kong, opensearch, fluent-bit, alloy); OpenShift/
  Kubernetes toolset available for the on-prem profile; Postgres toolset for
  DB-level checks.
- *changes/code*: GitHub + GitLab toolsets (recent commits, diffs, MRs/PRs,
  file contents, code search). Always runs - most incidents are
  change-induced.
- *ci* (pipeline-failure cases): failed job logs with exit codes, pipeline
  config (workflow YAML / .gitlab-ci.yml), the triggering diff, and run
  history of the same job across recent commits and retries (flaky
  detection), via the GitHub/GitLab toolsets.

Worker scoping is by prompt, not by per-request toolset gating; the set of
toolsets Holmes may use at all is fixed in its config file (in git), which
serves as the permission manifest for the evidence layer.

**Case kinds route to different worker sets.** Incident cases fan out to
metrics / logs / infra / changes. Pipeline-failure cases run ci + changes by
default, adding infra only when evidence points at runners or registries.
Triage classifies pipeline failures into: code, test, config, dependency,
infra-runner, flaky, permissions - and the classification is a field on the
case, revisable by synthesis.

Each worker is a bounded tool-loop that must attach every tool result as an
`Evidence` record (query, raw result excerpt, source link, timestamp, worker,
hypothesis links for/against). Workers see the hypothesis board and report
per-hypothesis findings plus any new hypothesis they propose.

**synthesize** (medium tier; frontier on escalation). Updates the hypothesis
board (supported / refuted / open, confidence), decides whether evidence
suffices or one more bounded round is needed, and posts an "early findings"
status update to Telegram. Escalation to the frontier tier happens only when
confidence is low or severity is high (framework cost discipline).

**rca** (frontier tier). Produces the RCA artifact: immediate mitigation
first (Google: mitigate before root-causing), then root cause as a causal
chain, blast radius, incident timeline, ranked alternative explanations and
why they were rejected, and monitoring gaps observed. Every claim must cite
evidence IDs.

**verify citations** (small tier). Checks each claim cites existing evidence
and the evidence supports it; one bounded repair loop back to `rca` on
failure. Verification results are stored on the artifact.

**HITL gates** via `interrupt()`. Gate 1 before the RCA is published, gate 2
before the runbook is published. Approve / approve-with-edits / reject, from
the UI or Telegram inline buttons; both resume the thread via
`Command(resume=...)`. Rejection loops back with the reviewer's annotation.
Original and edited artifact versions are both stored.

**remediate** (frontier tier). Drafts the fix as a runbook artifact:
pre-checks, steps (commands, config diffs, manifests), post-checks, rollback
plan, risk notes. For pipeline-failure cases the runbook includes a concrete
patch (workflow YAML / .gitlab-ci.yml / code diff). Never executes anything
during drafting - no write tools are bound to the drafting node. One
config-gated exception exists at publish time: when `scm_draft_mr` is
enabled, gate-2 approval may additionally push the patch to a new branch and
open a **draft** MR/PR (never merged, never to a protected branch), matching
the framework's Remediation Engineer contract. Off by default.

**publish + close**. Posts approved artifacts to Telegram, indexes the
approved runbook into the runbook index (the value loop), closes the case.

**Governance inside the graph.** A budget envelope (tokens, tool calls,
wall-clock) is checked between nodes; breach halts the case in a
`needs-human` state and pages via Telegram. Per-agent YAML permission
manifests determine which tools are bound to which node at startup - a tool
not declared cannot be called. Every LLM invocation and tool call is appended
to the audit table (model id, prompt hash, tool args, response hash, latency).

## 5. Data model and API

Postgres tables: `cases` (kind incident|pipeline_failure, status, severity,
failure_class for pipeline cases, fingerprint, thread_id, budget spend),
`signals`, `hypotheses`, `evidence`, `artifacts` (kind rca|runbook, version,
raw + edited body, verification result), `approvals` (decision, who, when,
diff), `audit_events` (append-only; insert-only DB role), `runbooks` (index
corpus + embeddings), `repos` (watched repositories: provider github|gitlab,
slug, credentials reference, poll state), plus LangGraph checkpoint tables.

API (FastAPI):

- `POST /webhooks/grafana` - HMAC-verified alert intake.
- `GET /cases`, `GET /cases/{id}` - queue and detail (signals, hypotheses,
  evidence, artifacts, approvals, timeline).
- `GET /cases/{id}/stream` - SSE relaying the graph's `updates` / `custom` /
  `messages` stream events for the live timeline; replays recent events on
  reconnect.
- `POST /cases/{id}/decision` - approve / approve-with-edits / reject a gate;
  resumes the thread.
- `GET /governance` - per-agent budgets and spend, manifests, suppression
  stats; `POST /governance/pause` - global pause switch (audit-logged).

## 6. UI

React + Vite + TypeScript ops console (not a chatbot). Dark, dense,
SRE-flavored. Screens:

1. **Case queue** - severity, status, age, live-activity indicator.
2. **Case detail** - three-pane: live agent timeline (streamed node/tool
   events, collapsible tool results), hypothesis board (per-hypothesis status,
   confidence, evidence for/against), evidence panel with deep links to
   Grafana Explore.
3. **Artifact view** - rendered RCA (causal chain + timeline visualization)
   and runbook, per-claim citation chips that jump to evidence, approval bar
   with approve / edit-with-diff / reject.
4. **Governance** - per-agent spend vs budget, manifests, suppression counts,
   global pause.

Streaming via native `EventSource` against the SSE endpoint; state via
TanStack Query. No LangGraph-Server-specific client libraries, keeping the
frontend decoupled from the runtime choice.

## 7. Model provider layer

`ModelFactory` reads `config/models.yaml`: three tiers (`small`, `medium`,
`frontier`), each mapping to `provider`, `model`, and params. Providers:

- `vertex-gemini` - Gemini 2.5 Flash / Pro via the consolidated
  `langchain-google-genai` SDK with `vertexai=True`.
- `vertex-anthropic` - Claude via `ChatAnthropicVertex`
  (`langchain-google-vertexai`).
- `openai-compatible` - `ChatOpenAI` with `base_url`, covering LiteLLM proxy
  or vLLM directly.

Local profile: small/medium = Gemini 2.5 Flash, frontier = Claude Sonnet on
Vertex. Air-gap profile: all tiers -> LiteLLM -> MiniMax on vLLM. Swapping is
a config change only.

The same `models.yaml` drives HolmesGPT: it is LiteLLM-based and accepts a
`model` per request, so evidence workers pass their tier's model string
(e.g. `vertex_ai/gemini-2.5-flash`) with each call, and the air-gap swap
covers Holmes with no extra work. The same adapter seam applies to channels
(Telegram now, Mattermost later) and observability (Grafana Cloud now;
on-prem LGTM exposes identical APIs and Holmes's toolsets work against
both).

## 8. Tools and permissions

The evidence layer is HolmesGPT's toolset registry, enabled per toolset in
`config/holmes.yaml` (in git, version-pinned image). Enabled for the local
profile: prometheus, grafana/loki, docker (read-only socket), github,
gitlab, opensearch, postgres. The on-prem profile adds openshift/kubernetes
and swaps Grafana Cloud endpoints for the self-hosted LGTM stack. All
enabled toolsets are read-only; Holmes's tool-approval feature stays off
because no write-capable toolset is enabled at all. This config file is the
permission manifest for the evidence layer; changing it is a reviewed git
change.

Gateway-side tool groups (bound to LangGraph nodes by per-agent YAML
manifests, default-deny):

- **runbooks** - semantic search over the runbook index (triage, synthesize,
  remediate).
- **scm intake/publish** - a unified `ScmProvider` interface with GitHub and
  GitLab implementations, used by the intake poller/webhooks (pipeline
  events, job metadata) and by publish actions. Not exposed to any LLM node
  as a free tool.

The single write capability in the system - branch push + draft MR/PR
creation for approved fixes - is not an agent tool at all. It is a
gateway-side publish action that runs only on gate-2 approval with
`scm_draft_mr` enabled, using a separate credential scoped to branch
creation.

Per-agent permission manifests (YAML in git) bind tool groups to nodes at
startup, default-deny. No write-capable tool exists in the codebase's tool
registry at all in v1.

## 9. System under test: Spectre + chaos injection

The SUT is the operator's existing **Spectre** stack (`~/Code/spectre`):
Keycloak 26.6 + Postgres, Express admin-server, React admin-ui, Kong edge
gateway, OpenSearch audit store, Fluent Bit, and Alloy already shipping
metrics/logs to Grafana Cloud. GitHub Actions CI (`ci.yml`,
`container-scan.yml`, `security.yml`, `lint-workflows.yml`) already exists.
Spectre stays deployed from its own compose file; this project contributes
chaos capability only, in two layers:

1. **App-level chaos middleware in admin-server** (small PR to the Spectre
   repo): an Express middleware mounted only when `CHAOS_ENABLED=true`
   (default off, never in the production profile), controlled via an
   internal-only endpoint. Modes: `error-storm` (inject 5xx on a percentage
   of API responses), `latency` (delay responses), `cpu` (event-loop burn),
   `memory` (heap growth). This exercises the code-level RCA path (the
   agents should trace symptoms to the middleware's origin commit).
2. **Docker-level chaos scripts in this repo** (no Spectre changes):
   `scripts/chaos.sh` drives realistic infra failures - stop/pause
   `keycloak` (login outage), stop `keycloak-db` (Keycloak degradation),
   stop `opensearch` (audit pipeline backpressure through Fluent Bit), pause
   `kong` (edge outage). These exercise the infra RCA path.

The `provision` one-shot creates Grafana Cloud alert rules matched to
Spectre's failure modes (admin-server error rate and p95 latency via Kong /
OTel metrics, Keycloak availability, OpenSearch indexing lag, container-down
signals from Alloy) plus the webhook contact point when webhook mode is
used. Makefile targets: `make up`, `make provision`, `make chaos-<mode>`,
`make demo`.

Acceptance demo: `make chaos-error-storm` -> Grafana Cloud alert fires ->
case opens with Telegram ack -> parallel Holmes-backed investigation visible
live in the UI -> RCA with citations reaches gate 1 -> approve in Telegram
-> runbook reaches gate 2 -> approve in UI -> both artifacts in Telegram,
case closed. Target under ~5 minutes end to end.

DevSecOps demo: Spectre's GitHub Actions CI is the target. `make chaos-ci`
pushes a branch with a seeded failure (dependency pin typo or failing Vitest
case) -> the poller picks up the failed `ci.yml` run -> pipeline-failure
case opens, classified -> RCA cites the job log lines, workflow config, and
diff -> runbook with patch reaches gate 2 -> approval (optionally opening a
draft PR when `scm_draft_mr` is on). The GitLab adapter is validated with
contract tests plus a minimal mirror repo on gitlab.com running the same
seeded-failure flow.

## 10. Error handling

- Gateway restart mid-case: thread resumes from the Postgres checkpoint.
- LLM/provider errors: tiered retry with backoff, then park the case in
  `needs-human` with all evidence preserved and a Telegram page.
- Tool errors: recorded as evidence-gathering failures on the worker result,
  never fatal to the case; workers proceed with partial evidence.
- Poller / Telegram adapters: supervised asyncio tasks with exponential
  backoff and health exposed on `/healthz`.
- Holmes container unavailable or a toolset failing: the affected worker
  records the failure as evidence-gathering degradation with an
  operator-visible warning; investigation proceeds on other domains, and the
  synthesize node factors the gap into confidence.

## 11. Testing

- **Unit**: intake normalization, noise control (dedup/debounce/burst), HMAC
  verification, model factory, permission manifest loading, budget enforcer.
- **Graph**: full case-graph runs with a scripted fake chat model and a
  **fake Holmes server** (recorded `/api/chat` responses with realistic
  `tool_calls` transcripts) - one incident scenario and one pipeline-failure
  scenario per SCM provider; asserts hypothesis-board transitions, worker
  routing by case kind, evidence mapping from Holmes transcripts, failure
  classification, interrupt placement, citation verification, budget halt.
- **SCM adapters**: contract tests against recorded GitHub/GitLab API
  fixtures so both providers satisfy the same `ScmProvider` behavior.
- **API/UI**: FastAPI TestClient for REST/SSE contract; Vitest + Testing
  Library for UI components; one Playwright smoke over queue -> detail ->
  approve.
- **E2E smoke** (`scripts/smoke.py`): posts a canned Grafana payload to the
  webhook, drives the case to gate 1 with the fake-model profile, asserts an
  RCA artifact with valid citations exists.
- **Live chaos path**: the acceptance demo above against real Grafana Cloud +
  Vertex, run manually.

## 12. Risks and open items

- **Grafana Cloud poller latency** vs webhook immediacy: poll interval 30s
  default; acceptable for a local demo, tunable.
- **Vertex quota / model availability** (Claude on Vertex requires Model
  Garden enablement in the project region); the model factory makes falling
  back to Gemini Pro a one-line config change.
- **Token cost of parallel investigation**: bounded by effort scaling,
  round limits, and budget envelopes; governance page makes spend visible.
- **HolmesGPT coupling**: its toolset behavior and response schema can drift
  across releases; mitigated by a pinned image, the fake-Holmes test
  fixtures acting as a contract, and the thin-worker seam (workers only
  depend on `/api/chat` + `tool_calls`, so replacing Holmes with native
  workers later stays a bounded change).
- **Split observability of agent runs**: LangSmith traces the LangGraph
  plane but not Holmes internals; the case's evidence/audit records carry
  the Holmes transcript, and deeper Holmes tracing is a later option.
- Postmortem scribe and observability-engineer agents are the natural next
  slice after v1; the artifact and audit schemas already carry what they need.
