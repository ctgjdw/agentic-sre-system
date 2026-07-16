# AI/LLMOps Platform — Design Specification

> **Status:** Draft for review
> **Date:** 2026-06-08
> **Relationship to the Agentic SRE Framework:** Sibling subsystem. The SRE
> framework monitors this platform as infrastructure (see §7).
>
> **Audience.** This document follows the same two-reader convention as the
> Agentic SRE Framework docs:
> - **Management-level execs (primary).** Read §1–§3. They cover value, risk,
>   and cost without engineering detail.
> - **Engineers (secondary).** §4–§9 and the appendices contain the
>   architecture, adapter splits, and integration detail needed to implement.

---

## 1. What this is

An **AI/LLMOps platform** — a multi-tenant system where internal teams and
external customers build, run, observe, test, and govern their own low-code
agentic systems.

Where the Agentic SRE Framework is a fixed roster of agents *doing SRE work*,
this platform is a *place where other people build agents*. The platform does
not build agents itself. It provides the lifecycle around tenant-built agents:

- **A visual builder** — tenants compose agents from pre-built components
  (tools, prompts, guardrails) without writing code.
- **A runtime** — executes those agents. AWS Bedrock AgentCore online; a
  self-hosted runtime on-prem.
- **Observability** — every agent run is traced: every LLM call, tool call,
  token, cost, and latency. Powered by Langfuse.
- **Testing & evaluation** — quality scoring, regression gates on agent
  changes, and adversarial/red-team suites.
- **Policies** — cost caps, safety guardrails, PII handling, access control,
  and a full audit trail.

## 2. Why it exists — value, risk, cost

### 2.1 The value

| Need | Without the platform | With the platform |
|---|---|---|
| Teams want to build AI agents | Each team rebuilds observability, evals, and safety from scratch | One governed platform; teams focus on their agent, not the plumbing |
| Leadership needs cost control | LLM spend is opaque and uncapped per team | Per-tenant, per-agent budget caps and usage metering |
| Compliance needs assurance | No record of what tenant agents did or whether output was screened | WORM audit log of every execution and policy decision |
| Quality must not silently degrade | A prompt change can break a production agent unnoticed | Eval gates block regressions before promotion |
| Safety is non-negotiable for customer-facing agents | Each team improvises content filtering | Platform-mandatory guardrails that tenants cannot disable |

### 2.2 The risks (and how the design answers them)

| Risk | Mitigation built into the design |
|---|---|
| Runaway LLM cost | Per-tenant + per-agent budget caps; quota enforcement at the LLM gateway (§6) |
| Harmful or non-compliant agent output | Platform-mandatory safety + PII guardrails tenants cannot weaken (§6) |
| Tenant data leakage across tenants | Group-level isolation (group = tenant = Langfuse org); stronger isolation tier for external customers (§5) |
| Silent quality drift | Eval regression gates on every agent version change (§4b) |
| On-prem safety classifiers weaker than cloud | Stricter default thresholds on-prem; stated plainly (§6) |
| No defensible record for audit/dispute | WORM audit log, append-only, separate write credentials (§5b) |

### 2.3 The cost shape

| Cost | Magnitude | Control |
|---|---|---|
| LLM inference (tenant agents) | The dominant cost; scales with tenant usage | Budget caps; tiered model selection; metered + billed per tenant |
| Eval inference (LLM-as-judge) | Secondary; competes for GPU on-prem | Sampling for online evals; eval workload counted in GPU scheduling |
| Platform infrastructure (Langfuse, runtime, ClickHouse) | Fixed operational baseline | Shared across tenants; self-hosted to avoid per-seat SaaS fees |

## 3. The six components at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENTIC SRE FRAMEWORK                        │
│  (existing — monitors this platform as infrastructure, §7)      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ monitors
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AI / LLMOps PLATFORM                          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Visual Agent │  │   Agent      │  │    Langfuse          │  │
│  │ Builder      │──│   Runtime    │──│    (Observability +   │  │
│  │ (no-code UI) │  │              │  │     Evals + Prompts) │  │
│  └──────────────┘  └──────┬───────┘  └──────────────────────┘  │
│                           │                                      │
│  ┌──────────────┐  ┌──────┴───────┐  ┌──────────────────────┐  │
│  │ Policy       │  │   LLM        │  │    Tenant            │  │
│  │ Engine       │──│   Gateway    │  │    Management        │  │
│  │ (guardrails) │  │              │  │    (RBAC, billing)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Audit Log (WORM-backed)                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

| # | Component | Responsibility | Detail |
|---|---|---|---|
| 1 | Visual Agent Builder | No-code composition of agents; compiles to a portable spec | §4 |
| 2 | Agent Runtime | Executes agents; adapter-split online/on-prem | §4 |
| 3 | Langfuse | Traces, cost, evals, prompt management | §4 |
| 4 | Policy Engine | Cost caps, safety guardrails, PII, access control | §6 |
| 5 | Tenant Management | Multi-tenant RBAC, isolation, billing | §5 |
| 6 | Audit Log | Append-only WORM record of all platform activity | §5 |

---

## 4. Agent runtime and the portable spec

> Audience: engineering.

The Visual Builder compiles a no-code flow into a **portable agent spec** — a
JSON/YAML document that is the portability contract between the builder and any
runtime. This mirrors the SRE framework's "same conceptual model, adapters
swap" principle.

### 4.1 Portable agent spec

| Field | Contents |
|---|---|
| `tools[]` | Declared tool integrations (API calls, DB queries, file ops), each with a schema and a permission scope |
| `prompt_refs[]` | References to Langfuse prompt versions — never inline text |
| `guardrails[]` | Policy rules applied to this agent (content filters, PII redaction, topic restrictions, output validators) |
| `flow_graph` | The execution graph — steps, branches, loops, human-in-the-loop checkpoints (what the visual builder produces) |
| `model_tier` | LLM tier: small / medium / frontier (same tiering as the SRE framework) |
| `budget` | Token cap, tool-call cap, wall-clock limit per execution |

### 4.2 Runtime adapter split

| Responsibility | Online — Bedrock AgentCore | On-prem — custom runtime (**TBD**) |
|---|---|---|
| Agent execution | AgentCore native | Custom orchestrator (candidate: LangGraph Platform self-hosted) |
| Tool calling | AgentCore Action Groups + Lambda | Direct HTTP/gRPC to tool registry |
| Session / memory | AgentCore managed sessions | Redis-backed session store |
| Scaling | Managed auto-scaling | HPA on OpenShift |
| Guardrails | Bedrock Guardrails + Policy Engine sidecar | Policy Engine sidecar only |
| Telemetry | OTEL → dual export (CloudWatch + Langfuse) | OTEL → Langfuse |

**On-prem runtime is deliberately left TBD.** The portable spec is the
contract; the runtime behind it is a replaceable adapter. Decision deferred.

> **Trade-off stated plainly.** Bedrock AgentCore gives managed scaling,
> session management, and native AWS integration online for free. The on-prem
> runtime will lag in features — the same accepted reality as the SRE
> framework's "on-prem frontier-tier output is visibly weaker than online."

### 4.3 Langfuse — observability, evaluation, prompt management

Langfuse is the LLM-specific operational layer. It plays three roles.

**(a) Observability.** Every execution produces a Langfuse trace regardless of
runtime adapter, instrumented via the **Langfuse SDK** (chosen over OpenLLMetry
for tighter integration with Langfuse prompt/eval/score features). A trace
captures every tool call and LLM call as spans, with tenant_id, agent
id+version, prompt version refs, user_id, and session_id as metadata.

**(b) Evaluation & testing.**

| Eval type | When | How |
|---|---|---|
| Online evals | Every execution (sampled or 100%) | Lightweight LLM-as-judge / heuristic scorers attached to traces in real time |
| Dataset evals | On agent version change (CI/CD gate) | Run the new version against a curated dataset; compare to baseline; regression **blocks** promotion |
| Human evals | Async, tenant-initiated | Annotation in Langfuse; scores feed dataset curation |
| Adversarial / red-team | On-demand or scheduled | Platform-provided suites testing prompt injection, jailbreaks, PII leakage, off-topic steering |

**(c) Prompt management.** All prompts are Langfuse-managed and versioned.
Agent specs reference prompt *names*; Langfuse resolves to the active version at
runtime. Promotion flow: Draft → Staging → Production. A/B testing via traffic
splits, with scores compared per version. Every change is versioned and
attributed.

### 4.4 Observability adapter split (online vs on-prem)

AWS-native services **supplement** Langfuse online; on-prem, Langfuse does
everything. This reflects research into AWS's native LLM observability
(AgentCore Observability, CloudWatch GenAI Observability, Bedrock Evaluations,
Bedrock Guardrails) — none of which fully replace Langfuse, chiefly because AWS
lacks single-instance multi-tenant project isolation, a full prompt-management
lifecycle, and experiment management.

| Capability | Online (AWS) | On-prem (OpenShift) |
|---|---|---|
| Ops monitoring / alerting | CloudWatch GenAI Observability + Alarms | Grafana LGTM stack |
| LLM trace & debug UX | Langfuse (self-hosted on ECS/Fargate) | Langfuse (self-hosted on OCP) |
| Telemetry pipeline | AgentCore OTEL → dual export (CloudWatch + Langfuse) | Runtime OTEL → Langfuse |
| Batch evaluation | Bedrock Evaluations + Langfuse experiments | Langfuse evals (LLM-as-judge via on-prem vLLM) |
| Online evaluation | AgentCore Evaluations (continuous scoring) | Custom eval pipeline → Langfuse scores |
| Policy / safety | Bedrock Guardrails + AgentCore Cedar Policy | Custom Policy Engine sidecar |
| Prompt management | Langfuse Prompt Management | Langfuse Prompt Management |
| Cost tracking | CloudWatch metrics + Langfuse per-trace cost | Langfuse per-trace cost |
| Multi-tenant RBAC | Supergroup → Group(=Langfuse org) → Project/User | Supergroup → Group(=Langfuse org) → Project/User |

> **AWS-endorsed pattern.** AWS and Langfuse have published a joint reference
> for AgentCore→Langfuse OTEL export. Disable ADOT
> (`DISABLE_ADOT_OBSERVABILITY=true`) and point the OTEL exporter at Langfuse's
> `/api/public/otel` endpoint. CloudWatch handles ops alerting and
> infrastructure correlation; Langfuse handles the LLM engineering workflow.

---

## 5. Tenant management and audit log

> Audience: engineering.

### 5.1 Tenant hierarchy — two grouping levels

The platform uses a **three-level hierarchy**: a **supergroup** contains
**groups**; a **group** contains **users** and **projects**. The **group is the
tenant boundary** — the unit of isolation, billing, and policy.

The motivating case: one external customer (e.g. an organization) has several
departments. Each department must be its own isolated tenant, but the
organization groups them together. The supergroup is that organizing parent.

```
Supergroup  (e.g. "Organization" — name TBC)   ← always present; groups tenants
  └── Group  (e.g. "Department")               ← THE TENANT BOUNDARY
        ├── Users          (RBAC: Owner / Admin / Developer / Viewer)
        ├── Projects       (one per agentic system / app)
        │     ├── Agents       (the built agents)
        │     ├── Prompts      (versioned, Langfuse-managed)
        │     ├── Eval datasets
        │     └── Traces       (scoped to project)
        ├── Policy namespace   (tenant-owned + platform-mandatory)
        └── Billing account    (usage metering)
```

**Hierarchy rules:**

- **The supergroup is always present.** Every group belongs to exactly one
  supergroup, even a single-department customer (the supergroup then has one
  group). This keeps one invariant instead of two code paths.
- **Depth is capped at two grouping levels.** No super-supergroups.
- **The group is the isolation boundary.** Users, projects, traces, prompts,
  policies, and billing all scope to the group. Two groups in the same
  supergroup are as isolated from each other as two unrelated customers.

**Supergroup scope (v1): a logical grouping only.** In v1 the supergroup has no
admins and no cross-group visibility — it only associates groups for organizing
and reporting. **Forward path (not v1):** supergroup-level admins with
read-only rollup of usage/billing across member groups, and optionally group
lifecycle management. The data model reserves this — the supergroup is a
first-class entity from day one — but no supergroup roles ship in v1.

### 5.2 Mapping to Langfuse

Langfuse's native hierarchy is only **two levels** (Organization → Project, with
users as organization members). The mapping aligns the tenant boundary with
Langfuse's strongest isolation boundary:

| Platform concept | Langfuse concept | Notes |
|---|---|---|
| Supergroup | *(none)* | Lives in the platform Tenant Management layer, **above** Langfuse. Langfuse never sees supergroups. |
| **Group (tenant)** | **Organization** | Langfuse's hard isolation boundary lands exactly on the tenant boundary. |
| User | Organization member | Langfuse RBAC: Owner / Admin / Member / Viewer at org and project level. |
| Project | Project | One per agentic system. |

> **Naming caution.** Langfuse calls its top level "Organization". This spec
> maps a **Group** to a Langfuse Organization. So if the supergroup is
> eventually named "Organization", that label collides with Langfuse's internal
> term. Keep the platform-facing terms (Supergroup / Group) distinct from the
> Langfuse-internal term in code and docs to avoid confusion.

The supergroup is tracked entirely by the Tenant Management component (its own
table keyed to a set of Langfuse organization IDs). This is what makes the
future rollup path clean: aggregating usage across a supergroup is a query over
its member Langfuse organizations, requiring no Langfuse schema change.

### 5.3 Isolation tiers

| Tenant type | Isolation | Rationale |
|---|---|---|
| Internal teams | Logical — group = Langfuse org, separate policy namespaces, shared infra | Lower risk; cost efficiency |
| External customers | Stronger — group = dedicated Langfuse org, dedicated policy namespace, optionally dedicated runtime workers | Data residency, contractual isolation |

**Billing / metering.** Per-trace cost from Langfuse is aggregated per **group
(tenant)**. Online, reconciled against CloudWatch metrics and AWS billing tags.
On-prem, Langfuse cost data is the source of truth, with GPU-time allocation for
self-hosted models. The future supergroup rollup sums group-level totals across
the supergroup's member organizations.

### 5.2 Audit log

Append-only, WORM-backed. Logically distinct from the SRE framework's audit log
(different questions, shared storage adapter).

| Logged | Why |
|---|---|
| Every agent execution (tenant, agent version, prompt versions, input/output hashes) | Reproducibility + dispute resolution |
| Every policy decision (gate, pass/fail, trigger) | Compliance evidence + safety audit |
| Every tenant admin action (member added, policy changed, agent promoted) | Access governance |
| Every prompt/agent version change | Change traceability |
| Cost events (budget cap hit, quota exceeded) | Billing dispute resolution |

Storage: MinIO with WORM (on-prem) / S3 with Object Lock (online). No component
writes directly to the log except the append-only writer service.

---

## 6. Policy engine

> Audience: engineering.

### 6.1 Three enforcement points

```
  Tenant agent execution
    │
    ▼
  ① INPUT GATE     — quota check, PII scan on input, prompt-injection
    │                detection, topic restriction
    ▼
  ② LLM GATEWAY    — model access control, token budget enforcement,
    │  (per call)    content filter + PII scan on output
    ▼
  ③ TOOL GATE      — tool permission check, scope restriction,
       (per call)    rate limiting on external calls
    │
    ▼
  Every decision → Langfuse span (tenant-visible) + Audit log (WORM)
```

### 6.2 Adapter split

| Concern | Online (AWS) | On-prem (OpenShift) |
|---|---|---|
| Content safety | Bedrock Guardrails | Custom filter (open-weight classifier / rules) |
| PII detection & masking | Bedrock Guardrails | Presidio or equivalent OSS |
| Prompt injection | Bedrock Guardrails (prompt attack filter) | Custom classifier / rules |
| Topic restrictions | Bedrock Guardrails (denied topics) | Custom topic classifier |
| Tool-call authorization | AgentCore Policy (Cedar) | Custom engine — Cedar-compatible YAML |
| Model access control | IAM + LiteLLM gateway routing (in front of Bedrock) | LiteLLM gateway routing (in front of vLLM) |
| Cost / quota (gateway-enforced) | LiteLLM virtual-key budgets + rate limits | LiteLLM virtual-key budgets + rate limits |
| Cost metering / billing | CloudWatch + Langfuse per-trace cost, reconciled to AWS billing | Langfuse per-trace cost (source of truth) |
| Rate limiting | API Gateway throttling + LiteLLM per-key RPM/TPM | LiteLLM per-key RPM/TPM |

**The LLM Gateway is LiteLLM (MIT) in both contexts.** AWS ships no standalone
LLM-gateway service — Bedrock's Converse API unifies *model invocation* but not
per-tenant virtual keys, budget caps, or fallback routing. AWS's own
"Multi-Provider Generative AI Gateway" Guidance is itself built on LiteLLM. We
adopt the same gateway in both contexts: online it fronts Bedrock, on-prem it
fronts vLLM. It is a routing/quota/cost layer only — safety (guardrails, PII,
prompt injection) stays in the Policy Engine rows above. Per-call cost flows to
Langfuse via LiteLLM's native callback. Pin to a cosign-signed immutable image
(§9.1).

**Cedar is the one component that genuinely ports.** AgentCore uses Cedar (AWS's
open-source policy language) for tool-call authorization. The same Cedar
policies express on-prem authorization, so "Agent X may call the search API only
for namespace Y" is written once for both environments.

### 6.3 Policy ownership tiers

| Tier | Who controls | Examples |
|---|---|---|
| Platform-mandatory | Operator only; tenants cannot weaken | PII output scan, audit logging, prompt-injection detection, max token ceiling, banned model list |
| Platform-default, tenant-adjustable | Platform default; tenants may tighten, not loosen | Content safety thresholds, rate limits, tool-call scopes |
| Tenant-owned | Tenant configures within platform ceiling | Custom topic restrictions, output validators, agent budget caps, model tier |

```yaml
# Platform-mandatory (cannot be overridden)
policy:
  id: platform/pii-output-scan
  type: mandatory
  scope: all_tenants
  enforcement: block
  config:
    scan: [output]
    entities: [SSN, CREDIT_CARD, API_KEY, PASSWORD]
    action: mask        # replace with [PII-TYPE-N] placeholders

---
# Tenant-owned
policy:
  id: tenant/acme-corp/budget-cap
  type: tenant_owned
  scope: tenant:acme-corp
  config:
    max_tokens_per_execution: 50000
    max_tokens_per_day: 2000000
    max_frontier_calls_per_day: 100
    alert_at_pct: [75, 90]
```

### 6.4 On-prem safety quality — stated plainly

| Concern | Online | On-prem | Implication |
|---|---|---|---|
| Content safety | Bedrock Guardrails (trained ML) | Open-weight / rules | Visibly weaker; higher false-positive rate |
| PII detection | Bedrock Guardrails ML+regex | Presidio or equivalent | Good for structured PII, weaker for contextual |
| Prompt injection | Bedrock prompt-attack filter | Rules + lightweight classifier | Less robust against novel attacks |

**Mitigation:** on-prem defaults to stricter thresholds (more aggressive
blocking), accepting a higher false-positive rate as the cost of safety.

---

## 7. Integration with the Agentic SRE Framework

> Audience: engineering + exec.

The relationship is **layered**: the LLMOps platform is its own system; the SRE
framework treats it as another service to monitor.

```
┌──────────────────────── SRE FRAMEWORK ────────────────────────┐
│  Observability Engineer Agent → platform infra health          │
│    (pod health, Langfuse availability, ClickHouse lag,         │
│     runtime queue depth, GPU saturation on-prem)               │
│  SRE Investigator / Principal SRE → platform incidents         │
│  Compliance Evidence Agent → reads LLMOps audit log            │
│  Duty Engineer Agent → receives platform alerts as signals     │
└──────────────────────────┬─────────────────────────────────────┘
                          │ signals up (alerts, metrics, audit reads)
┌──────────────────────────┴─────────────────────────────────────┐
│                    LLMOps PLATFORM                              │
│  Emits to SRE framework:                                        │
│    • Infra metrics → Grafana LGTM / CloudWatch                  │
│    • Platform alerts → Alertmanager → Duty Engineer Agent       │
│    • Audit log → readable by Compliance Evidence Agent          │
│  Stays internal (NOT emitted):                                  │
│    • Tenant LLM traces (Langfuse, domain-specific)              │
│    • Tenant prompt content (tenant-private)                     │
│    • Eval scores (LLMOps-internal quality signal)              │
└─────────────────────────────────────────────────────────────────┘
```

**The boundary that matters.** The SRE framework monitors the **platform as
infrastructure** — is it up, healthy, within cost. It does **not** reach into
tenant LLM traces or prompt content; that is the LLMOps domain and is
tenant-private. This keeps separation of concerns clean and avoids SRE agents
needing tenant data access.

### 7.1 Two kinds of "agent" — do not conflate

| | SRE Framework Agents | LLMOps Tenant Agents |
|---|---|---|
| Built by | SRE/platform team (fixed roster) | Tenants (internal teams + customers) |
| Do what | SRE work — triage, investigate, remediate | Whatever the tenant builds |
| Governance | SRE HITL gates + permission manifests | LLMOps Policy Engine + tenant RBAC |
| Observability | SRE framework audit log | Langfuse + LLMOps audit log |

---

## 8. Deployment model summary

Same dual-context principle as the SRE framework: one conceptual model, two
adapter sets selected by config (Helm values).

| Capability port | On-prem (OpenShift) | Online (AWS) |
|---|---|---|
| Agent runtime | Custom runtime (**TBD**) | Google Vertex |
| LLM gateway | LiteLLM (self-hosted on OCP) → vLLM | LiteLLM (ECS/Fargate or EKS) → Bedrock |
| LLM observability | Langfuse (self-hosted on OCP) | Langfuse (self-hosted on ECS/Fargate) |
| Ops monitoring | Grafana LGTM | CloudWatch GenAI Observability |
| Observability DB (OLAP) | ClickHouse on OCP | ClickHouse on EKS / ClickHouse Cloud |
| State DB (OLTP) | PostgreSQL on OCP | RDS PostgreSQL |
| Object storage (audit + datasets) | MinIO + WORM | S3 + Object Lock |
| Eval LLM (LLM-as-judge) | on-prem vLLM | Bedrock / Anthropic API |
| Content safety / PII | Custom Policy Engine | Bedrock Guardrails |
| Tool-call authorization | Cedar (self-hosted) | AgentCore Cedar Policy |

---

## 9. Open questions and out-of-scope

### 9.1 Open questions (to resolve before/within implementation planning)

| # | Question |
|---|---|
| 1 | On-prem agent runtime: LangGraph Platform self-hosted vs custom engine — licensing and feature parity to confirm |
| 2 | Visual builder: build in-house vs adopt/wrap an existing OSS builder (e.g. Flowise/n8n-style) — needs its own design cycle |
| 3 | Langfuse version pinning + fork-as-insurance policy given the ClickHouse acquisition |
| 4 | GPU scheduling policy on-prem when eval (LLM-as-judge) workload competes with tenant agent execution |
| 5 | External-customer data residency requirements — do any require fully dedicated infrastructure rather than logical isolation? |
| 6 | Final name for the **supergroup** level ("Organization", "Tenant Group", etc.) — must not collide with Langfuse's internal "Organization" term (§5.2) |
| 7 | LiteLLM gateway hardening: image-pinning + cosign signature-verification policy for air-gapped installs (a rolling tag once shipped a backdoor); mirrors the Langfuse version-pinning item (§9.1.3) |

### 9.2 Out of scope (v1)

| Out of scope | Why |
|---|---|
| The visual builder's detailed UX | Its own design cycle; this spec defines the portable spec it must emit |
| **Supergroup-level admins + cross-group billing rollup** | Data model reserves the supergroup as a first-class entity, but no supergroup roles or rollup views ship in v1 (§5.1). Planned forward path. |
| Autonomous tenant-agent state changes without tenant-defined HITL | Tenants own their agents' autonomy within platform policy ceilings |
| Replacing CloudWatch / Grafana | The platform integrates with them, does not replace them |
| Cross-tenant shared agent marketplace | Future consideration; not v1 |
| Fine-tuning / model training services | This is an *ops* platform, not a training platform |

---

## Appendix A — Why Langfuse over alternatives

19 LLM observability platforms were evaluated against the requirement of
**both** AWS-online and air-gapped on-prem deployment with multi-tenant
isolation. Langfuse was selected as the only OSS option satisfying all of:
native multi-tenancy (Org→Project→User RBAC), explicit air-gapped support,
prompt management, evaluations, and OTEL compatibility — under an MIT licence.

| Candidate | Why not (for this use case) |
|---|---|
| Arize Phoenix (OSS) | No multi-tenancy in OSS; ELv2 licence. Arize AX (commercial) fixes both but adds cost |
| MLflow | Apache-2.0 and safest licence, but no native multi-tenancy and weaker LLM-specific UX |
| LangWatch | Strong fit on paper (air-gapped, multi-tenant, OTEL) but ~9× smaller community |
| Opik (Comet) | OSS lacks user management/multi-tenancy; air-gap needs closed Enterprise |
| Helicone, Laminar, OpenLIT | Gaps in air-gap support, multi-tenancy, or prompt management |
| LangSmith, Braintrust, HoneyHive, W&B Weave | Proprietary / no real self-hosting |

**Residual risk:** Langfuse was acquired by ClickHouse (Jan 2026). Licence is
unchanged (MIT) and self-hosting remains first-class, but long-term licence
stability is a watch item. Mitigation: pin a known-good version; maintain a
fork as insurance (open question §9.1.3).

## Appendix B — Why Langfuse SDK over OpenLLMetry for instrumentation

OpenLLMetry emits generic OTEL spans; the Langfuse SDK adds native linking to
Langfuse prompt management, evaluation datasets, user/session tracking, and
score attachment. Since Langfuse is already the committed observability layer,
the SDK's tighter integration outweighs the vendor-neutrality of OpenLLMetry.
The trade-off (vendor coupling) is accepted.
