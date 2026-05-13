# Agentic SRE Framework — Documentation Index

A framework for using a team of AI agents to support and automate the SRE and
SysAdmin workflow in our organisation.

## Audience

These documents serve two readers:

- **Management-level execs (primary).** Start with `01-framework-overview.md`
  and `02-current-gaps-and-value.md`. Those two cover the entire value pitch
  without engineering detail.
- **Engineers (secondary).** Documents 03 through 08 contain the architecture,
  governance plane, deployment shape, and rollout plan needed to implement.

## Reading order

| # | Document | Audience | Read time |
|---|---|---|---|
| 1 | [Framework Overview](01-framework-overview.md) | Exec + Eng | 5 min |
| 2 | [Current Gaps & Value](02-current-gaps-and-value.md) | Exec + Eng | 5 min |
| 3 | [Agent Roster](03-agent-roster.md) | Eng | 10 min |
| 4 | [Orchestration & Governance](04-orchestration-and-governance.md) | Eng | 10 min |
| 5 | [Workflow Mappings](05-workflow-mappings.md) | Exec + Eng | 10 min |
| 6 | [Deployment Model](06-deployment-model.md) | Eng | 10 min |
| 7 | [Risks, Limits & Out-of-Scope](07-risks-limits-out-of-scope.md) | Exec + Eng | 5 min |
| 8 | [Preconditions & Rollout](08-preconditions-and-rollout.md) | Eng + PM | 5 min |

## One-line summary

A supervisor agent and seven role-specialist agents that mirror our SRE/SysAdmin
org chart. Agents draft investigations, runbooks, change specs, postmortems,
dashboards, alerts, and compliance evidence. **Humans approve every state
change.** The same conceptual model runs on-prem (OpenShift, open-weight LLMs)
and online (AWS, frontier LLMs) — only the adapters swap.
