# 05 — Workflow Mappings

> Audience: management + engineering.
>
> Each in-scope workflow is mapped from the current human flow to the
> agent-assisted flow. **Bold steps with ★ are HITL gates** — humans cannot be
> skipped at these points.

The framework supports five workflows in v1:

1. Incident response (chat- or alert-initiated)
2. SysAdmin service tickets (DB / IAM / network)
3. Patch & vulnerability management
4. Postmortem + observability authoring (the value loop)
5. Compliance evidence (cadence-driven)

---

## 5.1 Incident response

**Today.** Developer or user posts in Mattermost → duty engineer reads → asks
clarifying questions → checks dashboards and logs manually → forms a
hypothesis → escalates if stuck → mitigates → updates the channel.

**With the framework.**

```
   Signal (Mattermost msg | Alert | GitLab issue with kind::incident)
        │
        ▼
   Supervisor — intake, dedup, open case
        │
        ▼
   Duty Engineer Agent
     • Filters non-incident chatter
     • Asks 2–3 clarifying Qs in thread
     • Opens GitLab issue + links reporter
     • Posts initial triage summary
        │
        ▼
   SRE Investigator Agent
     • Pulls logs / metrics / traces / recent-change feed
     • Drafts initial investigation report
     • Self-reports confidence
        │
        ├─── confidence ≥ threshold AND runbook found ──┐
        │                                                │
        └─── escalate ─► Principal SRE Agent             │
                          • Reviews initial report      │
                          • Uses architecture + code    │
                          • Produces final RCA + plan   │
                                  │                     │
                                  ▼                     │
                          Remediation Engineer ◄────────┘
                            • Drafts fix MR
                            • Pre/post checks + rollback
                                  │
                                  ▼
                          ★ HITL GATE — on-call approves
                                  │
                                  ▼
                          Execute via Ansible / GitLab CI / kubectl
                                  │
                                  ▼
                          Case closed → Postmortem Scribe (if eligible)
```

**Where the cost is shaped.** Most cases stop at the medium-tier SRE
Investigator with a known runbook. The frontier-tier Principal SRE and
Remediation Engineer are invoked only when the escalation policy triggers
(low confidence, high severity, no runbook, novel signature, recent deploy
correlated, repeat-fire).

| Step | Agent | Avg cost tier |
|---|---|---|
| Triage | Duty Engineer | small |
| Investigation | SRE Investigator | medium |
| Senior review | Principal SRE (escalation only) | frontier |
| Fix authoring | Remediation Engineer (bespoke fix only) | frontier |

---

## 5.2 SysAdmin service tickets

**Today.** Requester writes a free-text GitLab issue → SysAdmin reads →
interprets → asks back and forth → manually composes the change → executes
against the target → records the result.

**With the framework.**

```
   New ticket on GitLab (label: kind::service-request, free-text body)
        │
        ▼
   Supervisor → SysAdmin Drafter Agent
        │
        ▼
   SysAdmin Drafter Agent
     • Parses request, identifies target system + domain
     • Asks structured clarifying Qs as ticket comments
       (target, scope, environment, window, rollback)
     • Looks up similar past tickets
     • Produces:
         (a) Structured change spec
         (b) Draft Ansible playbook / IAM diff / SQL
         (c) Risk note (blast radius, prerequisites)
         (d) Suggested approver
        │
        ▼
   ★ HITL GATE — on-call SysAdmin reviews draft
        │
   ┌────┼─────────────┬────────────────┐
   ▼    ▼             ▼                ▼
 Approve  Approve   Reject — annotate; agent revises
 as-is    w/ edits
   │        │
   ▼        ▼
 Execute via existing Ansible / GitLab CI pipeline
        │
        ▼
 SysAdmin Drafter writes verification step output
 back to ticket; closes ticket
```

**Value landed.**

| What gets eliminated | What gets added |
|---|---|
| Manual translation from prose to action | Structured spec drafted in minutes |
| Manual scripting from scratch | Reusable draft playbook |
| Forgotten edge cases | Explicit risk + rollback note |
| "Have we done this before?" hunt | Past-ticket match attached |

The agent never executes the playbook. The on-call SysAdmin clicks approve and
the existing CI pipeline runs.

---

## 5.3 Patch & vulnerability management

**Today.** Scanner produces CVE list → security or SRE engineer reads →
judges exploitability per CVE → opens ticket → writes patch playbook or
mitigation → schedules → executes.

**With the framework.**

```
   CVE feed update | Vulnerability scan results
        │
        ▼
   Supervisor → Security Triage Agent (medium model)
        │
        ▼
   Security Triage Agent
     • Pulls SBOM, asset inventory, exposure context
     • Assesses exploitability per CVE
       (public-facing? auth required? known PoC? reachable code path?)
     • Groups CVEs by remediation strategy
     • Produces per-group:
         - Affected asset list
         - Risk score with reasoning
         - Draft mitigation:
             * patch (Ansible playbook MR)
             * config change (IaC diff)
             * compensating control (network policy / WAF rule)
     • Escalates novel CVEs to frontier model
        │
        ▼
   ★ HITL GATE — security lead reviews + prioritises
     • Approve patch order → queue against change windows
     • Approve compensating controls → queue for execution
        │
        ▼
   Existing patching pipeline executes (Ansible + GitLab CI)
        │
        ▼
   Security Triage Agent verifies post-patch scan
   and updates the risk register
```

**Boundary.** The agent never decides patch priority autonomously. It produces
a ranked draft; the security lead sets the actual queue.

---

## 5.4 Postmortem + observability authoring — the value loop

This is the workflow that makes the framework's value **compound**. Every
incident closed produces a postmortem; every postmortem feeds the Observability
Engineer; every dashboard merged means the next similar incident gets caught
earlier with richer context.

**Today.** Incident closed → someone writes a postmortem days later → action
items logged → most monitoring AIs never get done because nobody has time.

**With the framework.**

```
   Incident case closed (state::closed)
        │
        ▼
   Postmortem Scribe Agent
     • Pulls timeline from case audit log
     • Pulls chat thread + ticket history + metric/log excerpts
     • Produces draft postmortem:
         - Timeline (machine-reconstructed)
         - Contributing factors (as hypotheses, not assertions)
         - Action items with proposed owners
         - "What we'd have wanted to see in monitoring" section
        │
        ▼
   ★ HITL GATE — incident lead reviews + finalises
     • Edit timeline, factors, ownership
     • Tag monitoring-related action items
        │
        ▼
   Approved monitoring action items → obs-eng-request events
        │
        ▼
   Observability Engineer Agent
     • Reads request + incident signal patterns
     • Drafts:
         - Grafana dashboard JSON
         - Mimir / Prometheus recording + alert rules
         - Alertmanager routing
         - Stub runbook linking back to this postmortem
     • EXECUTES proposed query against live O11y stack
       (attaches result or "no data" warning to the MR)
     • Opens MR to the obs-as-code repo
        │
        ▼
   ★ HITL GATE — SRE reviews + merges MR
        │
        ▼
   New alert / dashboard live
        │
        ▼
   Next time, the issue is caught by the alert,
   arrives at the Duty Engineer Agent with structure,
   and Investigation starts from a richer baseline
```

**The exec one-liner.** The framework converts every incident into a permanent
monitoring improvement, without engineers having to find the time.

---

## 5.5 Compliance evidence (cadence-driven)

**Today.** Audit approaching → SRE / compliance scrambles to collect evidence
→ manual screenshots, config dumps, attestations → reactive.

**With the framework.**

```
   Cadence trigger (daily | weekly | per-control-event)
        │
        ▼
   Compliance Evidence Agent (small model, runs cheap)
     • Per control: collect prescribed evidence
       (config exports, screenshots-of-record, log excerpts)
     • Hash + sign artefacts
     • Map to control IDs (SOC2 / ISO27001 / internal)
     • Detect gaps: control with no evidence in window
        │
        ▼
   Evidence packets → WORM evidence store
        │
        ▼
   Gap report → compliance channel
   (gaps tagged "monitoring-missing" → routed to Obs Engineer)
        │
        ▼
   ★ HITL GATE — only when gap closure needs human action
```

No state changes here in v1 — purely read + write to the evidence store.
This is the framework's lowest-risk agent.

---

## 5.6 How the workflows chain

The agents form an organism that learns:

| Trigger | Chains into | Result |
|---|---|---|
| Incident closed | Postmortem Scribe → Observability Engineer | Monitoring improvement merged |
| Service ticket reveals misconfiguration class | Security Triage Agent | Risk surfaced + draft mitigation |
| Compliance gap = missing monitoring | Observability Engineer | New evidence-yielding dashboard |
| Recurring case signature detected | Observability Engineer (proactive) | Trend-based dashboard proposed (v2 — disabled in v1) |

These chains are what turn the framework from a *set of agents* into a *system
that compounds returns over time*.
