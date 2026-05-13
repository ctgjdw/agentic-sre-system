# 01 — Framework Overview

> Audience: management + engineering leads. This is the document to bring into
> a steering committee.

## What this is

A framework — not a product — for assembling a small team of AI agents that
**support and automate** parts of the SRE and SysAdmin workload, while keeping
humans in command of every state-changing action.

The framework gives us:

- **A consistent way to ingest signals** — automated alerts, free-form chat
  messages, service tickets, CVE reports, scheduled audit events — through a
  single orchestrator.
- **Role-specialist agents** that mirror our existing job titles, each drafting
  the artefacts a human would otherwise produce by hand: triage notes,
  investigation reports, change specs, runbooks, postmortems, dashboards,
  alerts, compliance evidence.
- **A governance plane** that controls what each agent can see and do, caps the
  compute spend, and writes an append-only audit log for every case.
- **The same conceptual model in both deployment contexts** — on-prem
  (OpenShift, open-weight LLMs) and online (AWS, frontier LLMs).

## What we are NOT building

- Agents that change production systems on their own.
- A replacement for the on-call human, the service owner, or the change manager.
- A replacement for Grafana, GitLab, Ansible, or any existing tooling.

These are deliberate non-goals, documented in
[07-risks-limits-out-of-scope.md](07-risks-limits-out-of-scope.md).

## The six framework pillars

1. **Human-in-command, always.** Agents investigate, draft, and propose. Every
   state-changing action is executed by a human (or by a human clicking
   "approve" on a pre-authored playbook). No exceptions in v1.
2. **Role-mapped specialists.** Agent roles mirror our existing job titles —
   Duty Engineer, SRE Investigator, Principal SRE, Remediation Engineer,
   SysAdmin, Security, Compliance, Postmortem Scribe, Observability Engineer.
3. **One orchestrator, one audit trail.** A single supervisor routes work to
   specialists, owns the human-in-the-loop gates, and emits one append-only
   audit log per case. No agent sprawl.
4. **Deterministic tooling first.** Where Ansible or GitLab CI or a scripted
   runbook already does the job, the agent **calls** it — never re-implements
   it. Agents add value at the *interpret, draft, correlate* layer.
5. **Noise-aware ingestion.** Alerts and tickets are debounced, deduplicated,
   and grouped before invoking an agent. Compute cost stays proportional to
   value delivered.
6. **Portable conceptual model.** The same agent roster and governance plane
   runs on-prem and online. Only the adapters swap — observability, LLM
   gateway, secrets, queue, comms.

## Architecture at a glance

```
       Humans (Mattermost / Slack / GitLab Issues)
                          │
                          ▼
   ┌─────────────────────────────────────────────────┐
   │      Orchestration & Governance Plane           │
   │   ─ Supervisor                                  │
   │   ─ HITL approval gates                         │
   │   ─ Permission manifests (default-deny)         │
   │   ─ Budget caps + audit log                     │
   │   ─ Debounce / dedup / noise control            │
   └─────────────────────────────────────────────────┘
                          │
   ┌──────────┬──────┴──────┬──────────┬──────────┬──────────┐
   ▼          ▼             ▼          ▼          ▼          ▼
  Duty        SRE         Principal  SysAdmin   Security   Compliance
  Engineer    Investigator   SRE     Drafter    Triage     Evidence
                              │
                              ▼
                       Remediation
                       Engineer       Postmortem    Observability
                                      Scribe        Engineer
                          │
                          ▼
            Existing tooling (Ansible, GitLab CI, kubectl,
            Grafana LGTM, Vault, MinIO/S3, Kafka)
```

- **Top:** the orchestration and governance plane that this framework places
  above everything.
- **Middle:** the seven specialist agents (plus the supervisor) that map to
  human roles.
- **Bottom:** existing tools the agents call into. The framework does not
  replace these.

## Where this fits in the org

The framework is operated by the SRE team. It augments — does not replace —
existing roles:

| Existing role | What stays human | What the framework drafts for them |
|---|---|---|
| Duty engineer (L1) | Final paging decisions, customer comms | Triage summaries, dedup decisions, intake structuring |
| SRE / Service owner | Mitigation decisions, code reviews | Investigation reports, RCA drafts, fix MRs |
| SysAdmin | Change execution, approval | Change specs, draft Ansible playbooks |
| Security engineer | Patch prioritisation | Exploitability assessments, mitigation MRs |
| Compliance officer | Audit attestation | Continuous evidence collection |
| Postmortem facilitator | Final report sign-off | Draft timeline + factors + action items |

## What success looks like in the first quarter

- Every Mattermost incident report becomes a structured GitLab case within
  minutes, not "after a human gets to it."
- Every service ticket arrives at the SysAdmin with a draft playbook attached.
- Every postmortem produces at least one merged monitoring improvement.
- Every CVE in scope gets an exploitability assessment within the agreed SLA.
- Compliance evidence is collected continuously rather than during an audit
  scramble.
- Zero unauthorised state changes — the human-approval gate holds.

Numbers and SLAs are set per phase in
[08-preconditions-and-rollout.md](08-preconditions-and-rollout.md).
