# Agentic SRE Framework — Architecture

> **Status:** Draft for review
> **Date:** 2026-06-25
> **Audience.** Engineers only. This is the buildable architecture for
> implementers. It is **not** an exec document — value/risk/cost framing lives in
> `docs/framework/01–02`.
> **Relationship to the design spec.** Derived from and subordinate to
> `docs/framework-spec/2026-06-22-agentic-sre-framework-design.md` (the "design
> spec"). The design spec is the source of truth for *what* and *why*; this
> document is *how* — it binds the spec's capability ports to a concrete harness.
> Where this document and the design spec disagree, the design spec wins and this
> document is a bug.
> **Harness decision.** CORE is built on **LangGraph (OSS, MIT)** with **LiteLLM**
> as the LLM gateway, **OPA/Cerbos** as the tool-authorization policy engine, and
> **Langfuse + OpenTelemetry** for traces. Rationale and alternatives are in §2
> and Appendix D. The commercial **LangGraph Platform / Server (`langgraph-api`,
> Elastic License) is explicitly NOT used** — see §2.3.

---

## 1. Purpose & scope

This document describes the runtime architecture of the Agentic SRE Framework
CORE and its adapters: the processes, their responsibilities, the data and event
flows between them, the state model, and the deployment topology. It maps every
governance guarantee in design-spec §4 to a concrete mechanism in the chosen
harness.

It does **not** restate the agent roster (design-spec §3), the workflow mappings
(design-spec §5), or the rollout plan (design-spec §7) except where architecture
depends on them.

**Invariants inherited from the design spec (non-negotiable):**

1. Human-in-command — every state-changing action passes the HITL gate (§4.3 of
   the design spec). No agent merges, deploys, or mutates a target.
2. One supervisor, one append-only audit log per case.
3. Default-deny tooling — an agent calls only tools declared in its permission
   manifest.
4. Substrate- and adapter-portable — CORE depends only on a container runtime and
   the capability ports in §6; never on Swarm- or K8s-specific APIs.

---

## 2. Key architectural decisions

ADR-style summary of the binding decisions. Each is load-bearing for the rest of
the document.

| # | Decision | Rationale | Consequence |
|---|---|---|---|
| AD-1 | **LangGraph OSS (MIT) library is the orchestration/HITL/state core** | First-party durable `interrupt`/`resume`, Postgres + Redis checkpointers, MIT, runs fully offline, deploys as a plain container | CORE is a Python service embedding LangGraph; no platform/operator dependency |
| AD-2 | **Use the LangGraph *library*, never LangGraph Platform/Server** | `langgraph-api` is Elastic License 2.0 and the enterprise server can require egress to `beacon.langchain.com` for license checks — violates air-gapped + MIT-portability | We own the server process; no license key, no phone-home (§2.3) |
| AD-3 | **LiteLLM proxy is the single LLM gateway** | Uniform OpenAI-compatible interface across vLLM (air-gapped) and Claude API (online); native per-key/team `max_budget` + TPM/RPM | Budget enforcement (design-spec §4.6) lives at the gateway, not in agent code |
| AD-4 | **Per-tool authorization is enforced outside the model** (OPA/Cerbos policy node + tool filtering at discovery) | LangGraph has **no native per-tool RBAC**; default-deny must be a policy enforcement point | Permission manifests (design-spec §4.4) compile to policy; blocked tools never reach the model |
| AD-5 | **Observability via OpenTelemetry → self-hosted Langfuse; LangSmith disabled** | Air-gapped cannot depend on SaaS tracing; LangChain emits OTel natively | `LANGSMITH_TRACING=false`; traces export to in-cluster collector |
| AD-6 | **Supervisor built with the native tool-calling pattern**, not the `langgraph-supervisor` package | That package is soft-deprecated (0.0.x); maintainers recommend the native pattern | Supervisor is our own graph; fewer external version risks |
| AD-7 | **Postgres checkpointer with `durability="sync"`; tools are idempotent** | Node-level replay re-runs side effects on resume; sync persistence minimises the crash window | Every tool wrapper is idempotent / safe to replay (§11.1) |
| AD-8 | **Audit log is a separate WORM system, written only by the audit-writer service** | Design-spec §4.5 — no agent holds audit credentials; Kafka/OTel are transport, not the system of record | LangChain callback → audit-writer append-only API → MinIO WORM / S3 Object Lock |

### 2.3 Why the library and not the Platform

The design spec's portability model (§2.2–2.3) requires CORE to depend only on a
container runtime and the capability ports. LangGraph the **library** satisfies
this: it is embedded Python, MIT-licensed, makes zero external calls with tracing
disabled, and runs identically air-gapped and online. The **LangGraph Platform /
Server** (`langgraph-api`) is a separate Elastic-licensed product whose
enterprise standalone server can require license-verification egress; adopting it
would break both the air-gapped invariant and the "no vendor substrate" principle.
We therefore wrap LangGraph in our own FastAPI/worker process (the **case
worker**, §4) and own deployment, scaling, and persistence ourselves.

---

## 3. System context (C4 level 1)

```
        ┌─────────────────────────────────────────────────────────────┐
        │                       Signal producers                       │
        │  Mattermost/Slack · Grafana Alertmanager · GitLab Issues ·    │
        │  CVE feed mirror · swarm-cronjob / CI schedule                │
        └───────────────────────────┬─────────────────────────────────┘
                                     │ normalise → Signal (Appendix D, design spec)
                                     ▼
        ┌─────────────────────────────────────────────────────────────┐
        │            AGENTIC SRE FRAMEWORK (this system)               │
        │   Supervisor · governance plane · 8 specialist agents        │
        │   on LangGraph; LiteLLM gateway; OPA policy; audit-writer     │
        └───────────────┬─────────────────────────────┬───────────────┘
            reads (RO)  │                             │  drafts (MR/issue/comment)
                        ▼                             ▼
        ┌───────────────────────────┐   ┌─────────────────────────────┐
        │  Observability (RO)        │   │  Systems of record          │
        │  Grafana LGTM / Cloud      │   │  GitLab (Issues + SCM)      │
        │  via grafana-mcp           │   │  Mattermost/Slack (HITL)    │
        └───────────────────────────┘   └─────────────────────────────┘
                        │                             │
                        ▼                             ▼
        ┌─────────────────────────────────────────────────────────────┐
        │     Execution surfaces (human-triggered ONLY)               │
        │     Ansible · GitLab CI · Docker/Swarm API · kubectl         │
        └─────────────────────────────────────────────────────────────┘
```

The framework only ever **reads** targets and **drafts** artefacts. The arrow to
execution surfaces is dashed by design: it is crossed by a human approval at the
HITL gate, never by an agent.

---

## 4. Container view (C4 level 2) — runtime processes

Every box below is a container image. CORE images depend only on a container
runtime + the ports in §6.

```
┌──────────────────────────── CORE (portable images) ────────────────────────────┐
│                                                                                  │
│  intake-gateway        supervisor (×2)         case-worker (×N, scales w/ load)  │
│  ─ adapter plugins     ─ routing rules         ─ embeds LangGraph runtime        │
│  ─ noise control       ─ case lifecycle        ─ runs the per-case graph         │
│  ─ → Kafka             ─ HITL gate orchestr.   ─ calls agents/tools/checkpointer │
│        │                     │                        │                          │
│        ▼                     ▼                        ▼                          │
│   ┌─────────────────── Kafka / Redpanda (event bus) ───────────────────┐         │
│   └────────────────────────────────────────────────────────────────────┘        │
│                                                                                  │
│  policy-engine (OPA)   litellm-gateway        audit-writer        hitl-bridge    │
│  ─ default-deny authz  ─ budget/TPM/RPM caps  ─ append-only API   ─ chat↔gate    │
│  ─ manifest → policy   ─ model routing        ─ → WORM bucket     ─ resume hook  │
│                                                                                  │
│  governance-dashboard  grafana-mcp (RO SA)    otel-collector → langfuse          │
│                                                                                  │
│  state: PostgreSQL (cases + LangGraph checkpoints) · Redis (locks/cache)         │
└──────────────────────────────────────────────────────────────────────────────────┘
        │ reads/drafts via adapters (§6)
        ▼
  GitLab · Mattermost/Slack · Grafana LGTM/Cloud · Vault · MinIO/S3 · Ansible/CI
```

### 4.1 Process responsibilities

| Process | Responsibility | Notes |
|---|---|---|
| **intake-gateway** | Host the intake adapters; normalise each source to a `Signal`; apply debounce/dedup/burst-suppression/maintenance-window/quality-score (design-spec §4.7); publish to Kafka | Stateless; horizontally scalable per adapter |
| **supervisor** (×2, active-active) | Consume `signal.*` topics; open/dedup cases; route to the right agent graph; own case lifecycle, HITL gating decisions, escalation, backpressure | Stateless; all state in Postgres + Kafka offsets (design-spec §4.9) |
| **case-worker** (×N) | Embeds the **LangGraph runtime**; executes the per-case graph (supervisor node → specialist subgraph → tool calls → HITL interrupt); reads/writes the checkpointer | The only process that runs LLM/agent graphs; scales with concurrent cases |
| **policy-engine** (OPA) | Evaluate every tool call against the agent's compiled permission manifest; default-deny; expose decision + reason | AD-4; manifests compiled to Rego/policy bundles on manifest-repo change |
| **litellm-gateway** | Single egress to all models; enforce per-agent/per-case token + request budgets; route tier→model per environment | AD-3; the only component that holds model credentials |
| **audit-writer** | Sole holder of WORM-bucket credentials; expose append-only JSONL API; maintain hash chain | AD-8; agents/callbacks call it, never the bucket directly |
| **hitl-bridge** | Render drafts into Mattermost/Slack approval threads; verify clicker identity against on-call; capture signed decision + edit diff; **resume the paused graph** | Bridges chat approval UI ↔ LangGraph `Command(resume=...)` (§8.2) |
| **grafana-mcp** | Read-only observability access for agents; one image, only `GRAFANA_URL`+token differ by env | design-spec Appendix E |
| **governance-dashboard** | Operator view; per-tool revoke toggles; global kill-switch; budget/spend; suppression + hash-chain status | design-spec §4.8 |

---

## 5. Component view — the case graph on LangGraph

A **case** is one LangGraph execution, keyed by `thread_id = case_id`, persisted
to the Postgres checkpointer. The graph is supervisor-routed: the supervisor node
selects exactly one specialist subgraph per turn; specialists are ReAct-style
tool-calling agents whose tools are wrapped by the policy + audit + budget layers.

```
                         (case-worker process)
   ┌──────────────────────── LangGraph: case graph ────────────────────────┐
   │                                                                        │
   │   START → supervisor_node ──route──┬─► duty_engineer  (subgraph)       │
   │              ▲                     ├─► sre_investigator                │
   │              │                     ├─► principal_sre (escalation)      │
   │              │                     ├─► remediation_engineer            │
   │              │                     ├─► sysadmin_drafter                │
   │              │  (returns control)  ├─► security_triage                 │
   │              │                     ├─► compliance_evidence             │
   │              │                     ├─► postmortem_scribe               │
   │              └─────────────────────┴─► observability_engineer          │
   │                                                                        │
   │   Each specialist subgraph: model → tool_router → [tool nodes]         │
   │     tool_router calls: policy-engine (allow?) → litellm budget check   │
   │                        → execute tool → audit-writer append            │
   │                                                                        │
   │   HITL: before emitting a draft for approval, the graph calls          │
   │     interrupt(draft_payload)  ──► pauses, checkpoint persisted         │
   │     resume via Command(resume=decision) from hitl-bridge               │
   └────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Agent → graph mapping

- Each of the 8 specialists (design-spec §3.1) is a compiled subgraph. Tier
  (small/medium/frontier) selects the LiteLLM model alias, not a different code
  path.
- The **supervisor_node** is rule-table-first; the LLM (small tier) is invoked
  only for routing edge cases no rule covers (design-spec Agent 0). Escalation
  (Investigator → Principal SRE → Remediation) is encoded as conditional edges
  driven by confidence score, severity, runbook-presence, and repeat-fire flags.
- Specialist tools are plain LangChain tools, but **every tool is wrapped** by a
  middleware that (1) asks OPA whether this agent may call this tool with these
  args/scopes, (2) records the call via the audit callback, (3) routes any model
  call through LiteLLM. Tools the manifest forbids are filtered out of the tool
  list at bind time, so the model never sees them (AD-4).

---

## 6. Capability ports & adapter mapping

The design-spec §6.1 inventory, extended with the harness components. Selecting an
adapter is config (env + compose/Helm values), never a code change.

| Capability port | Air-gapped / on-prem | Online (AWS) | Harness binding |
|---|---|---|---|
| Orchestration runtime | LangGraph (in case-worker) | same | AD-1 |
| LLM gateway | LiteLLM → vLLM (Qwen/DeepSeek/Llama) | LiteLLM → Claude API | AD-3 |
| Tool authorization | OPA/Cerbos policy-engine | same | AD-4 |
| Observability (agent reads) | grafana-mcp → LGTM | grafana-mcp → Grafana Cloud | design-spec App. E |
| Traces / agent telemetry | OTel collector → self-hosted Langfuse | same (or OTel → vendor) | AD-5 |
| Case / checkpoint store | PostgreSQL (Swarm svc) | RDS Postgres | LangGraph `AsyncPostgresSaver` |
| Cache / locks | Redis | ElastiCache | optional Redis checkpointer |
| Event bus | Kafka / Redpanda | Amazon MSK | Appendix B (topics) |
| Point-to-point queue *(if needed)* | RabbitMQ | Amazon MQ | ordered hand-offs only |
| Object storage (audit + evidence) | MinIO WORM | S3 + Object Lock | audit-writer only |
| Secrets | Vault → Swarm secrets | Secrets Manager | LiteLLM + adapters |
| Identity / SSO (HITL) | Keycloak | Cognito / SSO | hitl-bridge identity check |
| Ticketing / SCM | GitLab | GitLab | tool adapters |
| Config-mgmt executor | Ansible | Ansible + SSM | **human-triggered only** |
| Chat | Mattermost | Slack (+ Telegram echo) | intake + hitl-bridge |
| Code / arch index | Qdrant/pgvector over repos + Bookstack | same | Principal SRE / Drafter reads |
| CVE / threat feed | offline mirror | live feed | Security Triage read |
| Substrate | Docker Swarm + Portainer | Docker Swarm on EC2 | Appendix A (design spec) |

---

## 7. Governance mechanism mapping

How each design-spec §4 guarantee is realised in this architecture.

| Guarantee (design spec) | Mechanism |
|---|---|
| **HITL gate** (§4.3) | LangGraph `interrupt()` pauses the graph and persists a checkpoint; hitl-bridge renders the draft to chat, verifies clicker vs on-call, captures the signed decision + edit diff, then resumes with `Command(resume=...)`. Because the pause is checkpointed, an unanswered approval **survives a case-worker restart** and the SLA re-page logic (§4.3) runs from the supervisor. |
| **Default-deny manifests** (§4.4) | Manifests (YAML in the manifest repo) compile to OPA policy bundles on change; the tool middleware calls OPA per tool invocation; forbidden tools are also removed from the model's tool list. Live revocation = dashboard toggle flips a policy datum (seconds, no redeploy). |
| **Append-only audit** (§4.5) | A LangChain callback handler emits a record per model call + tool call + state transition; hitl-bridge emits HITL decisions; all go to audit-writer's append-only API → WORM bucket with a hash chain. No agent holds bucket credentials. |
| **Budget caps** (§4.6) | LiteLLM enforces per-agent/per-case token + request budgets and TPM/RPM; LangGraph `recursion_limit` caps the agent loop; wall-clock cap is a per-case deadline in the supervisor that cancels the graph and pages on-call. |
| **Noise control** (§4.7) | intake-gateway applies debounce/dedup/burst/maintenance/quality-score *before* publishing to Kafka, so a graph is never instantiated for suppressed signals. |
| **Supervisor reliability** (§4.9) | supervisor is stateless ×2; case state in Postgres (checkpoints) + Kafka offsets; backpressure pauses low-priority intake topics first. |
| **Kill-switch** (§4.8) | Global flag in Postgres read by supervisor + case-worker; in-flight graphs reach their next checkpoint and halt; queued Kafka signals stay queued. |

---

## 8. Key runtime flows

### 8.1 Signal → case (happy path)

```
producer → intake-gateway (normalise + noise control) → Kafka signal.<source>
   → supervisor consumes → dedup/open Case (Postgres + GitLab issue + chat thread)
   → supervisor publishes case.route → case-worker leases case
   → LangGraph: supervisor_node routes → specialist subgraph drafts artefact
   → audit-writer appended at every model/tool step
```

### 8.2 HITL interrupt / resume (the load-bearing flow)

```
specialist subgraph produces draft
   → graph calls interrupt(draft)  ──► checkpoint persisted (durability="sync")
   → case-worker returns; the case is now "paused, awaiting approval"
   → hitl-bridge renders draft to Mattermost/Slack thread (Approve/Edit/Reject)
   → human clicks → hitl-bridge verifies identity vs on-call rotation
       → signs decision, stores raw+edited diff via audit-writer
       → resumes: load thread_id=case_id, graph.invoke(Command(resume=decision))
   → Approve  → graph proceeds (for state changes: emit execution request to the
                 EXISTING Ansible/CI pipeline — the pipeline executes, not the agent)
     Edit     → resume with edited payload (NB: verify deepagents-style subgraph
                 edit bugs are not in scope — we resume the top-level graph, §11.4)
     Reject   → graph annotates and routes back to the agent
```

Crash safety: if any process dies while paused, no state is lost — the checkpoint
holds the full graph state; resume is idempotent on `thread_id`.

### 8.3 Escalation (incident workflow, design-spec §5.1)

```
sre_investigator drafts report + self-confidence
   conditional edge:
     confidence ≥ θ AND runbook found → HITL gate (medium-tier path)
     else → supervisor escalates → principal_sre (frontier) → final RCA
            → remediation_engineer (frontier) → draft MR + pre/post + rollback
            → HITL gate
LiteLLM frontier budget caps + supervisor escalation policy keep frontier
invocation to a fraction of cases (design-spec §6.6).
```

### 8.4 Value loop (postmortem → observability, design-spec §5.4)

```
case state::closed (eligible) → supervisor emits postmortem.request (Kafka)
   → postmortem_scribe drafts → HITL gate (incident lead finalises, tags AIs)
   → approved monitoring AIs → obs-eng-request (Kafka)
   → observability_engineer drafts dashboard/alert MR; MANDATORY: execute proposed
     query via grafana-mcp, attach result/"no data" → open MR → HITL gate (SRE merges)
```

---

## 9. State & data model

| Store | Holds | Notes |
|---|---|---|
| **PostgreSQL** | (a) case records & lifecycle; (b) **LangGraph checkpoints** (one row-set per `thread_id=case_id`); (c) budget ledgers mirror; (d) kill-switch & manifest-version pointers | Single durable store of record for orchestration state; backed up; survives restart |
| **Redis** | distributed case lease/lock, dedup window keys, short-lived caches | Optional; not a system of record |
| **Kafka / Redpanda** | event transport: `signal.*`, `case.*`, `hitl.*`, `*-request` | Retention sized for replay/backpressure, **not** for audit |
| **MinIO/S3 WORM** | append-only audit JSONL (hash-chained) + compliance evidence packets | Written only by audit-writer; periodic offline hash-chain verification |
| **Vector store (Qdrant/pgvector)** | architecture-doc + code + prior-incident indexes | Read-only RAG for Principal SRE / Drafter |

LangGraph checkpoint and case lifecycle are deliberately co-located in Postgres so
a case's orchestration state and business state commit together.

---

## 10. Deployment topology

### 10.1 Baseline — Docker Swarm + Portainer (both environments)

Same Compose v3 stack files in air-gapped and online (design-spec §6.2–6.3). CORE
images are identical; only adapter env/secrets differ.

```
stack: sre-framework-core
  ├── intake-gateway (×2)        ├── supervisor (×2)        ├── case-worker (×N)
  ├── policy-engine/OPA (×2)     ├── litellm-gateway (×2)   ├── audit-writer (×2)
  ├── hitl-bridge (×2)           ├── grafana-mcp            ├── governance-dashboard
  ├── otel-collector + langfuse  ├── postgres + redis       └── kafka OR redpanda
stack: sre-framework-llm   (air-gapped only)
  └── vllm-small / vllm-medium / vllm-frontier   (GPU reservations; design-spec §6.7)
stack: sre-framework-storage
  └── MinIO WORM + Qdrant
```

Online swaps (design-spec §6.3): drop `sre-framework-llm` (LiteLLM → Claude API);
LGTM → Grafana Cloud; MinIO → S3 Object Lock; in-stack PG/Redis → RDS/ElastiCache;
Kafka → MSK; Vault → Secrets Manager; Keycloak → Cognito. **No CORE image change.**

### 10.2 Future — OpenShift

Same images via Helm + ArgoCD; Swarm primitives map per design-spec Appendix A.
CORE is unchanged because nothing in it touches Swarm- or K8s-specific APIs.

### 10.3 GPU (air-gapped only)

LiteLLM routes tier aliases to the vLLM services; GPUs reserved via
`deploy.resources.reservations.devices`. If GPU is the binding constraint, freeze
the frontier tier first (design-spec §6.6–6.7) — LiteLLM aliasing makes this a
config change (point `frontier` alias at the medium model or disable).

---

## 11. Cross-cutting concerns & watch-outs

### 11.1 Durability & idempotency (AD-7)
LangGraph resumes by **replaying the interrupted node from its last checkpoint** —
side effects in that node run again. Therefore every tool wrapper must be
idempotent or replay-safe: observability/CVE reads are naturally safe; GitLab
issue/MR/comment creation uses an idempotency key (case_id + step) to avoid
duplicates. Use `durability="sync"` so the checkpoint commits before the next
step. **Optional hardening (v2):** put the case-worker under **DBOS**
(Postgres-only, air-gap-friendly) for exactly-once step semantics and durable
multi-day approval waits; defer unless crash-exactly-once becomes a requirement.

### 11.2 Egress control (air-gapped)
Per design-spec §6.5, every CORE container is `default-deny` egress with explicit
allow-lists. Critical settings: `LANGSMITH_TRACING=false` and unset
`LANGSMITH_*`/`OPENAI_*` cloud endpoints so LangChain makes **zero external
calls**; the only "egress" is LiteLLM → in-cluster vLLM and adapters → in-cluster
services. This also blocks prompt-injection-driven exfiltration (design-spec §8.1
risk 2).

### 11.3 Open-weight tool-calling reliability
On-prem tool calling and structured output are the real reliability risk
(design-spec §6.6, §8.3). Mitigations baked into the architecture: pin
`model + vLLM version + tool-call parser + chat template` as a unit per tier;
enable vLLM structured/guided decoding (xgrammar/outlines) for tool args;
**post-validate every tool call** in the tool middleware and reject-and-retry on
schema violation; on repeated malformed frontier output, the supervisor falls back
to the medium tier with the same context, then to a human (design-spec §8.2).

### 11.4 Harness-specific risks
- **Supervisor package:** do not depend on `langgraph-supervisor` (soft-deprecated);
  the supervisor is our own graph (AD-6).
- **Deep Agents not used as foundation:** its subagent edit/reject HITL path has
  known bugs; we resume the top-level graph and keep gating in our own nodes.
- **License boundary:** CI must fail if `langgraph-api` (Elastic License) is pulled
  into a CORE image — only the MIT `langgraph` library is permitted (AD-2).
- **Node-replay vs. budgets:** because nodes can replay, budget accounting is keyed
  on idempotency keys at the LiteLLM layer to avoid double-charging a replayed step.

---

## 12. Open questions / to confirm before build

1. **DBOS vs checkpointer-only** for durable approval waits — decide per the SLA
   re-page/escalate requirements (design-spec §4.3); default is checkpointer-only
   for v1.
2. **OPA vs Cerbos** — both satisfy AD-4; pick on operational familiarity and
   air-gapped packaging. Manifest→policy compiler is the same shape either way.
3. **Exactly-once on inter-agent events** — whether `*-request` hand-offs need the
   RabbitMQ ordered queue or Kafka with idempotent consumers (default: Kafka).
4. **vLLM parser matrix** — finalise the pinned model+parser+template tuples per
   tier after the open-weight acceptance tests (design-spec §7.3 precondition).

---

## Appendix A — Component → image inventory

| Image | Language/base | Key deps | Stateful? |
|---|---|---|---|
| intake-gateway | Python | adapter SDKs, Kafka client | no |
| supervisor | Python | Kafka client, psycopg | no (state in PG/Kafka) |
| case-worker | Python | **langgraph**, langchain, litellm client, psycopg | no (state in checkpointer) |
| policy-engine | OPA/Cerbos | policy bundles | no |
| litellm-gateway | LiteLLM | provider configs, Redis (budgets) | budget counters |
| audit-writer | Python | WORM SDK (MinIO/S3) | append-only |
| hitl-bridge | Python | chat SDK, IdP, langgraph client | no |
| grafana-mcp | grafana-mcp | RO SA token | no |
| governance-dashboard | web | Postgres, Grafana panels | no |

## Appendix B — Kafka topic catalog (initial)

| Topic | Producer | Consumer | Key | Notes |
|---|---|---|---|---|
| `signal.chat` / `signal.alert` / `signal.ticket` / `signal.cve` / `signal.cadence` | intake-gateway | supervisor | dedup signature | post-noise-control only |
| `case.route` | supervisor | case-worker | case_id | lease assignment |
| `hitl.requested` / `hitl.decided` | hitl-bridge | supervisor | case_id | drives SLA timers |
| `postmortem.request` | supervisor | postmortem_scribe worker | case_id | value loop §8.4 |
| `obs-eng-request` | postmortem (approved) | observability_engineer worker | case_id | value loop §8.4 |
| `case.state` | supervisor | dashboard, audit-writer | case_id | state transitions |

Retention is sized for backpressure + short replay only; audit durability is the
WORM bucket, never Kafka.

## Appendix C — Permission manifest → policy compilation

```
manifest repo (YAML, design-spec App. B)
   → CI validates schema + diff review (MR)
   → compiler emits OPA bundle (Rego) keyed by agent + tool + scopes
   → policy-engine hot-loads bundle; dashboard revoke toggles override datums live
   → tool middleware: query OPA per call → allow/deny(+reason) → audit
```

## Appendix D — Harness selection (summary)

LangGraph (MIT) chosen for first-party durable `interrupt`/`resume`, Postgres +
Redis checkpointers, fully-offline operation, and plain-container deployment.
Credible alternatives evaluated: Microsoft Agent Framework (built-in durable HITL
+ enterprise audit, but Azure-tilted and a confusing AutoGen/AG2 lineage) and
Pydantic AI (best structured output, DBOS/Temporal durability, but less turnkey
durable-HITL). Deep Agents was rejected as a *foundation* (pre-1.0 churn,
"trust-the-LLM" posture, known subagent edit/reject HITL bugs) though its
planning/subagent patterns may be borrowed. Full evaluation lives in the harness
research thread; this document records only the decision (§2).
