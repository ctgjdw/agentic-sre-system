# 03 — Agent Roster

> Audience: engineering. This document specifies each agent's scope, inputs,
> outputs, allowed tools, and the actions it must *never* perform.

## At-a-glance roster

| # | Agent | Tier | Job |
|---|---|---|---|
| 0 | Supervisor / Orchestrator | small | Route signals; own lifecycle, audit, budgets, HITL gate |
| 1 | Duty Engineer Agent | small | L1 triage; chat-message intake; dedup; case opening |
| 2 | SRE Investigator Agent | medium | Initial investigation from logs/metrics/traces |
| 2a | Principal SRE Agent | frontier | Senior review of investigations; final RCA with code + architecture context |
| 2b | Remediation Engineer Agent | frontier | Draft the actual fix as an MR (Ansible / IaC / SQL / k8s) |
| 3 | SysAdmin Drafter Agent | medium | Turn free-text service tickets into structured change specs + draft playbooks |
| 4 | Security Triage Agent | medium (escalates to frontier) | CVE exploitability + draft mitigation MR |
| 5 | Compliance Evidence Agent | small | Continuous evidence collection; gap detection |
| 6 | Postmortem Scribe Agent | medium | Timeline reconstruction; draft postmortem; action items |
| 7 | Observability Engineer Agent | medium | Draft Grafana dashboards + alert rules from incidents and recurring signatures |

## Three properties every agent must satisfy

1. **Permission manifest.** Declared in YAML, in git, applied by the governance
   plane. Lists every tool the agent may call and the scopes it may act on.
2. **Budget envelope.** Hard caps per case and per agent per day — tokens,
   tool calls, wall-clock. Tripping a cap halts the agent and pages on-call.
3. **Reproducible run record.** Model id + version, prompt hash, input
   context hash, every tool call, every output — appended to the case's
   audit log.

See [04-orchestration-and-governance.md](04-orchestration-and-governance.md)
for the schema and enforcement details.

---

## Agent 0 — Supervisor / Orchestrator

| Property | Value |
|---|---|
| **Tier** | small / fast model (used only when no deterministic rule applies) |
| **Triggers on** | Any inbound signal from any intake adapter |
| **Produces** | Routing decision, case record, audit entries, HITL gate decisions |
| **Allowed tools** | Case store, LLM gateway (small tier), HITL gate API, Kafka event bus |
| **Must NOT** | Touch any target system; modify drafted artefacts; approve on a human's behalf |

The supervisor is deterministic where possible. The LLM is invoked only for
routing edge cases that rule tables don't cover.

## Agent 1 — Duty Engineer Agent

| Property | Value |
|---|---|
| **Tier** | small (Haiku / Qwen-7B / Llama-3-8B class) |
| **Triggers on** | Mattermost / Slack chat messages, automated alerts, GitLab issue creation with `kind::incident` |
| **Produces** | (a) Intake decision (incident-worthy or not), (b) clarifying questions in-thread, (c) opened GitLab Issue with structured triage summary, (d) dedup decision against open cases, (e) severity proposal, (f) paging recommendation |
| **Allowed tools** | Alert store (read), runbook index (read), on-call schedule (read), GitLab Issues API (create + comment), Mattermost API (post + thread) |
| **Must NOT** | Auto-page; auto-ack alerts; auto-close cases; reply in customer-facing channels |

The Duty Engineer Agent is the **only** agent that speaks in human-facing chat
channels. Every reply carries an `AI draft — verify before acting` tag for the
first 90 days of operation.

## Agent 2 — SRE Investigator Agent

| Property | Value |
|---|---|
| **Tier** | medium (Sonnet / Qwen-32B / DeepSeek-Coder-V2-Lite class) |
| **Triggers on** | Triaged case with `severity::medium` or higher, OR explicit handoff from Duty Engineer Agent |
| **Produces** | Initial investigation report: hypotheses, supporting log / metric / trace excerpts, recent-change correlation, candidate mitigations, self-reported confidence score |
| **Allowed tools** | Read-only: Loki / Tempo / Mimir queries, kubectl read commands, OS-level read commands via Ansible ad-hoc, recent-change feed (GitLab MR + deploy log), runbook index |
| **Must NOT** | Run any mutating command; restart any workload; write to any system |

The Investigator self-reports confidence. When confidence is below the
escalation threshold, when severity is high, when no runbook is found, or when
the case is a repeat-fire of an unsolved signature, the supervisor escalates to
the Principal SRE Agent.

## Agent 2a — Principal SRE Agent

| Property | Value |
|---|---|
| **Tier** | **frontier** (Claude Opus online; DeepSeek-V3 / Qwen-Max / MiniMax-M2 on-prem) |
| **Triggers on** | Escalation from the SRE Investigator Agent |
| **Produces** | Final investigation report: confirmed root cause analysis, blast-radius assessment, recommended remediation **strategy** (not the code), references to architecture docs and prior incidents |
| **Allowed tools** | All Investigator tools, **plus** architecture-doc vector index (read), application-code repo search (read), service catalog (read), prior-incident corpus (read) |
| **Must NOT** | Any mutating command |

The Principal SRE is the framework's most expensive agent. The escalation
policy and the budget envelope keep its invocation rate to a fraction of all
cases. Expected on-prem quality: visibly weaker than online; mitigated by
keeping escalation conservative and routing more cases directly to humans on
on-prem.

## Agent 2b — Remediation Engineer Agent

| Property | Value |
|---|---|
| **Tier** | **frontier** |
| **Triggers on** | Final investigation from Principal SRE with a remediation strategy that requires bespoke code; OR explicit pre-approved escalation from SRE Investigator with a known-but-uncoded fix |
| **Produces** | Draft fix as a GitLab Merge Request: Ansible playbook / Kubernetes manifest / SQL migration / IaC diff, with pre-checks, post-checks, dry-run output, and a rollback plan |
| **Allowed tools** | IaC repo write to **branch only**, linter, syntax checker, dry-run sandbox (a separate non-prod namespace), GitLab Merge Request API |
| **Must NOT** | Merge a merge request; deploy directly to any environment |

The MR produced by this agent goes through the same review process as a human
engineer's MR. No fast-path approval.

## Agent 3 — SysAdmin Drafter Agent

| Property | Value |
|---|---|
| **Tier** | medium |
| **Triggers on** | New GitLab issue labelled `kind::service-request` |
| **Produces** | (a) Clarifying questions as ticket comments (target, scope, environment, window, rollback), (b) structured change spec, (c) draft Ansible playbook / IAM JSON diff / SQL statement, (d) risk note (blast radius, prerequisites, similar past tickets) |
| **Allowed tools** | GitLab Issues API (comment only), IaC repo (read), CMDB / inventory (read), prior-ticket index (read) |
| **Must NOT** | Push to any branch; merge any MR; execute any playbook |

This agent absorbs the largest volume of day-to-day SysAdmin toil. Its value
compounds as the prior-ticket index grows.

## Agent 4 — Security Triage Agent

| Property | Value |
|---|---|
| **Tier** | medium for standard CVEs; escalates to frontier for novel ones |
| **Triggers on** | CVE feed update, vulnerability scan result, suspicious log pattern referred from SRE Investigator |
| **Produces** | Per CVE or CVE group: exploitability assessment (public-facing? auth required? known PoC? reachable code path?), affected-asset list, risk score with reasoning, draft mitigation (patch playbook MR / compensating control / config change) |
| **Allowed tools** | CVE database mirror (read), SBOM (read), asset inventory (read), scanner API (read), GitLab MR API (open MR to branch) |
| **Must NOT** | Apply controls; merge MRs; deploy patches |

## Agent 5 — Compliance Evidence Agent

| Property | Value |
|---|---|
| **Tier** | small |
| **Triggers on** | Scheduled cadence (daily / weekly), control-mapped events from the audit log |
| **Produces** | Evidence packets (config exports, hashed screenshots of record, log excerpts) mapped to control IDs (SOC2 / ISO27001 / internal); gap reports listing controls with no evidence in the window |
| **Allowed tools** | Read-only access across all systems under the relevant controls; write to the evidence store (WORM) |
| **Must NOT** | Modify any configuration; close any audit finding; assign any owner |

Lowest-risk agent in the roster. Reads everywhere, writes only to its dedicated
evidence bucket.

## Agent 6 — Postmortem Scribe Agent

| Property | Value |
|---|---|
| **Tier** | medium |
| **Triggers on** | Case state transition to `state::closed` for incidents above an eligibility threshold |
| **Produces** | Draft postmortem document: machine-reconstructed timeline, contributing factors as hypotheses (not assertions), proposed action items with owners and dates, a "what we'd have wanted to see in monitoring" section |
| **Allowed tools** | Case audit log (read), Mattermost / Slack chat archive (read), GitLab issue history (read), incident store (read), Confluence / Bookstack write to draft space |
| **Must NOT** | Assign action items autonomously; close incidents; mark postmortems final |

Approved monitoring action items are emitted as `obs-eng-request` events,
consumed by the Observability Engineer Agent. This is how the value loop closes.

## Agent 7 — Observability Engineer Agent

| Property | Value |
|---|---|
| **Tier** | medium |
| **Triggers on** | (a) `obs-eng-request` events from approved postmortem action items, (b) supervisor-detected recurring case signatures, (c) new-service onboarding, (d) explicit @mention by an SRE |
| **Produces** | Draft MR to the observability-as-code repo containing: Grafana dashboard JSON, Mimir / Prometheus recording + alert rules, Alertmanager routing, a stub runbook linking back to the originating incident |
| **Allowed tools** | Case history (read), service catalog (read), existing dashboards / alerts (read), O11y stack query API (read — **must execute the proposed query and attach the result**), obs-as-code repo write to branch + open MR |
| **Must NOT** | Merge MR; modify live alert routing; mute alerts |

Mandatory: every proposed query is executed against the live observability
stack before the MR is opened. The execution result (or a "no data returned in
last 24h" warning) is attached to the MR. Without this guardrail, agents
generate plausible-looking but wrong queries.

Continuous trend-mining (triggers b and c) is disabled in v1 and enabled only
after the team trusts trigger (a) — otherwise the SRE team drowns in unsolicited
MRs.

---

## Roles that are deliberately NOT agents

| Role | Reason | Where it stays |
|---|---|---|
| Change Manager | Approval authority — must remain human | On-call engineer in scope |
| Service Owner | Domain knowledge + accountability | Consulted via @mention |
| Capacity Forecaster | Deterministic tooling is better | Prometheus recording rules |
| Config Drift Detector | GitOps reconciliation already covers it | ArgoCD / Ansible |
| Customer-comms Author | Tone + accountability must remain human | Human-authored only |
