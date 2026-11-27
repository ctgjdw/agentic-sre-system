# Agentic SRE Platform -- Phased Implementation Plan & Orchestrator Playbook

> **Status:** Ready for Execution
> **Date:** 2026-11-27
> **Target Executor:** Any AI Coding Agent, Multi-Agent Orchestrator, or Human Engineer (Provider-Agnostic)
> **Target Environment:** Local Windows Laptop (12 CPU threads, 64 GB RAM, NVIDIA Quadro RTX 3000 6 GB GDDR6 VRAM, WSL2 + Docker Desktop 29.5.3) + `gitlab.com` SCM
> **Authoritative Design Contracts (MUST Read Alongside This Plan):**
> 1. Root AI-Brain: [`../../../../AGENTS.md`](../../../../AGENTS.md)
> 2. Architecture & Component Spec: [`../specs/2026-11-27-airgap-platform-design.md`](../specs/2026-11-27-airgap-platform-design.md)
> 3. Docker Compose & Config Spec: [`../specs/2026-11-27-docker-compose-stack-spec.md`](../specs/2026-11-27-docker-compose-stack-spec.md)

---

## 0. Ready-to-Paste Kickoff Prompt (Provider-Agnostic)

Copy and paste the prompt below into any agentic coding session:

```text
Implement the full v2.0 local-GPU + air-gap-ready Agentic SRE Platform stack via Docker Compose on this laptop, executing Waves 0 through 6 (Tasks T01-T23) to completion without stopping early.

Read these 4 files in full first:
1. AGENTS.md
2. agentic-sre-team/docs/superpowers/specs/2026-11-27-airgap-platform-design.md
3. agentic-sre-team/docs/superpowers/specs/2026-11-27-docker-compose-stack-spec.md
4. agentic-sre-team/docs/superpowers/plans/2026-11-27-airgap-compose-implementation-plan.md

Follow the Wave 0 -> Wave 6 execution plan strictly:
- If the 2026-11-27 spec/plan docs are uncommitted on main, commit them to main first, then create branch feat/sre-team-airgap-compose off main.
- If your harness supports parallel subagents/workers, fan out ONLY across tasks marked Parallel-Safe in the same wave (P-1..P-5, strictly disjoint file sets) and run S (Sequential Integration) tasks one at a time; if running single-agent, execute tasks sequentially in order.
- Run verification commands directly after every task/wave (zero test failures, zero ruff/tsc/eslint errors).
- Never break deterministic fake-profile `smoke` or Playwright `e2e`.
- Bring up the real Docker Compose local-gpu + ui + sut stack on this laptop's RTX 3000 GPU, run the live incident chaos acceptance test + LLM-offline degraded-mode fallback test, and verify everything end to end.
```

---

## 1. Orchestration & Execution Rules (Agent-Agnostic)

To ensure first-pass reliability without merge collisions, context loss, or Windows Docker traps across any LLM/agent harness, enforce these seven rules:

1. **Strict File-Ownership Isolation on Parallel Dispatch:**
   When using parallel worker agents on a shared working tree, **never** run two workers concurrently if their **Files** lists overlap (especially shared wiring files: `settings.py`, `db/models.py`, `api/app.py`, `graph/deps.py`, `graph/build.py`, `graph/routers.py`, `tests/conftest.py`, `docker-compose.yml`). Each Wave splits work into:
   - **Parallel Track (`P-1`..`P-5`):** Disjoint new modules + isolated unit tests -- safe to execute concurrently via parallel subagents/worktrees, or sequentially in a single-agent harness.
   - **Sequential / Integration (`S`):** Shared wiring, Alembic migrations, full graph integration, and Docker Compose bring-up -- always run one at a time.
2. **Self-Contained Worker Briefs:**
   Delegated subagents typically start with a fresh context window. Every worker brief MUST specify:
   - Exact file paths to read first (the relevant section of `2026-11-27-airgap-platform-design.md` and neighbor modules).
   - Exact file paths it is allowed to create or edit (*"Do NOT edit any file outside this list"*).
   - Exact Pydantic/function signatures expected by downstream integration tasks.
   - Instruction to run `ruff check` / isolated unit tests and return a structured summary of files touched and verification results.
3. **Independent Verification Gate (Trust Nothing Unverified):**
   After workers return and after each Sequential integration step, run the Wave's verification gate command directly and inspect `git status -sb` + `git diff --stat` before committing.
4. **Windows + Sandboxed CLI Mechanics:**
   - Pure code checks (`uv run ruff check .`, `npm test`, `npm run lint`, `npx tsc --noEmit`) need no Docker socket or network access.
   - Commands talking to the Windows Docker Desktop daemon (`testcontainers` DB tests in `pytest`, `docker build`, `docker compose up`, `playwright`) or installing missing host tools (`uv`) require Docker named-pipe / host access if your agent CLI runs inside a restricted sandbox.
   - Never mount `/dev/null` in `docker-compose.yml`. Always keep `.gitattributes` `eol=lf` active so Linux containers never fail with `exec: \r: not found`.
5. **Preserve Fake-Profile Determinism (`smoke` & `e2e`):**
   - `preflight` MUST use `PF1..PFk` evidence IDs (never touching `cases.evidence_counter` which owns `E1..En`) and MUST skip network probes when `SRE_PREFLIGHT_PROBES_ENABLED=false` (default in unit tests and `--profile fake`).
   - Keep `config/environment.yaml` (Spectre) intact so `test_environment.py` passes; place `demo-sut`'s descriptor in `config/environment.local.yaml` selected via `SRE_ENVIRONMENT_FILE`.
6. **Git & Formatting Hygiene:**
   - Branch off `main`: `git checkout -b feat/sre-team-airgap-compose`.
   - Commit at the end of every task or wave with conventional commits (`feat(sre-team): ...`, `fix(sre-team): ...`, `chore(airgap): ...`).
   - Plain ASCII dashes (`-` or `--`) only -- zero Unicode em/en dashes. Never add `Co-Authored-By` trailers. Never stage `.env` or pre-existing untracked files outside your task.
7. **Hardware Guardrail (6 GB Dedicated VRAM on RTX 3000):**
   Default `SRE_LOCAL_CHAT_MODEL=qwen3:4b` (`~2.6 GB`) + `SRE_LOCAL_EMBED_MODEL=nomic-embed-text` (`274 MB`, native `768`-dim) in `ollama` with `OLLAMA_KEEP_ALIVE=-1` and `OLLAMA_MAX_LOADED_MODELS=2` so **both** models stay 100% resident in the 6 GB GDDR6 VRAM simultaneously with zero PCIe swap thrashing. Once verified green, `SRE_LOCAL_CHAT_MODEL=qwen3:8b` can also be tested as an optional capability upgrade.

---

## 2. Master Wave & File-Ownership Matrix

| Wave | Task | Mode | Summary | Owned Files (Exclusive Within Parallel Group) |
|---|---|---|---|---|
| **W0** | `T01` | `S` | Windows `.gitattributes`, `uv` + Python 3.12 bootstrap, cross-platform `scripts/cli.py` | `.gitattributes`, `agentic-sre-team/scripts/cli.py`, `agentic-sre-team/Makefile` |
| **W0** | `T02` | `S` | Baseline test & smoke verification on `feat/sre-team-airgap-compose` | *(verification only -- 119 gateway + 10 UI + `smoke` green)* |
| **W1** | `T03` | `P-1` | Hardened `call_llm_json` (`json_schema`, `<think>` strip, 4xx error class) | `gateway/src/sre_gateway/llm/json_call.py`, `gateway/tests/test_llm_json.py` |
| **W1** | `T04` | `P-1` | Salient evidence formatter (`head + middle errors + tail`) | `gateway/src/sre_gateway/evidence_fmt.py`, `gateway/tests/test_evidence_fmt.py` |
| **W1** | `T05` | `P-1` | UI SSE `lastEventId` & multi-round `Ledger.fold` bug fixes | `ui/src/api/sse.ts`, `ui/src/components/Ledger.tsx`, `ui/src/components/Ledger.test.tsx` |
| **W1** | `T06` | `S` | Model profiles (`local-gpu`, `airgap`), `OpenAIEmbeddings` fix, token budgets, `check_agent()` in `guarded()`, gate crash-window + `aclose()` + Alembic `0006` + Hybrid RRF `retrieval.py` + node excerpt/runbook wiring | `settings.py`, `llm/factory.py`, `budget.py`, `graph/deps.py`, `graph/nodes/{gates,triage,workers,synthesize,rca,verify,remediate}.py`, `graph/runner.py`, `api/{app,cases,governance}.py`, `holmes/client.py`, `retrieval.py`, `alembic/versions/0006_*.py`, `config/models.{local-gpu,airgap}.yaml`, `config/agents/*.yaml` |
| **W2** | `T07` | `P-2` | Tier-0 Deterministic Pre-Flight probes & circuit breaker | `gateway/src/sre_gateway/preflight/{__init__,probes,circuit,node}.py`, `gateway/tests/test_preflight.py` |
| **W2** | `T08` | `P-2` | Deterministic `validate_remediation` node & repair checks | `gateway/src/sre_gateway/graph/nodes/validate_remediation.py`, `gateway/tests/test_validate_remediation.py` |
| **W2** | `T09` | `S` | Wire `preflight` + `validate_remediation` into `StateGraph` + Alembic `0007` SHA-256 Audit Hash Chain + `/audit/verify` | `domain/enums.py`, `db/models.py`, `environment.py`, `graph/{state,routers,build}.py`, `alembic/versions/0007_*.py`, `audit.py`, `api/governance.py`, `tests/test_audit_chain.py` |
| **W3** | `T10` | `P-3` | `ScmProvider` contract + `GitlabProvider` (`gitlab.com`) + `GithubProvider` | `gateway/src/sre_gateway/scm/{__init__,base,gitlab,github}.py`, `gateway/tests/fixtures/scm/*.json`, `gateway/tests/test_scm_contract.py` |
| **W3** | `T11` | `P-3` | Gated `publish_scm.py` draft MR/PR helper (isolated module) | `gateway/src/sre_gateway/publish_scm.py`, `gateway/tests/test_publish_scm.py` |
| **W3** | `T12` | `S` | SCM webhooks, `repos.yaml`, `ScmPoller`, `patch_diffs`, pipeline-failure graph fixtures & tests, `scripts/chaos_ci.py` | `config/repos.yaml`, `intake/{scm_intake,poller_scm}.py`, `api/{webhooks,app,governance}.py`, `graph/nodes/{synthesize,remediate,publish}.py`, `tests/fixtures/{holmes,scripts}/pipeline_dep_typo/*`, `tests/{conftest,test_scm_intake,test_graph_pipeline,test_patch_diff}.py`, `scripts/chaos_ci.py` |
| **W4** | `T13` | `P-4` | `MattermostChannel` + `CompositeChannel` (buttons, callbacks, DM intake) | `gateway/src/sre_gateway/channels/{mattermost,composite}.py`, `gateway/tests/test_mattermost.py` |
| **W4** | `T14` | `P-4` | Toggleable Keycloak OIDC JWT verifier (`auth/oidc.py`) | `gateway/src/sre_gateway/auth/{__init__,oidc}.py`, `gateway/tests/test_auth_oidc.py` |
| **W4** | `T15` | `P-4` | Console Chat backend service (`chat/service.py`) | `gateway/src/sre_gateway/chat/{__init__,service}.py`, `gateway/tests/fixtures/holmes/incident_error_storm/chat.json`, `gateway/tests/fixtures/scripts/incident_error_storm/promote.json` |
| **W4** | `T16` | `S` | Wire Mattermost, OIDC Auth, and Chat API + React UI updates (`ChatScreen`, `ArtifactScreen` diffs/packets, `GovernanceScreen` tokens/chain, OIDC header) | `pyproject.toml`, `settings.py`, `api/{app,auth,chat,cases,governance,webhooks}.py`, `graph/runner.py`, `tests/{conftest,test_chat,test_chat_promote}.py`, `ui/src/**` |
| **W5** | `T17` | `P-5` | OpenTelemetry GenAI (`gen_ai.*`) tracing module | `gateway/src/sre_gateway/observability/{__init__,otel}.py`, `gateway/tests/test_otel.py` |
| **W5** | `T18` | `P-5` | Self-contained `demo-sut/` service + `config/environment.local.yaml` + `config/alerts/rules.local.yaml` + `provision/` | `demo-sut/**`, `config/environment.local.yaml`, `config/alerts/rules.local.yaml`, `gateway/src/sre_gateway/provision/{__init__,grafana,__main__}.py`, `gateway/tests/test_provision.py` |
| **W5** | `T19` | `P-5` | Infrastructure configs (`agentgateway`, `litellm`, `holmes.local.yaml`, `holmes-skills`, `keycloak/sre-realm.json`, `postgres/init-extra-dbs.sql`) | `config/agentgateway/config.yaml`, `config/litellm/config.yaml`, `config/holmes.local.yaml`, `config/holmes-skills/*.md`, `config/keycloak/sre-realm.json`, `config/postgres/init-extra-dbs.sql`, `config/lgtm/prometheus-extra.yaml` |
| **W5** | `T20` | `S` | Wire OTel into `app.py`/`json_call.py`/`holmes/client.py`, assemble full Windows-safe `docker-compose.yml` + `.env.example` + `scripts/chaos.py` + `scripts/demo.py` | `gateway/pyproject.toml`, `gateway/Dockerfile`, `api/app.py`, `llm/json_call.py`, `holmes/client.py`, `docker-compose.yml`, `.env.example`, `scripts/{chaos,demo}.py`, `README.md` |
| **W6** | `T21` | `S` | Full Offline Regression Gate (`pytest`, `ruff`, `vitest`, `eslint`, `smoke`, `e2e`) | *(all tests green, zero regressions)* |
| **W6** | `T22` | `S` | Live `local-gpu` + `ui` + `sut` Compose Bring-Up, Image Docs-Check, Ollama GPU Pull, `agentgateway` CEL Verification & LiteLLM Swap Check | *(live container bring-up & config verification)* |
| **W6** | `T23` | `S` | Live End-to-End Chaos Incident Acceptance Test + Tempo `gen_ai.*` Trace Verification + LLM-Offline Degraded Diagnostic Packet Test | *(live acceptance verification & final `AGENTS.md` status update)* |

---

## 3. Detailed Wave-by-Wave Implementation Specifications

### Wave 0 -- Toolchain Bootstrap, Windows Guards & Baseline Check

#### Task `T01` (Sequential): `.gitattributes`, `uv` + Python 3.12 Setup, and Cross-Platform `scripts/cli.py`
- **Spec Ref:** `2026-11-27-docker-compose-stack-spec.md` §2.
- **Steps:**
  1. Create branch `git checkout -b feat/sre-team-airgap-compose` off `main`.
  2. Write root `.gitattributes` enforcing `eol=lf` for all source/shell/SQL/Dockerfiles (`*.ps1` and `*.bat` `eol=crlf`).
  3. Check if `uv` is installed (`~/.local/bin/uv.exe` or PATH); if missing, install via PowerShell `irm https://astral.sh/uv/install.ps1 | iex` (or `winget install --id=Astral-sh.uv -e`) and run `cd agentic-sre-team/gateway && uv python install 3.12 && uv sync`.
  4. Create `agentic-sre-team/scripts/cli.py` supporting subcommands:
     - `test` (runs `uv run pytest -q` in `gateway/` and `npm test` in `ui/`)
     - `lint` (runs `uv run ruff check .` in `gateway/`, `npm run lint` and `npx tsc --noEmit` in `ui/`)
     - `smoke` (sets `SRE_MODELS_PROFILE=fake`, `SRE_HOLMES_URL=http://fake-holmes:5050`, `SRE_TELEGRAM_ENABLED=false`, `SRE_MATTERMOST_ENABLED=false`, `SRE_AUTH_ENABLED=false`, `SRE_PREFLIGHT_PROBES_ENABLED=false`, `SRE_FAKE_SCRIPT_DIR=/app/tests/fixtures/scripts/incident_error_storm`, brings up `--profile fake`, runs `scripts/smoke.py`)
     - `e2e` (downs volumes, brings up `--profile fake --profile ui`, runs Playwright `smoke.spec.ts`)
     - `up-local` (brings up `--profile local-gpu --profile ui --profile sut` with `SRE_MODELS_PROFILE=local-gpu`, `SRE_ENVIRONMENT_FILE=environment.local.yaml`, `SRE_PREFLIGHT_PROBES_ENABLED=true`, `SRE_OTEL_ENABLED=true`)
     - `provision` (runs `--profile provision run --rm provision`)
     - `down` (downs all profiles cleanly)
     - Automatically handles `DOCKER_CONFIG` fallback if `~/.docker/config.json` is unreadable in a sandboxed shell.
  5. Update `agentic-sre-team/Makefile` to delegate or work cleanly alongside `scripts/cli.py`.
- **Commit:** `chore(airgap): add lf gitattributes and cross-platform cli runner`

#### Task `T02` (Sequential): Baseline Verification Gate
- **Run:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint
  python agentic-sre-team/scripts/cli.py test
  python agentic-sre-team/scripts/cli.py smoke
  ```
- **Pass Criteria:** 119 gateway tests pass, 10 UI tests pass, `ruff` + `eslint` clean, `smoke` prints `PASS: case closed with published artifacts`. Do NOT proceed to Wave 1 until baseline is green.

---

### Wave 1 -- P0 OSS LLM Harness, Hybrid Retrieval & Core Bug Fixes

> **Dispatch:** Run `T03`, `T04`, and `T05` concurrently (`P-1` -- zero overlapping files) or sequentially. Verify all three, then execute `T06` sequentially.

#### Task `T03` (`P-1` Parallel-Safe): Hardened `call_llm_json`
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §5.2.
- **Files:** `gateway/src/sre_gateway/llm/json_call.py`, `gateway/tests/test_llm_json.py`.
- **Deliverables:**
  1. `strip_thinking(text: str) -> tuple[str, str]` stripping `<think>...</think>` blocks (and raising `LlmJsonError` on unclosed `<think>` truncation so repair retry triggers).
  2. Optional `structured_output: Literal["json_schema", "json_object", "prompt"] = "prompt"` parameter on `call_llm_json` (default `"prompt"` so all existing callers compile unchanged until `T06` passes tier settings; when `"json_schema"` and model supports `.bind`, binds `response_format={"type": "json_schema", "json_schema": {"name": schema.__name__, "strict": False, "schema": schema.model_json_schema()}}`).
  3. `is_retryable_llm_error(err)` + `LlmContextOverflowError`: fail fast without `asyncio.sleep` on 400/401/403/404/context-overflow; retry up to 3x with jitter on 429/5xx/timeout/connection errors.
  4. Record `thinking_chars` in `audit.log_llm` (keep backward-compatible kwargs on `log_llm` or pass inside payload).
  5. Unit tests in `test_llm_json.py`: `<think>{rate(http{code="500"}[5m])}</think>{"ok": true}` parses `{"ok": true}`; unclosed `<think>` triggers repair and succeeds on 2nd attempt; 401/400 fails with 0 retries; 503 retries and succeeds; `json_schema` mode binds `response_format`.

#### Task `T04` (`P-1` Parallel-Safe): Salient Evidence Extractor
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §7.2.
- **Files:** `gateway/src/sre_gateway/evidence_fmt.py`, `gateway/tests/test_evidence_fmt.py`.
- **Deliverables:**
  1. `format_evidence_excerpt(text: str, budget_chars: int = 1200) -> str`: returns verbatim if `<= budget_chars`, else combines 35% head + up to 30% salient error/exception/status lines + 35% tail with `\n... [omitted] ...\n`, guaranteed `<= budget_chars + 40`.
  2. Unit tests proving a 3500-char Java/Python stack trace whose root `Caused by: PoolTimeoutError` sits at byte 3200 preserves both line 1 and `PoolTimeoutError` within a 900-char budget.

#### Task `T05` (`P-1` Parallel-Safe): UI SSE & Multi-Round Ledger Fixes
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §10.3.
- **Files:** `ui/src/api/sse.ts`, `ui/src/components/Ledger.tsx`, `ui/src/components/Ledger.test.tsx`.
- **Deliverables:**
  1. `sse.ts`: Track `lastSeqRef` so an event with empty `lastEventId` (like `token`) never resets sequence tracking.
  2. `Ledger.tsx`: Add `preflight: "Pre-flight · deterministic"` and `validate_remediation: "Validate remediation · deterministic"` to `NAMES`; scope `byNode` keys by current round (`${node}-${round}`) so Round-2 `synthesize` never clobbers Round-1 `synthesize`.
  3. Add Vitest cases in `Ledger.test.tsx` covering 2-round `synthesize` folding and `preflight` rendering.

#### Task `T06` (Sequential Integration): Model Profiles, Token Budgets, Gate Crash Fix, Hybrid Search (`0006`) & Node Excerpt Wiring
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §5.1, §7.1, §7.3, §9.4.
- **Files:** `settings.py`, `llm/factory.py`, `budget.py`, `audit.py`, `graph/deps.py`, `graph/state.py`, `graph/runner.py`, `graph/nodes/{gates,triage,workers,synthesize,rca,verify,remediate}.py`, `api/{app,cases,governance}.py`, `holmes/client.py`, `retrieval.py`, `alembic/versions/0006_hybrid_search_and_gate_idempotency.py`, `config/models.{local-gpu,airgap}.yaml`, `config/agents/*.yaml`, `tests/{test_model_factory,test_budget,test_retrieval,test_holmes_client}.py`.
- **Deliverables:**
  1. `settings.py`: `models_config_path` resolves `models.yaml` for `"local"` and `models.{profile}.yaml` for `"fake"`, `"local-gpu"`, `"airgap"`. Add `environment_file: str = "environment.yaml"`, `llm_gateway_url: str = "http://agentgateway:4000/v1"`, `preflight_probes_enabled: bool = False`, `preflight_prom_url: str = "http://lgtm:9090"`, `preflight_loki_url: str = "http://lgtm:3100"`.
  2. `llm/factory.py`: `_ENV_RE` supports `${VAR:-default}`; optional pricing (no `ValueError` when absent); `TierConfig.structured_output`, `TierConfig.extra_body`, `TierConfig.timeout_s`; `EmbeddingsConfig.send_dimensions: bool = False` + `OpenAIEmbeddings(..., check_embedding_ctx_length=False)`. Write `config/models.local-gpu.yaml` and `config/models.airgap.yaml`.
  3. `budget.py` + `config/agents/*.yaml` + `graph/deps.py` + `api/governance.py`: Add `tokens_per_day` to each `config/agents/*.yaml` (`500000` to `2000000`) alongside `usd_per_day`; implement `agent_tokens_today()` and updated `check_agent()` in `BudgetEnforcer`; wire `check_agent()` into `guarded()` in `graph/deps.py`; expose `tokens_per_day` & `tokens_today` in `/api/governance`.
  4. `gates.py`, `runner.py`, `holmes/client.py`, `api/app.py`, `api/cases.py`:
     - Migration `0006` adds `ix_approvals_case_artifact_gate` unique index + `runbooks.search_tsv` & `case_learnings.search_tsv` GIN indexes.
     - `gates.py`: idempotent `Approval` check before insert; `runner.py`: stamp `waiting_since` on error-park + checkpoint reconciliation for interrupted gates in `relaunch_open_cases()`; `holmes/client.py`: add `aclose()` called in `api/app.py` shutdown; `api/cases.py`: omit `"id"` key on unpersisted SSE frames (`seq is None`).
  5. `retrieval.py`: Hybrid `pgvector` + `tsvector` RRF (`k=60`) with graceful BM25-only fallback when `embed()` raises, preserving `fake` `hash_embedding` test compatibility.
  6. `triage.py`, `workers.py`, `synthesize.py`, `rca.py`, `verify.py`, `remediate.py`: Use `format_evidence_excerpt` (`900`/`1200`/`1400`/`800` chars), store `[:4000]` in `workers.py`, pass `matched_runbooks` from `triage` into `workers.py` prompt.
- **Wave 1 Gate Command:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint && python agentic-sre-team/scripts/cli.py test
  ```
- **Commit:** `feat(sre-team): oss llm harness, hybrid rrf search, token budgets and p0 bug fixes`

---

### Wave 2 -- Tier-0 Deterministic Pre-Flight, Remediation Validator & Audit Hash Chain

> **Dispatch:** Run `T07` and `T08` concurrently (`P-2`) or sequentially. Then run `T09` sequentially.

#### Task `T07` (`P-2` Parallel-Safe): Tier-0 Pre-Flight Collector & Circuit Breaker
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §6.
- **Files:** `gateway/src/sre_gateway/preflight/{__init__,probes,circuit,node}.py`, `gateway/tests/test_preflight.py`.
- **Deliverables:**
  1. `probes.py`: `probe_prometheus_golden`, `probe_loki_errors`, `probe_service_health`, `probe_recent_commits` (all bounded `<= 3s` via `httpx`, returning structured `PreflightFinding(toolset, invocation, excerpt, source_url)` or `None`).
  2. `circuit.py`: `InferenceCircuitBreaker` probing `{llm_gateway_url}/models` (`2.0s` timeout) when `models_profile != "fake"`, opening on unreachable/5xx and tracking failure streak.
  3. `node.py`: `make_preflight(deps)` writing `PF1..PFk` `EvidenceRow`s (only when `preflight_probes_enabled=True`, never touching `cases.evidence_counter`), running hybrid RAG, and on `healthy == False` persisting `Artifact(kind="diagnostic_packet", version=1, ...)` + notifying channel + returning `{"halt": {"reason": "llm_unavailable: diagnostic_packet_ready", "at_node": "preflight"}}`.
  4. Unit tests with `respx` verifying: (a) probes disabled (`fake` default) -> 0 HTTP calls, 0 `EvidenceRow`s, RAG runs; (b) probes enabled -> `PF1..PF3` written, `evidence_counter` remains `0`; (c) circuit open -> `diagnostic_packet` artifact persisted and `halt` returned in `< 1s`.

#### Task `T08` (`P-2` Parallel-Safe): Deterministic Remediation Validator Node
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §9.3.
- **Files:** `gateway/src/sre_gateway/graph/nodes/validate_remediation.py`, `gateway/tests/test_validate_remediation.py`.
- **Deliverables:**
  1. `make_validate_remediation(deps)` validating `RunbookOut`: destructive command denylist, `sh -n` syntax on concrete shell commands, `yaml.safe_load_all` on `.yml`/`.yaml` patches (plus K8s manifest required keys when `apiVersion` present), `json.loads` on `.json` patches, PromQL balanced delimiters, and required non-empty `patch_files` when `kind == "pipeline_failure"`.
  2. Writes validation summary into `Artifact.verification` (`{verified, checked, failures}`), sets `runbook_validation` in state, and appends repair notes to `context_notes` on failure.
  3. Unit tests covering valid runbook, broken YAML patch triggering failure + repair note, dangerous `rm -rf /` command rejection, and pipeline case missing `patch_files`.

#### Task `T09` (Sequential Integration): Wire `preflight` & `validate_remediation` into `StateGraph` + Migration `0007` Audit Hash Chain
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §4.1, §9.4, §10.1.
- **Files:** `domain/enums.py`, `db/models.py`, `environment.py`, `graph/{state,routers,build}.py`, `graph/nodes/gates.py`, `alembic/versions/0007_audit_hash_chain.py`, `audit.py`, `api/governance.py`, `tests/test_audit_chain.py`.
- **Deliverables:**
  1. `domain/enums.py`: add `ArtifactKind.diagnostic_packet` and `SignalSource.mattermost`.
  2. `environment.py`: add optional `health_url: str | None = None` and `metrics_job: str | None = None` to `ServiceEntry`.
  3. `graph/build.py` & `graph/routers.py`: wire `START -> preflight -> triage` (`route_after_preflight`: `"park"` if halted else `"triage"`) and `remediate -> validate_remediation -> gate_runbook | remediate | park` (`route_after_validate_remediation`: `"remediate"` if not verified and `not state.get("runbook_repair_used")` else `"gate_runbook"`). In `gates.py`, when `gate == "runbook"` and `verdict == "reject"`, reset `runbook_validation: None, runbook_repair_used: False`.
  4. Migration `0007`: enable `pgcrypto`, add `prev_hash` and `event_hash` to `audit_events`, backfill any existing rows, create `BEFORE INSERT` trigger `audit_events_compute_hash()` using `pg_advisory_xact_lock(77411)`.
  5. `audit.py` + `api/governance.py`: add `verify_audit_chain(sessionmaker) -> dict` recomputing hashes in Python from `GENESIS` and asserting every row matches `prev_hash`/`event_hash`; expose `GET /api/governance/audit/verify`.
  6. `test_audit_chain.py`: insert 10 concurrent audit events via `asyncio.gather`, assert `/api/governance/audit/verify` returns `{"valid": True, "checked": 10}`, and confirm `UPDATE`/`DELETE` still raise append-only trigger errors.
- **Wave 2 Gate Command:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint && python agentic-sre-team/scripts/cli.py test && python agentic-sre-team/scripts/cli.py smoke
  ```
- **Commit:** `feat(sre-team): tier-0 preflight collector, remediation validator and sha256 audit chain`

---

### Wave 3 -- Phase 7 DevSecOps Pipeline Failures (`gitlab.com` Primary + GitHub)

> **Dispatch:** Run `T10` and `T11` concurrently (`P-3`) or sequentially. Then run `T12` sequentially.

#### Task `T10` (`P-3` Parallel-Safe): `ScmProvider` Protocol + `GitlabProvider` (`gitlab.com`) + `GithubProvider`
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §1.1, `2026-07-11-agentic-sre-team-implementation.md` Tasks 36-37.
- **Files:** `gateway/src/sre_gateway/scm/{__init__,base,gitlab,github}.py`, `gateway/tests/fixtures/scm/{gitlab_pipeline,github_workflow_run}.json`, `gateway/tests/test_scm_contract.py`.
- **Deliverables:**
  1. `scm/base.py`: `JobRef`, `CommitRef`, `PipelineFailure`, `ScmProvider` protocol (including `list_recent_commits(repo, branch, limit=5)` used by `preflight` + `verify_webhook`, `parse_webhook`, `poll_failures`, `fetch_file`, `create_branch`, `commit_files`, `open_draft_change` -- **no merge method exists**), `failure_to_signal`.
  2. `scm/gitlab.py`: `GitlabProvider(base_url="https://gitlab.com", token=..., webhook_secret=...)` using `/api/v4/projects/{url_encoded_slug}/...`, constant-time `X-Gitlab-Token`, `Draft: <title>` MR creation.
  3. `scm/github.py`: `GithubProvider(token=..., webhook_secret=...)` using `X-Hub-Signature-256` HMAC-SHA256 and `draft: True` PR creation.
  4. Shared contract test suite `test_scm_contract.py` passing for **both** GitLab and GitHub.

#### Task `T11` (`P-3` Parallel-Safe): Gated `publish_scm.py` Draft MR/PR Action
- **Files:** `gateway/src/sre_gateway/publish_scm.py`, `gateway/tests/test_publish_scm.py`.
- **Deliverables:**
  1. `publish_draft_change(deps, case_id, state) -> str | None`: executes ONLY when `settings.scm_draft_mr` is `True`, `kind == "pipeline_failure"`, approved runbook has `patch_files`, and dedicated `gitlab_publish_token` / `github_publish_token` is set. Creates branch `fix/<display_id>`, commits `patch_files`, opens **draft** MR/PR, logs `publish` audit event, degrades gracefully on API error without blocking case close.
  2. Unit tests with `respx` covering both GitLab (`gitlab.com`) and GitHub draft MR/PR flows, flag-off no-op, and error containment.

#### Task `T12` (Sequential Integration): SCM Webhooks, `ScmPoller`, `patch_diffs`, Pipeline Graph Tests & `chaos_ci.py`
- **Files:** `settings.py`, `graph/deps.py`, `config/repos.yaml`, `intake/{scm_intake,poller_scm}.py`, `api/{webhooks,app,governance}.py`, `graph/nodes/{synthesize,remediate,publish}.py`, `tests/fixtures/{holmes,scripts}/pipeline_dep_typo/*`, `tests/{conftest,test_scm_intake,test_graph_pipeline,test_patch_diff}.py`, `scripts/chaos_ci.py`, `docs/gitlab-setup.md`.
- **Deliverables:**
  1. `settings.py`: add `gitlab_publish_token: str | None = None`, `github_publish_token: str | None = None`.
  2. `config/repos.yaml` + `intake/scm_intake.py` (`sync_repos`) + `intake/poller_scm.py` (`ScmPoller`) + `api/webhooks.py` (`POST /api/webhooks/gitlab`, `POST /api/webhooks/github`) + `api/app.py` lifespan wiring.
  3. `synthesize.py`: persist revised `failure_class` to `Case` row.
  4. `remediate.py`: compute deterministic `patch_diffs` via `provider.fetch_file` + `difflib.unified_diff`.
  5. `publish.py`: invoke `publish_draft_change`; `api/governance.py`: include `"scm_draft_mr": settings.scm_draft_mr`.
  6. Pipeline graph fixtures (`pipeline_dep_typo`) + `test_graph_pipeline.py` verifying both `GitlabProvider` and `GithubProvider` route to `{"ci", "changes"}` workers, set `failure_class == "dependency"`, pass `validate_remediation`, and produce `patch_files`.
  7. Cross-platform `scripts/chaos_ci.py` + concise `docs/gitlab-setup.md` for seeding a failing pipeline on `gitlab.com`.
- **Wave 3 Gate Command:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint && python agentic-sre-team/scripts/cli.py test
  ```
- **Commit:** `feat(sre-team): gitlab and github pipeline-failure intake, diffs and draft-mr publish`

---

### Wave 4 -- Mattermost Channel, Toggleable Keycloak OIDC Auth & Console Chat (Phase 8)

> **Dispatch:** Run `T13`, `T14`, and `T15` concurrently (`P-4` -- completely disjoint directories) or sequentially. Then run `T16` sequentially.

#### Task `T13` (`P-4` Parallel-Safe): `MattermostChannel` & `CompositeChannel`
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §9.1.
- **Files:** `gateway/src/sre_gateway/channels/{mattermost,composite}.py`, `gateway/tests/test_mattermost.py`.
- **Deliverables:**
  1. `MattermostChannel`: posts messages + interactive Approve/Reject button attachments to `/api/v4/posts`; handles button action payloads (`verify callback_secret`, check allowed users, call `on_decision(..., channel="mattermost")`, update post via `PUT /api/v4/posts/{post_id}`); handles DM intake payloads via `on_report`; redacts bot tokens from any `httpx` error strings (matching `TelegramChannel._redact`).
  2. `CompositeChannel(channels: list[Channel])`: fans out `send()` across active channels cleanly, falling back to `LogChannel` if empty.
  3. Unit tests in `test_mattermost.py` (`respx`) covering button send, authorized/unauthorized action callback, post update, DM report intake, and token redaction.

#### Task `T14` (`P-4` Parallel-Safe): Toggleable Keycloak OIDC JWT Auth
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §9.2.
- **Files:** `gateway/src/sre_gateway/auth/{__init__,oidc}.py`, `gateway/tests/test_auth_oidc.py`.
- **Deliverables:**
  1. `OidcVerifier` + FastAPI dependency `require_operator`: no-op passthrough when `settings.auth_enabled == False`; full RS256 JWT verification (`PyJWT` + cached JWKS via `httpx`), `iss`/`aud`/`exp` validation, `sre-approver` realm/client role check, and verified `preferred_username` extraction when `settings.auth_enabled == True`.
  2. Unit tests generating an ephemeral RSA keypair + local JWKS mock (`respx`), testing: `auth_enabled=False` passthrough, missing token -> 401, expired token -> 401, valid token without `sre-approver` -> 403, valid token with `sre-approver` -> 200 and verified username returned.

#### Task `T15` (`P-4` Parallel-Safe): Console Chat Service ("Ask the Team")
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §1.1, `2026-07-11-agentic-sre-team-implementation.md` Tasks 42-44.
- **Files:** `gateway/src/sre_gateway/chat/{__init__,service}.py`, `gateway/tests/fixtures/holmes/incident_error_storm/chat.json`, `gateway/tests/fixtures/scripts/incident_error_storm/promote.json`.
- **Deliverables:**
  1. `ChatService`: `create_thread`, `list_threads`, `get_thread`, `attach_case`, `stream_message` (daily token/USD cap check, environment + optional case-context grounding with `format_evidence_excerpt`, Holmes SSE tool relay, persistence + audit), and `promote_thread` (`confirm=False` small-tier preview vs `confirm=True` `SignalSource.chat` case creation).

#### Task `T16` (Sequential Integration): Wire Channels, OIDC, Chat API & React UI Screens
- **Files:** `gateway/pyproject.toml` (add `PyJWT[crypto]>=2.9`), `settings.py`, `api/{app,auth,chat,cases,governance,webhooks}.py`, `graph/runner.py`, `tests/{conftest,test_chat,test_chat_promote}.py`, `ui/src/api/{client,postSse,types}.ts`, `ui/src/components/TopBar.tsx`, `ui/src/screens/{ArtifactScreen,CaseDetailScreen,ChatScreen,GovernanceScreen}.tsx`, `ui/src/screens/ChatScreen.test.tsx`, `ui/src/App.tsx`.
- **Deliverables:**
  1. Wire `MattermostChannel` + `CompositeChannel` + `/api/webhooks/mattermost/{action,dm}` into `settings.py`, `api/webhooks.py`, and `api/app.py`.
  2. Wire `require_operator` onto mutating routes (`decide_case`, `park_case`, `resume_case`, `set_pause`) -- overriding `decided_by`/`actor` with verified OIDC identity when `auth_enabled=True` -- and add `GET /api/auth/config`.
  3. Wire `/api/chat/*` router + `runner.py` postbacks into promoted `ChatThread`s + `test_chat.py` & `test_chat_promote.py`.
  4. React UI updates:
     - `ChatScreen.tsx` + `postSse.ts` + `/chat` nav link in `TopBar.tsx` + `"Ask about this"` button on `CaseDetailScreen.tsx`.
     - `ArtifactScreen.tsx`: support `diagnostic_packet` view, render `patch_diffs` unified diffs (`+`/`-` highlighted), show `"validation verified"` on runbooks, channel-neutral outcome preview text.
     - `GovernanceScreen.tsx`: show token/day budgets + `"Audit Chain Verified"` indicator (`/api/governance/audit/verify`).
     - `client.ts` + `TopBar.tsx`: optional Bearer token support (`localStorage.getItem("sre_oidc_token")`) and OIDC status badge when `/api/auth/config` reports `enabled: true`.
- **Wave 4 Gate Command:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint && python agentic-sre-team/scripts/cli.py test && python agentic-sre-team/scripts/cli.py e2e
  ```
- **Commit:** `feat(sre-team): mattermost channel, toggleable keycloak oidc auth and console chat ui`

---

### Wave 5 -- OpenTelemetry `gen_ai.*`, `agentgateway` + MCP, `demo-sut` & Docker Compose Stack

> **Dispatch:** Run `T17`, `T18`, and `T19` concurrently (`P-5`) or sequentially. Then run `T20` sequentially.

#### Task `T17` (`P-5` Parallel-Safe): OpenTelemetry GenAI (`gen_ai.*`) Instrumentation Module
- **Spec Ref:** `2026-11-27-airgap-platform-design.md` §8.3.
- **Files:** `gateway/src/sre_gateway/observability/{__init__,otel}.py`, `gateway/tests/test_otel.py`.
- **Deliverables:**
  1. `setup_otel(app, settings)` (idempotent; when `otel_enabled=False` uses no-op tracer; supports custom `SpanExporter` injection for unit tests; configures OTLP HTTP exporter to `otel_exporter_endpoint` and optional secondary exporter to `langfuse_otel_endpoint` with Basic Auth).
  2. Context-manager helpers `genai_chat_span(...)`, `genai_node_span(...)`, `genai_tool_span(...)`, and `inject_trace_headers(headers: dict) -> dict` setting standard `gen_ai.*` and `sre.*` attributes.
  3. Unit test `test_otel.py` using `InMemorySpanExporter` asserting `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `sre.case_id`, and `traceparent` header injection.

#### Task `T18` (`P-5` Parallel-Safe): Self-Contained `demo-sut/` + Grafana Provisioner
- **Spec Ref:** `2026-11-27-docker-compose-stack-spec.md` §5, `2026-07-11-agentic-sre-team-implementation.md` Task 48.
- **Files:** `agentic-sre-team/demo-sut/{Dockerfile,pyproject.toml,app.py}`, `agentic-sre-team/config/environment.local.yaml`, `agentic-sre-team/config/alerts/rules.local.yaml`, `agentic-sre-team/config/alerts/rules.yaml`, `gateway/src/sre_gateway/provision/{__init__,grafana,__main__}.py`, `gateway/tests/test_provision.py`.
- **Deliverables:**
  1. `demo-sut/`: FastAPI app with `/healthz`, `/metrics`, `/api/v1/orders`, `/api/v1/auth/verify`, `/internal/chaos` (`off`, `error-storm`, `latency`, `db-disconnect`), background 2 req/s traffic loop, OTLP metrics/logs/traces export to `OTEL_EXPORTER_OTLP_ENDPOINT`.
  2. `provision/grafana.py`: idempotent Grafana folder + Prometheus/Loki datasource UID discovery (works with both Basic Auth `admin:admin` on local `otel-lgtm` AND Bearer `SRE_GRAFANA_SA_TOKEN` on enterprise Grafana) + alert rule upsert + HMAC webhook contact point + notification policy binding (`test_provision.py` with `respx`).

#### Task `T19` (`P-5` Parallel-Safe): Stack Service Configs & Holmes Skills
- **Spec Ref:** `2026-11-27-docker-compose-stack-spec.md` §3.1, §4.3-4.6.
- **Files:** `agentic-sre-team/config/agentgateway/config.yaml`, `agentic-sre-team/config/litellm/config.yaml`, `agentic-sre-team/config/holmes.local.yaml`, `agentic-sre-team/config/holmes-skills/{http-5xx-error-storm,latency-degradation,database-and-auth-outage,ci-pipeline-failure}.md`, `agentic-sre-team/config/keycloak/sre-realm.json`, `agentic-sre-team/config/postgres/init-extra-dbs.sql`, `agentic-sre-team/config/lgtm/prometheus-extra.yaml`.
- **Deliverables:** Exact config files matching `2026-11-27-docker-compose-stack-spec.md` (strict YAML block mappings in `holmes.local.yaml`, CEL read-only rules in `agentgateway/config.yaml`, scrape job for `demo-sut:8090` in `lgtm`).

#### Task `T20` (Sequential Integration): Wire OTel, Assemble `docker-compose.yml`, `.env.example`, `chaos.py`, `demo.py` & Docs
- **Files:** `gateway/pyproject.toml` (add OTel packages + `uv lock`), `gateway/Dockerfile`, `settings.py`, `api/app.py`, `llm/json_call.py`, `graph/deps.py`, `holmes/client.py`, `agentic-sre-team/docker-compose.yml`, `agentic-sre-team/.env.example`, `agentic-sre-team/scripts/{chaos,demo}.py`, `agentic-sre-team/README.md`, root `README.md`.
- **Deliverables:**
  1. Add OTel dependencies in `gateway/pyproject.toml`, run `uv lock && uv sync`, wire spans into `app.py`, `guarded()`, `call_llm_json()`, and `HolmesClient.chat()` (`inject_trace_headers`).
  2. Update `api/app.py` to load `settings.config_dir / settings.environment_file` (`environment.yaml` default, `environment.local.yaml` in `local-gpu` SUT stack).
  3. Write Windows-safe `agentic-sre-team/docker-compose.yml` and updated `.env.example`.
  4. Write cross-platform Python `scripts/chaos.py` (`error-storm`, `latency`, `sut-stop`, `restore` + timeline annotation POST) and `scripts/demo.py` (automated live acceptance driver).
- **Wave 5 Gate Command:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint && python agentic-sre-team/scripts/cli.py test
  ```
- **Commit:** `feat(airgap): otel genai tracing, agentgateway mcp filtering, demo-sut and compose stack`

---

### Wave 6 -- Full Regression Sweep & Live Laptop GPU Acceptance Verification

#### Task `T21` (Sequential): Full Offline Deterministic Regression Gate
- **Run:**
  ```powershell
  python agentic-sre-team/scripts/cli.py lint
  python agentic-sre-team/scripts/cli.py test
  python agentic-sre-team/scripts/cli.py smoke
  python agentic-sre-team/scripts/cli.py e2e
  ```
- **Pass Criteria:** 100% of unit, contract, migration, graph, UI, `smoke`, and Playwright `e2e` tests pass with zero warnings.

#### Task `T22` (Sequential): Live `local-gpu` Stack Bring-Up, Live Docs-Check & Gateway Swap Verification on RTX 3000
- **Steps:**
  1. Bring up the live stack:
     ```powershell
     python agentic-sre-team/scripts/cli.py up-local
     ```
  2. Wait for `sre-ollama-pull` to complete pulling `qwen3:4b` and `nomic-embed-text`. Verify GPU offload inside Ollama (`docker exec sre-ollama ollama ps` -> confirm processor shows `% GPU` on the Quadro RTX 3000 and total VRAM stays `<= 5.8 GB` via `nvidia-smi`).
  3. **Live Container Contract Probes (Fix Any Config Drift Immediately):**
     - Probe `agentgateway` LLM route (`POST http://127.0.0.1:4000/v1/chat/completions` with `json_schema` `response_format` -> assert valid JSON response) and Embeddings (`POST http://127.0.0.1:4000/v1/embeddings` with `nomic-embed-text` -> assert `len(embedding) == 768`).
     - Probe `agentgateway` MCP route (`http://127.0.0.1:3003/mcp` `tools/list`) -> **SECURITY ASSERTION:** verify `query_prometheus` and `query_loki_logs` are present AND verify zero write tools (`update_dashboard`, `create_incident`, `create_merge_request`, `delete_*`) appear in `tools/list`.
     - Probe `holmes` (`POST http://127.0.0.1:5050/api/chat` asking for `up` metric from `lgtm`) -> assert `tool_calls` contains Prometheus result.
     - Test interchangeable **LiteLLM swap**: start `--profile litellm`, probe `POST http://127.0.0.1:4001/v1/chat/completions`, verify identical OpenAI-compatible response, then stop `litellm`.
  4. Run Grafana provisioning:
     ```powershell
     python agentic-sre-team/scripts/cli.py provision
     ```
     Verify rules exist at `http://127.0.0.1:3000/api/v1/provisioning/alert-rules`.

#### Task `T23` (Sequential): Live End-to-End Chaos Incident Run + Tempo Trace Check + LLM-Offline Degraded Mode Test
- **Steps:**
  1. **Live Incident Loop (GPU Active):**
     - Inject chaos: `python agentic-sre-team/scripts/chaos.py error-storm`
     - Observe `OrdersApiHighErrorRate` fire in `lgtm` Grafana -> HMAC webhook opens `CASE-0001` on `gateway`.
     - Verify `PF1..PFk` Tier-0 pre-flight receipts land within 5 seconds, followed by parallel Holmes `0.43.0` workers, hypothesis board update, and citation-verified RCA reaching `gate_rca`.
     - Approve Gate 1 (`POST /api/cases/{id}/decision`), verify `remediate` + `validate_remediation` pass and reach `gate_runbook`, approve Gate 2, and confirm `status == "closed"`, `Runbook` + `CaseLearning` indexed in Postgres (`search_tsv` populated), and `/api/governance/audit/verify` returns `{"valid": true}`.
     - Query Tempo (`GET http://127.0.0.1:3200/api/search?tags=gen_ai.operation.name%3Dchat`) and confirm `gen_ai.*` spans are recorded locally.
     - Restore SUT: `python agentic-sre-team/scripts/chaos.py restore`.
  2. **Live Degraded-Inference Fallback Loop (Zero-Degradation Law Proof):**
     - Pause `sre-ollama` (`docker pause sre-ollama`).
     - Post a synthetic Grafana alert webhook with a fresh fingerprint.
     - Assert that within `< 8 seconds`, `preflight` detects the open inference circuit, persists a `diagnostic_packet` artifact containing real Prometheus/Loki golden signals (`PF1..PFk`), parks the case cleanly in `needs_human` without crashing, and unpause `sre-ollama` (`docker unpause sre-ollama`).
  3. **Optional Profile Smoke Checks:**
     - Start `--profile auth` (`sre-keycloak`), fetch a real JWT for `alex.goh` from `http://127.0.0.1:8180/realms/sre/protocol/openid-connect/token`, and verify authenticated endpoint access.
     - If `SRE_GITLAB_TOKEN` is set in `.env`, verify `GitlabProvider` live poll against `https://gitlab.com/api/v4`.
  4. Update `AGENTS.md` Section 3 to mark P0-P2 local Docker Compose stack complete and commit cleanly on `feat/sre-team-airgap-compose`.

---

## 4. Provider-Neutral Worker Task Brief Template

When delegating any Parallel-Safe task (`P-1`..`P-5`) to a worker agent in any multi-agent framework, structure the worker prompt using this template so file boundaries and verification contracts stay airtight:

```text
Task ID: <Txx>
Read First:
- agentic-sre-team/docs/superpowers/specs/2026-11-27-airgap-platform-design.md (Section <X.Y>)
- agentic-sre-team/docs/superpowers/plans/2026-11-27-airgap-compose-implementation-plan.md (Task <Txx>)

Exclusive Owned Files (Do NOT create or modify any file outside this list):
- <path 1>
- <path 2>

Requirements:
- Implement the exact interfaces and unit tests specified in Task <Txx>.
- Use plain ASCII dashes (- or --) only.
- Run linter/unit checks scoped to your owned files before finishing.

Return Summary:
- task_id
- files_touched
- checks_run_and_status
- notes_for_wave_integrator
```
