# Agentic SRE & Platform Engineering System

An open-source, cloud-native platform for streamlining **Site Reliability Engineering (SRE)** and **Platform Engineering** with AI agents -- designed to run **fully offline in air-gapped environments** on **self-hosted open-weight (OSS) models** without sacrificing reliability or human governance.

## Core Design Principles

- **Air-Gap-First, Zero-Degradation Offline:** No frontier cloud LLM APIs, no SaaS control planes, and no internet egress required. Deterministic pre-flight diagnostics, grammar-constrained structured decoding (`vLLM`/`SGLang` + `XGrammar`), runbook/skill injection, hybrid BM25+vector retrieval, and `agentgateway` read-only MCP tool filtering keep OSS models accurate and ensure operators still receive actionable diagnostic packets even if GPUs are saturated or offline.
- **Human-in-Command:** Agents are strictly read-only and draft-only (RCAs, runbooks, patches, observability rules). Every publication or draft MR/PR passes through explicit human approval gates (`interrupt()` / `Command(resume=...)`).
- **Cloud-Native & Open Standards:** Built on LangGraph 1.x (library mode), FastAPI, PostgreSQL 16 + `pgvector`, `agentgateway` (LLM + MCP + A2A), `llm-d` + `vLLM`/`SGLang`, HolmesGPT, OpenTelemetry GenAI (`gen_ai.*`), self-hosted Langfuse, Grafana LGTM, Mattermost, and Kubernetes/OpenShift.

## Repository Structure

| Path | Description | Status |
|---|---|---|
| [`agentic-sre-team/docs/superpowers/specs/2026-11-27-airgap-platform-design.md`](agentic-sre-team/docs/superpowers/specs/2026-11-27-airgap-platform-design.md) | v2.0 System Architecture & Component Design Spec (OSS LLM harness, Tier-0 pre-flight, hybrid RRF, OTel `gen_ai.*`, OIDC, Mattermost, GitLab/GitHub SCM, validator) | **Approved Contract** |
| [`agentic-sre-team/docs/superpowers/specs/2026-11-27-docker-compose-stack-spec.md`](agentic-sre-team/docs/superpowers/specs/2026-11-27-docker-compose-stack-spec.md) | Local Laptop Docker Compose Stack, Service Configs (`agentgateway`, LiteLLM, Holmes 0.43, LGTM, Keycloak, Langfuse) & Reference SUT Spec | **Approved Contract** |
| [`agentic-sre-team/docs/superpowers/plans/2026-11-27-airgap-compose-implementation-plan.md`](agentic-sre-team/docs/superpowers/plans/2026-11-27-airgap-compose-implementation-plan.md) | Wave 0-6 Implementation Playbook & Kickoff Prompt for Agentic Orchestrators | **Ready to Execute** |
| [`docs/2026-11-research-and-architecture-review.md`](docs/2026-11-research-and-architecture-review.md) | Late-2026 OSS/CNCF research, full repo architecture review, target air-gap design, and prioritized P0-P4 roadmap | **Current Master Review** |
| [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) | Portable AI-brain & cross-IDE context for agentic sessions on any machine | **Current** |
| [`agentic-sre-team/`](agentic-sre-team/) | Primary runnable platform: FastAPI + LangGraph gateway, React 19 Ops Console UI, HolmesGPT sidecar, configs, tests | **Active** (Phases 0-6 complete; v2.0 Compose stack specs ready) |
| [`agentic-sre-framework/`](agentic-sre-framework/) | Full 9-agent SRE/SysAdmin framework blueprints (`docs/framework/`) and sibling multi-tenant LLMOps platform spec (`docs/llm-ops-spec/`) | Reference Blueprints |
| [`open-sre-agents/`](open-sre-agents/) | Earlier AWS-native OpenSRE MVP testbed (ECS/RDS/FIS/Lambda/Next.js) | Superseded / Legacy |

## Quickstart (Offline Fake Profile)

```bash
cd agentic-sre-team
make test        # Gateway pytest (119 tests) + UI vitest (10 tests)
make lint        # Ruff + ESLint/TypeScript
make smoke       # Full webhook -> gate1 -> approve -> gate2 -> closed E2E on fake profile
make e2e         # Playwright browser smoke against Ops Console UI (http://localhost:8088)
```
