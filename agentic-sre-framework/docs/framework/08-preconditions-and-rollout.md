# 08 — Preconditions & Rollout

> Audience: engineering leads + project managers.
>
> This document lists the operational preconditions the framework depends on,
> and the phased rollout plan that builds those preconditions while delivering
> early value.

## 8.1 Preconditions

These need to be true for the framework to function. Several are themselves
small projects.

| Precondition | What it means | Why the framework needs it |
|---|---|---|
| **Service catalogue exists** | Every service has a registry entry: owner, tier, runbook link, on-call route, comms channel | Agents need to know who owns what and where to route notifications |
| **GitLab labels are consistent** | Group-level scoped label dictionary, applied via issue templates | Drives intake routing, lifecycle state machine, and HITL gate signalling (see §8.2) |
| **On-call rotation is queryable via API** | The framework must know who is on call for what, right now | HITL gate routing and SLA escalation depend on it |
| **Existing Ansible playbooks are inventoried** | The SysAdmin Drafter Agent reuses them; can't reuse what isn't catalogued | Quality of draft playbooks depends on this corpus |
| **A permission-manifest repo exists** | One GitLab repo as the source of truth for all agent permissions | Drives the default-deny governance model |
| **Maintenance windows are declared in a queryable form** | Supervisor needs to know not to fire during them | Avoids false-positive cases during planned work |

## 8.2 GitLab labels — the minimum dictionary

The framework reads labels at five points: intake routing, domain narrowing,
severity, lifecycle, and HITL state. Without consistent labels, the supervisor
would have to run an LLM classifier on every inbound issue, which is real
on-prem compute cost.

Use **group-level scoped labels** in GitLab so they're inherited by every
project. The minimum dictionary:

```
kind::incident
kind::service-request
kind::cve
kind::postmortem
kind::obs-request

domain::db
domain::iam
domain::network
domain::k8s
domain::os
domain::app

severity::critical
severity::high
severity::medium
severity::low

state::triage
state::investigating
state::awaiting-approval
state::executing
state::closed

review::needs-approval
review::approved
review::rejected

ai::draft-pending       # agent attaches when output is fresh
ai::human-edited        # human modified draft before approving
```

24 labels in total. Issue templates (`.gitlab/issue_templates/*.md`) should
default-apply the right `kind::*` label so reporters don't have to.

The team may add more labels for internal reporting purposes; the framework
only depends on the ones above.

## 8.3 Phased rollout

Each phase is gated on the previous phase's exit criteria. Independent of
deployment environment, the same shape applies.

### Phase 0 — Foundations

**Goal:** preconditions met; orchestration plane up; no agents enabled.

- Stand up supervisor, case-api, audit-writer, governance-dashboard.
- Set up Kafka (Strimzi on-prem / MSK online), PostgreSQL, Redis, MinIO/S3.
- Define and apply the GitLab label dictionary (group-level).
- Publish issue templates with default `kind::*` labels.
- Build (or verify) the service catalogue and the on-call API.
- Inventory existing Ansible playbooks.
- Configure permission-manifest repo with default-deny baseline.

**Exit criteria:** governance dashboard live; supervisor accepts a synthetic
signal and writes to the audit log; no agents enabled yet.

### Phase 1 — Triage and Investigation (read-only)

**Goal:** the framework starts ingesting real signals and producing read-only
output.

Enable:

- Duty Engineer Agent (chat + alert intake → structured GitLab cases)
- SRE Investigator Agent (initial investigation reports on cases)

Stay read-only. No HITL gates fire because no state changes are proposed.

**Exit criteria:** ≥ 100 cases handled; agent-output edit rate trending down;
no signal lost; no permission breach; budget caps not tripped.

### Phase 2 — Drafting

**Goal:** introduce the first agents that produce drafts requiring HITL
approval.

Enable:

- SysAdmin Drafter Agent (free-text tickets → structured spec + draft
  playbook MR)
- Postmortem Scribe Agent (incident closure → draft postmortem)

HITL gates fire for the first time. The on-call SysAdmin and the incident
lead become the framework's first approvers.

**Exit criteria:** ≥ 50 SysAdmin tickets and ≥ 5 postmortems handled with
HITL approval; agent-vs-human edit rate documented; no out-of-scope tool
calls.

### Phase 3 — Security and Compliance

**Goal:** continuous security triage and evidence collection.

Enable:

- Security Triage Agent (CVE feed → exploitability + draft mitigation MR)
- Compliance Evidence Agent (cadence → continuous evidence packets)

These agents have low blast radius. The Compliance agent writes only to the
evidence store; the Security agent writes only to branches on the IaC repo.

**Exit criteria:** evidence store accumulating; risk register updated by
Security Triage; first compliance gap report reviewed by compliance lead.

### Phase 4 — Senior tier and the value loop

**Goal:** enable the most expensive agents and close the value loop.

Enable:

- Principal SRE Agent (escalation from Investigator on hard cases)
- Remediation Engineer Agent (bespoke fix MR drafting)
- Observability Engineer Agent (draft dashboards + alerts from postmortem
  action items)

Frontier-tier budget caps are tight. Escalation policy is conservative
initially (escalate sparingly).

**Exit criteria:** ≥ 10 frontier-tier escalations; first observability MR
merged; first "we caught this with the new alert" incident.

### Phase 5 — Trust calibration and tuning

**Goal:** the framework runs at steady state.

- Quarterly permission audit.
- Quarterly model bundle review (on-prem) / model version review (online).
- Quality regression replays against historical incidents.
- Consider enabling continuous trend-mining for the Observability Engineer
  (trigger b in [03-agent-roster.md](03-agent-roster.md)) once SRE team
  has trust in trigger (a) output.

## 8.4 What this rollout is NOT

- **Not Big Bang.** Each phase delivers value independently. If Phase 2
  doesn't pass exit criteria, Phase 3 doesn't start.
- **Not "ship and forget".** The Phase 5 disciplines (audit, regression,
  drift review) are ongoing, not one-time.
- **Not "agents replace anyone".** The headcount footprint is *augmentation*,
  not reduction. Roles shift from manual drafting toward review and exception
  handling.

## 8.5 Day-one ownership

| Component | Owner |
|---|---|
| Framework operation (supervisor, agents, governance dashboard) | SRE team |
| Permission manifests | SRE team, reviewed by Security |
| Audit log + evidence store | Compliance |
| Budget caps + cost reporting | SRE lead + Finance liaison |
| Model registry (on-prem weights) | SRE team + Security |
| Incident response on the framework itself | On-call SRE |

The framework is operated like any other internal platform. It has its own
on-call (the SRE team), its own runbooks, and its own postmortems. *Yes — it
has a Postmortem Scribe Agent that can draft its own postmortems.*
