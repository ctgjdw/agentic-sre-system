# AGENTS.md - Project Context & AI Brain

> **Portable AI Context:** This file is the canonical project brain for **any** agentic IDE or CLI (Antigravity, Claude Code, Cursor, Codex, Windsurf, Gemini CLI, OpenCode) on **any** machine. Keep all durable project context, decisions, constraints, and status inside this git repository -- never rely on laptop-local paths (such as `~/.claude/` or `~/Code/agentic-ons/.superpowers/`).

---

## 1. Mission & Non-Negotiable Constraints

**Goal:** Build an open-source, cloud-native **Agentic SRE & Platform Engineering** platform that streamlines incident triage, root-cause analysis (RCA), CI/CD pipeline failure diagnostics, remediation drafting, and platform operations with AI agents.

### Hard Constraints (Updated 2026-11-26 -- Supersedes Older Cloud-First Assumptions)

1. **Air-Gap-First, Offline-Native Operation:** The platform MUST run completely offline in an air-gapped environment with zero external internet egress (no Vertex AI, AWS Bedrock, Anthropic/OpenAI cloud APIs, Grafana Cloud, LangSmith Cloud, Telegram Bot API, or public PyPI/npm/container registries at runtime).
2. **OSS Self-Hosted Models Only (Zero Degradation):** Assume **no access to frontier cloud LLMs**. All agentic reasoning runs on permissive-license open-weight models deployed on internal GPU infrastructure (`llm-d` + `vLLM`/`SGLang`). Crucially, the system must operate **without degradation that renders automation unusable** -- achieved through architectural scaffolding rather than frontier model size:
   - Tier-0 deterministic pre-flight evidence collection & Diagnostic Packet fallback (useful even when GPUs are saturated or offline),
   - Native grammar-constrained structured decoding (`XGrammar`/`LLGuidance` `json_schema`) + `<think>` block handling,
   - Runbook / Skill injection + `agentgateway` CEL-scoped read-only MCP tool lists (4-8 tools per worker, never 50 unfiltered tools),
   - Hybrid retrieval (`pgvector` + Postgres `tsvector` BM25 + RRF) + salient head/tail evidence extraction (never blind `[:300]` truncation),
   - Deterministic remediation/query validation (`promtool`, `yamllint`, `kubectl --dry-run=client`, `ansible-lint`, `git apply --check`) before human review.
3. **Human-in-Command (Read-Only Agents Always):** Agents investigate, correlate, verify citations, and draft artifacts (RCAs, runbooks, patches, alerts). They **never** execute state-changing actions against production. Every publication or draft MR/PR requires explicit Human-in-the-Loop (HITL) approval (`interrupt()` / `Command(resume=...)`). Default-deny permission manifests in git.
4. **Deterministic Tooling First:** Use deterministic code for routing, dedup/grouping, golden-signal pre-collection, budget/pause guards, citation existence checks, and syntax/dry-run validation. Invoke LLMs only where interpretation, synthesis, or drafting adds value.
5. **Latest OSS & Cloud-Native Standards:** Align with CNCF/Linux Foundation agentic primitives: **LangGraph 1.x** (library mode in FastAPI), **agentgateway** (unified Rust gateway for LLM + MCP + A2A), **llm-d + vLLM/SGLang**, **HolmesGPT 0.43.x+** (behind thin adapter seam), **OpenTelemetry GenAI (`gen_ai.*`)**, **self-hosted Langfuse (MIT + ClickHouse)**, **Mattermost + Keycloak OIDC**, **Grafana LGTM**, **Kubernetes/OpenShift (Helm + ArgoCD)**, and **MCP / A2A** protocols.

---

## 2. Monorepo Map

| Directory | Role | Current Status |
|---|---|---|
| `docs/` | Cross-repo architecture reviews, research, and modernization roadmaps | **Active** -- see `docs/2026-11-research-and-architecture-review.md` |
| `agentic-sre-team/` | **Primary runnable system**: FastAPI + LangGraph 1.x gateway (`gateway/`), React 19 + Vite 7 Ops Console (`ui/`), configs (`config/`), Docker Compose, tests | **Active** -- Phases 0-6 complete (119 gateway tests + 10 UI tests + Playwright E2E green). Pivoting to Air-Gap-First / OSS-Parity (Priority 0) before/alongside Phases 7-9 |
| `agentic-sre-framework/` | Architectural blueprints for the full 9-agent SRE/SysAdmin roster (`docs/framework/01..08`) and sibling multi-tenant LLMOps platform (`docs/llm-ops-spec/`) | **Reference Docs** -- older May-Jun 2026 cloud-first assumptions are superseded by `docs/2026-11-research-and-architecture-review.md` |
| `open-sre-agents/` | Legacy AWS Free Tier MVP (ECS/RDS/FIS/Lambda/Next.js + OpenSRE/Claude) | **Archived / Superseded** by `agentic-sre-team/` |

---

## 3. Current Technical State (as of 2026-11-26)

### What Is Built & Verified (`agentic-sre-team/`)
- **Phases 0-6 merged on `main`** (last code commit `222e674`, last doc commit `a3211a4`):
  - Postgres 16 + `pgvector` schema & Alembic migrations (`0001`..`0005`), append-only `audit_events` trigger, `AsyncPostgresSaver` LangGraph checkpoints.
  - Intake normalization (`Signal`), noise control (fingerprint dedup, debounce, burst suppression), declarative cross-signature correlation grouping (`config/grouping.yaml`), Grafana webhook + poller.
  - Full incident `StateGraph`: `triage -> plan -> parallel Send workers (metrics/logs/infra/changes/ci) -> synthesize (max 2 rounds) -> rca -> verify_citations (1 repair loop) -> gate_rca -> remediate -> gate_runbook -> publish (+ case learnings) | park`.
  - HolmesGPT sidecar HTTP/SSE client (`holmes/client.py`, currently pinned to `0.36.0`), Grafana Explore deep links, fake Holmes + scripted model offline test harness.
  - React 19 Ops Console UI (`ui/`): Case Queue + Activity Timeline, 3-pane Case Detail + Live Ledger + Hypothesis Board + Evidence Receipts, Artifact Review + Citation Inspector + Approvals, Governance Screen.
  - Telegram companion channel (`channels/telegram.py`, DM-only intake + inline gate approvals; online dev only -- not usable in air-gap).

### Locked Architecture Decisions (Confirmed 2026-11-26 -- Do Not Reopen Without Asking)

1. **Dual Offline GPU Profiles (Zero Cloud LLM Calls):**
   - **`local-gpu` (Dev & Testing First):** Operator's local laptop with **NVIDIA Quadro RTX 3000 (54GB total GPU memory)** running Ollama / llama.cpp / vLLM with quantized small/mid OSS models (`Qwen3.5-9B`, `Qwen3.6-35B-A3B`, `Qwen3.6-27B`) + lightweight local embeddings (`Qwen3-Embedding-0.6B` / `nomic-embed-text`).
   - **`airgap` (Production Target):** Air-gapped **multi-GPU cluster** running `llm-d` + `vLLM` hosting Small + Medium + Heavy reasoning tiers (`Qwen3.6-35B-A3B`, `Qwen3.6/3.8-27B`, `DeepSeek-V4` / `GLM-5.2` + `Qwen3-Embedding` / `BGE-M3`). Same code; config-only swap (`config/models.local-gpu.yaml` vs `config/models.airgap.yaml`).
2. **Runtime & Packaging Sequence:** Build the **local Docker Compose "air-gap-in-a-box"** first (self-hosted Grafana LGTM + Ollama/vLLM + gateway + Spectre/demo SUT, zero cloud), then **Kubernetes / OpenShift Helm charts** for the production multi-GPU cluster.
3. **Evidence Engine:** **Keep HolmesGPT** (upgrade `0.36.0` -> `0.43.x+`) behind the thin `HolmesClient` seam + `agentgateway` CEL read-only MCP tool filtering, **AND** add a **Tier-0 Deterministic Pre-Flight Collector** ahead of it (instant golden-signal collection + LLM-offline Deterministic Diagnostic Packet fallback).
4. **Interchangeable LLM Gateway + Offline Observability:**
   - **LLM Gateway MUST be interchangeable via config (`SRE_LLM_GATEWAY_URL`):** Production air-gap currently runs **LiteLLM**, and the operator also wants to evaluate **`agentgateway` (Rust, LF/CNCF)**. Both gateway and HolmesGPT talk standard OpenAI-compatible HTTP so swapping between LiteLLM, `agentgateway`, and direct local Ollama/vLLM requires zero code changes; `agentgateway` also fronts MCP servers for CEL read-only tool filtering and future A2A.
   - **Observability:** Emit **OpenTelemetry GenAI (`gen_ai.*`)** everywhere. Default local laptop export to **Grafana Tempo** (light RAM footprint); put **self-hosted Langfuse (MIT + ClickHouse)** behind an optional local Compose profile (`--profile langfuse`) and always-on in cluster Helm charts.
5. **Air-Gap Human Surfaces, Auth & SCM:** **Ops Console Web UI** with **toggleable Keycloak OIDC SSO** (`SRE_AUTH_ENABLED`: `false` locally, `true` in air-gap) + **`MattermostChannel`** as primary air-gap chat/approvals (keeping `TelegramChannel` opt-in for online dev) + **self-hosted GitLab** as primary SCM (with GitHub also supported behind `ScmProvider`).
6. **Legacy MVP:** `open-sre-agents/` stays in place with an archive notice in its `README.md`.

### Known Bugs & Priority Backlog (Tracked in Git -- See `docs/2026-11-research-and-architecture-review.md`)
- **P0 (Air-Gap & OSS Parity -- Immediate Next Milestone on RTX 3000 Laptop):**
  1. Fix `settings.py:models_config_path` to resolve `models.{profile}.yaml`; create `config/models.local-gpu.yaml` and `config/models.airgap.yaml` (interchangeable `SRE_LLM_GATEWAY_URL` for LiteLLM / `agentgateway` / Ollama / vLLM); make USD pricing optional, add token/GPU-second budgets, make `OpenAIEmbeddings.dimensions` optional.
  2. Replace prompt-only JSON + `find("{")`..`rfind("}")` in `llm/json_call.py` with native vLLM/SGLang/Ollama `json_schema` constrained decoding + `<think>` block stripping + 4xx/context-overflow error classification (`TODO(Task 25)`).
  3. Add Tier-0 deterministic `preflight` collector + LLM-offline **Deterministic Diagnostic Packet** fallback.
  4. Upgrade `retrieval.py` to Postgres hybrid search (`pgvector` + `tsvector` BM25 + RRF + score cutoff + BM25-only fallback), fix `[:300]`/`[:200]` head truncation across `synthesize.py`/`rca.py`/`verify.py`/`remediate.py`, and inject matched runbooks/skills into workers.
  5. Fix live bugs: wire dead-code `budget.check_agent()` into `graph/deps.py:guarded()`, fix `gates.py` resume crash-window, stamp `waiting_since` on error-park in `runner.py`, add `HolmesClient.aclose()`, fix UI SSE token-frame `lastEventId` & multi-round `Ledger.fold` minors.
- **P1 (Air-Gap Stack):** Interchangeable LiteLLM / `agentgateway` Compose profiles + `agentgateway` CEL read-only MCP tool filtering (closing Grafana MCP write-surface risk) + self-hosted local Grafana LGTM, OTel `gen_ai.*` (Tempo default locally, optional Langfuse locally / always-on cluster) + HolmesGPT `0.43.x+`, `MattermostChannel` + toggleable Keycloak OIDC UI auth, offline Docker/Helm air-gap bundle.
- **P2 (Unbuilt v1 Slices + Validation):** Phase 7 (self-hosted GitLab primary + GitHub pipeline failures + filtered SCM MCP), deterministic remediation validator node, Phase 8 (Console Chat), audit SHA-256 hash-chaining + MinIO WORM.
- **P3-P4 (Scale & Platform Engineering):** Offline SRE fault-injection benchmark suite, multi-replica HA `CaseRunner`, Backstage/OpenChoreo Catalog MCP, remaining specialist agents (Postmortem Scribe, Observability Engineer, SysAdmin Drafter, Security Triage, Compliance Evidence) via A2A / `kagent`.

---

## 4. Development & Verification Commands

Run from `agentic-sre-team/`:

```bash
# Gateway tests & lint (requires local Docker for pgvector testcontainers)
cd agentic-sre-team/gateway && uv run pytest -q && uv run ruff check .

# UI tests & lint
cd agentic-sre-team/ui && npm test && npm run lint

# Full repo checks via Makefile
cd agentic-sre-team && make test && make lint

# Offline fake-profile end-to-end smoke & Playwright E2E (no external network/creds needed)
cd agentic-sre-team && make smoke
cd agentic-sre-team && make e2e
```

---

## 5. Working Conventions & Preferences

- **Research & Docs-Check First:** Always verify external SDKs, APIs, MCP servers, and container images against current docs or live probes before writing code against them. Cite sources.
- **Approval Gates:** Check in with the user at major architecture or phase boundaries before large implementations.
- **Quality Over Speed:** Fix real issues now rather than deferring; pristine test output (zero warnings, zero lint errors) is a merge gate.
- **Deterministic Offline Tests:** Never break `make smoke` or `make e2e` offline determinism. Any live external integration must be explicitly feature-flagged (default `false`).
- **Secrets Hygiene:** Never commit `.env`, API tokens, or credentials. Keep `.env.example` clean and documented.
- **Git & Style Conventions:**
  - Conventional commits: `<type>(<scope>): <summary>` (scopes: `sre-team` for code, `agentic-sre-team` or `docs` for docs, `airgap` for infra/packaging).
  - Never add agent `Co-Authored-By` trailers.
  - Use plain ASCII dashes (`-` or `--`), avoid Unicode em dashes, in authored docs and commits.
  - Update this `AGENTS.md` (Section 3 & backlog status) whenever a phase/milestone completes or an architectural decision changes, so the next session on any machine starts with accurate context.

---

## 6. Next-Session Kickoff Protocol (RTX 3000 Laptop)

1. Read this file (`AGENTS.md`) and `docs/2026-11-research-and-architecture-review.md` (Parts 3-5).
2. Verify baseline tests pass locally (`cd agentic-sre-team && make test && make lint`).
3. Create branch `feat/sre-team-p0-airgap-oss` off `main`.
4. Implement **Priority 0 (P0.1 through P0.5)** in incremental, test-verified commits without breaking `make smoke` or `make e2e`.
5. Validate end-to-end against a local OSS model running on the RTX 3000 GPU (`models.local-gpu.yaml`) before proceeding to **Priority 1**.

### Recommended Reading Order for Any New Session
1. This file (`AGENTS.md`)
2. `docs/2026-11-research-and-architecture-review.md` (latest research, gap analysis, target air-gap architecture, locked decisions, and P0-P4 roadmap)
3. `agentic-sre-team/docs/superpowers/specs/2026-07-11-agentic-sre-team-design.md` (baseline v1 system design)
4. `agentic-sre-team/docs/superpowers/HANDOFF.md` (detailed Phase 0-6 implementation notes & watch-items)
5. `agentic-sre-team/gateway/src/sre_gateway/` and `agentic-sre-team/config/` (actual runtime code)
