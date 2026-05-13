# 07 — Risks, Limits & Out-of-Scope

> Audience: management + engineering.
>
> The framework is only credible if its limits are stated as clearly as its
> capabilities. This document is the one that should let exec readers trust
> the proposal — *we know what this won't do, and we've thought about what
> could go wrong.*

## 7.1 Explicitly out of scope (v1)

| Out of scope | Why |
|---|---|
| Autonomous state changes | Locked at the autonomy ceiling: read-only + drafts always. Lifted only by a separate governance review, never by code. |
| Replacing CAB / change-manager authority | The on-call human is the change manager. The framework provides better drafts; it does not replace authority. |
| Replacing existing observability, ticketing, or config-mgmt tooling | The framework integrates with Grafana LGTM, GitLab, Ansible. It does not introduce competing systems. |
| Capacity forecasting agent | Prometheus recording rules + simple regression do this better and cheaper. No agent justified. |
| Drift detection agent | GitOps reconciliation already covers this deterministically. |
| Customer-facing communication | Agents speak only in operations-internal channels. Customer comms remain human-authored. |
| Cost / FinOps optimisation agent | Out of charter for SRE / SysAdmin in v1. |
| "Agent that replaces the on-call" | Not a goal at any timeline. Frame this explicitly in exec material. |
| Vendor-specific wrappers (Datadog Bits, Dynatrace Davis, Azure SRE Agent) | The framework stays open and adapter-driven. Wrap them later only on business case. |

## 7.2 Known risks & mitigations

| # | Risk | Likelihood | Mitigation built in |
|---|---|---|---|
| 1 | Hallucinated investigation misleads on-call | High | Confidence scoring; mandatory evidence excerpts; HITL review of every draft; "AI draft — verify" tag on every output for first 90 days |
| 2 | Prompt injection via chat / ticket / log content | Medium | Strict input sanitisation; agents have no write tools by default; tool calls go through a policy proxy that rejects out-of-scope targets; default-deny egress |
| 3 | Alert storm overwhelms agents → GPU starved | Medium | Debounce + dedup + burst suppression at supervisor; per-case budget caps; daily per-agent caps; queue with backpressure |
| 4 | Stale or compromised model weights on-prem | Medium | Signed model bundles via approved channel; weight hashes recorded; quarterly review of supported models; model upgrade is a change-managed event |
| 5 | Audit log tampering | Low | WORM storage; append-only writer with separate write credentials; periodic offline hash-chain verification |
| 6 | Permission creep (agents accumulating tools) | Medium | Permission manifests in git, reviewed via MR; quarterly permission audit; default-deny baseline |
| 7 | Engineers over-rely on agent output | Medium | "AI draft" tag persists; SRE leads track human-edit rate per agent; periodic "agent off" drills |
| 8 | Sensitive data leakage to external LLM (online deployment) | Medium | Pre-flight redaction filter on prompts (PII, credentials, customer data); contractual zero-retention with provider; on-prem-only for regulated workloads |
| 9 | Silent agent quality drift | High over time | Sampled human review of agent outputs (week 1: 100 %, ramp down); per-agent quality dashboard; regression tests against historical incidents (replay) |
| 10 | Supervisor as bottleneck / SPOF | Medium | Stateless supervisor, two replicas, state in PostgreSQL + Kafka; cases survive supervisor restart |

## 7.3 Failure modes & framework behaviour

| Failure | Framework behaviour |
|---|---|
| LLM gateway down (any tier) | Cases queue with a posted "LLM unavailable, human on-call required" message in the case thread. No silent failure. |
| Supervisor crashes | Replica takes over; in-flight cases resume from durable state. Worst case: short delay in routing; no lost signals. |
| HITL approver non-responsive past SLA | Re-page to next on-call in rotation; after 2× SLA, escalate to SRE lead. Default SLA = 15 min for `severity::high` and above. |
| Tool call fails (e.g., GitLab API down) | Agent reports failure, marks case `state::awaiting-tooling`, posts visible status; does not retry blindly. |
| Budget cap tripped mid-case | Agent halts, case is annotated, on-call paged with current state and the draft so far. |
| Frontier model returns malformed output | Validator rejects; supervisor falls back to medium-tier with the same context; if that also fails, hand to human. |
| Kafka backpressure | Supervisor pauses lowest-priority intakes first (cadence-driven compliance before incident-driven signals). |

## 7.4 Quality limits to state plainly

- **On-prem frontier-tier output is visibly weaker than online frontier
  output.** Plan for higher human edit rate in air-gapped deployments.
- **The Observability Engineer Agent will sometimes propose alerts that don't
  fire.** Mandatory query verification reduces this but does not eliminate it.
  SRE review of the MR is the safety net.
- **The framework cannot infer business impact.** Severity classification is
  driven by signal patterns + service tier metadata, not by knowing what each
  service actually does for revenue. Humans correct this at the HITL gate.
- **Code-level fixes from the Remediation Engineer Agent need code-review
  treatment.** They go through the same MR review as a human engineer's
  changes — no fast-path approval.
- **Agents do not learn from a single case.** Quality improvements come from
  manifest updates, prompt updates, model upgrades — not from in-conversation
  reinforcement. Setting this expectation matters.

## 7.5 The single most important safety control

The framework's load-bearing safety control is the **HITL approval gate**
described in [04-orchestration-and-governance.md](04-orchestration-and-governance.md).
Every state change passes through it. The gate cannot be bypassed by any
agent. The gate's identity verification, signature, and audit logging together
form the framework's compliance posture.

If the gate is intact, every other failure mode is recoverable. If the gate is
ever compromised, the framework must be paused via the kill-switch and
reviewed before resuming.
