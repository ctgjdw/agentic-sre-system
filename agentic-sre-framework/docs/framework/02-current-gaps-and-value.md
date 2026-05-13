# 02 — Current SRE Gaps & How the Framework Closes Them

> Audience: management + engineering leads.
>
> This document is the framework's **value pitch**. Every agent in the roster
> exists because there is a current, concrete pain in our SRE operations.

## The seven gaps

| # | Gap (today) | Why it hurts | Agent(s) that close it | Visible win |
|---|---|---|---|---|
| 1 | **Most issues are surfaced via ad-hoc Mattermost messages, not automated alerts.** | Engineers must read every channel; reporters get inconsistent triage; cases are inconsistently logged. | Duty Engineer Agent (chat intake) | Every chat report becomes a structured GitLab case with initial triage, within minutes. |
| 2 | **Few fine-tuned dashboards & alerts exist for our most impactful signals.** | The SRE team can't see what matters before users complain. Postmortems repeatedly conclude "we should have had a dashboard for that." | Observability Engineer Agent | Each postmortem and recurring case auto-produces a draft Grafana dashboard + alert MR. Monitoring compounds over time. |
| 3 | **Service tickets arrive as free-text and are interpreted manually.** | High SysAdmin toil; risk of misinterpretation; no consistent change spec or rollback plan. | SysAdmin Drafter Agent | Each ticket comes back with a structured change spec + draft playbook in minutes. |
| 4 | **Investigation depth varies by who's on call.** | Junior engineers re-derive what seniors already know; MTTR is uneven. | SRE Investigator + Principal SRE | Every case gets a consistent L2 pass; complex ones get a "senior reviewer" pass with architecture/code context. |
| 5 | **Postmortem action items often don't translate into actual improvements.** | The learning loop leaks; the same incident recurs. | Postmortem Scribe + Observability Engineer | Monitoring-related action items are auto-drafted into MRs the SRE team can review and merge. |
| 6 | **CVE triage and patch authoring is manual.** | Security debt accumulates; exploitability is judged ad-hoc. | Security Triage Agent | Each scanned CVE gets an exploitability assessment + draft mitigation MR. |
| 7 | **Compliance evidence is gathered reactively before audits.** | Audit prep is a scramble; controls may drift between cycles. | Compliance Evidence Agent | Continuous evidence packets mapped to controls; gaps surface early. |

## How the value compounds

The agents are not independent point solutions — they form a loop that gets
better over time:

```
   Incident reported (chat or alert)
        │
        ▼
   Duty Engineer Agent structures the case
        │
        ▼
   SRE Investigator → (escalate?) → Principal SRE → Remediation Engineer
        │
        ▼
   Human approves and executes mitigation
        │
        ▼
   Postmortem Scribe drafts the review
        │
        ▼
   Observability Engineer drafts new dashboards + alerts
        │
        ▼
   Next time, the issue arrives as an *automated* signal, earlier,
   with richer context.
```

The exec one-liner: **the framework turns every incident into a permanent
improvement in monitoring and process — without engineers having to find the
time to do that work.**

## What does not justify an agent

Some SRE workloads are deliberately left to deterministic tooling. They are
listed here so the framework's scope is unambiguous:

| Workload | Why no agent | What handles it |
|---|---|---|
| Capacity forecasting | Recording rules and simple regression are cheaper and more reliable | Prometheus / Mimir |
| Config drift detection | GitOps reconciliation already covers this | ArgoCD / Ansible |
| Backup verification | Scheduled checks suffice | Existing scripts |
| TLS / cert rotation | Existing automation handles this | cert-manager / Vault PKI |

This list will grow over time. The framework's principle, from our CLAUDE.md,
is **prefer the simplest tool for the job**. Where a deterministic answer
exists, an agent does not earn its compute spend.

## Cost / benefit framing for the exec audience

The framework's costs come in three forms:

| Cost | Magnitude | Mitigation |
|---|---|---|
| LLM inference (on-prem GPU + online API) | Significant if uncapped | Per-case + per-agent budget caps; tiered model selection (small/medium/frontier); escalation policy |
| Engineering time to operate the framework | A small fraction of an SRE FTE | Once stable; week-1 setup is heavier |
| Risk of acting on a wrong draft | Low | HITL approval gate on every state change |

The benefits come back as **time returned to the team** — fewer manual triages,
fewer hand-written tickets, faster RCAs, more monitoring built, less audit
scramble. The first-quarter benchmarks are listed in
[01-framework-overview.md](01-framework-overview.md).
