# Agentic SRE Framework — Design Specification

> **Status:** Draft for review
> **Date:** 2026-06-22
> **Audience.** Engineering — implementers of the framework. This is the single
> buildable reference. The narrative/value framing for executives lives in
> `docs/framework/01–02`; this spec consolidates and supersedes the
> implementation detail in `docs/framework/03–08`.
> **Relationship to other specs.** Sibling to the AI/LLMOps Platform spec
> (`docs/llm-ops-spec/2026-06-08-llmops-platform-design.md`). This framework
> *does SRE work*; that platform is *where other teams build agents*.
> **What changed vs `docs/framework/06`.** The on-prem deployment is no longer
> OpenShift-first. The baseline deployment artifact is **Docker Compose / Swarm
> stack files, managed by Portainer** — used in **both** the air-gapped and
> online deployments. **OpenShift is a supported future substrate** (same
> container images). Online LLM access uses an **Anthropic Claude API key**;
> online observability uses **Grafana Cloud (free tier)**. Agents read
> observability through the **Grafana MCP server (`grafana-mcp`)** in both
> environments. See §2.3 and §6.

---

## 1. Overview & scope

### 1.1 What this is

A framework — not a product — for a small team of AI agents that **support and
automate** parts of the SRE / SysAdmin workload while keeping humans in command
of every state-changing action. It provides:

- **One ingestion path** for all signals — chat messages, automated alerts,
  service tickets, CVE reports, scheduled audit events — normalised through a
  single orchestrator.
- **Role-specialist agents** that mirror existing job titles and draft the
  artefacts a human would otherwise produce by hand.
- **A governance plane** controlling what each agent can see and do, capping
  compute spend, and writing an append-only audit log per case.
- **One conceptual model across deployments.** Core logic is identical; only
  adapters and the deployment substrate change.

### 1.2 Engineering invariants (the six pillars)

1. **Human-in-command.** Agents investigate, draft, and propose. Every
   state-changing action is executed by a human approving through the HITL
   gate (§4.3). No exceptions in v1.
2. **Role-mapped specialists.** Agent roles mirror existing job titles (§3).
3. **One orchestrator, one audit trail.** A single supervisor routes work,
   owns HITL gating, and emits one append-only audit log per case (§4).
4. **Deterministic tooling first.** Where Ansible / GitLab CI / a scripted
   runbook already does the job, the agent *calls* it — never re-implements it.
5. **Noise-aware ingestion.** Signals are debounced, deduplicated, and grouped
   before an agent is invoked (§4.7).
6. **Substrate- and adapter-portable.** The same agent roster and governance
   plane run air-gapped and online; only adapters and the orchestrator swap
   (§2, §6).

### 1.3 Why each agent exists (gap → agent)

Each agent earns its compute by closing a concrete, current SRE gap. This table
is the engineering rationale for the roster shape in §3.

| Gap (today) | Agent(s) that close it |
|---|---|
| Issues surface via ad-hoc chat, not structured alerts | Duty Engineer Agent |
| Few fine-tuned dashboards/alerts for impactful signals | Observability Engineer Agent |
| Service tickets arrive as free-text, interpreted manually | SysAdmin Drafter Agent |
| Investigation depth varies by who is on call | SRE Investigator + Principal SRE |
| Postmortem action items rarely become real improvements | Postmortem Scribe + Observability Engineer |
| CVE triage and patch authoring is manual | Security Triage Agent |
| Compliance evidence gathered reactively before audits | Compliance Evidence Agent |

### 1.4 Out of scope (v1)

| Out of scope | Why |
|---|---|
| Autonomous state changes | Hard ceiling: read-only + drafts only. Lifted only by separate governance review, never by code. |
| Replacing CAB / change-manager authority | The on-call human is the change manager. |
| Replacing observability / ticketing / config-mgmt tooling | The framework integrates with Grafana, GitLab, Ansible; it does not compete with them. |
| Capacity forecasting | Prometheus/Mimir recording rules + regression are cheaper and better. |
| Config drift detection | GitOps reconciliation already covers it deterministically. |
| Customer-facing communication | Agents speak only in ops-internal channels. |
| Cost / FinOps optimisation agent | Out of charter for v1. |
| "Agent that replaces the on-call" | Not a goal at any timeline. |
| Vendor-specific wrappers (Datadog Bits, Dynatrace Davis, Azure SRE Agent) | The framework stays open and adapter-driven. |

Deterministic-only workloads (no agent justified): capacity forecasting
(Prometheus/Mimir), config drift (ArgoCD/Ansible), backup verification
(scheduled checks), TLS/cert rotation (cert-manager / Vault PKI).

---

## 2. Architecture & portability model

### 2.1 At a glance

```
       Humans (Mattermost on-prem / Slack online / GitLab Issues)
                          │
                          ▼
   ┌─────────────────────────────────────────────────┐
   │      Orchestration & Governance Plane (CORE)     │
   │   ─ Supervisor                                   │
   │   ─ HITL approval gates                          │
   │   ─ Permission manifests (default-deny)          │
   │   ─ Budget caps + append-only audit log          │
   │   ─ Debounce / dedup / noise control             │
   └─────────────────────────────────────────────────┘
                          │
   ┌──────────┬───────────┴───────┬──────────┬──────────┬──────────┐
   ▼          ▼                   ▼          ▼          ▼          ▼
  Duty        SRE            Principal   SysAdmin   Security   Compliance
  Engineer    Investigator      SRE      Drafter    Triage     Evidence
                                 │
                                 ▼
                       Remediation     Postmortem      Observability
                       Engineer        Scribe          Engineer
                          │
                          ▼
   Existing tooling (Ansible, GitLab CI, Docker/Swarm API, kubectl
   for K8s targets, Grafana LGTM via grafana-mcp, Vault, MinIO/S3, Kafka)
```

### 2.2 Two-layer model: CORE + adapters

| Layer | Contents | Portability rule |
|---|---|---|
| **CORE (portable)** | Supervisor, agent logic, governance plane, audit-log writer, permission manifests, case lifecycle, HITL gate semantics, budget enforcement, workflow state machines | Ships as container images. Depends **only** on a container runtime and the capability ports below — never on Swarm- or Kubernetes-specific APIs. |
| **Adapters** | Concrete implementation behind each capability port: LLM gateway, observability, object storage, case/state store, event bus, point-to-point queue, secrets, identity/SSO, ticketing/SCM, config-mgmt executor, chat, code/arch index, CVE feed | Selected by config (env + compose/Helm values). Swapping an adapter is a config change, not a code change. |

### 2.3 Portability has two axes

This is the central design decision that lets the framework run air-gapped now
and on OpenShift later without forking CORE.

| Axis | Choices | Where it is expressed |
|---|---|---|
| **Adapter axis** — *which backing service* | Self-hosted (MinIO, Vault, in-cluster Postgres, vLLM, self-hosted LGTM) vs managed (S3, Secrets Manager, RDS, Claude API, Grafana Cloud) | Adapter config (§6.1) |
| **Substrate axis** — *which orchestrator* | **Docker Compose / Swarm (baseline, now)** vs **OpenShift / Kubernetes (future)** | Deployment manifests only (§6, Appendix A) |

**The substrate-agnostic principle.** CORE must not embed Swarm- *or* K8s-only
assumptions. Anything substrate-specific (stack files, Swarm secrets,
`swarm-cronjob`, Portainer, or — later — Helm charts, operators, CronJobs,
ArgoCD) lives **only** in the deployment layer. This keeps the OpenShift path
open while Compose/Swarm is the artifact we author and ship first.

**Consequence for the old portability claim.** `docs/framework/06` claimed
"the same Helm charts run on EKS and on-prem." That is replaced by: **the same
container images run everywhere; the deployment manifest format differs by
substrate** (Compose/Swarm stack files as the baseline; Helm/K8s manifests for
the future OpenShift target).

---

## 3. Agent roster

### 3.1 At-a-glance

| # | Agent | Tier | Job |
|---|---|---|---|
| 0 | Supervisor / Orchestrator | small | Route signals; own lifecycle, audit, budgets, HITL gate |
| 1 | Duty Engineer Agent | small | L1 triage; chat-message intake; dedup; case opening |
| 2 | SRE Investigator Agent | medium | Initial investigation from logs/metrics/traces |
| 2a | Principal SRE Agent | frontier | Senior review; final RCA with code + architecture context |
| 2b | Remediation Engineer Agent | frontier | Draft the fix as an MR (Ansible / IaC / SQL / k8s) |
| 3 | SysAdmin Drafter Agent | medium | Free-text service tickets → structured change specs + draft playbooks |
| 4 | Security Triage Agent | medium → frontier | CVE exploitability + draft mitigation MR |
| 5 | Compliance Evidence Agent | small | Continuous evidence collection; gap detection |
| 6 | Postmortem Scribe Agent | medium | Timeline reconstruction; draft postmortem; action items |
| 7 | Observability Engineer Agent | medium | Draft Grafana dashboards + alert rules from incidents/signatures |

**Tier → adapter mapping** (detail in §6.1):

| Tier | Air-gapped (vLLM, open-weight) | Online (Anthropic Claude API key) |
|---|---|---|
| small | Qwen-7B / Llama-3-8B class | Claude Haiku |
| medium | Qwen-32B / DeepSeek-Coder-V2-Lite class | Claude Sonnet |
| frontier | DeepSeek-V3 / Qwen-Max / MiniMax-M2 | Claude Opus |

### 3.2 Three properties every agent must satisfy

1. **Permission manifest** (Appendix B). Declared in YAML, in git, enforced by
   the governance plane at runtime. Default-deny: an agent cannot call a tool
   unless declared.
2. **Budget envelope.** Hard caps per case and per agent per day — tokens, tool
   calls, wall-clock. Tripping a cap halts the agent and pages on-call (§4.6).
3. **Reproducible run record.** Model id + version, prompt hash, input-context
   hash, every tool call, every output — appended to the case audit log (§4.5).

### 3.3 Agent specifications

Each agent declares: trigger, outputs, allowed tools, and forbidden actions.
"Observability reads" are always performed through `grafana-mcp` with a
read-only Grafana service account (Appendix E), against self-hosted LGTM
(air-gapped) or Grafana Cloud (online).

#### Agent 0 — Supervisor / Orchestrator
- **Tier:** small (LLM invoked only for routing edge cases no rule table covers).
- **Triggers on:** any inbound signal from any intake adapter.
- **Produces:** routing decision, case record, audit entries, HITL gate decisions.
- **Allowed tools:** case store, LLM gateway (small tier), HITL gate API, event bus.
- **Must NOT:** touch any target system; modify drafted artefacts; approve on a human's behalf.

#### Agent 1 — Duty Engineer Agent
- **Tier:** small.
- **Triggers on:** Mattermost/Slack messages, automated alerts, GitLab issue creation with `kind::incident`.
- **Produces:** intake decision (incident-worthy or not); clarifying questions in-thread; opened GitLab issue with structured triage summary; dedup decision; severity proposal; paging recommendation.
- **Allowed tools:** alert store (read), runbook index (read), on-call schedule (read), GitLab Issues API (create + comment), chat API (post + thread).
- **Must NOT:** auto-page; auto-ack alerts; auto-close cases; reply in customer-facing channels.
- **Note:** the **only** agent that speaks in human-facing chat. Every reply carries an `AI draft — verify before acting` tag for the first 90 days.

#### Agent 2 — SRE Investigator Agent
- **Tier:** medium.
- **Triggers on:** triaged case `severity::medium`+ or explicit handoff from Duty Engineer.
- **Produces:** initial investigation report — hypotheses, supporting log/metric/trace excerpts, recent-change correlation, candidate mitigations, self-reported confidence score.
- **Allowed tools:** read-only — **observability via `grafana-mcp`** (`query_prometheus`, `query_loki_logs`, Tempo trace queries, dashboard search); infra reads via **Docker/Swarm API** and **`kubectl` read commands for Kubernetes/OpenShift targets**; OS-level read commands via Ansible ad-hoc; recent-change feed (GitLab MR + deploy log); runbook index.
- **Must NOT:** run any mutating command; restart any workload; write to any system.
- **Escalation:** when confidence is below threshold, severity is high, no runbook is found, or the case is a repeat-fire of an unsolved signature, the supervisor escalates to the Principal SRE Agent.

#### Agent 2a — Principal SRE Agent
- **Tier:** frontier.
- **Triggers on:** escalation from the SRE Investigator Agent.
- **Produces:** final investigation report — confirmed RCA, blast-radius assessment, recommended remediation **strategy** (not code), references to architecture docs and prior incidents.
- **Allowed tools:** all Investigator tools **plus** architecture-doc vector index (read), application-code repo search (read), service catalog (read), prior-incident corpus (read).
- **Must NOT:** any mutating command.
- **Note:** most expensive agent. Escalation policy + budget envelope keep its invocation rate to a fraction of cases. On-prem quality is visibly weaker (§6.5) — keep escalation conservative and route more cases to humans.

#### Agent 2b — Remediation Engineer Agent
- **Tier:** frontier.
- **Triggers on:** final investigation from Principal SRE needing bespoke code; or explicit pre-approved escalation with a known-but-uncoded fix.
- **Produces:** draft fix as a GitLab Merge Request — Ansible playbook / Kubernetes manifest / SQL migration / IaC diff, with pre-checks, post-checks, dry-run output, rollback plan.
- **Allowed tools:** IaC repo write to **branch only**, linter, syntax checker, dry-run sandbox (separate non-prod stack/namespace), GitLab MR API.
- **Must NOT:** merge an MR; deploy to any environment.
- **Note:** the MR goes through the same review as a human's. No fast-path approval.

#### Agent 3 — SysAdmin Drafter Agent
- **Tier:** medium.
- **Triggers on:** new GitLab issue labelled `kind::service-request`.
- **Produces:** clarifying questions as ticket comments (target, scope, environment, window, rollback); structured change spec; draft Ansible playbook / IAM JSON diff / SQL; risk note (blast radius, prerequisites, similar past tickets).
- **Allowed tools:** GitLab Issues API (comment only), IaC repo (read), CMDB / inventory (read), prior-ticket index (read).
- **Must NOT:** push to any branch; merge any MR; execute any playbook.

#### Agent 4 — Security Triage Agent
- **Tier:** medium for standard CVEs; escalates to frontier for novel ones.
- **Triggers on:** CVE feed update, vulnerability scan result, suspicious log pattern referred from SRE Investigator.
- **Produces:** per CVE/group — exploitability assessment (public-facing? auth required? known PoC? reachable code path?), affected-asset list, risk score with reasoning, draft mitigation (patch playbook MR / compensating control / config change).
- **Allowed tools:** CVE database mirror (read), SBOM (read), asset inventory (read), scanner API (read), GitLab MR API (open MR to branch).
- **Must NOT:** apply controls; merge MRs; deploy patches.

#### Agent 5 — Compliance Evidence Agent
- **Tier:** small.
- **Triggers on:** scheduled cadence (daily/weekly), control-mapped events from the audit log.
- **Produces:** evidence packets (config exports, hashed screenshots-of-record, log excerpts) mapped to control IDs (SOC2 / ISO27001 / internal); gap reports for controls with no evidence in the window.
- **Allowed tools:** read-only across all systems under the relevant controls; write to the evidence store (WORM).
- **Must NOT:** modify any configuration; close any audit finding; assign any owner.
- **Note:** lowest-risk agent. Reads everywhere, writes only to its evidence bucket.

#### Agent 6 — Postmortem Scribe Agent
- **Tier:** medium.
- **Triggers on:** case transition to `state::closed` for incidents above an eligibility threshold.
- **Produces:** draft postmortem — machine-reconstructed timeline, contributing factors as hypotheses (not assertions), proposed action items with owners and dates, a "what we'd have wanted to see in monitoring" section.
- **Allowed tools:** case audit log (read), chat archive (read), GitLab issue history (read), incident store (read), Bookstack / self-hosted Confluence write to draft space.
- **Must NOT:** assign action items autonomously; close incidents; mark postmortems final.
- **Note:** approved monitoring action items are emitted as `obs-eng-request` events for Agent 7. This closes the value loop.

#### Agent 7 — Observability Engineer Agent
- **Tier:** medium.
- **Triggers on:** (a) `obs-eng-request` events from approved postmortem action items; (b) supervisor-detected recurring case signatures; (c) new-service onboarding; (d) explicit @mention by an SRE.
- **Produces:** draft MR to the observability-as-code repo — Grafana dashboard JSON, Mimir/Prometheus recording + alert rules, Alertmanager routing, a stub runbook linking back to the originating incident.
- **Allowed tools:** case history (read), service catalog (read), existing dashboards/alerts (read), **observability query execution via `grafana-mcp`** (must execute the proposed query and attach the result), obs-as-code repo write to branch + open MR.
- **Must NOT:** merge MR; modify live alert routing; mute alerts.
- **Mandatory guardrail:** every proposed query is executed against the live stack (via `grafana-mcp`) **before** the MR is opened; the result (or a "no data returned in last 24h" warning) is attached to the MR. Without this, agents generate plausible-but-wrong queries.
- **Note:** continuous trend-mining (triggers b, c) is **disabled in v1** and enabled only after the team trusts trigger (a).

### 3.4 Roles deliberately NOT agents

| Role | Reason | Where it stays |
|---|---|---|
| Change Manager | Approval authority must remain human | On-call engineer in scope |
| Service Owner | Domain knowledge + accountability | Consulted via @mention |
| Capacity Forecaster | Deterministic tooling is better | Prometheus recording rules |
| Config Drift Detector | GitOps reconciliation already covers it | ArgoCD / Ansible |
| Customer-comms Author | Tone + accountability must remain human | Human-authored only |

---

## 4. Orchestration & governance plane

This plane delivers every governance, trust, and cost-discipline guarantee.

| Component | Purpose |
|---|---|
| Supervisor | Routing, lifecycle, audit, budgets, HITL gating |
| Intake adapters | Normalise inbound signals to one schema |
| Case store | Durable state for every case |
| HITL gate | Approval thread, signed approval, edit-with-diff |
| Permission manifest store | One YAML per agent, in git, enforced at runtime |
| Audit log writer | Append-only, WORM-backed |
| Budget enforcer | Per-case + per-agent caps |
| Noise control | Debounce, dedup, burst suppression, maintenance windows |
| Governance dashboard | Operator view of permissions, budgets, agent health |

### 4.1 Intake adapters & the Signal envelope

Every inbound signal becomes a uniform `Signal` before routing (schema in
Appendix D).

| Adapter | Source | Notes |
|---|---|---|
| Chat intake | Mattermost (on-prem), Slack (online). **Telegram not reachable on-prem.** | Listens in pre-agreed channels + DMs to a bot user |
| Alert intake | Grafana Alertmanager (or any OTel-compatible alerting) | Structured |
| Ticket intake | GitLab Issues with `kind::*` labels | Structured |
| CVE / scan intake | CVE feed mirror, vulnerability scanner | Structured |
| Cadence intake | `swarm-cronjob` / GitLab CI schedule (K8s CronJob on OpenShift) | Compliance + audits |

### 4.2 Case lifecycle

```
  signal → debounce/dedup → open Case (GitLab Issue + chat thread)
                                  │
                                  ▼
                          supervisor routes
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
              specialist drafts          specialist asks
              artefact                   clarifying Q
                    │                           │
                    └─────────────┬─────────────┘
                                  ▼
                          ★ HITL gate
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
              Approve      Approve w/ edits     Reject
                  │               │               │
                  ▼               ▼               ▼
               execute       execute amended  annotate; back to agent
                  │
                  ▼
            Case closed → Postmortem-eligible? → Scribe Agent
                                                    │
                                                    ▼
                                       Monitoring AIs? → Obs Eng Agent
```

States are tracked via `state::*` GitLab labels (§7.2).

### 4.3 HITL gate

| Property | Behaviour |
|---|---|
| One thread per case | Approval lives in Mattermost (on-prem) / Slack (online), pinned to the GitLab issue. |
| What the human sees | Rendered draft artefact, agent confidence + reasoning summary, affected systems, proposed rollback. |
| Buttons | `Approve`, `Approve with edits`, `Reject`. |
| Edit flow | `Approve with edits` opens an inline diff editor; original + edited versions both stored. |
| Identity verification | Clicker's identity checked against the on-call rotation at click time. |
| Signature | Approval is signed (crypto or audited IdP) and bound to the case ID. |
| Rotation change mid-case | Approval is **not** auto-transferred; supervisor pages the new on-call; prior approval invalidated. |
| SLA | Default 15 min for `severity::high`+. After SLA: re-page next on-call. After 2× SLA: escalate to SRE lead. |

### 4.4 Permission manifests

One YAML per agent, in version control, **enforced at runtime by the governance
plane** (default-deny). The plane loads manifests from the GitLab manifest repo
(poll/webhook); enforcement is substrate-independent. See Appendix B for the
schema and an example. Operator controls:

- **Live revocation.** A governance-dashboard toggle sets a tool to `denied`
  within seconds. No redeploy.
- **Permission audit.** Quarterly; every tool added since the last audit is reviewed.
- **Manifest drift detection.** The deployment layer reconciles against the git
  source of truth (Portainer Git-backed stack / GitLab CI on Swarm; ArgoCD on
  OpenShift). Out-of-band edits are blocked.

### 4.5 Audit log

| Property | Value |
|---|---|
| Storage | MinIO WORM bucket (on-prem) / S3 with Object Lock (online) |
| Granularity | One append-only record per case |
| Schema | JSONL — one event per line (Appendix D) |
| Entries | Signal payload; every agent invocation (model id, prompt hash, input-context hash, output hash); every tool call (id, args, response hash, latency); every HITL decision (who, when, raw + edited diff); every state transition |
| Retention | Aligned to compliance scope (SOC2: ≥ 1 yr security events; 7 yrs some controls) |
| Verification | Periodic offline hash-chain verification |

**No agent may write directly to the audit log.** Only the audit-writer service
holds credentials, exposing an append-only API.

### 4.6 Budget enforcement

| Layer | Cap | On breach |
|---|---|---|
| Per case | tokens, tool calls, wall-clock | Halt the agent; post `budget exceeded` in the case thread; page on-call with current state + draft so far |
| Per agent per day | total tokens, total frontier invocations | Disable the agent for the day; alert the SRE lead |

Caps are environment-specific (prod tighter than staging). Frontier tier
(Principal SRE, Remediation Engineer) carries the tightest caps.

### 4.7 Noise control

| Rule | Behaviour |
|---|---|
| Identity dedup | Same alert signature within a rolling window → attach to existing case |
| Burst suppression | > N similar signals in M seconds → collapse into one case with attached count |
| Maintenance windows | Declared via calendar; signals recorded but specialists not invoked |
| Source quality scoring | Chat messages get a cheap incident-likelihood score before invoking the full Duty Engineer Agent; very-low-score messages get a canned response or none |

Every suppression event is itself logged and surfaced on the dashboard.

### 4.8 Governance dashboard

A single web view (also rendered as Grafana panels):

- Per agent: current manifest, budget envelope, today's spend, current state
  (idle / running case X / disabled).
- Per-agent revoke toggles for individual tools.
- Per-environment **global kill-switch** (`pause all agents`) — invocable by SRE
  lead, audit-logged. In-flight cases pause gracefully; queued signals stay queued.
- Active cases and HITL gate state; suppression counts and dedup hit rate;
  audit-log hash-chain verification status.

### 4.9 Supervisor reliability

- **Stateless.** All state in PostgreSQL + the event bus; restartable anytime.
- **Replicated.** Two instances, active-active.
- **Backpressure-aware.** When event-bus lag rises, lowest-priority intakes pause
  first (cadence-driven compliance before incident-driven signals).

---

## 5. Workflow mappings

Five workflows in v1. **★ marks HITL gates** — humans cannot be skipped there.

### 5.1 Incident response (chat- or alert-initiated)

```
   Signal (chat msg | Alert | GitLab issue kind::incident)
        │  ▼  Supervisor — intake, dedup, open case
        ▼
   Duty Engineer Agent — filter chatter, ask 2–3 Qs, open issue, post triage
        ▼
   SRE Investigator Agent — pull logs/metrics/traces (grafana-mcp) +
        recent-change feed; draft report; self-report confidence
        ├── confidence ≥ threshold AND runbook found ──┐
        └── escalate ─► Principal SRE Agent             │
                          • final RCA + strategy        │
                                  ▼                      │
                          Remediation Engineer ◄─────────┘
                            • draft fix MR + pre/post checks + rollback
                                  ▼
                          ★ HITL GATE — on-call approves
                                  ▼
                          Execute via Ansible / GitLab CI / kubectl
                                  ▼
                          Case closed → Postmortem Scribe (if eligible)
```

Cost shaping: most cases stop at the medium-tier Investigator with a known
runbook. Frontier tiers fire only on escalation (low confidence, high severity,
no runbook, novel signature, recent-deploy correlation, repeat-fire).

### 5.2 SysAdmin service tickets

```
   New GitLab ticket (kind::service-request, free-text)
        ▼  Supervisor → SysAdmin Drafter Agent
   SysAdmin Drafter — parse request; ask structured Qs (target/scope/env/window/
        rollback); look up similar tickets; produce change spec + draft playbook/
        IAM diff/SQL + risk note + suggested approver
        ▼
   ★ HITL GATE — on-call SysAdmin reviews (Approve / Approve w/ edits / Reject)
        ▼
   Execute via existing Ansible / GitLab CI pipeline
        ▼
   SysAdmin Drafter writes verification output back to ticket; closes ticket
```

The agent never executes the playbook; the existing CI pipeline does, after approval.

### 5.3 Patch & vulnerability management

```
   CVE feed update | scan results
        ▼  Supervisor → Security Triage Agent (medium)
   Security Triage — pull SBOM + asset inventory + exposure; assess
        exploitability per CVE; group by remediation; produce per-group affected
        assets + risk score + draft mitigation (patch MR / IaC diff / WAF rule);
        escalate novel CVEs to frontier
        ▼
   ★ HITL GATE — security lead reviews + prioritises (sets the actual queue)
        ▼
   Existing patching pipeline executes (Ansible + GitLab CI)
        ▼
   Security Triage verifies post-patch scan; updates risk register
```

Boundary: the agent never decides patch priority autonomously.

### 5.4 Postmortem + observability authoring — the value loop

```
   Incident case closed (state::closed)
        ▼
   Postmortem Scribe — reconstruct timeline from audit log; pull chat + ticket
        + metric/log excerpts; draft postmortem (timeline, contributing factors
        as hypotheses, action items w/ owners, "what we'd want in monitoring")
        ▼
   ★ HITL GATE — incident lead reviews + finalises; tags monitoring action items
        ▼
   Approved monitoring action items → obs-eng-request events
        ▼
   Observability Engineer — read request + signal patterns; draft Grafana
        dashboard JSON + Mimir/Prometheus rules + Alertmanager routing + stub
        runbook; EXECUTE proposed query via grafana-mcp (attach result/"no data");
        open MR to obs-as-code repo
        ▼
   ★ HITL GATE — SRE reviews + merges MR
        ▼
   New alert/dashboard live → next time the issue is caught earlier with richer context
```

### 5.5 Compliance evidence (cadence-driven)

```
   Cadence trigger (daily | weekly | per-control-event)
        ▼
   Compliance Evidence Agent (small) — per control collect prescribed evidence
        (config exports, screenshots-of-record, log excerpts); hash + sign; map
        to control IDs; detect gaps (control with no evidence in window)
        ▼
   Evidence packets → WORM evidence store
   Gap report → compliance channel (gaps tagged "monitoring-missing" → Obs Engineer)
        ▼
   ★ HITL GATE — only when gap closure needs human action
```

No state changes here in v1 — purely read + write to the evidence store.

### 5.6 How workflows chain

| Trigger | Chains into | Result |
|---|---|---|
| Incident closed | Postmortem Scribe → Observability Engineer | Monitoring improvement merged |
| Service ticket reveals misconfig class | Security Triage Agent | Risk surfaced + draft mitigation |
| Compliance gap = missing monitoring | Observability Engineer | New evidence-yielding dashboard |
| Recurring case signature | Observability Engineer (proactive) | Trend-based dashboard (v2 — disabled in v1) |

---

## 6. Deployment model

### 6.1 Adapter inventory

Baseline substrate is **Docker Compose / Swarm** in both environments;
**OpenShift is the future substrate** (Appendix A). Adapter defaults:

| Capability port | Air-gapped / on-prem default | Online default |
|---|---|---|
| LLM gateway — small | vLLM serving Qwen-7B / Llama-3-8B class | **Anthropic Claude API (Haiku), API key** |
| LLM gateway — medium | vLLM serving Qwen-32B / DS-Coder-V2-Lite class | **Claude API (Sonnet)** |
| LLM gateway — frontier | vLLM serving DeepSeek-V3 / Qwen-Max / MiniMax-M2 | **Claude API (Opus)**; Bedrock optional |
| Observability stack | self-hosted Grafana LGTM (Loki/Tempo/Mimir/Alloy) | **Grafana Cloud (free tier)** |
| Observability **read access (agents)** | **`grafana-mcp` → LGTM** | **`grafana-mcp` → Grafana Cloud** |
| Object storage (audit + evidence) | MinIO WORM bucket | S3 + Object Lock (+ Glacier) |
| Case / state store | PostgreSQL + Redis (Swarm services + volumes) | RDS Postgres + ElastiCache (or PG/Redis on Swarm-EC2) |
| Event bus | **Kafka or Redpanda** (Swarm services + volumes) | Amazon MSK (or Kafka/Redpanda on Swarm-EC2) |
| Point-to-point queue *(if needed)* | RabbitMQ | Amazon MQ |
| Secrets | HashiCorp Vault → **Docker Swarm secrets** | AWS Secrets Manager (or Vault) |
| Identity / SSO (HITL) | Keycloak | Cognito / workforce SSO |
| Ticketing / SCM | **GitLab (same in both)** | **GitLab (same in both)** |
| Config-mgmt executor | **Ansible** (existing) | **Ansible** + AWS SSM Run Command for AWS-managed resources |
| Chat — primary | **Mattermost** | **Slack** |
| Chat — secondary | Mattermost only — Telegram not reachable on-prem | Slack + Telegram (echo only) |
| Code / arch context index | self-hosted vector store (Qdrant / Weaviate / pgvector) over local repos + Bookstack / self-hosted Confluence / GitLab Wiki | same |
| CVE / threat feed | offline mirror, updated via approved channel | live feed |
| **Substrate / orchestrator** | **Docker Swarm + Portainer** | **Docker Swarm on EC2** (EKS / OpenShift = alternatives) |
| **Deploy / CD** | **Portainer Git-backed stacks (poll/webhook) + GitLab CI image build/push** | same pattern (or ECS/EKS pipeline) |

`grafana-mcp` runs as a service in the stack with a **read-only Grafana service
account token**; only `GRAFANA_URL` + token differ between Cloud and self-hosted
LGTM (Appendix E). This makes the observability-read adapter identical in code
across environments.

### 6.2 Baseline reference shape — Docker Swarm + Portainer (air-gapped)

Deployed as Compose v3 **stack files** via `docker stack deploy --compose-file
<file> <stack>` (build is ignored — images come pre-built from the internal
registry). Stacks are managed by **Portainer** with **Git-backed stacks**
pointing at the internal GitLab repo (polling interval or webhook; Portainer
compares the latest commit hash and redeploys on change). Secrets are Docker
Swarm secrets (`docker secret create`), sourced from Vault.

```
┌──────────────────── Docker Swarm cluster (Portainer-managed) ────────────────────┐
│                                                                                  │
│  stack: sre-framework-core                                                       │
│   ├── supervisor            (replicas: 2)                                        │
│   ├── case-api              (replicas: 2)                                        │
│   ├── audit-writer          (replicas: 2)                                        │
│   ├── governance-dashboard  (replicas: 1)                                        │
│   ├── postgres + redis      (services + named volumes)                           │
│   ├── kafka OR redpanda     (event bus; services + volumes)                      │
│   ├── rabbitmq              (only if ordered point-to-point hand-offs needed)    │
│   └── grafana-mcp           (read-only SA token → LGTM)                          │
│                                                                                  │
│  stack: sre-framework-agents                                                     │
│   ├── duty-engineer / sre-investigator / principal-sre / remediation-engineer    │
│   ├── sysadmin-drafter / security-triage / postmortem-scribe / obs-engineer      │
│   └── compliance-evidence  (driven by swarm-cronjob / ofelia OR GitLab CI sched) │
│                                                                                  │
│  stack: sre-framework-llm                                                        │
│   ├── vllm-small / vllm-medium  (GPU via deploy.resources.reservations.devices)  │
│   └── vllm-frontier             (GPU — tight scheduling; see §6.6)               │
│                                                                                  │
│  stack: sre-framework-storage   (MinIO WORM + Qdrant)                            │
│  (Grafana LGTM: existing self-hosted stack)                                      │
│                                                                                  │
│  Talks to existing systems: GitLab · Mattermost · Vault · Ansible / GitLab CI    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Permission manifests live in a dedicated GitLab repo; the governance plane loads
and enforces them at runtime, and Portainer/GitLab CI keep the deployed manifest
files reconciled to git.

### 6.3 Online reference shape (AWS)

Same Compose stacks run on **Docker Swarm on EC2** (single deployment artifact).
Adapter swaps from the air-gapped shape:

- **Anthropic Claude API key** replaces the entire `sre-framework-llm` stack
  (no vLLM, no GPU nodes online).
- **Grafana Cloud (free tier)** replaces self-hosted LGTM; agents still read via
  `grafana-mcp` (only `GRAFANA_URL` + token change).
- **S3 + Object Lock** replaces MinIO; **RDS + ElastiCache** replace in-stack
  PG/Redis (or keep them on Swarm-EC2); **MSK** replaces self-hosted Kafka;
  **Secrets Manager** replaces Vault; **Cognito / SSO** replaces Keycloak.
- Same external systems: GitLab, Ansible (+ SSM), Slack, Telegram (echo).

### 6.4 Future substrate — OpenShift

OpenShift is a supported future target. The same container images deploy via
Helm charts + ArgoCD; Swarm primitives map to K8s primitives per Appendix A.
CORE requires no change because it is substrate-agnostic (§2.3). This path is
documented now so no Swarm-only assumption leaks into CORE.

### 6.5 Air-gapped considerations

1. **Model weights distribution.** Open-weight weights enter via an approved
   channel (sneakernet / internal artifact repo / signed bundle). Plan ~50–500 GB
   per model; quarterly update cadence. Record weight hashes.
2. **CVE feed.** No live NVD pull. Mirror the CVE database on a fixed cadence;
   the Security Triage Agent reads the mirror only.
3. **External docs / SDKs.** Architecture and code-context indexes built from
   internal sources only (Bookstack / self-hosted Confluence / GitLab Wiki).
4. **Time & NTP.** Audit-log integrity depends on monotonic, accurate timestamps;
   confirm signed NTP inside the air-gapped zone.
5. **Egress.** Every agent's outbound network policy is `default-deny` with
   explicit allow-lists. Blocks accidental telemetry, model "phone home", and
   prompt-injection-driven exfiltration. (Swarm: overlay networks + host
   firewall / no external routes; K8s future: NetworkPolicy.)
6. **Image supply.** All images pre-built and pushed to the internal registry;
   `docker stack deploy` ignores `build:` — nothing is built on cluster nodes.

### 6.6 Quality expectations — open-weight vs frontier

| Tier | Online (Claude API) | On-prem (open-weight, quantised, GPU-bounded) | Implication |
|---|---|---|---|
| Small | Haiku | Qwen-7B / Llama-3-8B | Close to parity for triage / dedup |
| Medium | Sonnet | Qwen-32B / DS-Coder-V2-Lite | ~80–90 % of frontier quality for investigation drafts |
| Frontier | Opus | DeepSeek-V3 / Qwen-Max / MiniMax-M2 | **Visibly weaker** for code reasoning + novel RCA; higher human edit rate at Principal SRE / Remediation steps |

**Mitigation on-prem:** keep escalation conservative; route a higher fraction of
cases directly to humans. The on-prem deployment delivers real value at small +
medium tiers; frontier-tier value is a supplement, not a replacement.

### 6.7 GPU planning (air-gapped only)

Online uses the Claude API and needs no GPUs. On-prem is GPU-bounded:

| Tier | Typical inflight | Memory (quantised) | Notes |
|---|---|---|---|
| Small | 1–4 concurrent | ~10–20 GB VRAM | Single A100 / L40S sufficient |
| Medium | 1–2 concurrent | ~40–80 GB VRAM | Single A100 80 GB or dual L40S |
| Frontier | 1 concurrent (queued) | 200–600 GB VRAM (multi-GPU) | Schedule tightly; budget caps prevent contention |

GPUs are reserved in the stack file via
`deploy.resources.reservations.devices: [{driver: nvidia, count: N,
capabilities: [gpu]}]`. **Note:** Swarm GPU scheduling is more manual than
Kubernetes (node labelling / generic resources; one GPU class per node is
simplest). If GPU capacity is the binding constraint, **freeze the frontier tier
first** — small + medium cover ~85 % of the framework's value.

---

## 7. Preconditions & phased rollout

### 7.1 Preconditions

| Precondition | What it means | Why needed |
|---|---|---|
| Service catalogue exists | Every service has owner, tier, runbook link, on-call route, comms channel | Agents must know who owns what and where to route |
| GitLab labels consistent | Group-level scoped label dictionary, applied via issue templates | Drives intake routing, lifecycle, HITL signalling (§7.2) |
| On-call rotation queryable via API | Framework must know who is on call right now | HITL routing + SLA escalation |
| Existing Ansible playbooks inventoried | SysAdmin Drafter reuses them | Quality of draft playbooks depends on this corpus |
| Permission-manifest repo exists | One GitLab repo as source of truth | Drives default-deny governance |
| Maintenance windows declared queryably | Supervisor must not fire during them | Avoids false-positive cases during planned work |
| Internal registry + GitLab reachable (air-gapped) | Images pre-built/pushed; Portainer Git-backed stacks point here | Baseline deploy + GitOps depend on it |

### 7.2 GitLab labels — minimum dictionary (24)

Use **group-level scoped labels** (inherited by every project). Issue templates
(`.gitlab/issue_templates/*.md`) default-apply the right `kind::*` label.

```
kind::incident   kind::service-request   kind::cve   kind::postmortem   kind::obs-request
domain::db   domain::iam   domain::network   domain::k8s   domain::os   domain::app
severity::critical   severity::high   severity::medium   severity::low
state::triage   state::investigating   state::awaiting-approval   state::executing   state::closed
review::needs-approval   review::approved   review::rejected
ai::draft-pending        ai::human-edited
```

### 7.3 Phased rollout

Each phase gated on the previous phase's exit criteria. Same shape in both
environments.

- **Phase 0 — Foundations.** Stand up supervisor, case-api, audit-writer,
  governance-dashboard; event bus, PostgreSQL, Redis, MinIO/S3; apply the GitLab
  label dictionary + issue templates; build/verify service catalogue + on-call
  API; inventory Ansible playbooks; configure permission-manifest repo
  (default-deny). **Exit:** dashboard live; supervisor accepts a synthetic signal
  and writes to the audit log; no agents enabled.
- **Phase 1 — Triage & Investigation (read-only).** Enable Duty Engineer +
  SRE Investigator. Stay read-only; no HITL gates fire. **Exit:** ≥ 100 cases
  handled; edit rate trending down; no signal lost; no permission breach; caps
  not tripped.
- **Phase 2 — Drafting.** Enable SysAdmin Drafter + Postmortem Scribe. First
  HITL gates fire. **Exit:** ≥ 50 SysAdmin tickets and ≥ 5 postmortems with HITL
  approval; edit rate documented; no out-of-scope tool calls.
- **Phase 3 — Security & Compliance.** Enable Security Triage + Compliance
  Evidence (low blast radius). **Exit:** evidence store accumulating; risk
  register updated; first compliance gap report reviewed.
- **Phase 4 — Senior tier & the value loop.** Enable Principal SRE + Remediation
  Engineer + Observability Engineer. Frontier caps tight; escalation
  conservative. **Exit:** ≥ 10 frontier escalations; first observability MR
  merged; first "we caught this with the new alert" incident.
- **Phase 5 — Trust calibration & tuning (steady state).** Quarterly permission
  audit; quarterly model-bundle review (on-prem) / version review (online);
  quality regression replays against historical incidents; consider enabling
  Observability Engineer trend-mining (trigger b) once trigger (a) is trusted.

**This rollout is NOT:** Big Bang (each phase delivers value independently);
ship-and-forget (Phase 5 disciplines are ongoing); headcount reduction (roles
shift from manual drafting toward review and exception handling).

### 7.4 Day-one ownership

| Component | Owner |
|---|---|
| Framework operation (supervisor, agents, dashboard) | SRE team |
| Permission manifests | SRE team, reviewed by Security |
| Audit log + evidence store | Compliance |
| Budget caps + cost reporting | SRE lead + Finance liaison |
| Model registry (on-prem weights) | SRE team + Security |
| Incident response on the framework itself | On-call SRE |

The framework is operated like any internal platform: its own on-call, runbooks,
and postmortems (drafted by its own Postmortem Scribe Agent).

---

## 8. Risks, limits & failure modes

### 8.1 Known risks & mitigations

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | Hallucinated investigation misleads on-call | High | Confidence scoring; mandatory evidence excerpts; HITL review of every draft; "AI draft" tag for first 90 days |
| 2 | Prompt injection via chat / ticket / log content | Medium | Strict input sanitisation; no write tools by default; tool calls via a policy proxy rejecting out-of-scope targets; default-deny egress |
| 3 | Alert storm → agents → GPU starved | Medium | Debounce + dedup + burst suppression; per-case caps; daily per-agent caps; queue with backpressure |
| 4 | Stale / compromised model weights on-prem | Medium | Signed bundles via approved channel; weight hashes recorded; quarterly review; upgrades are change-managed |
| 5 | Audit log tampering | Low | WORM storage; append-only writer with separate credentials; periodic offline hash-chain verification |
| 6 | Permission creep | Medium | Manifests in git, reviewed via MR; quarterly audit; default-deny baseline |
| 7 | Engineers over-rely on agent output | Medium | "AI draft" tag persists; SRE leads track human-edit rate; periodic "agent off" drills |
| 8 | Sensitive data leakage to external LLM (online) | Medium | Pre-flight redaction filter (PII, credentials, customer data); contractual zero-retention; on-prem-only for regulated workloads |
| 9 | Silent agent quality drift | High over time | Sampled human review (week 1: 100 %, ramp down); per-agent quality dashboard; regression replays against historical incidents |
| 10 | Supervisor bottleneck / SPOF | Medium | Stateless, two replicas, state in PostgreSQL + event bus; cases survive restart |

### 8.2 Failure modes & framework behaviour

| Failure | Behaviour |
|---|---|
| LLM gateway down (any tier) | Cases queue with a posted "LLM unavailable, human on-call required" message. No silent failure. |
| Supervisor crashes | Replica takes over; in-flight cases resume from durable state. No lost signals. |
| HITL approver non-responsive past SLA | Re-page next on-call; after 2× SLA escalate to SRE lead. Default SLA 15 min for `severity::high`+. |
| Tool call fails (e.g. GitLab API down) | Agent reports failure, marks case `state::awaiting-tooling`, posts status; does not retry blindly. |
| Budget cap tripped mid-case | Agent halts, case annotated, on-call paged with current state + draft so far. |
| Frontier model returns malformed output | Validator rejects; supervisor falls back to medium tier with the same context; if that also fails, hand to human. |
| Event-bus backpressure | Supervisor pauses lowest-priority intakes first (cadence compliance before incident signals). |

### 8.3 Quality limits to state plainly

- On-prem frontier output is visibly weaker than online; plan for higher human
  edit rate in air-gapped deployments.
- The Observability Engineer will sometimes propose alerts that don't fire;
  mandatory query verification (via `grafana-mcp`) reduces but doesn't eliminate
  this. SRE review of the MR is the safety net.
- The framework cannot infer business impact; severity is driven by signal
  patterns + service-tier metadata. Humans correct this at the HITL gate.
- Code-level fixes from the Remediation Engineer get full code-review treatment —
  no fast-path approval.
- Agents do not learn from a single case; quality improvements come from manifest
  updates, prompt updates, and model upgrades.

### 8.4 The single most important safety control

The load-bearing safety control is the **HITL approval gate** (§4.3). Every state
change passes through it; it cannot be bypassed by any agent. Its identity
verification, signature, and audit logging form the framework's compliance
posture. If the gate is ever compromised, pause the framework via the
kill-switch (§4.8) and review before resuming.

---

## Appendix A — Substrate primitive map (Swarm baseline ↔ OpenShift future)

| Concern | Baseline now: Docker Swarm + Portainer | Future: OpenShift / Kubernetes |
|---|---|---|
| Packaging / deploy | Compose v3 stack files (`docker stack deploy`, pre-built images) | Helm charts (same images) |
| GitOps / CD | Portainer Git-backed stacks (polling + webhook) against internal GitLab; GitLab CI builds/pushes images | ArgoCD |
| Isolation | Swarm stacks + overlay networks | Namespaces / projects |
| Event bus | Kafka or Redpanda as Swarm services + volumes | Strimzi operator |
| State store | PostgreSQL + Redis as Swarm services + named volumes | PG/Redis operators |
| Cadence (Compliance agent) | `swarm-cronjob` / ofelia, or GitLab CI scheduled pipeline | CronJob |
| Secrets | Vault → Docker Swarm secrets (`docker secret create`) | Vault + CSI / Agent injector |
| LLM serving (GPU) | vLLM Swarm service w/ `deploy.resources.reservations.devices`; manual GPU pinning | vLLM Deployment + device plugin |
| Egress control | Overlay networks + host firewall / no external routes | NetworkPolicy |
| Management console | **Portainer** | OCP console |
| Permission-manifest sync | Portainer Git-backed stack / GitLab CI keeps files reconciled; governance plane enforces at runtime | ArgoCD applies; governance plane enforces at runtime |
| Investigator infra reads | Docker / Swarm API + Portainer API + `docker service logs`; `kubectl`-read only for K8s targets under investigation | `kubectl` (read) for the substrate and targets |

CORE is identical across both columns (§2.3).

## Appendix B — Permission manifest schema

One YAML per agent, in the manifest repo. Default-deny: a tool not declared
cannot be called. Example:

```yaml
# agents/principal-sre.yaml
agent: principal-sre
version: 1
tier: frontier
budgets:
  tokens_per_case: 200000
  tool_calls_per_case: 60
  wallclock_per_case: 10m
  tokens_per_day: 5000000
  frontier_invocations_per_day: 40
tools:
  - id: o11y.read              # implemented via grafana-mcp, read-only SA token
    scopes: ["env:prod", "env:stg"]
  - id: code.search
    scopes: ["repo:service-*"]
  - id: arch_docs.read
    scopes: ["bookstack://sre/*"]
  - id: prior_incidents.read
    scopes: ["all"]
# No write tools declared. The agent cannot mutate any system.
```

## Appendix C — GitLab label dictionary

The 24 labels in §7.2. The team may add more for internal reporting; the
framework depends only on these.

## Appendix D — Signal envelope & audit schema

**Signal** (intake-normalised):

```yaml
signal:
  id: sig-2026-05-13-0001
  source: mattermost | slack | alertmanager | gitlab | cve-feed | cadence
  received_at: 2026-05-13T09:14:22Z
  reporter:
    type: human | system
    id: alex.goh@example.com | grafana-alertmanager
  channel: "ops-incidents"          # chat sources
  payload: { ...raw... }
  metadata:
    correlation_ids: []
    quality_score: 0.0..1.0          # chat-intake only
```

**Audit log:** JSONL, one event per line, one append-only record per case.
Entries: signal payload; agent invocations (model id + version, prompt hash,
input-context hash, output hash); tool calls (id, args, response hash, latency);
HITL decisions (who, when, raw + edited diff); state transitions. Stored on
MinIO WORM (on-prem) / S3 Object Lock (online); periodic offline hash-chain
verification.

## Appendix E — Observability reads via `grafana-mcp`

The Grafana MCP server is the single mechanism by which agents read
observability data, in both environments.

- **Deployment.** Runs as a service in the stack (air-gapped: in the Swarm
  cluster pointing at self-hosted LGTM; online: pointing at Grafana Cloud).
- **Auth.** A **read-only Grafana service account token**; only `GRAFANA_URL`
  and the token differ between environments. RBAC scopes used: `datasources:read`,
  `datasources:query`.
- **Tools used (read-only):** `query_prometheus` (PromQL instant/range over
  Mimir/Prometheus), `query_loki_logs` (LogQL logs + metric queries, plus label/
  pattern metadata), Tempo trace queries, `list_datasources`,
  `list_prometheus_metric_names`, dashboard search, alert/incident listing.
- **Used by:** SRE Investigator (evidence gathering), Principal SRE (review),
  Observability Engineer (**mandatory pre-MR query execution** — attach result or
  "no data returned in last 24h").
- **Guardrail:** agents hold no write/admin Grafana scopes; dashboard/alert
  changes are proposed only as MRs to the obs-as-code repo (§3.3, Agent 7).
