# Agentic SRE Team - Design Specification

> **Status:** Approved
> **Date:** 2026-07-11
> **Location:** `/agentic-sre-team` (new top-level directory in this monorepo)
> **Relationship to siblings:** Implements the incident slice of the
> `agentic-sre-framework` docs (agents 0, 1, 2, 2a, 2b) as a runnable system.
> `open-sre-agents` remains the AWS-native reference MVP; this system is the
> local-Docker / on-prem-portable successor.

## 1. What this is

A production-grade agentic system that acts as a functional SRE team for
incident response. It ingests events (Grafana alerts, human reports via
Telegram), triages them, runs a hypothesis-driven root cause analysis pulling
evidence from code, the observability layer (Grafana Cloud / LGTM), and the
infrastructure layer (Docker, optionally Kubernetes), and proposes fixes as
runbook artifacts. Humans approve every published artifact; the system never
executes state-changing actions.

Deployment target for v1: the operator's local Docker environment, using
Grafana Cloud for observability and Google Vertex AI for models. The
architecture is fully portable to an air-gapped on-prem environment by
swapping adapters (LiteLLM/vLLM for models, self-hosted LGTM for
observability, Mattermost for channels); every external dependency sits
behind a swappable adapter.

### Goals

- Prove the full loop locally: chaos event -> Grafana Cloud alert -> triage ->
  parallel evidence gathering -> evidence-cited RCA -> runbook draft -> human
  approval -> published to Telegram and visible in the ops UI.
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
  chain and timeline visualization.
- **Anthropic multi-agent lessons**: orchestrator-worker with parallel
  subagents only where work decomposes; effort scaled to complexity;
  a separate cheap citation-verification pass.

## 3. Architecture

Docker Compose on a single host. Services:

| Service | Image / stack | Purpose |
|---|---|---|
| `gateway` | Python 3.12, FastAPI, LangGraph 1.x, uv | Intake, noise control, case store, the case graph (library mode), REST + SSE API, Telegram bot (long polling), budget + audit |
| `ui` | React 18 + Vite + TypeScript, served by nginx | Ops console |
| `postgres` | postgres:16 | Case store + LangGraph checkpoints (AsyncPostgresSaver) |
| `grafana-mcp` | `mcp/grafana` (streamable HTTP) | Observability tools against Grafana Cloud (PromQL, LogQL, alert rules, Sift) |
| `sut` | Python FastAPI + OTel SDK | Demo "system under test": small posts API with chaos endpoints |
| `sut-db` | postgres:16 | SUT database |
| `alloy` | grafana/alloy | Ships SUT metrics + logs (and host/docker metrics) to Grafana Cloud |
| `provision` | one-shot Python container | Creates Grafana Cloud alert rules + webhook contact point via HTTP API; idempotent |

The gateway runs LangGraph as a library inside FastAPI (no LangGraph
Server, no LangSmith dependency). One incident case = one LangGraph thread,
checkpointed in Postgres, resumable across restarts.

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

**Evidence workers** (medium tier, one per domain, parallel):

- *metrics*: PromQL via Grafana MCP; alert-rule context; dashboards.
- *logs*: LogQL, log patterns, Sift error-pattern detection via Grafana MCP.
- *infra*: curated read-only Docker tools (list/inspect/logs/stats/events)
  over the mounted socket; optional kubectl read tools when a kubeconfig is
  mounted.
- *changes/code*: git log / diff of mounted target repos, deploy/docker
  events, ripgrep code search, file reads. Always runs - most incidents are
  change-induced.

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
plan, risk notes. Never executes anything - no write tools are bound.

**publish + close**. Posts approved artifacts to Telegram, indexes the
approved runbook into the runbook index (the value loop), closes the case.

**Governance inside the graph.** A budget envelope (tokens, tool calls,
wall-clock) is checked between nodes; breach halts the case in a
`needs-human` state and pages via Telegram. Per-agent YAML permission
manifests determine which tools are bound to which node at startup - a tool
not declared cannot be called. Every LLM invocation and tool call is appended
to the audit table (model id, prompt hash, tool args, response hash, latency).

## 5. Data model and API

Postgres tables: `cases` (status, severity, fingerprint, thread_id, budget
spend), `signals`, `hypotheses`, `evidence`, `artifacts` (kind rca|runbook,
version, raw + edited body, verification result), `approvals` (decision, who,
when, diff), `audit_events` (append-only; insert-only DB role), `runbooks`
(index corpus + embeddings), plus LangGraph checkpoint tables.

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
a config change only. The same adapter seam applies to channels (Telegram
now, Mattermost later) and observability (Grafana Cloud now; on-prem LGTM
exposes identical APIs and `mcp/grafana` works against both).

## 8. Tools and permissions

Tool groups, HolmesGPT-style, each config-gated and read-only:

- **observability** - loaded from the `grafana-mcp` container via
  `langchain-mcp-adapters` (allowlist of tools; not the full server surface).
- **docker** - curated wrappers over the read-only mounted socket.
- **kubernetes** (optional) - kubectl get/describe/logs/events when a
  kubeconfig is mounted.
- **code** - ripgrep search, file read, git log/blame/diff over read-only
  mounted target repos (v1: the SUT's own source).
- **runbooks** - semantic search over the runbook index.

Per-agent permission manifests (YAML in git) bind tool groups to nodes at
startup, default-deny. No write-capable tool exists in the codebase's tool
registry at all in v1.

## 9. Demo target and chaos

`sut`: a small FastAPI + Postgres "posts" API instrumented with the OTel SDK
(metrics + structured logs). `alloy` scrapes/collects and ships to Grafana
Cloud (Mimir + Loki), including docker/host metrics. Chaos endpoints on an
internal-only port: `/chaos/cpu` (CPU burn), `/chaos/errors` (5xx storm),
`/chaos/latency` (slow responses), `/chaos/db-down` (kill DB connectivity).

The `provision` one-shot creates matching Grafana Cloud alert rules (high
CPU, error rate, p95 latency, DB availability) and the webhook contact point
(when webhook mode is used). Makefile targets: `make up`, `make provision`,
`make chaos-<mode>`, `make demo` (fires chaos, tails the case).

Acceptance demo: `make chaos-errors` -> Grafana Cloud alert fires -> case
opens with Telegram ack -> parallel investigation visible live in the UI ->
RCA with citations reaches gate 1 -> approve in Telegram -> runbook reaches
gate 2 -> approve in UI -> both artifacts in Telegram, case closed. Target
under ~5 minutes end to end.

## 10. Error handling

- Gateway restart mid-case: thread resumes from the Postgres checkpoint.
- LLM/provider errors: tiered retry with backoff, then park the case in
  `needs-human` with all evidence preserved and a Telegram page.
- Tool errors: recorded as evidence-gathering failures on the worker result,
  never fatal to the case; workers proceed with partial evidence.
- Poller / Telegram adapters: supervised asyncio tasks with exponential
  backoff and health exposed on `/healthz`.
- MCP container unavailable: observability tool group degrades to disabled
  with an operator-visible warning; investigation proceeds on other domains.

## 11. Testing

- **Unit**: intake normalization, noise control (dedup/debounce/burst), HMAC
  verification, model factory, permission manifest loading, budget enforcer.
- **Graph**: full case-graph runs with a scripted fake chat model and
  recorded tool fixtures; asserts hypothesis-board transitions, interrupt
  placement, citation verification, budget halt.
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
- **`mcp/grafana` tool surface drift**: pinned image version + tool
  allowlist.
- Postmortem scribe and observability-engineer agents are the natural next
  slice after v1; the artifact and audit schemas already carry what they need.
