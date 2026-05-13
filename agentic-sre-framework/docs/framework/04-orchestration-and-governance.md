# 04 — Orchestration & Governance Plane

> Audience: engineering. This is the layer that delivers every governance,
> trust, and cost-discipline guarantee promised in the overview.

## What sits in this plane

| Component | Purpose |
|---|---|
| Supervisor | Routing, lifecycle, audit, budgets, HITL gating |
| Intake adapters | Normalise inbound signals to one schema |
| Case store | Durable state for every case |
| HITL gate | Approval thread, signed approval, edit-with-diff |
| Permission manifest store | One YAML per agent, in git, applied by ArgoCD |
| Audit log writer | Append-only, WORM-backed |
| Budget enforcer | Per-case + per-agent caps |
| Noise control | Debounce, dedup, burst suppression, maintenance windows |
| Governance dashboard | Operator view of permissions, budgets, agent health |

## 4.1 Intake adapters

Every inbound signal becomes a uniform `Signal` envelope before routing:

```yaml
signal:
  id: sig-2026-05-13-0001
  source: mattermost | alertmanager | gitlab | cve-feed | cadence
  received_at: 2026-05-13T09:14:22Z
  reporter:
    type: human | system
    id: alex.goh@example.com | grafana-alertmanager
  channel: "ops-incidents"          # for chat sources
  payload: { ...raw... }
  metadata:
    correlation_ids: []
    quality_score: 0.0..1.0          # chat-intake only
```

Adapters in scope (v1):

| Adapter | Source | Notes |
|---|---|---|
| Chat intake | Mattermost (on-prem), Slack (online). **Telegram not used on-prem.** | Listens in pre-agreed channels + DMs to a bot user |
| Alert intake | Grafana Alertmanager (or any OTel-compatible alerting) | Structured |
| Ticket intake | GitLab Issues with `kind::*` labels | Structured |
| CVE / scan intake | CVE feed mirror, vulnerability scanner | Structured |
| Cadence intake | Cron / k8s CronJob | Compliance + audits |

## 4.2 Case lifecycle

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

States are tracked via the `state::*` GitLab labels listed in
[08-preconditions-and-rollout.md](08-preconditions-and-rollout.md).

## 4.3 HITL gate

| Property | Behaviour |
|---|---|
| **One thread per case** | The approval lives in Mattermost (on-prem) or Slack (online), pinned to the GitLab issue. |
| **What the human sees** | Rendered draft artefact, agent's confidence + reasoning summary, affected systems, proposed rollback. |
| **Buttons** | `Approve`, `Approve with edits`, `Reject`. |
| **Edit flow** | `Approve with edits` opens an inline diff editor. Original + edited versions are both stored. |
| **Identity verification** | The clicker's identity is checked against the on-call rotation at click time. |
| **Signature** | The approval is signed (cryptographically or via audited IdP) and bound to the case ID. |
| **Rotation change mid-case** | The approval is **not** auto-transferred. The supervisor pages the new on-call and the prior approval is invalidated. |
| **SLA** | Default 15 min for `severity::high` and above. After SLA: re-page next on-call. After 2× SLA: escalate to SRE lead. |

## 4.4 Permission manifests

One YAML per agent, in version control, applied by ArgoCD. Default-deny:
an agent cannot call a tool unless declared.

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
  - id: o11y.read
    scopes: ["env:prod", "env:stg"]
  - id: code.search
    scopes: ["repo:service-*"]
  - id: arch_docs.read
    scopes: ["bookstack://sre/*"]
  - id: prior_incidents.read
    scopes: ["all"]
# No write tools are declared. The agent cannot mutate any system.
```

Operator controls:

- **Live revocation.** A toggle in the governance dashboard sets a tool to
  `denied`. Takes effect within seconds. No redeploy.
- **Permission audit.** Quarterly review; every tool addition since the last
  audit is reviewed.
- **Manifest drift detection.** ArgoCD reconciles against the git source of
  truth. Out-of-band edits are blocked.

## 4.5 Audit log

| Property | Value |
|---|---|
| **Storage** | MinIO with WORM bucket (on-prem) / S3 with Object Lock (online) |
| **Granularity** | One append-only record per case |
| **Schema** | JSONL — one event per line |
| **Entries** | Signal payload, every agent invocation (model id, prompt hash, input context hash, output hash), every tool call (id, args, response hash, latency), every HITL decision (who, when, raw + edited diff), every state transition |
| **Retention** | Aligned to compliance scope (SOC2: ≥ 1 year for security events; 7 years for some controls) |
| **Verification** | Periodic offline hash-chain verification |

The audit log is the framework's defensible artefact. **No agent may write
directly to it.** Only the audit-writer service has the credentials, and it
exposes an append-only API.

## 4.6 Budget enforcement

Two layers:

| Layer | Cap | On breach |
|---|---|---|
| **Per case** | tokens, tool calls, wall-clock | Halt the agent, post a `budget exceeded` notice in the case thread, page on-call with the current state and the draft so far |
| **Per agent per day** | total tokens, total frontier-model invocations | Disable the agent for the rest of the day, alert the SRE lead |

Caps are environment-specific (prod caps tighter than staging). The frontier
tier (Principal SRE, Remediation Engineer) carries the tightest caps. The
escalation policy keeps frontier invocations to a small fraction of total cases.

## 4.7 Noise control

The supervisor enforces noise rules before invoking any specialist:

| Rule | Behaviour |
|---|---|
| **Identity dedup** | Same alert signature within rolling window → attach to existing case, not new case |
| **Burst suppression** | More than N similar signals in M seconds → collapse into one case with attached signal count |
| **Maintenance windows** | Declared via calendar; signals are recorded but specialists are not invoked |
| **Source quality scoring** | Chat-intake messages get a cheap incident-likelihood score before invoking the full Duty Engineer Agent; very-low-score messages get a canned response or none |

Every suppression event is itself logged. Operators see "how many signals did
we suppress today, and why" on the governance dashboard.

## 4.8 Governance dashboard

A single web view (also rendered as Grafana panels), showing:

- Each agent: current manifest, budget envelope, today's spend, current state
  (idle / running case X / disabled).
- Per-agent revoke toggles for individual tools.
- Per-environment global kill-switch (`pause all agents`) — invocable by SRE
  lead, audit-logged.
- Active cases and their current HITL gate state.
- Suppression counts and dedup hit rate.
- Audit-log hash-chain verification status.

The kill-switch is a non-negotiable safety control: if anything looks wrong,
one click stops all agents from doing further work. In-flight cases are paused
gracefully; queued signals stay queued until resume.

## 4.9 Supervisor reliability

- **Stateless.** All state lives in PostgreSQL + Kafka. The supervisor can be
  restarted at any time.
- **Replicated.** Two instances behind a load balancer. Active-active.
- **Backpressure-aware.** When Kafka lag rises, lowest-priority intakes pause
  first (cadence-driven compliance before incident-driven signals).
- **Failure modes** documented in
  [07-risks-limits-out-of-scope.md](07-risks-limits-out-of-scope.md).
