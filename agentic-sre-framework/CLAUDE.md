# Agentic SRE Workflow

> **Updated Context (2026-11-26):** See root [`AGENTS.md`](../AGENTS.md) and [`docs/2026-11-research-and-architecture-review.md`](../docs/2026-11-research-and-architecture-review.md) for the current monorepo context and updated **Air-Gap-First, Self-Hosted OSS-Models-Only (Zero-Degradation)** constraint. Earlier assumptions below accepting degraded on-prem quality or prioritizing AWS/frontier cloud models are superseded.

This directory contains research and proposed plans for a framework that uses a team of agents to support and automate **Site Reliability Engineering (SRE)** and **Sys Admin** operations.

## Audience & Output Format

Plans and deliverables in this repo serve two readers:

- **Management-level execs (primary).** Non-technical or lightly technical. Lead with **value, risk, and cost** — not architecture. Avoid jargon; define terms on first use when unavoidable. Explain agents and processes at the level you would in a steering committee.
- **Engineers (secondary).** Implementers of the framework. Place concrete architecture, agent boundaries, and integration details into a technical appendix or sub-section so the plan is actionable.

When in doubt, write the body for execs and push implementation detail into appendices.

## Stack

- **LLM models** — Online: frontier models (Claude Opus, GPT-5.5). On-premise: locally deployed open-weight models (MiniMax, Qwen, DeepSeek).
- **Observability** — Online: AWS-native. On-premise: Grafana LGTM stack, or any OpenTelemetry-compatible stack.
- **Deployment infrastructure** — Online: AWS managed services. On-premise: OpenShift Container Platform.
- **Communication / Ticketing** — Online: Slack, Telegram, GitLab Issues. On-premise: Mattermost, GitLab Issues.

## Architectural Principles

- The framework **must support both online and air-gapped on-premise deployments** under the same conceptual model.
- The framework **must be cloud-native and versatile** — applicable to any modern system architecture, not tied to a single vendor.
- **Prefer the simplest tool for the job.** Agentic automation is not always the right answer. Where deterministic tooling fits better — RPA, configuration management (Ansible, Salt, etc.), or scripted runbooks — call it out explicitly and recommend that path instead of an agent.

## Cost & Resource Discipline

- **GPU and inference resources may be limited in on-premises.** Weigh the impact and value of each agent before introducing it; justify why an agent is the right tool over deterministic alternatives. Also, highlight that using open-weighted models on-premise with limited compute, might degrade the effectiveness/reliability of this framework.
- **SRE signals are noisy** — false positives and alert storms are normal. The framework must debounce, deduplicate, or aggregate signals before invoking an agent so orchestration cost stays proportional to value delivered.

## Human Control & Governance

- **Human approval gates are mandatory for state-changing actions.** Agents may draft scripts, runbooks, or remediation plans, but execution against real systems requires explicit human review and approval.
- **Agent permissions must be visible and governable.** The framework must let a human operator see which system permissions each agent holds and adjust or revoke them. Default to least privilege.
