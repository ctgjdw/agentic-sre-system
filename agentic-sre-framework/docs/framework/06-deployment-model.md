# 06 — Deployment Model

> Audience: engineering. This document specifies how the framework runs in both
> deployment contexts.

## The portability claim

**Same conceptual model, two adapter sets.** The code that implements the
supervisor, the agents, the governance plane, the audit log, and the workflow
state machines does not change between deployments. Only the **adapters**
behind each capability port change — LLM gateway, observability, storage,
queue, comms, identity.

```
┌────────────────────────────────────────────────────────────────┐
│                         CORE (portable)                         │
│  Supervisor · Agent logic · Governance plane · Workflow         │
│  state machines · Audit log writer · Permission manifests       │
│  · Case lifecycle · HITL gate semantics · Budget enforcement    │
└────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
     ┌────────────┐   ┌────────────┐   ┌────────────┐
     │  ADAPTERS  │   │  ADAPTERS  │   │  ADAPTERS  │
     │  (on-prem) │   │   (AWS)    │   │  (future)  │
     └────────────┘   └────────────┘   └────────────┘
```

Swapping is a config change (Helm values), not a code change.

## 6.1 Adapter inventory

| Capability port | On-prem default | Online default (AWS) |
|---|---|---|
| LLM gateway — small tier | vLLM serving Qwen-7B / Llama-3-8B class | Claude Haiku via API, or Bedrock |
| LLM gateway — medium tier | vLLM serving Qwen-32B / DeepSeek-Coder-V2-Lite class | Claude Sonnet via API, or Bedrock |
| LLM gateway — frontier tier | vLLM serving DeepSeek-V3 / Qwen-Max / MiniMax-M2 | Claude Opus / GPT-5.5 via API, or Bedrock |
| Observability | Grafana LGTM (Loki / Tempo / Mimir / Alloy) — any OTel-compatible stack | CloudWatch + Managed Grafana, or self-hosted LGTM on EKS |
| Object storage (audit + evidence) | MinIO with WORM bucket | S3 with Object Lock + Glacier transition |
| Case / state store | PostgreSQL on OCP + Redis | RDS Postgres + ElastiCache |
| **Event bus** | **Kafka via Strimzi operator on OCP** | **Amazon MSK** |
| **Point-to-point queue** *(if needed)* | **RabbitMQ** | **Amazon MQ** |
| Secrets | HashiCorp Vault (self-hosted) | AWS Secrets Manager |
| Identity / SSO for HITL | Keycloak | Cognito or workforce SSO |
| Ticketing / SCM | **GitLab (same in both)** | **GitLab (same in both)** |
| **Config mgmt executor** | **Ansible only** (existing) | **Ansible** + AWS SSM Run Command for AWS-managed resources |
| Chat — primary | **Mattermost** | **Slack** |
| Chat — secondary | Mattermost only — **Telegram is not reachable on-prem** | Slack + Telegram (echo / notification only) |
| Code / arch context index | Self-hosted vector store (Qdrant / Weaviate / pgvector) over local repos + Bookstack / self-hosted Confluence | Same, optionally Bedrock Knowledge Bases |
| CVE / threat feed | Offline mirror updated via approved channel | Live feed |

The two **same in both** rows (GitLab, Ansible) are intentional: those are
existing tools in both environments. Agents call **into** them, never around
them.

## 6.2 On-prem reference shape

```
┌──────────────────── OpenShift Cluster ────────────────────┐
│                                                            │
│  ns: sre-framework-core                                    │
│   ├── supervisor (Deployment, replicas: 2)                 │
│   ├── case-api  (Deployment, replicas: 2)                  │
│   ├── audit-writer  (Deployment, replicas: 2)              │
│   ├── governance-dashboard (Deployment, replicas: 1)       │
│   ├── postgres + redis  (Operators)                        │
│   ├── kafka via Strimzi  (event bus)                       │
│   └── rabbitmq           (only if point-to-point queue     │
│                           required for ordered hand-offs)  │
│                                                            │
│  ns: sre-framework-agents                                  │
│   ├── duty-engineer-agent  (Deployment)                    │
│   ├── sre-investigator-agent  (Deployment)                 │
│   ├── principal-sre-agent  (Deployment)                    │
│   ├── remediation-engineer-agent  (Deployment)             │
│   ├── sysadmin-drafter-agent  (Deployment)                 │
│   ├── security-triage-agent  (Deployment)                  │
│   ├── compliance-evidence-agent  (CronJob + Deployment)    │
│   ├── postmortem-scribe-agent  (Deployment)                │
│   └── observability-engineer-agent  (Deployment)           │
│                                                            │
│  ns: sre-framework-llm                                     │
│   ├── vllm-small  (Deployment, GPU)                        │
│   ├── vllm-medium (Deployment, GPU)                        │
│   └── vllm-frontier (Deployment, GPU — tight scheduling)   │
│                                                            │
│  ns: sre-framework-obs       (Grafana LGTM if not present) │
│  ns: sre-framework-storage   (MinIO + Qdrant)              │
│                                                            │
│  Pulls from / talks to:                                    │
│   • GitLab (existing)                                      │
│   • Mattermost (existing)                                  │
│   • Vault (existing)                                       │
│   • Ansible Tower / GitLab CI (existing)                   │
└────────────────────────────────────────────────────────────┘
```

Everything deployed via Helm charts + ArgoCD, GitOps-style. Permission
manifests live in a dedicated GitLab repo and are applied by ArgoCD.

## 6.3 Online (AWS) reference shape

```
┌─────────────────────────── AWS Account ──────────────────────────┐
│                                                                   │
│  EKS cluster (same Helm charts as on-prem)                        │
│   • core, agents, obs namespaces identical                        │
│   • LLM namespace OPTIONAL (most deployments use external API)    │
│                                                                   │
│  Adapter swaps from on-prem:                                      │
│   • Anthropic API / Bedrock   (replaces vLLM namespace)           │
│   • S3 + Object Lock          (replaces MinIO)                    │
│   • RDS + ElastiCache         (replaces in-cluster PG/Redis)      │
│   • Amazon MSK                (replaces self-hosted Kafka)        │
│   • Amazon MQ                 (only if point-to-point queue       │
│                                  required)                        │
│   • Secrets Manager           (replaces Vault)                    │
│   • Cognito / SSO             (replaces Keycloak)                 │
│   • CloudWatch + Managed Grafana (or self-hosted LGTM on EKS)     │
│                                                                   │
│  Same external systems:                                           │
│   • GitLab, Ansible (+ SSM), Slack, Telegram (echo)               │
└───────────────────────────────────────────────────────────────────┘
```

Agent containers and supervisor code are identical to the on-prem deployment.
A single Helm values file selects which adapter implementation is wired to
each port.

## 6.4 Air-gapped considerations

Five operational items that trip up first-time on-prem deployments:

1. **Model weights distribution.** Open-weight model weights must enter the
   air-gapped network via an approved channel (sneakernet, internal artifact
   repo, signed bundle). Plan for ~50–500 GB per model and an update cadence
   (quarterly is realistic).
2. **CVE feed.** No live NVD pull. Mirror the CVE database into the network
   on a fixed cadence; the Security Triage Agent reads the mirror, not the
   internet.
3. **External docs / SDKs.** Architecture and code-context indexes must be
   built from internal sources only — no live Confluence Cloud, no GitHub.com.
   Use Bookstack / self-hosted Confluence / GitLab Wiki.
4. **Time and NTP.** Audit-log integrity depends on monotonic, accurate
   timestamps. Confirm NTP is available and signed inside the air-gapped zone.
5. **Egress.** Every agent's outbound network policy is `default-deny`;
   allow-lists are explicit. This blocks accidental telemetry, model
   "phone home", and prompt-injection-driven exfiltration.

## 6.5 Quality expectations — open-weight vs frontier

This is stated plainly so exec expectations stay calibrated:

| Tier | Online (frontier-grade) | On-prem (open-weight, quantised, GPU-bounded) | Implication |
|---|---|---|---|
| Small | Claude Haiku | Qwen-7B / Llama-3-8B | Close to parity for triage / dedup |
| Medium | Claude Sonnet | Qwen-32B / DS-Coder-V2-Lite | ~80–90 % of frontier quality for investigation drafts |
| Frontier | Claude Opus | DeepSeek-V3 / Qwen-Max / MiniMax-M2 | **Visibly weaker** for code reasoning + novel RCA. Higher human edit rate at Principal SRE / Remediation Engineer steps. |

**Mitigation:** keep the escalation policy conservative on-prem. Route a higher
fraction of cases directly to humans. The on-prem deployment delivers real
value at the small + medium tiers; frontier-tier value is partial and should
be treated as a supplement rather than a replacement.

## 6.6 GPU planning

The on-prem deployment is GPU-bounded. Plan for:

| Tier | Typical inflight | Memory footprint (quantised) | Notes |
|---|---|---|---|
| Small | 1–4 concurrent | ~10–20 GB VRAM | Single A100/L40S sufficient |
| Medium | 1–2 concurrent | ~40–80 GB VRAM | Single A100 80 GB or dual L40S |
| Frontier | 1 concurrent (queued) | 200–600 GB VRAM (quantised, multi-GPU) | Schedule tightly; budget caps prevent contention |

If GPU capacity is the binding constraint, freeze the frontier tier first.
The small + medium tiers cover ~85 % of the framework's value.
