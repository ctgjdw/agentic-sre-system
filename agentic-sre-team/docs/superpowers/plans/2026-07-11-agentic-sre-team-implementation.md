# Agentic SRE Team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `/agentic-sre-team` system from the approved spec: a Docker-Compose-deployed agentic SRE/DevSecOps team (FastAPI + LangGraph gateway, HolmesGPT evidence sidecar, React ops console, Telegram companion) that investigates Spectre incidents and CI pipeline failures, produces citation-verified RCAs and runbooks, and publishes only through human approval gates.

**Architecture:** One durable LangGraph `StateGraph` per case (library mode inside FastAPI, AsyncPostgresSaver checkpoints), deterministic routing, thin evidence workers delegating to a HolmesGPT sidecar over `/api/chat`, Postgres as the case store, SSE streaming to a React console, Telegram long polling for notify + approve. Every external dependency (models, evidence engine, channel, observability) sits behind a swappable adapter.

**Tech Stack:** Python 3.12, uv, FastAPI, LangGraph 1.x, langgraph-checkpoint-postgres, SQLAlchemy 2 async + Alembic, pgvector, sse-starlette, httpx, HolmesGPT (pinned image), React 18 + Vite + TypeScript + TanStack Query, Vitest + Testing Library, Playwright, pytest + testcontainers, Grafana Cloud APIs, Telegram Bot API, GitHub/GitLab REST APIs, Vertex AI (Gemini + Claude), LangSmith (env-gated).

## Source documents

- Spec (approved v1.3): `agentic-sre-team/docs/superpowers/specs/2026-07-11-agentic-sre-team-design.md`
- Wireframes (approved): `agentic-sre-team/docs/design/wireframes-v1.html`
- Handoff: `agentic-sre-team/docs/superpowers/HANDOFF.md`

Do not re-litigate approved decisions (handoff section "Approved decisions").

## Global Constraints

Copied from the spec; every task implicitly includes these.

- LangGraph 1.x runs **as a library inside FastAPI** - no LangGraph Server. One case = one LangGraph thread, checkpointed via AsyncPostgresSaver, resumable across restarts.
- Gateway: Python 3.12, FastAPI, uv. UI: React 18 + Vite + TypeScript, served by nginx.
- Deterministic edges own all routing; LLMs decide only within nodes.
- Model tiers come from `config/models.yaml`: `small`, `medium`, `frontier`. Local profile: small/medium = Gemini 2.5 Flash, frontier = Claude on Vertex. Air-gap = LiteLLM/vLLM via `openai-compatible`. Swapping is a config change only.
- HolmesGPT runs as a **pinned-image sidecar in server mode**; workers call `POST /api/chat` with per-request `model`; `config/holmes.yaml` (in git) is the permission manifest for the evidence layer. All enabled toolsets read-only: prometheus, grafana/loki, grafana/tempo, the grafana MCP server (dashboards, alert rules, datasource exploration), elasticsearch/data + elasticsearch/cluster (OpenSearch-compatible: log search plus cluster health, shard allocation and query latency), docker (read-only socket), github, gitlab, postgres. openshift/core|logs|live-metrics ship `enabled: false` and flip on - as a reviewed git change - for OpenShift-platform targets.
- Agents never execute state-changing actions. The only write in the whole system is the gateway-side publish action that pushes a branch and opens a **draft** MR/PR on gate-2 approval when `scm_draft_mr` is enabled (off by default). No write-capable tool exists in the tool registry.
- Humans approve every published artifact: HITL gate 1 (RCA) and gate 2 (runbook) via `interrupt()` / `Command(resume=...)`, from UI or Telegram.
- Bounded loops: max 2 investigation rounds; exactly one citation-repair loop.
- Budget envelope (tokens, tool calls, wall clock) checked between nodes; breach parks the case `needs-human` and pages Telegram.
- Per-agent YAML permission manifests, default-deny, bound at startup. Append-only audit of every LLM call and tool call.
- Intake normalizes everything to the `Signal` envelope (source, reporter, received_at, payload, fingerprint); noise control = fingerprint dedup, debounce, burst suppression, cross-signature correlation grouping (declarative config, audit-logged).
- Channels: Telegram only in v1, behind a `Channel` adapter interface.
- LangSmith tracing env-gated (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`), off in air-gap.
- Grafana poller default for local (30s interval); webhook path HMAC-verified.
- SUT is Spectre from `~/Code/spectre`, deployed by its own compose file; this repo adds chaos scripts only, plus one small chaos-middleware PR inside the Spectre repo.
- Git: conventional commits (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`), scope `sre-team` in this monorepo. Never add an agent co-author line. Plain dashes only, no em dash, in all authored text.

## Locked implementation decisions (spec-consistent, decided here)

These are implementation-level choices the spec left open. They are decided now so tasks stay consistent; they do not contradict any approved decision.

1. **Postgres image is `pgvector/pgvector:pg16`** (Postgres 16 + pgvector). The spec's `runbooks` and `case_learnings` tables carry embeddings; pgvector is the simplest robust store. Embedding dimension fixed at **768**.
2. **`embeddings` entry added to `models.yaml`** (provider + model + dim). Local: Vertex `gemini-embedding-001` with 768-dim output. Fake profile: deterministic hash embeddings. Air-gap: `openai-compatible` embeddings via LiteLLM.
3. **All gateway LLM calls are prompt-JSON, parsed with Pydantic, with exactly one repair retry** (`call_llm_json`). No provider-native structured output on the gateway side - this keeps the fake model scriptable and the air-gap (vLLM/MiniMax) profile identical. Holmes-side `response_format` is still passed through to `/api/chat` per spec.
4. **API is served under the `/api` prefix** (e.g. `POST /api/webhooks/grafana`, `GET /api/cases`). The spec's paths are kept verbatim relative to that root. Reason: the UI owns browser routes like `/cases`; nginx needs an unambiguous proxy prefix.
5. **`case_events` table** persists every streamed graph event so `GET /api/cases/{id}/stream` can replay after reconnect and across gateway restarts (spec section 5 requires replay).
6. **Extra endpoints beyond the spec's list**, required by the approved wireframes: `POST /api/cases/{id}/park` (Escalate-to-human / Pause-case buttons), `POST /api/cases/{id}/resume` (parked-case Resume), `POST /api/cases/{id}/context` (Add-context-for-the-agents), `GET /api/activity` + `POST /api/activity/annotations` (queue timeline strip), `GET /api/governance/audit` (audit stream), `GET /api/healthz` (intake health for the empty-queue state).
7. **Telegram adapter is a thin httpx client over the Bot API** (getUpdates long polling, sendMessage, inline keyboards, answerCallbackQuery). No python-telegram-bot dependency; full control of the asyncio lifecycle inside FastAPI.
8. **Chat-message incident-likelihood scorer** ships first as a deterministic heuristic behind an interface, upgraded to a small-tier LLM scorer when the model layer lands (Phase 2). The interface (`IncidentScorer`) does not change.
9. **The fake Holmes server and the scripted chat model are the graph-test backbone** (per handoff): both live in the gateway package (`sre_gateway.testing.fake_holmes`, `sre_gateway.llm.scripted`) so tests import them in-process (httpx `ASGITransport`, no sockets) and compose can run them for the `fake` profile.
10. **Case identity**: `cases.id` is a UUID4 string; `display_id` is `CASE-%04d` from a Postgres sequence.
11. **Networking**: this stack joins Spectre's default compose network as external `spectre_default` (Spectre's compose has no explicit `networks:` block, so Docker names it `<project>_default` = `spectre_default`). Only the `holmes` service joins it (it needs `spectre-opensearch`); everything else stays on this stack's own network.
12. **Evidence IDs** (`E1..En`) are allocated per case via an atomic counter column on `cases` so parallel workers never collide. Hypothesis IDs (`H1..Hn`) are owned by triage/synthesize only; workers propose hypotheses through `worker_reports`, never write the board.
13. **Timestamps** are timezone-aware UTC everywhere (`datetime.now(UTC)`).
14. **Migrations**: Alembic, sync driver `psycopg` for migration runs; app runs `asyncpg`.
15. **The SUT is configuration, not code.** Spectre is only the reference target: `config/environment.yaml` describes the environment under management (name, platform, services, container names, repos, notes), and every SUT-specific string in a prompt (triage system prompt, worker scopes) renders from it. Pointing the system at another stack on the same platform family = replacing `environment.yaml` + the holmes.yaml endpoints + `repos.yaml` + `alerts/rules.yaml`; no code changes. The chaos scripts and Grafana alert rules are reference-SUT demo assets, not system dependencies.
16. **Toolset amendment (2026-07-12, user direction; supersedes the spec section 8 literal list):** the evidence layer additionally uses the Grafana MCP server (`mcp_servers.grafana`), `grafana/tempo` (TraceQL search + comparative fast/slow trace sampling for latency), and `elasticsearch/data` + `elasticsearch/cluster` in place of the notional `opensearch` key (Holmes's ES toolsets are OpenSearch-compatible; the cluster toolset is explicitly for cluster-health and query-latency investigation), plus the `openshift/*` family for OpenShift targets. Sources: holmesgpt.dev builtin-toolsets pages for grafana-mcp, grafanatempo, elasticsearch, openshift.

## Execution conventions

- Monorepo branch per phase off `main`: `feat/sre-team-p<N>-<slug>` (one focused PR per phase). The Spectre chaos middleware (Task 46) is its own branch + PR inside `~/Code/spectre` (gitflow: branch from `develop` if present, else `main` - check that repo's CONTRIBUTING.md first).
- All gateway commands run from `agentic-sre-team/gateway/` via `uv run ...`; all UI commands from `agentic-sre-team/ui/`.
- DB-backed tests use testcontainers (needs local Docker - already a project requirement).
- External-API surfaces (HolmesGPT, Grafana provisioning, langchain-google-*, Telegram, GitHub/GitLab) each carry an explicit **docs-check step** in the task that first touches them. Use Context7 (`resolve-library-id` then `query-docs`) or the official docs listed in the task. Do not skip these: the code in this plan encodes best-known API shapes, and the docs-check is where drift gets caught.
- Never commit secrets. `.env` is git-ignored; only `.env.example` is committed.

## Reference docs per surface

| Surface | Where to check at execution time |
|---|---|
| LangGraph 1.x (StateGraph, Send, interrupt, AsyncPostgresSaver, streaming) | Context7 `/langchain-ai/langgraph` |
| HolmesGPT server mode, `/api/chat`, toolsets config, image tags | https://holmesgpt.dev + pinned image's `GET /openapi.json` |
| langchain-google-genai / langchain-google-vertexai | Context7 `/langchain-ai/langchain-google` |
| Grafana alerting + provisioning APIs | https://grafana.com/docs/grafana/latest/developers/http_api/alerting_provisioning/ |
| Telegram Bot API | https://core.telegram.org/bots/api |
| GitHub Actions REST + webhooks | https://docs.github.com/en/rest/actions |
| GitLab pipelines REST + webhooks | https://docs.gitlab.com/ee/api/pipelines.html |
| LangSmith env setup | https://docs.smith.langchain.com |

## File structure

```
agentic-sre-team/
├── Makefile
├── README.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── config/
│   ├── models.yaml            # local profile tiers + embeddings + holmes model strings + pricing
│   ├── models.fake.yaml       # fake profile (scripted model, hash embeddings)
│   ├── budgets.yaml           # per-case envelope (tokens, tool calls, wall clock)
│   ├── grouping.yaml          # correlation grouping rules
│   ├── environment.yaml       # target-environment descriptor (Spectre = reference SUT)
│   ├── holmes.yaml            # HolmesGPT toolset manifest (evidence-layer permissions)
│   ├── repos.yaml             # watched SCM repositories
│   ├── alerts/rules.yaml      # Grafana alert rule definitions for provisioning
│   └── agents/                # per-agent permission manifests (default-deny)
│       ├── triage.yaml  workers.yaml  synthesize.yaml  rca.yaml
│       ├── verify.yaml  remediate.yaml  learnings.yaml  chat.yaml
├── gateway/
│   ├── pyproject.toml  .python-version  alembic.ini
│   ├── alembic/ (env.py, versions/)
│   ├── src/sre_gateway/
│   │   ├── __init__.py  settings.py  audit.py  manifests.py  budget.py
│   │   ├── retrieval.py  learnings.py  publish_scm.py
│   │   ├── db/       (engine.py, models.py)
│   │   ├── domain/   (enums.py, signal.py)
│   │   ├── intake/   (grafana.py, noise.py, grouping.py, scorer.py, service.py,
│   │   │              poller_grafana.py, scm_intake.py, poller_scm.py)
│   │   ├── llm/      (factory.py, scripted.py, json_call.py, embeddings.py)
│   │   ├── holmes/   (client.py)
│   │   ├── scm/      (base.py, github.py, gitlab.py)
│   │   ├── channels/ (base.py, log.py, telegram.py)
│   │   ├── chat/     (service.py)
│   │   ├── graph/    (state.py, deps.py, build.py, runner.py, decisions.py,
│   │   │              grafana_links.py, nodes/{triage,plan,workers,synthesize,
│   │   │              rca,verify,gates,remediate,publish,park}.py)
│   │   ├── api/      (app.py, health.py, webhooks.py, cases.py, governance.py,
│   │   │              activity.py, chat.py)
│   │   ├── provision/(__main__.py, grafana.py)
│   │   └── testing/  (fake_holmes.py)
│   └── tests/        (conftest.py, fixtures/, unit + graph + api tests)
├── ui/
│   ├── package.json  vite.config.ts  tsconfig.json  index.html  Dockerfile  nginx.conf
│   ├── src/ (main.tsx, App.tsx, theme.css, api/{client,types,sse}.ts,
│   │         components/*.tsx, screens/{Queue,CaseDetail,Artifact,Governance,Chat}Screen.tsx)
│   └── e2e/ (playwright.config.ts, smoke.spec.ts)
├── scripts/ (smoke.py, chaos.sh, chaos_ci.sh, demo.sh)
└── docs/ (existing spec + wireframes + this plan)
```

Spectre repo (separate PR, Task 46): `~/Code/spectre/admin-server/src/middlewares/chaosMiddleware.ts`, `admin-server/test/middlewares/chaos.test.ts`, one `docker-compose.yml` env line, docs note.

## Phase overview (every phase ends demoable)

| Phase | Tasks | Ships | Demo at phase end |
|---|---|---|---|
| 0 Walking skeleton | 1-2 | gateway package, compose (postgres+gateway), Makefile | `make up` then `curl :8080/api/healthz` returns component statuses |
| 1 Data + intake | 3-8 | schema+migrations, audit, Signal, Grafana webhook, noise control, grouping, case store | `curl` a canned Grafana payload; case JSON + suppression counters visible |
| 2 Model + governance plumbing | 9-12 | ModelFactory, scripted fake model, call_llm_json, manifests, budgets | `uv run pytest` green; fake tier answers a scripted call |
| 3 Case graph on fakes + core API | 13-22 | fake Holmes, full incident graph, gates, SSE, decisions, smoke | `make smoke` drives webhook -> gate 1 -> approve -> gate 2 -> closed |
| 4 Real integrations | 23-26 | Holmes sidecar, Grafana poller, Vertex tiers, LangSmith, Grafana deep links | stop `keycloak` by hand; watch a real investigation reach gate 1 |
| 5 Ops console UI | 27-33 | queue+timeline, case detail 3-pane, artifact review, governance, Playwright smoke | browser walkthrough against the fake profile |
| 6 Telegram | 34-35 | live bot: acks, status, gate buttons, pages, report intake | approve gate 1 from Telegram |
| 7 Pipeline failures | 36-41 | ScmProvider (GitHub+GitLab), pollers/webhooks, ci worker, classification, patch runbooks, draft-MR publish | graph tests for both providers; live seeded failure optional |
| 8 Chat surface | 42-45 | threads API + Holmes relay + promote-to-case + Chat screen | ask "why is Keycloak slow", promote to case in browser |
| 9 Chaos + provisioning + acceptance | 46-50 | Spectre chaos PR, chaos.sh, provision, chaos-ci, demo scripts, README | `make demo` end-to-end incident; `make chaos-ci` DevSecOps loop |

---

## Phase 0 - Walking skeleton

Branch: `feat/sre-team-p0-skeleton`

### Task 1: Gateway package with settings and healthz

**Files:**
- Create: `agentic-sre-team/gateway/pyproject.toml`
- Create: `agentic-sre-team/gateway/.python-version`
- Create: `agentic-sre-team/gateway/src/sre_gateway/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/settings.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/health.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/app.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/main.py`
- Create: `agentic-sre-team/gateway/tests/test_health.py`
- Create: `agentic-sre-team/.gitignore`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `Settings` (pydantic-settings, env prefix `SRE_`), `get_settings() -> Settings`, `create_app(settings: Settings | None = None) -> FastAPI`, `GET /api/healthz -> {"status": "ok", "components": {...}}`. `app.state.health: dict[str, str]` is the mutable component-status registry later tasks write into (`db`, `grafana_poller`, `telegram`, `scm_poller`, `holmes`).

- [ ] **Step 1: Scaffold the project**

```bash
cd agentic-sre-team && mkdir -p gateway/src/sre_gateway/api gateway/tests
cd gateway && echo "3.12" > .python-version
```

Write `gateway/pyproject.toml`:

```toml
[project]
name = "sre-gateway"
version = "0.1.0"
description = "Agentic SRE Team gateway: intake, case graph, API, channels"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "sse-starlette>=2.1",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
    "respx>=0.21",
    "testcontainers[postgres]>=4.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/sre_gateway"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

Write `agentic-sre-team/.gitignore`:

```
.env
__pycache__/
.venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
node_modules/
ui/dist/
ui/test-results/
ui/playwright-report/
```

Run: `uv sync` (from `gateway/`). Expected: lockfile created, deps resolved.

- [ ] **Step 2: Write the failing healthz test**

`gateway/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from sre_gateway.api.app import create_app
from sre_gateway.settings import Settings


def _client() -> TestClient:
    app = create_app(Settings(database_url="postgresql+asyncpg://x:x@localhost:1/x"))
    return TestClient(app)


def test_healthz_ok():
    with _client() as client:
        res = client.get("/api/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "sre-gateway"
    assert isinstance(body["components"], dict)


def test_settings_env_prefix(monkeypatch):
    monkeypatch.setenv("SRE_ENV_NAME", "unit-test")
    s = Settings(database_url="postgresql+asyncpg://x:x@localhost:1/x")
    assert s.env_name == "unit-test"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_health.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sre_gateway.api.app'`

- [ ] **Step 4: Implement settings, app factory, healthz**

`src/sre_gateway/__init__.py`: empty file. `src/sre_gateway/api/__init__.py`: empty file.

`src/sre_gateway/settings.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SRE_", env_file=".env", extra="ignore")

    env_name: str = "local-docker"
    api_port: int = 8080
    database_url: str = "postgresql+asyncpg://sre:sre@localhost:5433/sre"

    config_dir: Path = Path("../config")
    models_profile: str = "local"  # local | airgap | fake

    holmes_url: str = "http://holmes:5050"

    grafana_url: str | None = None
    grafana_sa_token: str | None = None
    grafana_webhook_secret: str | None = None
    grafana_poll_interval_s: int = 30
    grafana_poll_enabled: bool = False

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_allowed_user_ids: list[int] = []

    github_token: str | None = None
    github_webhook_secret: str | None = None
    gitlab_token: str | None = None
    gitlab_webhook_secret: str | None = None
    gitlab_base_url: str = "https://gitlab.com"
    scm_poll_enabled: bool = False
    scm_poll_interval_s: int = 60
    scm_draft_mr: bool = False

    chat_thread_daily_usd_cap: float = 1.00

    @property
    def models_config_path(self) -> Path:
        name = "models.fake.yaml" if self.models_profile == "fake" else "models.yaml"
        return self.config_dir / name


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`src/sre_gateway/api/health.py`:

```python
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    components: dict[str, str] = dict(request.app.state.health)
    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return {"status": status or "ok", "service": "sre-gateway", "components": components}
```

`src/sre_gateway/api/app.py`:

```python
from fastapi import FastAPI

from sre_gateway.api import health
from sre_gateway.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="sre-gateway")
    app.state.settings = settings
    app.state.health = {}
    app.include_router(health.router, prefix="/api")
    return app
```

`src/sre_gateway/main.py`:

```python
import uvicorn

from sre_gateway.api.app import create_app
from sre_gateway.settings import get_settings

app = create_app()

if __name__ == "__main__":
    uvicorn.run("sre_gateway.main:app", host="0.0.0.0", port=get_settings().api_port)
```

- [ ] **Step 5: Run tests and lint, verify pass**

Run: `uv run pytest -q && uv run ruff check .`
Expected: `2 passed`, ruff clean.

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/sre-team-p0-skeleton
git add agentic-sre-team/gateway agentic-sre-team/.gitignore
git commit -m "feat(sre-team): scaffold gateway package with settings and healthz"
```

### Task 2: Compose stack, env template, Makefile

**Files:**
- Create: `agentic-sre-team/docker-compose.yml`
- Create: `agentic-sre-team/.env.example`
- Create: `agentic-sre-team/gateway/Dockerfile`
- Create: `agentic-sre-team/Makefile`

**Interfaces:**
- Consumes: `sre_gateway.main:app` (Task 1).
- Produces: services `postgres` (pgvector/pgvector:pg16, host port 5433) and `gateway` (host port 8080); profile `fake` service `fake-holmes` is added in Task 13, `ui` in Task 27, `holmes` in Task 23, `provision` in Task 48. Make targets `up`, `up-fake`, `down`, `logs`, `ps`, `test`, `lint`, `migrate`.

- [ ] **Step 1: Write the gateway Dockerfile**

`gateway/Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "sre_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Write compose file and env template**

`agentic-sre-team/docker-compose.yml`:

```yaml
name: agentic-sre-team

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: sre-postgres
    environment:
      POSTGRES_DB: sre
      POSTGRES_USER: sre
      POSTGRES_PASSWORD: ${SRE_PG_PASSWORD:-sre}
    ports:
      - "5433:5432"
    volumes:
      - sre-pg:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sre -d sre"]
      interval: 5s
      timeout: 3s
      retries: 20

  gateway:
    build: ./gateway
    container_name: sre-gateway
    env_file: .env
    environment:
      SRE_DATABASE_URL: postgresql+asyncpg://sre:${SRE_PG_PASSWORD:-sre}@postgres:5432/sre
      SRE_CONFIG_DIR: /config
    volumes:
      - ./config:/config:ro
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  sre-pg:
```

`agentic-sre-team/.env.example` (commit this; `.env` never):

```bash
# --- core ---
SRE_ENV_NAME=local-docker
SRE_PG_PASSWORD=sre
SRE_MODELS_PROFILE=local            # local | airgap | fake

# --- models (local profile: Vertex) ---
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=us-east5
# Mount or ADC: path visible inside the gateway container
GOOGLE_APPLICATION_CREDENTIALS=

# --- LangSmith (optional, off by default; never set in air-gap) ---
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=agentic-sre-team

# --- Grafana Cloud ---
SRE_GRAFANA_URL=                    # e.g. https://<stack>.grafana.net
SRE_GRAFANA_SA_TOKEN=
SRE_GRAFANA_WEBHOOK_SECRET=
SRE_GRAFANA_POLL_ENABLED=true
SRE_GRAFANA_POLL_INTERVAL_S=30

# --- HolmesGPT sidecar ---
SRE_HOLMES_URL=http://holmes:5050
HOLMES_IMAGE=                       # pinned image ref, resolved in Task 23

# --- Telegram ---
SRE_TELEGRAM_BOT_TOKEN=
SRE_TELEGRAM_CHAT_ID=
SRE_TELEGRAM_ALLOWED_USER_IDS=[]    # JSON list of telegram user ids allowed to approve

# --- SCM ---
SRE_GITHUB_TOKEN=
SRE_GITHUB_WEBHOOK_SECRET=
SRE_GITLAB_TOKEN=
SRE_GITLAB_WEBHOOK_SECRET=
SRE_SCM_POLL_ENABLED=false
SRE_SCM_DRAFT_MR=false
```

- [ ] **Step 3: Write the Makefile**

`agentic-sre-team/Makefile`:

```makefile
COMPOSE := docker compose

.PHONY: up up-fake down logs ps test lint migrate smoke provision

up:
	$(COMPOSE) up -d --build

up-fake:
	$(COMPOSE) --profile fake up -d --build

down:
	$(COMPOSE) --profile fake down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

test:
	cd gateway && uv run pytest -q

lint:
	cd gateway && uv run ruff check .

migrate:
	cd gateway && uv run alembic upgrade head
```

(`smoke` and `provision` targets are added by Tasks 22 and 48.)

- [ ] **Step 4: Verify the walking skeleton**

```bash
cd agentic-sre-team && cp .env.example .env && make up
curl -s localhost:8080/api/healthz
```

Expected: `{"status":"ok","service":"sre-gateway","components":{}}`. Then `make down`.

- [ ] **Step 5: Commit and open the phase PR**

```bash
git add agentic-sre-team/docker-compose.yml agentic-sre-team/.env.example \
        agentic-sre-team/gateway/Dockerfile agentic-sre-team/Makefile
git commit -m "feat(sre-team): compose stack with postgres and gateway, env template, makefile"
# open PR: feat/sre-team-p0-skeleton -> main, merge before starting phase 1
```

---

## Phase 1 - Data model, audit, intake

Branch: `feat/sre-team-p1-intake`

### Task 3: Schema, migrations, DB engine

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/domain/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/domain/enums.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/db/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/db/engine.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/db/models.py`
- Create: `agentic-sre-team/gateway/alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`
- Create: `agentic-sre-team/gateway/alembic/versions/0001_extensions.py` (hand-written)
- Create: `agentic-sre-team/gateway/alembic/versions/0002_tables.py` (autogenerated, reviewed)
- Create: `agentic-sre-team/gateway/alembic/versions/0003_audit_append_only.py` (hand-written)
- Create: `agentic-sre-team/gateway/tests/conftest.py`
- Create: `agentic-sre-team/gateway/tests/test_migrations.py`

**Interfaces:**
- Consumes: `Settings.database_url` (Task 1).
- Produces: SQLAlchemy 2 models `Case, SignalRow, Hypothesis, EvidenceRow, Artifact, Approval, AuditEvent, Runbook, Repo, CaseLearning, ChatThread, ChatMessage, CaseEvent, Setting` in `sre_gateway.db.models`; `make_engine(url) -> AsyncEngine`; `make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`; `run_migrations(sync_url: str)`; test fixtures `pg_url` (session), `db` (function-scoped `async_sessionmaker` with clean tables).

- [ ] **Step 1: Add dependencies**

```bash
cd agentic-sre-team/gateway
uv add "sqlalchemy[asyncio]>=2.0" "asyncpg>=0.29" "psycopg[binary]>=3.2" "alembic>=1.13" "pgvector>=0.3"
```

- [ ] **Step 2: Write enums and models**

`src/sre_gateway/domain/__init__.py`: empty. `src/sre_gateway/domain/enums.py`:

```python
from enum import StrEnum


class CaseKind(StrEnum):
    incident = "incident"
    pipeline_failure = "pipeline_failure"


class CaseStatus(StrEnum):
    open = "open"                        # graph running or queued
    waiting_approval = "waiting_approval"  # parked at a HITL gate
    needs_human = "needs_human"          # budget breach / provider failure / manual escalate
    closed = "closed"


class SignalSource(StrEnum):
    grafana = "grafana"
    telegram = "telegram"
    chat = "chat"
    github = "github"
    gitlab = "gitlab"
    human_api = "human_api"


class FailureClass(StrEnum):
    code = "code"
    test = "test"
    config = "config"
    dependency = "dependency"
    infra_runner = "infra_runner"
    flaky = "flaky"
    permissions = "permissions"


class ArtifactKind(StrEnum):
    rca = "rca"
    runbook = "runbook"


class Decision(StrEnum):
    approve = "approve"
    approve_with_edits = "approve_with_edits"
    reject = "reject"
```

`src/sre_gateway/db/__init__.py`: empty. `src/sre_gateway/db/models.py`:

```python
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBED_DIM = 768


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_id: Mapped[str] = mapped_column(String(16), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    phase: Mapped[str] = mapped_column(String(32), default="queued")
    title: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[int] = mapped_column(Integer, default=3)
    effort: Mapped[str] = mapped_column(String(8), default="medium")
    round: Mapped[int] = mapped_column(Integer, default=0)
    failure_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(36))
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    spend_usd: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_counter: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    reporter: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(24))
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    labels: Mapped[dict] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    attach_reason: Mapped[str] = mapped_column(String(32), default="opened")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    hid: Mapped[str] = mapped_column(String(8))
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|supported|refuted
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_for: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_against: Mapped[list] = mapped_column(JSONB, default=list)
    round: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_hypotheses_case_hid", "case_id", "hid", unique=True),)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    eid: Mapped[str] = mapped_column(String(8))
    worker: Mapped[str] = mapped_column(String(24))
    toolset: Mapped[str] = mapped_column(String(48))
    invocation: Mapped[str] = mapped_column(Text, default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    hypothesis_links: Mapped[list] = mapped_column(JSONB, default=list)  # [{hid, direction}]
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_evidence_case_eid", "case_id", "eid", unique=True),)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    version: Mapped[int] = mapped_column(Integer, default=1)
    structured: Mapped[dict] = mapped_column(JSONB, default=dict)
    body_md: Mapped[str] = mapped_column(Text, default="")
    body_edited_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str] = mapped_column(String(96), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    gate: Mapped[str] = mapped_column(String(12))  # rca | runbook
    decision: Mapped[str] = mapped_column(String(24))
    decided_by: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(String(12))  # ui | telegram
    annotation: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64))       # node/agent name, "system", or human id
    event_type: Mapped[str] = mapped_column(String(24), index=True)
    # llm_call | tool_call | approval | suppression | intake | publish | pause | budget | chat
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class Runbook(Base):
    __tablename__ = "runbooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    source_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Repo(Base):
    __tablename__ = "repos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(12))  # github | gitlab
    slug: Mapped[str] = mapped_column(String(256))     # owner/name or gitlab project path
    default_branch: Mapped[str] = mapped_column(String(64), default="main")
    # env var name holding this repo's token; empty = the provider-level default token
    credential_env: Mapped[str] = mapped_column(String(64), default="")
    watch: Mapped[bool] = mapped_column(Boolean, default=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    poll_cursor: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_repos_provider_slug", "provider", "slug", unique=True),)


class CaseLearning(Base):
    __tablename__ = "case_learnings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    signal_signature: Mapped[str] = mapped_column(Text)
    confirmed_root_cause: Mapped[str] = mapped_column(Text)
    decisive_queries: Mapped[list] = mapped_column(JSONB, default=list)
    false_leads: Mapped[list] = mapped_column(JSONB, default=list)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatThread(Base):
    __tablename__ = "chat_threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(Text, default="")
    context_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    promoted_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    budget_date: Mapped[str] = mapped_column(String(10), default="")
    spend_usd_today: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(ForeignKey("chat_threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    tool_ledger: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseEvent(Base):
    __tablename__ = "case_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_case_events_case_seq", "case_id", "seq", unique=True),)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

`src/sre_gateway/db/engine.py`:

```python
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 3: Alembic setup**

```bash
cd agentic-sre-team/gateway && uv run alembic init alembic
```

Replace `alembic/env.py` body so it reads the URL from `SRE_DATABASE_URL` (converted to the sync psycopg driver) and targets our metadata:

```python
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from sre_gateway.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get(
        "SRE_DATABASE_URL", "postgresql+asyncpg://sre:sre@localhost:5433/sre"
    )
    return url.replace("+asyncpg", "+psycopg")


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Hand-write `alembic/versions/0001_extensions.py`:

```python
"""pgvector extension and case display sequence"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SEQUENCE IF NOT EXISTS case_display_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS case_display_seq")
```

Generate `0002_tables.py` with the DB from compose running (`make up` first, or a throwaway container):

```bash
SRE_DATABASE_URL=postgresql+asyncpg://sre:sre@localhost:5433/sre uv run alembic upgrade head
SRE_DATABASE_URL=postgresql+asyncpg://sre:sre@localhost:5433/sre uv run alembic revision --autogenerate -m "tables"
```

Review the generated file: it must create all 14 tables and the three unique indexes; edit `revision = "0002"`, `down_revision = "0001"` for readable ids. Hand-write `alembic/versions/0003_audit_append_only.py`:

```python
"""audit_events is append-only: trigger rejects UPDATE and DELETE"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_no_rewrite
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_rewrite ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only")
```

- [ ] **Step 4: Write conftest with testcontainers fixtures and the failing migration test**

`gateway/tests/conftest.py`:

```python
import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from sre_gateway.db.engine import make_engine, make_sessionmaker
from sre_gateway.db.models import Base


def run_migrations(sync_url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    import os

    os.environ["SRE_DATABASE_URL"] = sync_url.replace("+psycopg", "+asyncpg")
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_url() -> str:
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        sync_url = pg.get_connection_url()
        run_migrations(sync_url)
        yield sync_url.replace("+psycopg", "+asyncpg")


@pytest.fixture
async def db(pg_url):
    engine = make_engine(pg_url)
    async with engine.begin() as conn:
        # settings table is preserved config-free; wipe every domain table between tests
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE case_display_seq RESTART WITH 1"))
    yield make_sessionmaker(engine)
    await engine.dispose()
```

Note: `TRUNCATE` is not blocked by the audit trigger (the trigger is row-level); this is fine for tests only - production code never deletes audit rows.

`gateway/tests/test_migrations.py`:

```python
import pytest
from sqlalchemy import text

from sre_gateway.db.models import AuditEvent


async def test_all_tables_exist(db):
    async with db() as session:
        res = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )
        names = {r[0] for r in res}
    expected = {
        "cases", "signals", "hypotheses", "evidence", "artifacts", "approvals",
        "audit_events", "runbooks", "repos", "case_learnings", "chat_threads",
        "chat_messages", "case_events", "settings",
    }
    assert expected <= names


async def test_audit_is_append_only(db):
    async with db() as session:
        session.add(AuditEvent(actor="system", event_type="intake", payload={}))
        await session.commit()
        with pytest.raises(Exception, match="append-only"):
            await session.execute(text("UPDATE audit_events SET actor='x'"))
            await session.commit()
```

- [ ] **Step 5: Run tests to verify they fail, then pass**

Run: `uv run pytest tests/test_migrations.py -q`
Expected first: FAIL (missing migration files / import errors) while steps above are incomplete; after completing steps 2-3: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/sre-team-p1-intake
git add gateway/src/sre_gateway/domain gateway/src/sre_gateway/db gateway/alembic* gateway/tests gateway/pyproject.toml gateway/uv.lock
git commit -m "feat(sre-team): case-store schema, alembic migrations, append-only audit trigger"
```

### Task 4: Audit writer, settings flags, pause switch

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/audit.py`
- Create: `agentic-sre-team/gateway/tests/test_audit.py`

**Interfaces:**
- Consumes: `db.models.AuditEvent`, `db.models.Setting`, `db.models.Case`.
- Produces:
  - `AuditWriter(sessionmaker)` with `async log(event_type: str, actor: str, case_id: str | None = None, **payload) -> None` and `async log_llm(case_id, node, model_id, tokens_in, tokens_out, cost_usd, latency_ms, prompt_hash, response_hash)` which also increments the case's `tokens_in/tokens_out/spend_usd` counters, and `async log_tool(case_id, worker, toolset, invocation, latency_ms)` which increments `cases.tool_calls`.
  - `async get_flag(sessionmaker, key: str, default: bool = False) -> bool` / `async set_flag(sessionmaker, key: str, value: bool, actor: str, audit: AuditWriter)` (used for `paused`).

- [ ] **Step 1: Write the failing test**

`gateway/tests/test_audit.py`:

```python
from sqlalchemy import select

from sre_gateway.audit import AuditWriter, get_flag, set_flag
from sre_gateway.db.models import AuditEvent, Case


async def _mk_case(db) -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="fp", thread_id="t1")
        s.add(c)
        await s.commit()
        return c.id


async def test_log_llm_increments_case_counters(db):
    case_id = await _mk_case(db)
    audit = AuditWriter(db)
    await audit.log_llm(case_id, node="triage", model_id="fake", tokens_in=100,
                        tokens_out=20, cost_usd=0.01, latency_ms=5,
                        prompt_hash="a", response_hash="b")
    async with db() as s:
        case = await s.get(Case, case_id)
        events = (await s.execute(select(AuditEvent))).scalars().all()
    assert case.tokens_in == 100 and case.tokens_out == 20
    assert round(case.spend_usd, 4) == 0.01
    assert events[0].event_type == "llm_call" and events[0].actor == "triage"


async def test_pause_flag_roundtrip_and_audited(db):
    audit = AuditWriter(db)
    assert await get_flag(db, "paused") is False
    await set_flag(db, "paused", True, actor="alex", audit=audit)
    assert await get_flag(db, "paused") is True
    async with db() as s:
        events = (await s.execute(select(AuditEvent))).scalars().all()
    assert any(e.event_type == "pause" for e in events)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_audit.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sre_gateway.audit'`

- [ ] **Step 3: Implement**

`src/sre_gateway/audit.py`:

```python
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.db.models import AuditEvent, Case, Setting


class AuditWriter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def log(self, event_type: str, actor: str, case_id: str | None = None, **payload) -> None:
        async with self._sm() as s:
            s.add(AuditEvent(event_type=event_type, actor=actor, case_id=case_id, payload=payload))
            await s.commit()

    async def log_llm(self, case_id: str | None, *, node: str, model_id: str, tokens_in: int,
                      tokens_out: int, cost_usd: float, latency_ms: int,
                      prompt_hash: str, response_hash: str) -> None:
        async with self._sm() as s:
            s.add(AuditEvent(event_type="llm_call", actor=node, case_id=case_id, payload={
                "model_id": model_id, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": cost_usd, "latency_ms": latency_ms,
                "prompt_hash": prompt_hash, "response_hash": response_hash,
            }))
            if case_id:
                await s.execute(update(Case).where(Case.id == case_id).values(
                    tokens_in=Case.tokens_in + tokens_in,
                    tokens_out=Case.tokens_out + tokens_out,
                    spend_usd=Case.spend_usd + cost_usd,
                ))
            await s.commit()

    async def log_tool(self, case_id: str | None, *, worker: str, toolset: str,
                       invocation: str, latency_ms: int = 0) -> None:
        async with self._sm() as s:
            s.add(AuditEvent(event_type="tool_call", actor=worker, case_id=case_id, payload={
                "toolset": toolset, "invocation": invocation[:2000], "latency_ms": latency_ms,
            }))
            if case_id:
                await s.execute(update(Case).where(Case.id == case_id)
                                .values(tool_calls=Case.tool_calls + 1))
            await s.commit()


async def get_flag(sm: async_sessionmaker[AsyncSession], key: str, default: bool = False) -> bool:
    async with sm() as s:
        row = await s.get(Setting, key)
        return bool(row.value.get("enabled", default)) if row else default


async def set_flag(sm: async_sessionmaker[AsyncSession], key: str, value: bool,
                   actor: str, audit: AuditWriter) -> None:
    async with sm() as s:
        row = await s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value={"enabled": value}))
        else:
            row.value = {"enabled": value}
        await s.commit()
    await audit.log("pause", actor=actor, key=key, enabled=value)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_audit.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add gateway/src/sre_gateway/audit.py gateway/tests/test_audit.py
git commit -m "feat(sre-team): audit writer with case counters and audited pause flag"
```

### Task 5: Signal envelope, Grafana webhook normalizer, HMAC verification

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/domain/signal.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/grafana.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/grafana_webhook.json`
- Create: `agentic-sre-team/gateway/tests/test_intake_grafana.py`

**Interfaces:**
- Consumes: `domain.enums`.
- Produces:
  - `Signal` (pydantic): `source: SignalSource, reporter: str, kind: CaseKind, fingerprint: str, summary: str, labels: dict[str, str], payload: dict, received_at: datetime`.
  - `normalize_grafana(payload: dict) -> list[Signal]` (one Signal per firing alert in the webhook body).
  - `verify_grafana_hmac(secret: str, body: bytes, signature_header: str | None) -> bool` (HMAC-SHA256 hex compare, constant-time).

- [ ] **Step 1: Write the golden fixture**

`gateway/tests/fixtures/grafana_webhook.json` (standard Grafana alerting webhook shape):

```json
{
  "receiver": "sre-gateway",
  "status": "firing",
  "orgId": 1,
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "AdminServerHighErrorRate",
        "service": "admin-server",
        "component": "api",
        "severity": "sev2"
      },
      "annotations": {
        "summary": "Error rate spike on admin-server /api/v1/users",
        "description": "5xx ratio above 5% for 2m"
      },
      "startsAt": "2026-07-11T14:02:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "https://example.grafana.net/alerting/grafana/x/view",
      "fingerprint": "c4a2f1d9e8b7a3f0"
    }
  ],
  "groupLabels": {"alertname": "AdminServerHighErrorRate"},
  "commonLabels": {"alertname": "AdminServerHighErrorRate", "service": "admin-server"},
  "commonAnnotations": {},
  "externalURL": "https://example.grafana.net/",
  "version": "1",
  "groupKey": "{}:{alertname=\"AdminServerHighErrorRate\"}",
  "title": "[FIRING:1] AdminServerHighErrorRate",
  "state": "alerting",
  "message": ""
}
```

- [ ] **Step 2: Write the failing tests**

`gateway/tests/test_intake_grafana.py`:

```python
import hashlib
import hmac
import json
from pathlib import Path

from sre_gateway.intake.grafana import normalize_grafana, verify_grafana_hmac

FIXTURE = json.loads((Path(__file__).parent / "fixtures/grafana_webhook.json").read_text())


def test_normalize_produces_one_signal_per_firing_alert():
    signals = normalize_grafana(FIXTURE)
    assert len(signals) == 1
    s = signals[0]
    assert s.source == "grafana"
    assert s.kind == "incident"
    assert s.fingerprint == "grafana:c4a2f1d9e8b7a3f0"
    assert s.summary == "Error rate spike on admin-server /api/v1/users"
    assert s.labels["service"] == "admin-server"
    assert s.payload["generatorURL"].startswith("https://")


def test_resolved_alerts_are_skipped():
    payload = dict(FIXTURE)
    payload["alerts"] = [dict(FIXTURE["alerts"][0], status="resolved")]
    assert normalize_grafana(payload) == []


def test_hmac_verify_roundtrip():
    body = b'{"x":1}'
    sig = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert verify_grafana_hmac("topsecret", body, sig) is True
    assert verify_grafana_hmac("topsecret", body, "deadbeef") is False
    assert verify_grafana_hmac("topsecret", body, None) is False
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_intake_grafana.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sre_gateway.intake'`

- [ ] **Step 4: Implement**

`src/sre_gateway/domain/signal.py`:

```python
import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from sre_gateway.domain.enums import CaseKind, SignalSource


class Signal(BaseModel):
    source: SignalSource
    reporter: str = ""
    kind: CaseKind = CaseKind.incident
    fingerprint: str
    summary: str
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def fingerprint_of(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
```

`src/sre_gateway/intake/__init__.py`: empty. `src/sre_gateway/intake/grafana.py`:

```python
import hashlib
import hmac

from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal, fingerprint_of

# Grafana 11.x signs webhook bodies with HMAC-SHA256 in this header when an
# HMAC secret is configured on the contact point. Docs-check happens in Task 48
# when the contact point is provisioned; header name is config below.
SIGNATURE_HEADER = "X-Grafana-Alerting-Signature"


def verify_grafana_hmac(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # header may arrive as "t=...,v1=<hex>" or bare hex; accept the trailing token
    candidate = signature_header.split("=")[-1].strip()
    return hmac.compare_digest(expected, candidate)


def normalize_grafana(payload: dict) -> list[Signal]:
    signals: list[Signal] = []
    for alert in payload.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        labels = dict(alert.get("labels", {}))
        annotations = alert.get("annotations", {})
        fp = alert.get("fingerprint") or fingerprint_of(
            labels.get("alertname", ""), *sorted(f"{k}={v}" for k, v in labels.items())
        )
        signals.append(Signal(
            source=SignalSource.grafana,
            reporter="grafana-alerting",
            kind=CaseKind.incident,
            fingerprint=f"grafana:{fp}",
            summary=annotations.get("summary") or labels.get("alertname", "Grafana alert"),
            labels=labels,
            payload={
                "labels": labels,
                "annotations": annotations,
                "startsAt": alert.get("startsAt"),
                "generatorURL": alert.get("generatorURL"),
                "groupKey": payload.get("groupKey"),
            },
        ))
    return signals
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_intake_grafana.py -q`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add gateway/src/sre_gateway/domain/signal.py gateway/src/sre_gateway/intake gateway/tests
git commit -m "feat(sre-team): signal envelope and grafana webhook normalizer with hmac verify"
```

### Task 6: Noise control - dedup, debounce, burst suppression

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/noise.py`
- Create: `agentic-sre-team/gateway/tests/test_noise.py`

**Interfaces:**
- Consumes: `Signal`, `db.models.Case/SignalRow`, `AuditWriter`.
- Produces:
  - `IntakeDecision` dataclass: `action: Literal["open","attach","suppress"]`, `case_id: str | None`, `reason: str` (reasons: `"new"`, `"dedup"`, `"debounce"`, `"burst"`, `"grouped"`, `"low_value_chat"`).
  - `NoiseControl(sessionmaker, audit, dedup_window_s=1800, debounce_s=60, burst_n=5, burst_window_s=60)` with `async decide(signal: Signal) -> IntakeDecision`. Grouping (Task 7) plugs in via constructor arg `grouping: GroupingEngine | None`.

Rules, in order:
1. Open case (`status != closed`) with identical `fingerprint` exists: if the newest signal row with this fingerprint on that case is younger than `debounce_s` -> `suppress/debounce`; else -> `attach/dedup`.
2. Burst labeling: once `burst_n` intake decisions for one fingerprint have occurred within `burst_window_s` (cheap audit-count query), further suppressions are labeled `suppress/burst` instead of `suppress/debounce` - the collapse itself is rule 1; the label feeds the governance counter.
3. Grouping engine (Task 7): different fingerprint, shared label rule within window -> `attach/grouped`.
4. Otherwise `open/new`.

Every `suppress` and every `attach` decision is audit-logged (`event_type="suppression"` / `"intake"`).

- [ ] **Step 1: Write the failing tests**

`gateway/tests/test_noise.py`:

```python
from datetime import UTC, datetime, timedelta

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import NoiseControl


def _sig(fp="grafana:abc", summary="s", labels=None) -> Signal:
    return Signal(source="grafana", fingerprint=fp, summary=summary, labels=labels or {})


async def _open_case(db, fp="grafana:abc", signal_age_s=300) -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint=fp, thread_id="t")
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident", fingerprint=fp,
                        received_at=datetime.now(UTC) - timedelta(seconds=signal_age_s)))
        await s.commit()
        return c.id


async def test_new_fingerprint_opens(db):
    nc = NoiseControl(db, AuditWriter(db))
    d = await nc.decide(_sig())
    assert d.action == "open" and d.reason == "new"


async def test_same_fingerprint_attaches_as_dedup(db):
    case_id = await _open_case(db, signal_age_s=300)
    nc = NoiseControl(db, AuditWriter(db), debounce_s=60)
    d = await nc.decide(_sig())
    assert d.action == "attach" and d.case_id == case_id and d.reason == "dedup"


async def test_rapid_repeat_is_debounced(db):
    await _open_case(db, signal_age_s=5)
    nc = NoiseControl(db, AuditWriter(db), debounce_s=60)
    d = await nc.decide(_sig())
    assert d.action == "suppress" and d.reason == "debounce"


async def test_rapid_burst_is_labeled_burst(db):
    await _open_case(db, signal_age_s=5)
    nc = NoiseControl(db, AuditWriter(db), debounce_s=60, burst_n=3, burst_window_s=60)
    reasons = [(await nc.decide(_sig())).reason for _ in range(4)]
    assert reasons[:2] == ["debounce", "debounce"]  # decisions 1-2: below burst_n
    assert reasons[2:] == ["burst", "burst"]        # from the 3rd decision in the window


async def test_closed_cases_do_not_match(db):
    case_id = await _open_case(db)
    async with db() as s:
        (await s.get(Case, case_id)).status = "closed"
        await s.commit()
    nc = NoiseControl(db, AuditWriter(db))
    d = await nc.decide(_sig())
    assert d.action == "open"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_noise.py -q`
Expected: FAIL with `ModuleNotFoundError` (noise module missing)

- [ ] **Step 3: Implement**

`src/sre_gateway/intake/noise.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import AuditEvent, Case, SignalRow
from sre_gateway.domain.signal import Signal


@dataclass
class IntakeDecision:
    action: Literal["open", "attach", "suppress"]
    case_id: str | None
    reason: str


class GroupingEngine(Protocol):
    async def find_group_match(self, session: AsyncSession, signal: Signal) -> str | None: ...


class NoiseControl:
    def __init__(self, sm: async_sessionmaker[AsyncSession], audit: AuditWriter, *,
                 dedup_window_s: int = 1800, debounce_s: int = 60,
                 burst_n: int = 5, burst_window_s: int = 60,
                 grouping: GroupingEngine | None = None) -> None:
        self._sm = sm
        self._audit = audit
        self.dedup_window_s = dedup_window_s
        self.debounce_s = debounce_s
        self.burst_n = burst_n
        self.burst_window_s = burst_window_s
        self.grouping = grouping

    async def decide(self, signal: Signal) -> IntakeDecision:
        now = datetime.now(UTC)
        async with self._sm() as s:
            open_case = (await s.execute(
                select(Case).where(Case.fingerprint == signal.fingerprint,
                                   Case.status != "closed")
                .order_by(desc(Case.created_at)).limit(1)
            )).scalar_one_or_none()
            if open_case:
                last = (await s.execute(
                    select(SignalRow.received_at)
                    .where(SignalRow.case_id == open_case.id,
                           SignalRow.fingerprint == signal.fingerprint)
                    .order_by(desc(SignalRow.received_at)).limit(1)
                )).scalar_one_or_none()
                if last and now - last < timedelta(seconds=self.debounce_s):
                    prior = (await s.execute(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.ts >= now - timedelta(seconds=self.burst_window_s),
                            AuditEvent.payload["fingerprint"].astext
                            == signal.fingerprint))).scalar_one()
                    reason = "burst" if prior + 1 >= self.burst_n else "debounce"
                    decision = IntakeDecision("suppress", open_case.id, reason)
                else:
                    decision = IntakeDecision("attach", open_case.id, "dedup")
            elif self.grouping and (gid := await self.grouping.find_group_match(s, signal)):
                decision = IntakeDecision("attach", gid, "grouped")
            else:
                decision = IntakeDecision("open", None, "new")

        if decision.action == "suppress":
            await self._audit.log("suppression", actor="noise-control",
                                  case_id=decision.case_id,
                                  fingerprint=signal.fingerprint, reason=decision.reason)
        elif decision.action == "attach":
            await self._audit.log("intake", actor="noise-control", case_id=decision.case_id,
                                  fingerprint=signal.fingerprint, reason=decision.reason)
        return decision
```

Burst labeling: the collapse behavior itself is the dedup/debounce path (first signal opens the case, the rest attach or are suppressed), but once `burst_n` intake decisions for one fingerprint have occurred within `burst_window_s` (counted from the audit trail, which records every intake and suppression decision), further suppressions are labeled `burst` instead of `debounce`. That label is what the governance screen's "burst-suppressed" counter aggregates. Cross-signature collapse is the grouping engine (Task 7).

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_noise.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add gateway/src/sre_gateway/intake/noise.py gateway/tests/test_noise.py
git commit -m "feat(sre-team): noise control with dedup, debounce and audit-logged suppression"
```

### Task 7: Correlation grouping engine

**Files:**
- Create: `agentic-sre-team/config/grouping.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/grouping.py`
- Create: `agentic-sre-team/gateway/tests/test_grouping.py`

**Interfaces:**
- Consumes: `Signal`, `db.models.Case/SignalRow`.
- Produces: `GroupingConfig` (pydantic: `window_seconds: int`, `rules: list[GroupingRule]` where `GroupingRule = {name: str, label_keys: list[str]}`), `load_grouping(path: Path) -> GroupingConfig`, `CorrelationGrouping(config)` implementing `find_group_match(session, signal) -> case_id | None`: an open case matches when one rule's every `label_key` is present with equal values on both the candidate signal and any signal of the case, and that case signal is younger than `window_seconds`. Grouping never crosses case kinds: an incident signal cannot attach to a pipeline-failure case or vice versa, even when they share a `service` label.

- [ ] **Step 1: Write the config**

`config/grouping.yaml`:

```yaml
# Correlation grouping: signals with different fingerprints that share these
# label values within the window attach to the same open case.
# Deterministic; every grouping decision is audit-logged by NoiseControl.
window_seconds: 120
rules:
  - name: same-service
    label_keys: [service]
  - name: same-component
    label_keys: [service, component]
```

- [ ] **Step 2: Write the failing tests**

`gateway/tests/test_grouping.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.grouping import CorrelationGrouping, load_grouping
from sre_gateway.intake.noise import NoiseControl

CONFIG = Path(__file__).parents[2] / "config/grouping.yaml"


def _grouping() -> CorrelationGrouping:
    return CorrelationGrouping(load_grouping(CONFIG))


async def _case_with_signal(db, labels, age_s=30, fp="grafana:kc-down") -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint=fp, thread_id="t")
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident", fingerprint=fp,
                        labels=labels,
                        received_at=datetime.now(UTC) - timedelta(seconds=age_s)))
        await s.commit()
        return c.id


async def test_cross_signature_same_service_groups(db):
    case_id = await _case_with_signal(db, {"service": "keycloak"})
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:5xx-admin",
                               summary="admin-server 5xx", labels={"service": "keycloak"}))
    assert d.action == "attach" and d.case_id == case_id and d.reason == "grouped"


async def test_outside_window_opens_new_case(db):
    await _case_with_signal(db, {"service": "keycloak"}, age_s=600)
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:5xx-admin",
                               summary="x", labels={"service": "keycloak"}))
    assert d.action == "open"


async def test_missing_label_never_groups(db):
    await _case_with_signal(db, {"service": "keycloak"})
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:other",
                               summary="x", labels={}))
    assert d.action == "open"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_grouping.py -q`
Expected: FAIL with `ModuleNotFoundError` (grouping module missing)

- [ ] **Step 4: Implement**

`src/sre_gateway/intake/grouping.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal


class GroupingRule(BaseModel):
    name: str
    label_keys: list[str]


class GroupingConfig(BaseModel):
    window_seconds: int = 120
    rules: list[GroupingRule] = []


def load_grouping(path: Path) -> GroupingConfig:
    return GroupingConfig.model_validate(yaml.safe_load(path.read_text()) or {})


class CorrelationGrouping:
    def __init__(self, config: GroupingConfig) -> None:
        self.config = config

    async def find_group_match(self, session: AsyncSession, signal: Signal) -> str | None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.config.window_seconds)
        for rule in self.config.rules:
            values = {k: signal.labels.get(k) for k in rule.label_keys}
            if any(v is None for v in values.values()):
                continue
            recent = (await session.execute(
                select(SignalRow).join(Case, Case.id == SignalRow.case_id)
                .where(Case.status != "closed",
                       SignalRow.kind == signal.kind.value,  # never group across case kinds
                       SignalRow.received_at >= cutoff)
                .order_by(desc(SignalRow.received_at)).limit(200)
            )).scalars().all()
            for row in recent:
                if all(row.labels.get(k) == v for k, v in values.items()):
                    return row.case_id
        return None
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_grouping.py -q`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add config/grouping.yaml gateway/src/sre_gateway/intake/grouping.py gateway/tests/test_grouping.py
git commit -m "feat(sre-team): declarative cross-signature correlation grouping"
```

### Task 8: Intake service, webhook endpoint, minimal case API

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/scorer.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/service.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/webhooks.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/cases.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/app.py`
- Create: `agentic-sre-team/gateway/tests/test_intake_service.py`
- Create: `agentic-sre-team/gateway/tests/test_api_intake.py`

**Interfaces:**
- Consumes: everything from Tasks 3-7.
- Produces:
  - `IncidentScorer` protocol with `score(text: str) -> float` (0..1) and `HeuristicScorer` (keyword-based, threshold 0.3); the LLM scorer replaces the heuristic in Task 34 without changing the interface.
  - `IntakeService(sessionmaker, audit, noise, on_case_opened: Callable[[str], Awaitable[None]] | None)` with `async ingest(signal: Signal) -> IngestResult(action, case_id, display_id)`. Opening a case allocates `display_id` from `case_display_seq`, creates the `Case` + primary `SignalRow`, generates `thread_id = case id`, audits `intake`, and awaits `on_case_opened(case_id)` (the graph runner hook, wired in Task 22 - `None` until then). Attach writes an additional `SignalRow` with `attach_reason`. Suppress writes nothing but audit (already logged by NoiseControl); returns `case_id=None`.
  - When the global `paused` flag is set, `ingest` suppresses everything with reason `"paused"` (audited).
  - `POST /api/webhooks/grafana`: raw body, verifies HMAC when `grafana_webhook_secret` set (401 on failure), normalizes, ingests each signal, returns `{results: [{action, case_id, display_id}]}`.
  - `GET /api/cases?status=&limit=` and `GET /api/cases/{id}` returning the case row plus its signals (hypotheses/evidence/artifacts join added in Task 22).
  - `app.state.deps`-style wiring: `create_app` now builds engine/sessionmaker/audit/noise/intake on startup via lifespan, exposes `app.state.intake`, and sets `app.state.health["db"]`.

- [ ] **Step 1: Write the failing service tests**

`gateway/tests/test_intake_service.py`:

```python
from sqlalchemy import select

from sre_gateway.audit import AuditWriter, set_flag
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.service import IntakeService


def _svc(db, opened):
    audit = AuditWriter(db)

    async def on_opened(case_id: str) -> None:
        opened.append(case_id)

    return IntakeService(db, audit, NoiseControl(db, audit), on_case_opened=on_opened)


async def test_open_creates_case_signal_and_display_id(db):
    opened: list[str] = []
    svc = _svc(db, opened)
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:a", summary="s1"))
    assert res.action == "open" and res.display_id == "CASE-0001"
    assert opened == [res.case_id]
    async with db() as s:
        case = await s.get(Case, res.case_id)
        sigs = (await s.execute(select(SignalRow))).scalars().all()
    assert case.title == "s1" and case.thread_id == case.id
    assert len(sigs) == 1 and sigs[0].is_primary


async def test_attach_adds_signal_row_without_new_case(db):
    opened: list[str] = []
    svc = _svc(db, opened)
    first = await svc.ingest(Signal(source="grafana", fingerprint="grafana:a", summary="s1"))
    # age the first signal past debounce
    async with db() as s:
        row = (await s.execute(select(SignalRow))).scalars().one()
        from datetime import UTC, datetime, timedelta
        row.received_at = datetime.now(UTC) - timedelta(seconds=300)
        await s.commit()
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:a", summary="s2"))
    assert res.action == "attach" and res.case_id == first.case_id
    assert len(opened) == 1


async def test_paused_suppresses_everything(db):
    opened: list[str] = []
    svc = _svc(db, opened)
    await set_flag(db, "paused", True, actor="t", audit=AuditWriter(db))
    res = await svc.ingest(Signal(source="grafana", fingerprint="grafana:z", summary="s"))
    assert res.action == "suppress" and opened == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_intake_service.py -q`
Expected: FAIL with `ModuleNotFoundError` (service module missing)

- [ ] **Step 3: Implement scorer and service**

`src/sre_gateway/intake/scorer.py`:

```python
from typing import Protocol

INCIDENT_WORDS = (
    "down", "error", "fail", "slow", "latency", "timeout", "5xx", "500", "crash",
    "outage", "unavailable", "broken", "degraded", "cannot", "can't", "spike",
)


class IncidentScorer(Protocol):
    async def score(self, text: str) -> float: ...


class HeuristicScorer:
    async def score(self, text: str) -> float:
        t = text.lower()
        hits = sum(1 for w in INCIDENT_WORDS if w in t)
        return min(1.0, 0.25 * hits)


INCIDENT_THRESHOLD = 0.3
```

`src/sre_gateway/intake/service.py`:

```python
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.audit import AuditWriter, get_flag
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.noise import IntakeDecision, NoiseControl


@dataclass
class IngestResult:
    action: str
    case_id: str | None
    display_id: str | None


class IntakeService:
    def __init__(self, sm: async_sessionmaker[AsyncSession], audit: AuditWriter,
                 noise: NoiseControl,
                 on_case_opened: Callable[[str], Awaitable[None]] | None = None) -> None:
        self._sm = sm
        self._audit = audit
        self._noise = noise
        self.on_case_opened = on_case_opened

    async def ingest(self, signal: Signal) -> IngestResult:
        if await get_flag(self._sm, "paused"):
            await self._audit.log("suppression", actor="noise-control",
                                  fingerprint=signal.fingerprint, reason="paused")
            return IngestResult("suppress", None, None)

        decision: IntakeDecision = await self._noise.decide(signal)
        if decision.action == "suppress":
            return IngestResult("suppress", decision.case_id, None)
        if decision.action == "attach":
            async with self._sm() as s:
                s.add(self._row(signal, decision.case_id, primary=False,
                                reason=decision.reason))
                await s.commit()
            return IngestResult("attach", decision.case_id, None)

        async with self._sm() as s:
            seq = (await s.execute(text("SELECT nextval('case_display_seq')"))).scalar_one()
            case = Case(display_id=f"CASE-{seq:04d}", kind=signal.kind.value,
                        title=signal.summary, fingerprint=signal.fingerprint, thread_id="")
            case.thread_id = case.id
            s.add(case)
            await s.flush()
            s.add(self._row(signal, case.id, primary=True, reason="opened"))
            await s.commit()
            case_id, display_id = case.id, case.display_id
        await self._audit.log("intake", actor="intake", case_id=case_id,
                              fingerprint=signal.fingerprint, reason="opened",
                              source=signal.source.value)
        if self.on_case_opened is not None:
            await self.on_case_opened(case_id)
        return IngestResult("open", case_id, display_id)

    @staticmethod
    def _row(signal: Signal, case_id: str, *, primary: bool, reason: str) -> SignalRow:
        return SignalRow(case_id=case_id, source=signal.source.value,
                         reporter=signal.reporter, kind=signal.kind.value,
                         fingerprint=signal.fingerprint, summary=signal.summary,
                         labels=signal.labels, payload=signal.payload,
                         is_primary=primary, attach_reason=reason,
                         received_at=signal.received_at)
```

- [ ] **Step 4: Run service tests, verify pass**

Run: `uv run pytest tests/test_intake_service.py -q`
Expected: `3 passed`

- [ ] **Step 5: Write the failing API tests**

`gateway/tests/test_api_intake.py`:

```python
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from sre_gateway.api.app import create_app
from sre_gateway.settings import Settings

FIXTURE = (Path(__file__).parent / "fixtures/grafana_webhook.json").read_text()


@pytest.fixture
async def client(pg_url):
    settings = Settings(database_url=pg_url, grafana_webhook_secret="topsecret",
                        config_dir=Path(__file__).parents[2] / "config")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


def _sig(body: str) -> str:
    return hmac.new(b"topsecret", body.encode(), hashlib.sha256).hexdigest()


async def test_webhook_rejects_bad_signature(client):
    res = await client.post("/api/webhooks/grafana", content=FIXTURE,
                            headers={"X-Grafana-Alerting-Signature": "bad"})
    assert res.status_code == 401


async def test_webhook_opens_case_and_case_api_reads_it(client, db):
    res = await client.post("/api/webhooks/grafana", content=FIXTURE,
                            headers={"X-Grafana-Alerting-Signature": _sig(FIXTURE)})
    assert res.status_code == 200
    result = res.json()["results"][0]
    assert result["action"] == "open" and result["display_id"] == "CASE-0001"

    listed = (await client.get("/api/cases")).json()
    assert listed["cases"][0]["display_id"] == "CASE-0001"

    detail = (await client.get(f"/api/cases/{result['case_id']}")).json()
    assert detail["case"]["title"].startswith("Error rate spike")
    assert len(detail["signals"]) == 1
```

Note: `client` uses the same `pg_url` container; the `db` fixture's truncate keeps tests isolated.

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_api_intake.py -q`
Expected: FAIL with 404s / missing router imports.

- [ ] **Step 7: Implement webhook + case routes and lifespan wiring**

`src/sre_gateway/api/webhooks.py`:

```python
from fastapi import APIRouter, HTTPException, Request

from sre_gateway.intake.grafana import SIGNATURE_HEADER, normalize_grafana, verify_grafana_hmac

router = APIRouter()


@router.post("/webhooks/grafana")
async def grafana_webhook(request: Request) -> dict:
    body = await request.body()
    settings = request.app.state.settings
    if settings.grafana_webhook_secret:
        if not verify_grafana_hmac(settings.grafana_webhook_secret, body,
                                   request.headers.get(SIGNATURE_HEADER)):
            raise HTTPException(status_code=401, detail="bad signature")
    import json

    payload = json.loads(body)
    results = []
    for signal in normalize_grafana(payload):
        res = await request.app.state.intake.ingest(signal)
        results.append({"action": res.action, "case_id": res.case_id,
                        "display_id": res.display_id})
    return {"results": results}
```

`src/sre_gateway/api/cases.py` (minimal read model; extended in Task 22):

```python
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, select

from sre_gateway.db.models import Case, SignalRow

router = APIRouter()


def case_json(c: Case) -> dict:
    return {
        "id": c.id, "display_id": c.display_id, "kind": c.kind, "status": c.status,
        "phase": c.phase, "title": c.title, "severity": c.severity, "effort": c.effort,
        "round": c.round, "failure_class": c.failure_class, "spend_usd": round(c.spend_usd, 4),
        "tokens_in": c.tokens_in, "tokens_out": c.tokens_out, "tool_calls": c.tool_calls,
        "halt_reason": c.halt_reason,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
    }


@router.get("/cases")
async def list_cases(request: Request, status: str | None = None, limit: int = 100) -> dict:
    async with request.app.state.sessionmaker() as s:
        q = select(Case).order_by(desc(Case.created_at)).limit(limit)
        if status:
            q = q.where(Case.status == status)
        cases = (await s.execute(q)).scalars().all()
    return {"cases": [case_json(c) for c in cases]}


@router.get("/cases/{case_id}")
async def get_case(request: Request, case_id: str) -> dict:
    async with request.app.state.sessionmaker() as s:
        case = await s.get(Case, case_id)
        if case is None:
            raise HTTPException(404)
        signals = (await s.execute(
            select(SignalRow).where(SignalRow.case_id == case_id)
            .order_by(SignalRow.received_at)
        )).scalars().all()
    return {"case": case_json(case), "signals": [
        {"id": x.id, "source": x.source, "reporter": x.reporter, "summary": x.summary,
         "fingerprint": x.fingerprint, "labels": x.labels, "is_primary": x.is_primary,
         "attach_reason": x.attach_reason, "received_at": x.received_at.isoformat()}
        for x in signals
    ]}
```

Update `src/sre_gateway/api/app.py`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sre_gateway.api import cases, health, webhooks
from sre_gateway.audit import AuditWriter
from sre_gateway.db.engine import make_engine, make_sessionmaker
from sre_gateway.intake.grouping import CorrelationGrouping, load_grouping
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.service import IntakeService
from sre_gateway.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.audit = AuditWriter(app.state.sessionmaker)
        grouping = CorrelationGrouping(load_grouping(settings.config_dir / "grouping.yaml"))
        noise = NoiseControl(app.state.sessionmaker, app.state.audit, grouping=grouping)
        app.state.intake = IntakeService(app.state.sessionmaker, app.state.audit, noise)
        app.state.health["db"] = "ok"
        yield
        await engine.dispose()

    app = FastAPI(title="sre-gateway", lifespan=lifespan)
    app.state.settings = settings
    app.state.health = {}
    app.include_router(health.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    return app
```

Also update `tests/test_health.py`'s `_client` to pass `database_url=pg_url`? No - keep healthz test DB-free by making it a plain unit check: change `_client()` to build the app but assert against a stubbed lifespan is overkill. Instead move the two healthz assertions into `test_api_intake.py` style using the `client` fixture, and delete the standalone TestClient usage if it now fails on lifespan DB connection. Simplest: `test_health.py` keeps `test_settings_env_prefix` and gains `async def test_healthz_ok(client)` using the shared fixture (move the `client` fixture into `conftest.py` so both files use it).

- [ ] **Step 8: Run the full suite and the live demo**

Run: `uv run pytest -q`
Expected: all pass.

Live check (migrations must run before first boot):

```bash
cd agentic-sre-team && make up && make migrate
BODY=$(cat gateway/tests/fixtures/grafana_webhook.json)
SIG=$(python3 -c "import hmac,hashlib,sys;print(hmac.new(b'topsecret',sys.stdin.buffer.read(),hashlib.sha256).hexdigest())" <<< "$BODY")
curl -s -X POST localhost:8080/api/webhooks/grafana -H "X-Grafana-Alerting-Signature: $SIG" -d "$BODY" | python3 -m json.tool
curl -s localhost:8080/api/cases | python3 -m json.tool
```

Expected: first curl returns `action: open, display_id: CASE-0001`; second lists the case. (Set `SRE_GRAFANA_WEBHOOK_SECRET=topsecret` in `.env` for this check.)

- [ ] **Step 9: Commit and open the phase PR**

```bash
git add gateway/src/sre_gateway gateway/tests
git commit -m "feat(sre-team): intake service, grafana webhook endpoint, minimal case api"
# PR: feat/sre-team-p1-intake -> main
```

---

## Phase 2 - Model provider layer, manifests, budgets

Branch: `feat/sre-team-p2-models-governance`

### Task 9: models.yaml profiles and ModelFactory

**Files:**
- Create: `agentic-sre-team/config/models.yaml`
- Create: `agentic-sre-team/config/models.fake.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/llm/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/llm/embeddings.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/llm/factory.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/settings.py` (add `fake_script_dir`)
- Create: `agentic-sre-team/gateway/tests/test_model_factory.py`

**Interfaces:**
- Consumes: `Settings.models_config_path` (Task 1), `ScriptedChatModel` (Task 10 - factory imports it lazily; write factory now, its fake path is exercised after Task 10; run the fake-provider test at the end of Task 10).
- Produces:
  - `ModelsConfig` (pydantic): `tiers: dict[str, TierConfig]`, `embeddings: EmbeddingsConfig`, `holmes: dict[str, str]`, `pricing: dict[str, dict]`, `vertex: dict`, `script_dir: str | None`.
  - `TierConfig`: `provider: Literal["vertex-gemini","vertex-anthropic","openai-compatible","fake"]`, `model: str`, `params: dict`, `base_url: str | None`, `api_key_env: str`.
  - `load_models_config(path: Path) -> ModelsConfig` (expands `${ENV_VARS}`).
  - `ModelFactory(config, script_dir: Path | None = None)` with `chat(tier: str, node: str) -> BaseChatModel`, `describe(tier) -> tuple[str, tuple[float, float]]` (model id + usd-per-1M-token input/output prices), `holmes_model(tier) -> str`, `async embed(texts: list[str]) -> list[list[float]]`.
  - `hash_embedding(text: str, dim: int = 768) -> list[float]` (deterministic token-overlap-aware unit vector, fake profile - shared tokens produce genuinely closer vectors so retrieval ordering is meaningful, not a coin flip).

- [ ] **Step 1: Add langchain-core dependency**

```bash
cd agentic-sre-team/gateway && uv add "langchain-core>=0.3"
```

(Provider SDKs `langchain-google-genai`, `langchain-google-vertexai`, `langchain-openai` are added in Task 25; the factory imports them lazily so the fake profile never needs them.)

- [ ] **Step 2: Write the config files**

`config/models.yaml`:

```yaml
# Local profile. Swapping providers is a config change only (spec section 7).
tiers:
  small:
    provider: vertex-gemini
    model: gemini-2.5-flash
    params: {temperature: 0}
  medium:
    provider: vertex-gemini
    model: gemini-2.5-flash
    params: {temperature: 0}
  frontier:
    provider: vertex-anthropic
    model: claude-sonnet-4-5@20250929   # verify current Vertex Claude id in Task 25
    params: {temperature: 0.2, max_tokens: 8000}
embeddings:
  provider: vertex          # vertex | openai-compatible | fake
  model: gemini-embedding-001
  dim: 768                  # must stay 768 (DB vector columns are Vector(768))
holmes:                     # LiteLLM model strings passed per-request to /api/chat
  small: vertex_ai/gemini-2.5-flash
  medium: vertex_ai/gemini-2.5-flash
  frontier: vertex_ai/claude-sonnet-4-5@20250929
pricing:                    # usd per 1M tokens, for spend display and budgets
  gemini-2.5-flash: {input: 0.30, output: 2.50}
  claude-sonnet-4-5@20250929: {input: 3.00, output: 15.00}
vertex:
  project: ${GOOGLE_CLOUD_PROJECT}
  location: ${GOOGLE_CLOUD_LOCATION}
```

`config/models.fake.yaml`:

```yaml
# Fake profile: scripted chat model + deterministic hash embeddings. No network.
tiers:
  small:    {provider: fake, model: fake-small, params: {}}
  medium:   {provider: fake, model: fake-medium, params: {}}
  frontier: {provider: fake, model: fake-frontier, params: {}}
embeddings: {provider: fake, model: hash, dim: 768}
holmes:
  small: fake/small
  medium: fake/medium
  frontier: fake/frontier
pricing: {}
script_dir: tests/fixtures/scripts/incident_error_storm
```

Add to `Settings` (after `models_profile`): `fake_script_dir: Path | None = None  # overrides models.fake.yaml script_dir`.

- [ ] **Step 3: Write the failing tests**

`gateway/tests/test_model_factory.py`:

```python
from pathlib import Path

import pytest

from sre_gateway.llm.embeddings import hash_embedding
from sre_gateway.llm.factory import ModelFactory, load_models_config

CONFIG_DIR = Path(__file__).parents[2] / "config"


def test_local_profile_parses(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-x")
    cfg = load_models_config(CONFIG_DIR / "models.yaml")
    assert cfg.tiers["frontier"].provider == "vertex-anthropic"
    assert cfg.vertex["project"] == "proj-x"
    f = ModelFactory(cfg)
    assert f.holmes_model("medium") == "vertex_ai/gemini-2.5-flash"
    model_id, (pin, pout) = f.describe("small")
    assert model_id == "gemini-2.5-flash" and pin == 0.30 and pout == 2.50


def test_unknown_tier_raises():
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    with pytest.raises(KeyError):
        ModelFactory(cfg).describe("gigantic")


async def test_fake_embeddings_deterministic_unit_vectors():
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    f = ModelFactory(cfg)
    a1 = (await f.embed(["keycloak down"]))[0]
    a2 = (await f.embed(["keycloak down"]))[0]
    b = (await f.embed(["something else"]))[0]
    assert a1 == a2 and a1 != b and len(a1) == 768
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-6
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/test_model_factory.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sre_gateway.llm'`

- [ ] **Step 5: Implement**

`src/sre_gateway/llm/__init__.py`: empty. `src/sre_gateway/llm/embeddings.py`:

```python
import hashlib
import math
import re

_TOKEN = re.compile(r"[a-z0-9]+")


def hash_embedding(text: str, dim: int = 768) -> list[float]:
    """Deterministic bag-of-tokens pseudo-embedding for the fake profile: same text,
    same vector, and texts sharing tokens land measurably closer. Retrieval tests
    rely on that: token overlap, not luck, decides nearest-neighbor order."""
    acc = [0.0] * dim
    for token in _TOKEN.findall(text.lower()) or [text]:
        seed = hashlib.sha256(token.encode()).digest()
        for i in range(dim):
            byte = seed[(i * 7 + 3) % len(seed)] ^ (i & 0xFF)
            acc[i] += (byte / 255.0) * 2 - 1
    norm = math.sqrt(sum(v * v for v in acc)) or 1.0
    return [v / norm for v in acc]
```

`src/sre_gateway/llm/factory.py`:

```python
import os
import re
from pathlib import Path
from typing import Literal

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from sre_gateway.llm.embeddings import hash_embedding

_ENV_RE = re.compile(r"\$\{(\w+)\}")


class TierConfig(BaseModel):
    provider: Literal["vertex-gemini", "vertex-anthropic", "openai-compatible", "fake"]
    model: str
    params: dict = Field(default_factory=dict)
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"


class EmbeddingsConfig(BaseModel):
    provider: Literal["vertex", "openai-compatible", "fake"]
    model: str
    dim: int = 768
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"


class ModelsConfig(BaseModel):
    tiers: dict[str, TierConfig]
    embeddings: EmbeddingsConfig
    holmes: dict[str, str] = Field(default_factory=dict)
    pricing: dict[str, dict] = Field(default_factory=dict)
    vertex: dict = Field(default_factory=dict)
    script_dir: str | None = None


def load_models_config(path: Path) -> ModelsConfig:
    raw = path.read_text()
    raw = _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), raw)
    return ModelsConfig.model_validate(yaml.safe_load(raw))


class ModelFactory:
    def __init__(self, config: ModelsConfig, script_dir: Path | None = None) -> None:
        self.config = config
        self.script_dir = script_dir or Path(config.script_dir or "tests/fixtures/scripts")

    def chat(self, tier: str, node: str) -> BaseChatModel:
        tc = self.config.tiers[tier]
        if tc.provider == "fake":
            from sre_gateway.llm.scripted import ScriptedChatModel

            return ScriptedChatModel(node=node, script_dir=self.script_dir)
        if tc.provider == "vertex-gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=tc.model, vertexai=True,
                project=self.config.vertex.get("project"),
                location=self.config.vertex.get("location"), **tc.params)
        if tc.provider == "vertex-anthropic":
            from langchain_google_vertexai.model_garden import ChatAnthropicVertex

            return ChatAnthropicVertex(
                model_name=tc.model,
                project=self.config.vertex.get("project"),
                location=self.config.vertex.get("location"), **tc.params)
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=tc.model, base_url=tc.base_url,
                          api_key=os.environ.get(tc.api_key_env, "unused"), **tc.params)

    def describe(self, tier: str) -> tuple[str, tuple[float, float]]:
        tc = self.config.tiers[tier]
        p = self.config.pricing.get(tc.model, {})
        return tc.model, (float(p.get("input", 0.0)), float(p.get("output", 0.0)))

    def holmes_model(self, tier: str) -> str:
        return self.config.holmes[tier]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ec = self.config.embeddings
        if ec.provider == "fake":
            return [hash_embedding(t, ec.dim) for t in texts]
        if ec.provider == "vertex":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            emb = GoogleGenerativeAIEmbeddings(
                model=ec.model, vertexai=True,
                project=self.config.vertex.get("project"),
                location=self.config.vertex.get("location"),
                output_dimensionality=ec.dim)
            return await emb.aembed_documents(texts)
        from langchain_openai import OpenAIEmbeddings

        emb = OpenAIEmbeddings(model=ec.model, base_url=ec.base_url,
                               api_key=os.environ.get(ec.api_key_env, "unused"),
                               dimensions=ec.dim)
        return await emb.aembed_documents(texts)
```

Note the exact kwargs for `ChatGoogleGenerativeAI(vertexai=True, ...)`, `GoogleGenerativeAIEmbeddings(output_dimensionality=...)` and `ChatAnthropicVertex` are re-verified in Task 25's docs-check; only the fake path runs before then, and the lazy imports keep provider SDKs optional.

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/test_model_factory.py -q`
Expected: `3 passed` (the fake `chat()` path is covered in Task 10 once `ScriptedChatModel` exists).

- [ ] **Step 7: Commit**

```bash
git checkout -b feat/sre-team-p2-models-governance
git add config/models.yaml config/models.fake.yaml gateway/src/sre_gateway/llm gateway/src/sre_gateway/settings.py gateway/tests/test_model_factory.py gateway/pyproject.toml gateway/uv.lock
git commit -m "feat(sre-team): model factory with tiered providers, embeddings, pricing"
```

### Task 10: ScriptedChatModel and call_llm_json

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/llm/scripted.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/llm/json_call.py`
- Create: `agentic-sre-team/gateway/tests/test_llm_json.py`

**Interfaces:**
- Consumes: `AuditWriter` (Task 4), `ModelFactory` (Task 9).
- Produces:
  - `ScriptedChatModel(node: str, script_dir: Path)` - a `BaseChatModel` that pops responses in order from `<script_dir>/<node>.json` (a JSON list whose items are strings or objects; objects are serialized). Queues are module-level keyed by `(script_dir, node)` so every factory call for the same node shares one queue; `reset_scripts()` clears them (call in test fixtures). Exhausted queue raises `IndexError` with the node name.
  - `call_llm_json(model, *, system: str, user: str, schema: type[T], audit: AuditWriter, node: str, case_id: str | None, model_id: str = "", pricing=(0.0, 0.0)) -> T` - appends the schema's JSON Schema to the user prompt, invokes, extracts JSON (strips code fences), validates with Pydantic, retries exactly once with the validation error appended, audits every attempt via `audit.log_llm` (tokens from `usage_metadata`, cost from `pricing`), raises `LlmJsonError` after the failed repair.
  - `extract_json(text: str) -> dict`.

- [ ] **Step 1: Write the failing tests**

`gateway/tests/test_llm_json.py`:

```python
import json

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import AuditEvent
from sre_gateway.llm.json_call import LlmJsonError, call_llm_json, extract_json
from sre_gateway.llm.scripted import ScriptedChatModel, reset_scripts


class Out(BaseModel):
    answer: str
    score: float


def _script(tmp_path, node, items):
    (tmp_path / f"{node}.json").write_text(json.dumps(items))
    reset_scripts()
    return ScriptedChatModel(node=node, script_dir=tmp_path)


def test_extract_json_strips_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": {"b": 2}} trailing') == {"a": {"b": 2}}


async def test_happy_path_parses_and_audits(db, tmp_path):
    model = _script(tmp_path, "triage", [{"answer": "ok", "score": 0.9}])
    out = await call_llm_json(model, system="s", user="u", schema=Out,
                              audit=AuditWriter(db), node="triage", case_id=None,
                              model_id="fake", pricing=(1.0, 2.0))
    assert out.answer == "ok"
    async with db() as s:
        events = (await s.execute(select(AuditEvent))).scalars().all()
    assert len(events) == 1 and events[0].event_type == "llm_call"
    assert events[0].payload["tokens_in"] == 50


async def test_repair_retry_recovers(db, tmp_path):
    model = _script(tmp_path, "triage", ["not json at all", {"answer": "fixed", "score": 1.0}])
    out = await call_llm_json(model, system="s", user="u", schema=Out,
                              audit=AuditWriter(db), node="triage", case_id=None)
    assert out.answer == "fixed"


async def test_double_failure_raises(db, tmp_path):
    model = _script(tmp_path, "triage", ["junk", "more junk"])
    with pytest.raises(LlmJsonError):
        await call_llm_json(model, system="s", user="u", schema=Out,
                            audit=AuditWriter(db), node="triage", case_id=None)


def test_script_exhaustion_is_loud(tmp_path):
    model = _script(tmp_path, "triage", [])
    with pytest.raises(IndexError, match="triage"):
        model.invoke("hi")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_llm_json.py -q`
Expected: FAIL with `ModuleNotFoundError` (scripted/json_call missing)

- [ ] **Step 3: Implement**

`src/sre_gateway/llm/scripted.py`:

```python
import json
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_QUEUES: dict[tuple[str, str], list[Any]] = {}


def reset_scripts() -> None:
    _QUEUES.clear()


class ScriptedChatModel(BaseChatModel):
    node: str
    script_dir: Path

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        key = (str(self.script_dir), self.node)
        if key not in _QUEUES:
            path = Path(self.script_dir) / f"{self.node}.json"
            if not path.exists():
                raise FileNotFoundError(f"no script for node '{self.node}' at {path}")
            _QUEUES[key] = list(json.loads(path.read_text()))
        queue = _QUEUES[key]
        if not queue:
            raise IndexError(f"script exhausted for node '{self.node}'")
        item = queue.pop(0)
        content = item if isinstance(item, str) else json.dumps(item)
        msg = AIMessage(content=content, usage_metadata={
            "input_tokens": 50, "output_tokens": 50, "total_tokens": 100})
        return ChatResult(generations=[ChatGeneration(message=msg)])
```

`src/sre_gateway/llm/json_call.py`:

```python
import asyncio
import hashlib
import json
import re
import time
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from sre_gateway.audit import AuditWriter

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


class LlmJsonError(Exception):
    pass


def extract_json(text: str) -> dict:
    cleaned = _FENCE.sub("", text).strip().strip("`")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LlmJsonError(f"no JSON object in response: {text[:200]!r}")
    return json.loads(cleaned[start:end + 1])


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def call_llm_json(model: BaseChatModel, *, system: str, user: str, schema: type[T],
                        audit: AuditWriter, node: str, case_id: str | None,
                        model_id: str = "", pricing: tuple[float, float] = (0.0, 0.0)) -> T:
    prompt = (f"{user}\n\nReturn ONLY a JSON object matching this JSON Schema "
              f"(no prose, no code fences):\n{json.dumps(schema.model_json_schema())}")
    messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
    last_err: Exception | None = None
    for _attempt in range(2):
        t0 = time.monotonic()
        response = None
        for retry in range(3):  # provider errors: tiered retry with backoff (spec 10);
            try:                # final failure propagates and the runner parks the case
                response = await model.ainvoke(messages)
                break
            except Exception:
                if retry == 2:
                    raise
                await asyncio.sleep(2**retry)
        usage = getattr(response, "usage_metadata", None) or {}
        tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        await audit.log_llm(
            case_id, node=node, model_id=model_id, tokens_in=tin, tokens_out=tout,
            cost_usd=(tin * pricing[0] + tout * pricing[1]) / 1_000_000,
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_hash=_h("".join(str(m.content) for m in messages)),
            response_hash=_h(str(response.content)))
        try:
            return schema.model_validate(extract_json(str(response.content)))
        except (LlmJsonError, ValidationError, json.JSONDecodeError) as err:
            last_err = err
            messages += [response, HumanMessage(
                content=f"That was invalid ({err.__class__.__name__}). "
                        "Return ONLY the corrected JSON object.")]
    raise LlmJsonError(f"node {node}: response unparseable after one repair: {last_err}")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_llm_json.py tests/test_model_factory.py -q`
Expected: all pass. Add one line to `test_model_factory.py` confirming the fake chat path now works:

```python
def test_fake_chat_returns_scripted_model(tmp_path):
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    model = ModelFactory(cfg, script_dir=tmp_path).chat("small", "triage")
    assert type(model).__name__ == "ScriptedChatModel"
```

- [ ] **Step 5: Commit**

```bash
git add gateway/src/sre_gateway/llm gateway/tests
git commit -m "feat(sre-team): scripted chat model and audited json llm call with one repair"
```

### Task 11: Per-agent permission manifests and target-environment descriptor

**Files:**
- Create: `agentic-sre-team/config/environment.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/environment.py`
- Create: `agentic-sre-team/gateway/tests/test_environment.py`
- Create: `agentic-sre-team/config/agents/triage.yaml`
- Create: `agentic-sre-team/config/agents/workers.yaml`
- Create: `agentic-sre-team/config/agents/synthesize.yaml`
- Create: `agentic-sre-team/config/agents/rca.yaml`
- Create: `agentic-sre-team/config/agents/verify.yaml`
- Create: `agentic-sre-team/config/agents/remediate.yaml`
- Create: `agentic-sre-team/config/agents/learnings.yaml`
- Create: `agentic-sre-team/config/agents/chat.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/manifests.py`
- Create: `agentic-sre-team/gateway/tests/test_manifests.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `TOOL_REGISTRY: dict[str, str]` - the complete tool universe: `{"runbook_search": ..., "learning_search": ...}`. **No write-capable tool exists here, by design (spec section 8).**
  - `AgentManifest` (pydantic): `agent: str`, `tier: str`, `tools: list[str]`, `budgets: dict` (`usd_per_day: float`).
  - `load_manifests(dir: Path) -> dict[str, AgentManifest]` - fails at startup on any tool not in the registry.
  - `assert_tool_allowed(manifests, agent: str, tool: str) -> None` - raises `PermissionError` unless the agent's manifest declares the tool (default-deny: unknown agent or missing manifest also raises).
  - `EnvironmentConfig` (pydantic, in `sre_gateway/environment.py`): `name: str`, `description: str`, `platform: "docker-compose"|"kubernetes"|"openshift"`, `services: list[ServiceEntry]` (`ServiceEntry: {name, containers: list[str], repo: str | None, notes: str}`); methods `prompt_block() -> str` (the environment paragraph every SUT-aware prompt embeds) and `all_containers() -> list[str]`. `load_environment(path: Path) -> EnvironmentConfig`. This is locked decision 15: the ONLY place the system under test is named - triage and workers render from it (Tasks 15-16), and swapping targets is a config change.

- [ ] **Step 1: Write the manifest files and the environment descriptor**

`config/environment.yaml` (Spectre is the shipped reference; replace this file to manage another stack):

```yaml
# Target-environment descriptor - the only place the SUT is named (locked decision 15).
name: spectre
platform: docker-compose        # docker-compose | kubernetes | openshift
description: >-
  IAM admin console stack: Keycloak (OIDC) backed by Postgres, an Express
  admin-server, a React admin-ui, Kong edge gateway, OpenSearch audit store,
  and Fluent Bit + Alloy shipping metrics/logs/traces to Grafana Cloud.
services:
  - name: keycloak
    containers: [keycloak, keycloak-db]
    notes: OIDC provider, Postgres-backed; login outages start here
  - name: admin-server
    containers: [spectre-admin-server]
    repo: alexgoh/spectre
    notes: only workload holding Keycloak Admin API credentials
  - name: admin-ui
    containers: [spectre-admin-ui]
  - name: kong
    containers: [spectre-kong]
    notes: edge gateway fronting /api and /audit
  - name: opensearch
    containers: [spectre-opensearch]
    notes: audit log store; watch cluster health and query latency
  - name: log-pipeline
    containers: [spectre-fluent-bit, spectre-alloy]
    notes: Fluent Bit buffers audit logs; Alloy ships telemetry to Grafana Cloud
```

`config/agents/triage.yaml`:

```yaml
agent: triage
tier: small
tools: [runbook_search, learning_search]
budgets: {usd_per_day: 3.0}
```

`config/agents/workers.yaml` (evidence workers hold no gateway tools; their evidence layer is HolmesGPT, whose own manifest is `config/holmes.yaml`):

```yaml
agent: workers
tier: medium
tools: []
budgets: {usd_per_day: 6.0}
```

`config/agents/synthesize.yaml`:

```yaml
agent: synthesize
tier: medium
tools: [runbook_search]
budgets: {usd_per_day: 3.0}
```

`config/agents/rca.yaml`:

```yaml
agent: rca
tier: frontier
tools: []
budgets: {usd_per_day: 6.0}
```

`config/agents/verify.yaml`:

```yaml
agent: verify
tier: small
tools: []
budgets: {usd_per_day: 1.0}
```

`config/agents/remediate.yaml`:

```yaml
agent: remediate
tier: frontier
tools: [runbook_search]
budgets: {usd_per_day: 6.0}
```

`config/agents/learnings.yaml`:

```yaml
agent: learnings
tier: small
tools: []
budgets: {usd_per_day: 1.0}
```

`config/agents/chat.yaml`:

```yaml
agent: chat
tier: medium
tools: []
budgets: {usd_per_day: 5.0}
```

- [ ] **Step 2: Write the failing tests**

`gateway/tests/test_manifests.py`:

```python
from pathlib import Path

import pytest

from sre_gateway.manifests import assert_tool_allowed, load_manifests

AGENTS_DIR = Path(__file__).parents[2] / "config/agents"


def test_loads_all_agents_and_validates_tools():
    m = load_manifests(AGENTS_DIR)
    assert set(m) >= {"triage", "workers", "synthesize", "rca", "verify",
                      "remediate", "learnings", "chat"}
    assert m["triage"].tier == "small"
    assert "runbook_search" in m["triage"].tools


def test_default_deny(tmp_path):
    m = load_manifests(AGENTS_DIR)
    assert_tool_allowed(m, "triage", "runbook_search")  # declared: no raise
    with pytest.raises(PermissionError):
        assert_tool_allowed(m, "rca", "runbook_search")  # not declared for rca
    with pytest.raises(PermissionError):
        assert_tool_allowed(m, "ghost-agent", "runbook_search")  # unknown agent


def test_unknown_tool_fails_at_load(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "agent: bad\ntier: small\ntools: [delete_everything]\nbudgets: {usd_per_day: 1}\n")
    with pytest.raises(ValueError, match="delete_everything"):
        load_manifests(tmp_path)
```

`gateway/tests/test_environment.py`:

```python
from pathlib import Path

from sre_gateway.environment import load_environment

CONFIG_DIR = Path(__file__).parents[2] / "config"


def test_environment_descriptor_renders_prompt_block():
    env = load_environment(CONFIG_DIR / "environment.yaml")
    assert env.name == "spectre" and env.platform == "docker-compose"
    assert "keycloak" in env.all_containers()
    block = env.prompt_block()
    assert "Target environment 'spectre'" in block
    assert "spectre-opensearch" in block and "cluster health" in block
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_manifests.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sre_gateway.manifests'`

- [ ] **Step 4: Implement**

`src/sre_gateway/manifests.py`:

```python
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# The complete tool universe on the gateway side. Read-only by construction:
# no write-capable tool exists in this registry at all (spec section 8).
TOOL_REGISTRY: dict[str, str] = {
    "runbook_search": "semantic search over the approved-runbook index",
    "learning_search": "semantic search over distilled case learnings",
}


class AgentManifest(BaseModel):
    agent: str
    tier: str
    tools: list[str] = Field(default_factory=list)
    budgets: dict = Field(default_factory=dict)


def load_manifests(dir_path: Path) -> dict[str, AgentManifest]:
    manifests: dict[str, AgentManifest] = {}
    for path in sorted(dir_path.glob("*.yaml")):
        m = AgentManifest.model_validate(yaml.safe_load(path.read_text()))
        for tool in m.tools:
            if tool not in TOOL_REGISTRY:
                raise ValueError(f"manifest {path.name}: unknown tool '{tool}' "
                                 f"(registry: {sorted(TOOL_REGISTRY)})")
        manifests[m.agent] = m
    return manifests


def assert_tool_allowed(manifests: dict[str, AgentManifest], agent: str, tool: str) -> None:
    m = manifests.get(agent)
    if m is None or tool not in m.tools:
        raise PermissionError(f"agent '{agent}' is not permitted tool '{tool}' (default-deny)")
```

`src/sre_gateway/environment.py`:

```python
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ServiceEntry(BaseModel):
    name: str
    containers: list[str] = Field(default_factory=list)
    repo: str | None = None
    notes: str = ""


class EnvironmentConfig(BaseModel):
    """Descriptor of the environment under management (locked decision 15).

    The only place the SUT is named: prompts render from prompt_block(), so
    pointing the system at another stack is a config change, never a code change.
    """

    name: str
    description: str
    platform: Literal["docker-compose", "kubernetes", "openshift"] = "docker-compose"
    services: list[ServiceEntry] = Field(default_factory=list)

    def prompt_block(self) -> str:
        lines = [f"Target environment '{self.name}' ({self.platform}): "
                 f"{self.description}", "Services:"]
        for svc in self.services:
            repo = f" repo={svc.repo}" if svc.repo else ""
            notes = f" - {svc.notes}" if svc.notes else ""
            lines.append(f"- {svc.name} (containers: "
                         f"{', '.join(svc.containers)}){repo}{notes}")
        return "\n".join(lines)

    def all_containers(self) -> list[str]:
        return [c for svc in self.services for c in svc.containers]


def load_environment(path: Path) -> EnvironmentConfig:
    return EnvironmentConfig.model_validate(yaml.safe_load(path.read_text()))
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_manifests.py tests/test_environment.py -q`
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add config/agents config/environment.yaml gateway/src/sre_gateway/manifests.py \
        gateway/src/sre_gateway/environment.py gateway/tests
git commit -m "feat(sre-team): default-deny agent manifests and target-environment descriptor"
```

### Task 12: Budget envelopes and enforcer

**Files:**
- Create: `agentic-sre-team/config/budgets.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/budget.py`
- Create: `agentic-sre-team/gateway/tests/test_budget.py`

**Interfaces:**
- Consumes: `db.models.Case/AuditEvent`, `AgentManifest.budgets`.
- Produces:
  - `CaseBudget` (pydantic): `tokens: int = 500_000`, `tool_calls: int = 60`, `wall_clock_s: int = 900`; `load_budgets(path) -> CaseBudget`.
  - `BudgetEnforcer(sessionmaker, budget: CaseBudget)`:
    - `async check_case(case_id) -> str | None` - breach description (`"tokens 501000/500000"`, `"tool_calls 61/60"`, `"wall_clock 950s/900s"`) or `None`. Wall clock measures `created_at` to now.
    - `async agent_spend_today(agent: str) -> float` - sum of `llm_call` audit `cost_usd` for that actor since UTC midnight.
    - `async check_agent(agent: str, usd_per_day: float) -> str | None`.
  - The graph node guard (Task 14) calls `check_case` between nodes, per spec.

- [ ] **Step 1: Write the config**

`config/budgets.yaml`:

```yaml
# Per-case envelope, checked between graph nodes. Breach parks the case
# needs-human and pages Telegram. Per-agent usd_per_day lives in config/agents/.
case:
  tokens: 500000
  tool_calls: 60
  wall_clock_s: 900
```

- [ ] **Step 2: Write the failing tests**

`gateway/tests/test_budget.py`:

```python
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sre_gateway.audit import AuditWriter
from sre_gateway.budget import BudgetEnforcer, load_budgets
from sre_gateway.db.models import Case

CONFIG = Path(__file__).parents[2] / "config/budgets.yaml"


async def _case(db, **kw) -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t", **kw)
        s.add(c)
        await s.commit()
        return c.id


async def test_within_budget_returns_none(db):
    case_id = await _case(db)
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    assert await enforcer.check_case(case_id) is None


async def test_token_breach(db):
    case_id = await _case(db, tokens_in=400_000, tokens_out=200_000)
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    breach = await enforcer.check_case(case_id)
    assert breach and breach.startswith("tokens")


async def test_wall_clock_breach(db):
    case_id = await _case(db)
    async with db() as s:
        (await s.get(Case, case_id)).created_at = datetime.now(UTC) - timedelta(seconds=2000)
        await s.commit()
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    breach = await enforcer.check_case(case_id)
    assert breach and breach.startswith("wall_clock")


async def test_agent_daily_spend_and_cap(db):
    audit = AuditWriter(db)
    await audit.log_llm(None, node="rca", model_id="m", tokens_in=1, tokens_out=1,
                        cost_usd=4.20, latency_ms=1, prompt_hash="a", response_hash="b")
    enforcer = BudgetEnforcer(db, load_budgets(CONFIG))
    assert abs(await enforcer.agent_spend_today("rca") - 4.20) < 1e-6
    assert await enforcer.check_agent("rca", usd_per_day=6.0) is None
    breach = await enforcer.check_agent("rca", usd_per_day=4.0)
    assert breach and "usd_per_day" in breach
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_budget.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sre_gateway.budget'`

- [ ] **Step 4: Implement**

`src/sre_gateway/budget.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.db.models import Case


class CaseBudget(BaseModel):
    tokens: int = 500_000
    tool_calls: int = 60
    wall_clock_s: int = 900


def load_budgets(path: Path) -> CaseBudget:
    data = yaml.safe_load(path.read_text()) or {}
    return CaseBudget.model_validate(data.get("case", {}))


class BudgetEnforcer:
    def __init__(self, sm: async_sessionmaker[AsyncSession], budget: CaseBudget) -> None:
        self._sm = sm
        self.budget = budget

    async def check_case(self, case_id: str) -> str | None:
        async with self._sm() as s:
            case = await s.get(Case, case_id)
        if case is None:
            return None
        total_tokens = case.tokens_in + case.tokens_out
        if total_tokens > self.budget.tokens:
            return f"tokens {total_tokens}/{self.budget.tokens}"
        if case.tool_calls > self.budget.tool_calls:
            return f"tool_calls {case.tool_calls}/{self.budget.tool_calls}"
        age = (datetime.now(UTC) - case.created_at).total_seconds()
        if age > self.budget.wall_clock_s:
            return f"wall_clock {int(age)}s/{self.budget.wall_clock_s}s"
        return None

    async def agent_spend_today(self, agent: str) -> float:
        async with self._sm() as s:
            res = await s.execute(text(
                "SELECT COALESCE(SUM((payload->>'cost_usd')::float), 0) FROM audit_events "
                "WHERE actor = :actor AND event_type = 'llm_call' "
                "AND ts >= date_trunc('day', now() AT TIME ZONE 'utc')"
            ), {"actor": agent})
            return float(res.scalar_one())

    async def check_agent(self, agent: str, usd_per_day: float) -> str | None:
        spend = await self.agent_spend_today(agent)
        if spend >= usd_per_day:
            return f"usd_per_day {spend:.2f}/{usd_per_day:.2f}"
        return None
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_budget.py -q`
Expected: `4 passed`

- [ ] **Step 6: Commit and open the phase PR**

```bash
git add config/budgets.yaml gateway/src/sre_gateway/budget.py gateway/tests/test_budget.py
git commit -m "feat(sre-team): case budget envelope and per-agent daily spend enforcement"
# PR: feat/sre-team-p2-models-governance -> main
```

---

## Phase 3 - Case graph on fakes, core API, smoke

Branch: `feat/sre-team-p3-case-graph`

This phase is the backbone (per handoff): the fake Holmes server and scripted chat model make the whole lifecycle testable without any external service. All graph tests run against them.

### Task 13: Fake Holmes server and HolmesClient

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/holmes/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/holmes/client.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/testing/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/testing/fake_holmes.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/holmes/incident_error_storm/metrics.json` (and `logs.json`, `infra.json`, `changes.json`)
- Create: `agentic-sre-team/gateway/tests/test_holmes_client.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `HolmesToolCall` dataclass: `tool_name: str`, `toolset: str`, `description: str`, `invocation: str`, `result: str`.
  - `HolmesAnswer` dataclass: `text: str`, `tool_calls: list[HolmesToolCall]`, `raw: dict`.
  - `HolmesClient(base_url: str, client: httpx.AsyncClient | None = None)` with `async chat(ask: str, *, model: str, response_format: dict | None = None, on_event: Callable[[dict], Awaitable[None]] | None = None, timeout_s: int = 180) -> HolmesAnswer`. When `on_event` is set the client requests SSE (`stream: true`) and forwards `{"type": "tool_start"|"tool_result", ...}` events as they arrive; otherwise it posts and parses a single JSON body `{analysis, tool_calls}`. All Holmes response parsing lives in this one module (the thin-worker seam from spec section 12).
  - Fake server: FastAPI app `sre_gateway.testing.fake_holmes:app`; `POST /api/chat` reads the scenario directory from env `FAKE_HOLMES_DIR`, extracts the domain from the ask's first line (`Domain: metrics`), loads `<dir>/<domain>.json`, and replies - SSE (tool events then final answer) when the request has `stream: true`, plain JSON otherwise. Runnable standalone: `python -m sre_gateway.testing.fake_holmes` (port 5050).
- **Contract note:** this request/response/SSE shape is our pinned contract with Holmes, mirrored from its documented server mode. Task 23 verifies it against the real pinned image (`GET /openapi.json` + holmesgpt.dev docs) and adjusts `client.py` + these fixtures together if drift is found. Workers depend only on `HolmesClient`, never on wire details.

- [ ] **Step 1: Write a fixture**

`gateway/tests/fixtures/holmes/incident_error_storm/metrics.json`:

```json
{
  "analysis": "{\"summary\": \"admin-server 5xx ratio at 18% since 14:02; keycloak-db connections 5x baseline\", \"findings\": [{\"hid\": \"H1\", \"direction\": \"for\", \"note\": \"5xx ratio spiked to 18% at 14:02\", \"evidence_idx\": [0]}, {\"hid\": \"H3\", \"direction\": \"against\", \"note\": \"host CPU flat at 22%\", \"evidence_idx\": [1]}], \"proposed_hypotheses\": []}",
  "tool_calls": [
    {
      "tool_name": "prometheus_query_range",
      "toolset": "prometheus",
      "description": "5xx ratio by route via Kong",
      "arguments": "sum(rate(kong_http_requests_total{code=~\"5..\"}[5m])) / sum(rate(kong_http_requests_total[5m]))",
      "result": "0.18 from 14:02, baseline 0.002"
    },
    {
      "tool_name": "prometheus_query",
      "toolset": "prometheus",
      "description": "docker host cpu",
      "arguments": "avg(rate(node_cpu_seconds_total{mode!=\"idle\"}[5m]))",
      "result": "0.22 flat"
    }
  ]
}
```

Create `logs.json`, `infra.json`, `changes.json` in the same shape (2 tool calls each, findings tagged to H1/H2/H3; `changes.json` must include a finding `{"hid": "H2", "direction": "for", "note": "PR #212 adds per-user admin API call in group listing", "evidence_idx": [0]}` with a github tool call whose `result` mentions `PR #212` - the graph test in Task 20 asserts H2 becomes supported).

- [ ] **Step 2: Write the failing client tests**

`gateway/tests/test_holmes_client.py`:

```python
from pathlib import Path

import httpx
import pytest

import sre_gateway.testing.fake_holmes as fh
from sre_gateway.holmes.client import HolmesClient

FIXTURES = Path(__file__).parent / "fixtures/holmes/incident_error_storm"


@pytest.fixture
def client(monkeypatch) -> HolmesClient:
    monkeypatch.setenv("FAKE_HOLMES_DIR", str(FIXTURES))
    transport = httpx.ASGITransport(app=fh.app)
    return HolmesClient("http://fake", client=httpx.AsyncClient(transport=transport,
                                                                base_url="http://fake"))


async def test_non_streaming_chat_parses_tool_calls(client):
    answer = await client.chat("Domain: metrics\ninvestigate", model="fake/medium")
    assert "5xx ratio" in answer.text
    assert len(answer.tool_calls) == 2
    tc = answer.tool_calls[0]
    assert tc.toolset == "prometheus" and "kong_http_requests_total" in tc.invocation


async def test_streaming_relays_tool_events(client):
    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    answer = await client.chat("Domain: metrics\ninvestigate", model="fake/medium",
                               on_event=on_event)
    assert len(answer.tool_calls) == 2
    types = [e["type"] for e in events]
    assert types.count("tool_start") == 2 and types.count("tool_result") == 2


async def test_unknown_domain_is_a_clean_error(client):
    with pytest.raises(httpx.HTTPStatusError):
        await client.chat("Domain: nonsense\nx", model="fake/medium")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_holmes_client.py -q`
Expected: FAIL with `ModuleNotFoundError` (holmes/testing modules missing)

- [ ] **Step 4: Implement the fake server**

`src/sre_gateway/testing/__init__.py`: empty. `src/sre_gateway/testing/fake_holmes.py`:

```python
"""Recorded-fixture HolmesGPT stand-in. POST /api/chat replays <FAKE_HOLMES_DIR>/<domain>.json
where <domain> comes from the ask's first line 'Domain: <name>'. Serves both the test suite
(in-process ASGI) and the compose `fake` profile (python -m sre_gateway.testing.fake_holmes)."""
import asyncio
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="fake-holmes")
_DOMAIN = re.compile(r"Domain:\s*(\w+)", re.IGNORECASE)


def _load(ask: str) -> dict:
    match = _DOMAIN.search(ask)
    domain = match.group(1).lower() if match else "default"
    path = Path(os.environ.get("FAKE_HOLMES_DIR", "tests/fixtures/holmes/incident_error_storm"))
    file = path / f"{domain}.json"
    if not file.exists():
        raise HTTPException(status_code=404, detail=f"no fixture for domain '{domain}'")
    return json.loads(file.read_text())


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    fixture = _load(body.get("ask", ""))
    if not body.get("stream"):
        return {"analysis": fixture["analysis"], "tool_calls": fixture["tool_calls"]}

    async def sse():
        for tc in fixture["tool_calls"]:
            yield _event("tool_start", {"tool_name": tc["tool_name"],
                                        "toolset": tc.get("toolset", ""),
                                        "description": tc.get("description", "")})
            await asyncio.sleep(0)
            yield _event("tool_result", tc)
        yield _event("answer", {"analysis": fixture["analysis"],
                                "tool_calls": fixture["tool_calls"]})

    return StreamingResponse(sse(), media_type="text/event-stream")


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5050)
```

- [ ] **Step 5: Implement the client**

`src/sre_gateway/holmes/__init__.py`: empty. `src/sre_gateway/holmes/client.py`:

```python
import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx


@dataclass
class HolmesToolCall:
    tool_name: str
    toolset: str = ""
    description: str = ""
    invocation: str = ""
    result: str = ""


@dataclass
class HolmesAnswer:
    text: str
    tool_calls: list[HolmesToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _parse_tool_call(entry: dict) -> HolmesToolCall:
    return HolmesToolCall(
        tool_name=entry.get("tool_name", entry.get("name", "unknown")),
        toolset=entry.get("toolset", ""),
        description=entry.get("description", ""),
        invocation=str(entry.get("arguments", entry.get("invocation", ""))),
        result=str(entry.get("result", ""))[:4000],
    )


class HolmesClient:
    """The single module that knows Holmes's wire format (spec section 12 seam)."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url)

    async def chat(self, ask: str, *, model: str, response_format: dict | None = None,
                   on_event: Callable[[dict], Awaitable[None]] | None = None,
                   timeout_s: int = 180) -> HolmesAnswer:
        payload: dict = {"ask": ask, "model": model, "stream": on_event is not None}
        if response_format:
            payload["response_format"] = response_format
        if on_event is None:
            res = await self._client.post("/api/chat", json=payload, timeout=timeout_s)
            res.raise_for_status()
            body = res.json()
            return HolmesAnswer(
                text=str(body.get("analysis", "")),
                tool_calls=[_parse_tool_call(t) for t in body.get("tool_calls", [])],
                raw=body)

        answer = HolmesAnswer(text="")
        async with self._client.stream("POST", "/api/chat", json=payload,
                                       timeout=timeout_s) as res:
            res.raise_for_status()
            event_name = ""
            async for line in res.aiter_lines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = json.loads(line.split(":", 1)[1].strip() or "{}")
                    if event_name == "tool_start":
                        await on_event({"type": "tool_start", **data})
                    elif event_name == "tool_result":
                        tc = _parse_tool_call(data)
                        answer.tool_calls.append(tc)
                        await on_event({"type": "tool_result", "tool_name": tc.tool_name,
                                        "toolset": tc.toolset,
                                        "description": tc.description})
                    elif event_name == "answer":
                        answer.text = str(data.get("analysis", ""))
                        if not answer.tool_calls and data.get("tool_calls"):
                            answer.tool_calls = [_parse_tool_call(t)
                                                 for t in data["tool_calls"]]
                        answer.raw = data
        return answer
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/test_holmes_client.py -q`
Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git checkout -b feat/sre-team-p3-case-graph
git add gateway/src/sre_gateway/holmes gateway/src/sre_gateway/testing gateway/tests
git commit -m "feat(sre-team): holmes client with sse tool events and recorded-fixture fake server"
```

### Task 14: Graph state, deps, routers, node guard, checkpointer

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/state.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/deps.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/routers.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/channels/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/channels/base.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/channels/log.py`
- Create: `agentic-sre-team/gateway/tests/test_routers.py`

**Interfaces:**
- Consumes: Tasks 4, 9-13.
- Produces:
  - `CaseState` (TypedDict, `total=False`): `case_id, display_id, kind, title, severity: int, effort, round: int, failure_class, hypotheses: list[dict]` (owned by triage/synthesize only), `evidence: Annotated[list[dict], operator.add]`, `worker_reports: Annotated[list[dict], operator.add]`, `context_notes: Annotated[list[str], operator.add]`, `query_hints: list[str]`, `need_more: bool, rca: dict | None, verification: dict | None, repair_used: bool, runbook: dict | None, non_incident: bool, halt: dict | None`.
  - `GraphDeps` dataclass: `settings, sessionmaker, audit, models: ModelFactory, manifests: dict[str, AgentManifest], budget: BudgetEnforcer, holmes: HolmesClient, channel: Channel, environment: EnvironmentConfig` (Task 11's descriptor - every SUT-aware prompt renders from it).
  - `Channel` protocol: `async send(text: str, *, buttons: list[dict] | None = None) -> str | None`; `LogChannel` records `sent: list[dict]` (fake profile + tests).
  - `guarded(deps, name, fn)` - wraps a node: checks the global pause flag and `budget.check_case` **before** running; on breach/pause returns `{"halt": {"reason": ..., "at_node": name}}` without running `fn`; also emits a `node_start`/`node_end` custom stream event around `fn` (via `langgraph.config.get_stream_writer`) and updates `cases.phase` to the node name.
  - Routers (pure functions, unit-testable): `route_after_triage`, `fan_out` (returns `list[Send]`), `route_after_synthesize`, `route_after_verify`, `route_after_gate_rca`, `route_after_gate_runbook`. **Every router returns `"park"` first whenever `state.get("halt")` is set** - this is the between-nodes budget stop.
  - Worker fan-out policy (deterministic, spec section 4): incident + effort low -> single worker by primary label (`metrics` default); incident + medium/high -> `metrics, logs, infra, changes`; pipeline_failure -> `ci, changes` (infra added only when a prior round's `worker_reports` flag `needs_infra`).
  - `make_checkpointer(database_url) -> AsyncPostgresSaver` context helper (strips the `+asyncpg` driver suffix for the psycopg-based saver; calls `.setup()`).

- [ ] **Step 1: Add langgraph dependencies**

```bash
cd agentic-sre-team/gateway && uv add "langgraph>=1.0" "langgraph-checkpoint-postgres>=2.0"
```

Docs-check (Context7 `/langchain-ai/langgraph`): confirm current import paths used below - `langgraph.graph.StateGraph/START/END`, `langgraph.types.Send/Command/interrupt`, `langgraph.config.get_stream_writer`, `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` - and `AsyncPostgresSaver.from_conn_string(...)` + `await saver.setup()` usage.

- [ ] **Step 2: Write the failing router tests**

`gateway/tests/test_routers.py`:

```python
from langgraph.types import Send

from sre_gateway.graph.routers import (
    fan_out, route_after_synthesize, route_after_triage, route_after_verify,
)


def test_triage_routes_to_plan_or_end_or_park():
    assert route_after_triage({"non_incident": False}) == "plan"
    assert route_after_triage({"non_incident": True}) == "__end__"
    assert route_after_triage({"halt": {"reason": "x"}}) == "park"


def test_fan_out_incident_medium_is_four_workers():
    sends = fan_out({"kind": "incident", "effort": "medium", "case_id": "c"})
    assert {s.node for s in sends} == {"metrics_worker", "logs_worker",
                                       "infra_worker", "changes_worker"}
    assert all(isinstance(s, Send) for s in sends)


def test_fan_out_incident_low_is_one_worker():
    sends = fan_out({"kind": "incident", "effort": "low", "case_id": "c"})
    assert [s.node for s in sends] == ["metrics_worker"]


def test_fan_out_pipeline_failure_is_ci_plus_changes():
    sends = fan_out({"kind": "pipeline_failure", "effort": "medium", "case_id": "c"})
    assert {s.node for s in sends} == {"ci_worker", "changes_worker"}


def test_fan_out_pipeline_adds_infra_when_flagged():
    state = {"kind": "pipeline_failure", "effort": "medium", "case_id": "c",
             "worker_reports": [{"worker": "ci", "needs_infra": True}]}
    assert "infra_worker" in {s.node for s in fan_out(state)}


def test_synthesize_loops_bounded():
    assert route_after_synthesize({"need_more": True, "round": 1}) == "plan"
    assert route_after_synthesize({"need_more": True, "round": 2}) == "rca"
    assert route_after_synthesize({"need_more": False, "round": 1}) == "rca"


def test_verify_repairs_exactly_once():
    failed = {"verification": {"verified": False}, "repair_used": False}
    assert route_after_verify(failed) == "rca"
    assert route_after_verify({"verification": {"verified": False},
                               "repair_used": True}) == "gate_rca"
    assert route_after_verify({"verification": {"verified": True},
                               "repair_used": False}) == "gate_rca"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_routers.py -q`
Expected: FAIL with `ModuleNotFoundError` (graph package missing)

- [ ] **Step 4: Implement**

`src/sre_gateway/channels/__init__.py`: empty. `src/sre_gateway/channels/base.py`:

```python
from typing import Protocol


class Channel(Protocol):
    async def send(self, text: str, *, buttons: list[dict] | None = None) -> str | None: ...
```

`src/sre_gateway/channels/log.py`:

```python
import logging

logger = logging.getLogger("sre.channel")


class LogChannel:
    """Channel adapter that only logs. Used by tests and the fake profile."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, text: str, *, buttons: list[dict] | None = None) -> str | None:
        self.sent.append({"text": text, "buttons": buttons or []})
        logger.info("channel: %s", text)
        return str(len(self.sent))
```

`src/sre_gateway/graph/__init__.py`: empty. `src/sre_gateway/graph/state.py`:

```python
import operator
from typing import Annotated, TypedDict


class CaseState(TypedDict, total=False):
    case_id: str
    display_id: str
    kind: str
    title: str
    severity: int
    effort: str
    round: int
    failure_class: str | None
    non_incident: bool
    hypotheses: list[dict]            # owned by triage/synthesize only
    evidence: Annotated[list[dict], operator.add]
    worker_reports: Annotated[list[dict], operator.add]
    context_notes: Annotated[list[str], operator.add]
    query_hints: list[str]            # decisive-query hints from case learnings (triage)
    need_more: bool
    rca: dict | None
    verification: dict | None
    repair_used: bool
    runbook: dict | None
    halt: dict | None
```

`src/sre_gateway/graph/deps.py`:

```python
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.audit import AuditWriter, get_flag
from sre_gateway.budget import BudgetEnforcer
from sre_gateway.channels.base import Channel
from sre_gateway.db.models import Case
from sre_gateway.environment import EnvironmentConfig
from sre_gateway.holmes.client import HolmesClient
from sre_gateway.llm.factory import ModelFactory
from sre_gateway.manifests import AgentManifest
from sre_gateway.settings import Settings


@dataclass
class GraphDeps:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    audit: AuditWriter
    models: ModelFactory
    manifests: dict[str, AgentManifest]
    budget: BudgetEnforcer
    holmes: HolmesClient
    channel: Channel
    environment: EnvironmentConfig


def guarded(deps: GraphDeps, name: str, fn):
    """Between-nodes governance: pause + budget checks run before every node."""

    async def wrapped(state: dict):
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        case_id = state.get("case_id", "")
        if await get_flag(deps.sessionmaker, "paused"):
            return {"halt": {"reason": "paused", "at_node": name}}
        breach = await deps.budget.check_case(case_id)
        if breach:
            await deps.audit.log("budget", actor=name, case_id=case_id, breach=breach)
            return {"halt": {"reason": f"budget: {breach}", "at_node": name}}
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(phase=name))
            await s.commit()
        writer({"type": "node_start", "node": name})
        result = await fn(state)
        writer({"type": "node_end", "node": name})
        return result

    return wrapped
```

`src/sre_gateway/graph/routers.py`:

```python
from langgraph.graph import END
from langgraph.types import Send

INCIDENT_WORKERS = ["metrics_worker", "logs_worker", "infra_worker", "changes_worker"]
PIPELINE_WORKERS = ["ci_worker", "changes_worker"]
MAX_ROUNDS = 2


def _halted(state: dict) -> bool:
    return bool(state.get("halt"))


def route_after_triage(state: dict) -> str:
    if _halted(state):
        return "park"
    return END if state.get("non_incident") else "plan"


def fan_out(state: dict) -> list[Send]:
    """Deterministic worker fan-out (spec section 4). Runs as plan's conditional edge."""
    if _halted(state):
        return [Send("park", state)]
    if state.get("kind") == "pipeline_failure":
        workers = list(PIPELINE_WORKERS)
        if any(r.get("needs_infra") for r in state.get("worker_reports", [])):
            workers.append("infra_worker")
    elif state.get("effort") == "low":
        workers = ["metrics_worker"]
    else:
        workers = list(INCIDENT_WORKERS)
    payload = {k: v for k, v in state.items()
               if k not in ("evidence", "worker_reports")}  # workers append, never replay
    return [Send(w, payload) for w in workers]


def route_after_synthesize(state: dict) -> str:
    if _halted(state):
        return "park"
    if state.get("need_more") and state.get("round", 1) < MAX_ROUNDS:
        return "plan"
    return "rca"


def route_after_verify(state: dict) -> str:
    if _halted(state):
        return "park"
    verification = state.get("verification") or {}
    if not verification.get("verified", False) and not state.get("repair_used"):
        return "rca"
    return "gate_rca"


def route_after_gate_rca(state: dict) -> str:
    if _halted(state):
        return "park"
    decision = (state.get("gate_rca") or {}).get("decision", "reject")
    return "remediate" if decision in ("approve", "approve_with_edits") else "rca"


def route_after_gate_runbook(state: dict) -> str:
    if _halted(state):
        return "park"
    decision = (state.get("gate_runbook") or {}).get("decision", "reject")
    return "publish" if decision in ("approve", "approve_with_edits") else "remediate"
```

Note on round semantics: `round` is the number of the investigation round that has just run. Triage seeds `round: 0`, the plan node increments and persists it as each round starts (Task 16), and synthesize leaves it unchanged - so `route_after_synthesize` loops back only while the just-completed round number is `< MAX_ROUNDS`, giving at most 2 investigation rounds. `gate_rca`/`gate_runbook` state keys are written by the gate nodes (Task 19); add both to `CaseState` now:

```python
    gate_rca: dict | None
    gate_runbook: dict | None
```

Also add `make_checkpointer` to `src/sre_gateway/graph/__init__.py`:

```python
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


@asynccontextmanager
async def make_checkpointer(database_url: str):
    conninfo = database_url.replace("postgresql+asyncpg", "postgresql")
    async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
        await saver.setup()
        yield saver
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_routers.py -q`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add gateway/src/sre_gateway/graph gateway/src/sre_gateway/channels gateway/tests gateway/pyproject.toml gateway/uv.lock
git commit -m "feat(sre-team): graph state, deterministic routers, guarded nodes, checkpointer"
```

### Task 15: Retrieval (runbooks + learnings) and the triage node

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/retrieval.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/triage.py`
- Create: `agentic-sre-team/gateway/tests/test_retrieval.py`
- Create: `agentic-sre-team/gateway/tests/test_node_triage.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/triage.json`

**Interfaces:**
- Consumes: `ModelFactory.embed`, `call_llm_json`, `assert_tool_allowed`, `GraphDeps`.
- Produces:
  - `async search_runbooks(sm, embed, query, k=3) -> list[dict]` (`{id, title, snippet}` by cosine distance), `async search_learnings(sm, embed, query, k=3) -> list[dict]` (`{signal_signature, confirmed_root_cause, decisive_queries}`), `async index_runbook(sm, embed, *, title, body_md, source_case_id, tags) -> str`, `async index_learning(sm, embed, *, case_id, signal_signature, confirmed_root_cause, decisive_queries, false_leads) -> str`.
  - `make_triage(deps) -> async node`: loads the case + signals from DB; retrieves top learnings/runbooks (manifest-gated via `assert_tool_allowed(manifests, "triage", ...)`); calls the small tier with `TriageOut` schema; persists severity/effort/title/status onto the case row and `Hypothesis` rows (`H1..Hn`, round 0); sends the Telegram-style ack via `deps.channel`; on `is_incident=False` closes the case with the canned reply and returns `{"non_incident": True}`. Returns state update `{title, severity, effort, failure_class, hypotheses, round: 0, query_hints}` - `round: 0` means no investigation round has run yet (the plan node owns the counter, Task 16), and `query_hints` carries the retrieved learnings' `decisive_queries` into the worker prompts (the spec's retrieved-at-triage-and-planning loop).
  - `TriageOut` pydantic schema (in `nodes/triage.py`): `is_incident: bool = True`, `title: str`, `severity: int (1..4)`, `effort: "low"|"medium"|"high"`, `failure_class: str | None`, `hypotheses: list[str] (max 6)`, `canned_reply: str | None`.

- [ ] **Step 1: Write the failing retrieval tests**

`gateway/tests/test_retrieval.py`:

```python
from sre_gateway.llm.embeddings import hash_embedding
from sre_gateway.retrieval import index_runbook, search_runbooks


async def _embed(texts):
    return [hash_embedding(t) for t in texts]


async def test_index_then_search_finds_exact_match(db):
    await index_runbook(db, _embed, title="Keycloak login outage",
                        body_md="restart keycloak", source_case_id=None, tags=["keycloak"])
    await index_runbook(db, _embed, title="OpenSearch disk pressure",
                        body_md="prune indices", source_case_id=None, tags=[])
    hits = await search_runbooks(db, _embed, "Keycloak login outage", k=1)
    assert hits[0]["title"] == "Keycloak login outage"
```

- [ ] **Step 2: Run to verify failure, then implement retrieval**

Run: `uv run pytest tests/test_retrieval.py -q` -> `ModuleNotFoundError`.

`src/sre_gateway/retrieval.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sre_gateway.db.models import CaseLearning, Runbook

Embedder = "Callable[[list[str]], Awaitable[list[list[float]]]]"


async def index_runbook(sm: async_sessionmaker[AsyncSession], embed, *, title: str,
                        body_md: str, source_case_id: str | None, tags: list) -> str:
    vec = (await embed([f"{title}\n{body_md[:2000]}"]))[0]
    async with sm() as s:
        row = Runbook(title=title, body_md=body_md, source_case_id=source_case_id,
                      tags=tags, embedding=vec)
        s.add(row)
        await s.commit()
        return row.id


async def search_runbooks(sm, embed, query: str, k: int = 3) -> list[dict]:
    vec = (await embed([query]))[0]
    async with sm() as s:
        rows = (await s.execute(
            select(Runbook).order_by(Runbook.embedding.cosine_distance(vec)).limit(k)
        )).scalars().all()
    return [{"id": r.id, "title": r.title, "snippet": r.body_md[:400]} for r in rows]


async def index_learning(sm, embed, *, case_id: str, signal_signature: str,
                         confirmed_root_cause: str, decisive_queries: list,
                         false_leads: list) -> str:
    vec = (await embed([signal_signature]))[0]
    async with sm() as s:
        row = CaseLearning(case_id=case_id, signal_signature=signal_signature,
                           confirmed_root_cause=confirmed_root_cause,
                           decisive_queries=decisive_queries, false_leads=false_leads,
                           embedding=vec)
        s.add(row)
        await s.commit()
        return row.id


async def search_learnings(sm, embed, query: str, k: int = 3) -> list[dict]:
    vec = (await embed([query]))[0]
    async with sm() as s:
        rows = (await s.execute(
            select(CaseLearning).order_by(CaseLearning.embedding.cosine_distance(vec)).limit(k)
        )).scalars().all()
    return [{"signal_signature": r.signal_signature,
             "confirmed_root_cause": r.confirmed_root_cause,
             "decisive_queries": r.decisive_queries} for r in rows]
```

Run: `uv run pytest tests/test_retrieval.py -q` -> `1 passed`.

- [ ] **Step 3: Write the triage script fixture and failing node test**

`gateway/tests/fixtures/scripts/incident_error_storm/triage.json`:

```json
[
  {
    "is_incident": true,
    "title": "Error rate spike on admin-server /api/v1/users",
    "severity": 2,
    "effort": "medium",
    "failure_class": null,
    "hypotheses": [
      "keycloak-db connection pool exhaustion from traffic increase",
      "N+1 Keycloak Admin API calls introduced by a recent PR inflate latency under load",
      "Host CPU saturation on the Docker host",
      "Kong upstream misconfiguration dropping healthy targets"
    ],
    "canned_reply": null
  }
]
```

`gateway/tests/test_node_triage.py`:

```python
from pathlib import Path

import pytest
from sqlalchemy import select

from sre_gateway.audit import AuditWriter
from sre_gateway.budget import BudgetEnforcer, load_budgets
from sre_gateway.channels.log import LogChannel
from sre_gateway.db.models import Case, Hypothesis, SignalRow
from sre_gateway.environment import load_environment
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.graph.nodes.triage import make_triage
from sre_gateway.holmes.client import HolmesClient
from sre_gateway.llm.factory import ModelFactory, load_models_config
from sre_gateway.llm.scripted import reset_scripts
from sre_gateway.manifests import load_manifests
from sre_gateway.settings import Settings

ROOT = Path(__file__).parents[2]
SCRIPTS = Path(__file__).parent / "fixtures/scripts/incident_error_storm"


@pytest.fixture
def deps(db, pg_url) -> GraphDeps:
    reset_scripts()
    settings = Settings(database_url=pg_url, config_dir=ROOT / "config")
    return GraphDeps(
        settings=settings, sessionmaker=db, audit=AuditWriter(db),
        models=ModelFactory(load_models_config(ROOT / "config/models.fake.yaml"),
                            script_dir=SCRIPTS),
        manifests=load_manifests(ROOT / "config/agents"),
        budget=BudgetEnforcer(db, load_budgets(ROOT / "config/budgets.yaml")),
        holmes=HolmesClient("http://unused"), channel=LogChannel(),
        environment=load_environment(ROOT / "config/environment.yaml"))


async def _seed_case(db) -> Case:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="grafana:x",
                 thread_id="t", title="raw alert")
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident",
                        fingerprint="grafana:x", is_primary=True,
                        summary="Error rate spike on admin-server /api/v1/users",
                        labels={"service": "admin-server"}))
        await s.commit()
        return c


async def test_triage_seeds_board_and_acks(deps, db):
    case = await _seed_case(db)
    node = make_triage(deps)
    update = await node({"case_id": case.id, "kind": "incident"})
    assert update["severity"] == 2 and update["effort"] == "medium"
    assert [h["hid"] for h in update["hypotheses"]] == ["H1", "H2", "H3", "H4"]
    assert update["round"] == 0 and update["query_hints"] == []
    async with db() as s:
        rows = (await s.execute(select(Hypothesis))).scalars().all()
        refreshed = await s.get(Case, case.id)
    assert len(rows) == 4 and refreshed.severity == 2
    assert deps.channel.sent and "CASE-0001" in deps.channel.sent[0]["text"]
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/test_node_triage.py -q`
Expected: FAIL with `ModuleNotFoundError` (nodes package missing)

- [ ] **Step 5: Implement the triage node**

`src/sre_gateway/graph/nodes/__init__.py`: empty. `src/sre_gateway/graph/nodes/triage.py`:

```python
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from sre_gateway.db.models import Case, Hypothesis, SignalRow
from sre_gateway.environment import EnvironmentConfig
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json
from sre_gateway.manifests import assert_tool_allowed
from sre_gateway.retrieval import search_learnings, search_runbooks

def build_system(env: EnvironmentConfig) -> str:
    """SUT-aware prompts render from the environment descriptor (locked decision 15)."""
    return (
        "You are the triage agent of an SRE team.\n"
        f"{env.prompt_block()}\n"
        "Classify the incoming signal, propose severity (1=worst) and investigation "
        "effort, and seed 3-6 distinct candidate hypotheses. If this is clearly not "
        "an incident or pipeline failure, say so with a short canned reply."
    )


class TriageOut(BaseModel):
    is_incident: bool = True
    title: str
    severity: int = Field(ge=1, le=4, default=3)
    effort: Literal["low", "medium", "high"] = "medium"
    failure_class: Literal["code", "test", "config", "dependency", "infra_runner",
                           "flaky", "permissions"] | None = None
    hypotheses: list[str] = Field(default_factory=list, max_length=6)
    canned_reply: str | None = None


def make_triage(deps: GraphDeps):
    async def triage(state: dict) -> dict:
        case_id = state["case_id"]
        async with deps.sessionmaker() as s:
            case = await s.get(Case, case_id)
            signals = (await s.execute(
                select(SignalRow).where(SignalRow.case_id == case_id)
                .order_by(SignalRow.received_at))).scalars().all()
        primary = next((x for x in signals if x.is_primary), signals[0])

        assert_tool_allowed(deps.manifests, "triage", "learning_search")
        assert_tool_allowed(deps.manifests, "triage", "runbook_search")
        learnings = await search_learnings(deps.sessionmaker, deps.models.embed,
                                           primary.summary)
        runbooks = await search_runbooks(deps.sessionmaker, deps.models.embed,
                                         primary.summary)
        # the query-hint half of the learning loop (spec section 4): decisive
        # queries from similar past cases flow into the evidence workers' prompts
        query_hints = [q for hit in learnings
                       for q in hit.get("decisive_queries", [])][:6]

        tier = deps.manifests["triage"].tier
        model_id, pricing = deps.models.describe(tier)
        user = (
            f"Case {case.display_id} (kind: {case.kind}).\n"
            f"Signals:\n" + "\n".join(
                f"- [{x.source}] {x.summary} labels={x.labels}" for x in signals) +
            f"\n\nPrior learnings (seed hypotheses from confirmed causes):\n{learnings}\n"
            f"Matching runbooks:\n{runbooks}\n"
            f"Pipeline-failure cases must set failure_class."
        )
        out = await call_llm_json(deps.models.chat(tier, "triage"),
                                  system=build_system(deps.environment),
                                  user=user, schema=TriageOut, audit=deps.audit,
                                  node="triage", case_id=case_id,
                                  model_id=model_id, pricing=pricing)

        if not out.is_incident:
            async with deps.sessionmaker() as s:
                await s.execute(update(Case).where(Case.id == case_id).values(
                    status="closed", phase="closed", closed_at=datetime.now(UTC),
                    title=out.title or case.title))
                await s.commit()
            await deps.channel.send(
                f"{case.display_id}: not an incident. {out.canned_reply or ''}".strip())
            return {"non_incident": True}

        hypotheses = [{"hid": f"H{i + 1}", "statement": text, "status": "open",
                       "confidence": 0.25} for i, text in enumerate(out.hypotheses)]
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(
                title=out.title, severity=out.severity, effort=out.effort,
                failure_class=out.failure_class, status="open"))
            for h in hypotheses:
                s.add(Hypothesis(case_id=case_id, hid=h["hid"], statement=h["statement"],
                                 confidence=h["confidence"], round=0))
            await s.commit()

        await deps.channel.send(
            f"Alert received: {out.title}. Opened {case.display_id}, SEV-{out.severity} "
            f"proposed. Investigating ({out.effort} effort).")
        return {"title": out.title, "severity": out.severity, "effort": out.effort,
                "failure_class": out.failure_class, "hypotheses": hypotheses,
                "kind": case.kind, "display_id": case.display_id, "round": 0,
                "query_hints": query_hints, "non_incident": False}

    return triage
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/test_node_triage.py tests/test_retrieval.py -q`
Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add gateway/src/sre_gateway/retrieval.py gateway/src/sre_gateway/graph/nodes gateway/tests
git commit -m "feat(sre-team): pgvector retrieval and triage node seeding the hypothesis board"
```

### Task 16: Plan node and evidence workers

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/plan.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/workers.py`
- Create: `agentic-sre-team/gateway/tests/test_node_workers.py`

**Interfaces:**
- Consumes: `HolmesClient`, `GraphDeps`, `fan_out` policy (Task 14), fixtures (Task 13).
- Produces:
  - `make_plan(deps)`: deterministic node - no LLM. Owns the round counter: increments it as the round starts (`state.round + 1`, triage seeded 0) and persists it to `cases.round` (this is what the UI's "round N of 2" reads), then emits a `plan` custom event describing the fan-out (workers chosen, effort, round). Returns `{round, need_more: False, worker_reports: [], evidence: []}` - the two list keys are `operator.add` no-op appends. The actual dispatch is the `fan_out` conditional edge.
  - `make_worker(deps, domain: str)` for domains `metrics, logs, infra, changes, ci`:
    - Builds the ask prompt whose **first line is `Domain: <domain>`** (the fake server keys on it; real Holmes just reads it as context), followed by scope instructions per domain, the environment descriptor block (`deps.environment.prompt_block()` - no SUT names are hard-coded), the case title/kind, the current hypothesis board, `context_notes`, `query_hints`, and the instruction to return findings JSON (`FindingsOut` schema passed as `response_format`).
    - Calls `deps.holmes.chat(model=deps.models.holmes_model(deps.manifests["workers"].tier), on_event=...)`; each `tool_result` event -> `audit.log_tool` + custom stream event `{"type": "tool_call", "worker": domain, ...}`.
    - Allocates evidence IDs atomically: `UPDATE cases SET evidence_counter = evidence_counter + :n RETURNING evidence_counter`; persists one `EvidenceRow` per Holmes tool call (`eid`, `worker=domain`, `toolset`, `invocation`, `excerpt=result[:2000]`, `hypothesis_links` from findings).
    - Parses `answer.text` as `FindingsOut` (plain `extract_json` + Pydantic - no LLM retry here; Holmes owns its own loop); on any exception returns a degraded report (`{"worker": domain, "degraded": True, "error": str(e)}`) plus a `worker_warning` custom event, never raises (spec section 10).
    - Returns `{"evidence": [...], "worker_reports": [report]}` where report = `{worker, summary, findings: [{hid, direction, note, eids}], proposed_hypotheses, degraded, needs_infra}`.
  - `FindingsOut` schema: `summary: str`, `findings: list[{hid: str | None, direction: "for"|"against", note: str, evidence_idx: list[int]}]`, `proposed_hypotheses: list[str]`, `needs_infra: bool = False` (pipeline ci worker sets it when runner/registry issues surface).
  - Worker prompts per domain (constants in `workers.py`), scoping by prompt per spec section 4; container/service names come from the environment descriptor, never from the scope text:
    - metrics: Prometheus (PromQL: rates, latencies, saturation, alert-rule state) + grafana/tempo traces (`tempo_fetch_traces_comparative_sample` compares fast/slow/typical traces to localize latency; TraceQL search) + Grafana MCP tools (dashboards, alert rules).
    - logs: Loki + elasticsearch/data (OpenSearch-compatible log/document search): error patterns, slow-call patterns, first-occurrence timestamps.
    - infra: Docker (container state, restarts, resource stats) + Postgres (DB health) + elasticsearch/cluster (cluster status, shard allocation, node/index stats, **query-latency investigation** - the user-directed ES cluster-health mission) + openshift/* on kubernetes/openshift platforms.
    - changes: GitHub/GitLab toolsets. Most incidents are change-induced: recent commits, merged PRs/MRs, diffs touching the implicated services.
    - ci: pipeline-failure investigation: failed job logs with exit codes, workflow/.gitlab-ci.yml config, the triggering diff, and run history of the same job across recent commits and retries (flaky detection).

- [ ] **Step 1: Write the failing worker tests**

`gateway/tests/test_node_workers.py` (reuses the `deps` fixture pattern from `test_node_triage.py` - move that fixture into `tests/conftest.py` now, parameterized with a `holmes_client` built from the fake app + `FAKE_HOLMES_DIR` env, so every graph test shares it):

```python
from sqlalchemy import select

from sre_gateway.db.models import Case, EvidenceRow
from sre_gateway.graph.nodes.workers import make_worker


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error rate spike on admin-server")
        s.add(c)
        await s.commit()
        return c


async def test_metrics_worker_maps_tool_calls_to_evidence(deps, db):
    case = await _seed(db)
    worker = make_worker(deps, "metrics")
    state = {"case_id": case.id, "kind": "incident", "title": case.title,
             "hypotheses": [{"hid": "H1", "statement": "pool exhaustion", "status": "open"},
                            {"hid": "H3", "statement": "cpu saturation", "status": "open"}]}
    update = await worker(state)
    report = update["worker_reports"][0]
    assert report["worker"] == "metrics" and not report["degraded"]
    assert {e["eid"] for e in update["evidence"]} == {"E1", "E2"}
    findings = {f["hid"]: f for f in report["findings"]}
    assert findings["H3"]["direction"] == "against"
    assert findings["H1"]["eids"] == ["E1"]
    async with db() as s:
        rows = (await s.execute(select(EvidenceRow))).scalars().all()
        refreshed = await s.get(Case, case.id)
    assert len(rows) == 2 and refreshed.tool_calls == 2
    assert refreshed.evidence_counter == 2


async def test_parallel_eid_allocation_never_collides(deps, db):
    case = await _seed(db)
    import asyncio

    state = {"case_id": case.id, "kind": "incident", "title": case.title, "hypotheses": []}
    updates = await asyncio.gather(make_worker(deps, "metrics")(state),
                                   make_worker(deps, "logs")(state))
    eids = [e["eid"] for u in updates for e in u["evidence"]]
    assert len(eids) == len(set(eids)) == 4


async def test_holmes_failure_degrades_not_raises(deps, db, monkeypatch):
    case = await _seed(db)
    worker = make_worker(deps, "infra")
    monkeypatch.setenv("FAKE_HOLMES_DIR", "/nonexistent")  # fake server now 404s
    update = await worker({"case_id": case.id, "kind": "incident", "title": "x",
                           "hypotheses": []})
    report = update["worker_reports"][0]
    assert report["degraded"] and update["evidence"] == []
```

Note: node functions call `get_stream_writer()`; outside a graph run LangGraph provides a no-op or raises - wrap writer acquisition in `graph/deps.py` with a helper `def stream_writer():` returning a no-op lambda on `RuntimeError`, and use it everywhere (guarded, workers, plan). Add that helper in this task:

```python
def stream_writer():
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except RuntimeError:
        return lambda _event: None
```

(Also switch `guarded` to use it.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_node_workers.py -q`
Expected: FAIL with `ModuleNotFoundError` (workers module missing)

- [ ] **Step 3: Implement plan and workers**

`src/sre_gateway/graph/nodes/plan.py`:

```python
from sqlalchemy import update

from sre_gateway.db.models import Case
from sre_gateway.graph.deps import GraphDeps, stream_writer
from sre_gateway.graph.routers import fan_out


def make_plan(deps: GraphDeps):
    async def plan(state: dict) -> dict:
        writer = stream_writer()
        this_round = state.get("round", 0) + 1
        workers = [s.node for s in fan_out({**state, "round": this_round})]
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == state["case_id"])
                            .values(round=this_round))
            await s.commit()
        writer({"type": "plan", "workers": workers,
                "effort": state.get("effort", "medium"), "round": this_round})
        return {"round": this_round, "need_more": False,
                "worker_reports": [], "evidence": []}

    return plan
```

`src/sre_gateway/graph/nodes/workers.py`:

```python
import json
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from sre_gateway.db.models import EvidenceRow
from sre_gateway.graph.deps import GraphDeps, stream_writer
from sre_gateway.llm.json_call import extract_json

SCOPES = {
    "metrics": "Use the Prometheus toolset for PromQL (rates, latencies, saturation, "
               "alert-rule state), the Tempo toolset for traces - "
               "tempo_fetch_traces_comparative_sample localizes latency by comparing "
               "fast/slow/typical traces, TraceQL search finds affected routes - and "
               "the Grafana MCP tools for dashboards and alert rules.",
    "logs": "Use the Loki toolset and elasticsearch/data (OpenSearch-compatible "
            "document/log search) to find error patterns, slow-call patterns and "
            "first-occurrence timestamps across app and audit logs.",
    "infra": "Use the Docker toolset (container state, restarts, resource stats), the "
             "Postgres toolset (DB health), and elasticsearch/cluster for search-store "
             "health: cluster status, shard allocation, node/index stats and query "
             "latency. On kubernetes/openshift platforms use the openshift/* toolsets "
             "(describe, events, logs, top).",
    "changes": "Use only GitHub / GitLab toolsets. Most incidents are change-induced: "
               "list recent commits and merged PRs/MRs, inspect diffs touching the "
               "implicated services, correlate merge times with symptom onset.",
    "ci": "Pipeline-failure investigation via GitHub / GitLab toolsets only: fetch the "
          "failed job logs with exit codes, the pipeline config (workflow YAML or "
          ".gitlab-ci.yml), the triggering diff, and the run history of the same job "
          "across recent commits and retries to detect flakiness. Set needs_infra=true "
          "only if evidence points at runners or registries.",
}


class Finding(BaseModel):
    hid: str | None = None
    direction: Literal["for", "against"] = "for"
    note: str
    evidence_idx: list[int] = Field(default_factory=list)


class FindingsOut(BaseModel):
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    proposed_hypotheses: list[str] = Field(default_factory=list)
    needs_infra: bool = False


def _board_text(hypotheses: list[dict]) -> str:
    return "\n".join(f"- {h['hid']} [{h.get('status', 'open')}] {h['statement']}"
                     for h in hypotheses) or "(no hypotheses yet)"


def make_worker(deps: GraphDeps, domain: str):
    async def worker(state: dict) -> dict:
        writer = stream_writer()
        case_id = state["case_id"]
        report = {"worker": domain, "summary": "", "findings": [],
                  "proposed_hypotheses": [], "degraded": False, "needs_infra": False}
        try:
            ask = (
                f"Domain: {domain}\n{SCOPES[domain]}\n\n"
                f"{deps.environment.prompt_block()}\n\n"
                f"Case: {state.get('title', '')} (kind: {state.get('kind', 'incident')})\n"
                f"Hypothesis board:\n{_board_text(state.get('hypotheses', []))}\n"
                f"Operator context notes: {state.get('context_notes', [])}\n"
                f"Decisive queries from similar past cases (try these first): "
                f"{state.get('query_hints', [])}\n\n"
                "Investigate this domain. Tag every finding to a hypothesis id (hid) as "
                "for/against with evidence_idx = indexes into your own tool calls, and "
                "propose new hypotheses if the evidence suggests one."
            )

            async def on_event(event: dict) -> None:
                writer({"type": "tool_call", "worker": domain,
                        "phase": event["type"], "tool_name": event.get("tool_name", ""),
                        "toolset": event.get("toolset", ""),
                        "description": event.get("description", "")})
                if event["type"] == "tool_result":
                    await deps.audit.log_tool(case_id, worker=domain,
                                              toolset=event.get("toolset", ""),
                                              invocation=event.get("description", ""))

            tier = deps.manifests["workers"].tier
            answer = await deps.holmes.chat(
                ask, model=deps.models.holmes_model(tier),
                response_format=FindingsOut.model_json_schema(), on_event=on_event)

            # atomic evidence-id allocation across parallel workers
            n = len(answer.tool_calls)
            evidence: list[dict] = []
            if n:
                async with deps.sessionmaker() as s:
                    start = (await s.execute(text(
                        "UPDATE cases SET evidence_counter = evidence_counter + :n "
                        "WHERE id = :id RETURNING evidence_counter"),
                        {"n": n, "id": case_id})).scalar_one() - n
                    await s.commit()
                out = FindingsOut.model_validate(extract_json(answer.text))
                idx_to_eid = {i: f"E{start + i + 1}" for i in range(n)}
                links: dict[str, list] = {eid: [] for eid in idx_to_eid.values()}
                findings = []
                for f in out.findings:
                    eids = [idx_to_eid[i] for i in f.evidence_idx if i in idx_to_eid]
                    findings.append({"hid": f.hid, "direction": f.direction,
                                     "note": f.note, "eids": eids})
                    for eid in eids:
                        links[eid].append({"hid": f.hid, "direction": f.direction})
                async with deps.sessionmaker() as s:
                    for i, tc in enumerate(answer.tool_calls):
                        eid = idx_to_eid[i]
                        s.add(EvidenceRow(case_id=case_id, eid=eid, worker=domain,
                                          toolset=tc.toolset or tc.tool_name,
                                          invocation=tc.invocation or tc.description,
                                          excerpt=tc.result[:2000],
                                          hypothesis_links=links[eid]))
                        evidence.append({"eid": eid, "worker": domain,
                                         "toolset": tc.toolset or tc.tool_name,
                                         "invocation": tc.invocation or tc.description,
                                         "excerpt": tc.result[:2000],
                                         "hypothesis_links": links[eid]})
                    await s.commit()
                report.update(summary=out.summary, findings=findings,
                              proposed_hypotheses=out.proposed_hypotheses,
                              needs_infra=out.needs_infra)
            else:
                out = FindingsOut.model_validate(extract_json(answer.text))
                report.update(summary=out.summary,
                              proposed_hypotheses=out.proposed_hypotheses)
                evidence = []
            return {"evidence": evidence, "worker_reports": [report]}
        except Exception as err:  # evidence-gathering degradation, never fatal (spec 10)
            report.update(degraded=True, error=str(err)[:500])
            writer({"type": "worker_warning", "worker": domain, "error": str(err)[:200]})
            await deps.audit.log("tool_call", actor=domain, case_id=case_id,
                                 degraded=True, error=str(err)[:500])
            return {"evidence": [], "worker_reports": [report]}

    return worker
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_node_workers.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add gateway/src/sre_gateway/graph gateway/tests
git commit -m "feat(sre-team): plan node and holmes-backed evidence workers with atomic evidence ids"
```

### Task 17: Synthesize node

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/synthesize.py`
- Create: `agentic-sre-team/gateway/tests/test_node_synthesize.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/synthesize.json`

**Interfaces:**
- Consumes: worker reports/evidence in state, `Hypothesis` rows, `call_llm_json`, `Channel`.
- Produces:
  - `make_synthesize(deps)`: re-reads human-context signals (`attach_reason='human_context'`) newer than the round start and appends them to `context_notes`; picks the tier deterministically (**frontier when `severity <= 2` or the current best confidence `< 0.5`, else medium** - the spec's escalation discipline); calls the LLM with the board + worker reports + evidence index; upserts `Hypothesis` rows (existing by `hid`, new ones `H<n+1>` from `new_hypotheses`); posts the early-findings status update via `deps.channel`; returns `{hypotheses, need_more, failure_class?, context_notes}` (the plan node owns the round counter - synthesize never touches it).
  - `SynthesizeOut` schema: `board: list[{hid, status: "open"|"supported"|"refuted", confidence: float, note: str}]`, `new_hypotheses: list[str]`, `need_more: bool`, `focus: str | None`, `failure_class: str | None`, `status_update: str`.

- [ ] **Step 1: Write the script fixture**

`gateway/tests/fixtures/scripts/incident_error_storm/synthesize.json`:

```json
[
  {
    "board": [
      {"hid": "H1", "status": "open", "confidence": 0.31, "note": "pool elevated but explained by H2"},
      {"hid": "H2", "status": "supported", "confidence": 0.78, "note": "N+1 admin api calls from PR #212"},
      {"hid": "H3", "status": "refuted", "confidence": 0.05, "note": "host cpu flat at 22%"},
      {"hid": "H4", "status": "open", "confidence": 0.1, "note": "no kong config change found"}
    ],
    "new_hypotheses": [],
    "need_more": false,
    "focus": null,
    "failure_class": null,
    "status_update": "Strongest hypothesis: N+1 Admin API call pattern from PR #212 (confidence 0.78). Full RCA next."
  }
]
```

- [ ] **Step 2: Write the failing test**

`gateway/tests/test_node_synthesize.py`:

```python
from sqlalchemy import select

from sre_gateway.db.models import Case, Hypothesis
from sre_gateway.graph.nodes.synthesize import make_synthesize


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 severity=3, title="p95 climbing")
        s.add(c)
        await s.flush()
        for i, stmt in enumerate(["pool exhaustion", "n+1 admin api", "cpu", "kong"], 1):
            s.add(Hypothesis(case_id=c.id, hid=f"H{i}", statement=stmt, round=0))
        await s.commit()
        return c


async def test_synthesize_updates_board_and_posts_status(deps, db):
    case = await _seed(db)
    node = make_synthesize(deps)
    state = {"case_id": case.id, "severity": 3, "round": 1,
             "hypotheses": [{"hid": f"H{i}", "statement": s, "status": "open",
                             "confidence": 0.25}
                            for i, s in enumerate(["pool", "n+1", "cpu", "kong"], 1)],
             "worker_reports": [{"worker": "metrics", "summary": "5xx up",
                                 "findings": [], "degraded": False}],
             "evidence": [{"eid": "E1", "excerpt": "5xx 18%"}]}
    update = await node(state)
    assert update["need_more"] is False
    board = {h["hid"]: h for h in update["hypotheses"]}
    assert board["H2"]["status"] == "supported" and board["H3"]["status"] == "refuted"
    async with db() as s:
        h2 = (await s.execute(select(Hypothesis).where(Hypothesis.hid == "H2"))).scalar_one()
    assert h2.status == "supported" and abs(h2.confidence - 0.78) < 1e-6
    assert any("0.78" in m["text"] or "N+1" in m["text"] for m in deps.channel.sent)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_node_synthesize.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement**

`src/sre_gateway/graph/nodes/synthesize.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from sre_gateway.db.models import Hypothesis, SignalRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = (
    "You are the synthesis agent. Update the hypothesis board from the workers' findings: "
    "mark each hypothesis supported / refuted / open with a confidence in [0,1] grounded "
    "in the evidence ids. Decide whether the evidence suffices for an RCA or one more "
    "bounded investigation round is needed (need_more). Write a one-sentence status "
    "update for the ops channel. For pipeline-failure cases you may revise failure_class."
)


class BoardEntry(BaseModel):
    hid: str
    status: Literal["open", "supported", "refuted"] = "open"
    confidence: float = Field(ge=0, le=1, default=0.0)
    note: str = ""


class SynthesizeOut(BaseModel):
    board: list[BoardEntry]
    new_hypotheses: list[str] = Field(default_factory=list)
    need_more: bool = False
    focus: str | None = None
    failure_class: Literal["code", "test", "config", "dependency", "infra_runner",
                           "flaky", "permissions"] | None = None
    status_update: str = ""


def make_synthesize(deps: GraphDeps):
    async def synthesize(state: dict) -> dict:
        case_id = state["case_id"]
        hypotheses = list(state.get("hypotheses", []))
        best = max((h.get("confidence", 0.0) for h in hypotheses), default=0.0)
        tier = ("frontier" if state.get("severity", 3) <= 2 or best < 0.5
                else deps.manifests["synthesize"].tier)

        async with deps.sessionmaker() as s:  # mid-flight human context (Add context)
            notes = (await s.execute(
                select(SignalRow.summary).where(SignalRow.case_id == case_id,
                                                SignalRow.attach_reason == "human_context")
            )).scalars().all()

        model_id, pricing = deps.models.describe(tier)
        reports = "\n".join(
            f"- [{r['worker']}]{' DEGRADED: ' + r.get('error', '') if r.get('degraded') else ''} "
            f"{r.get('summary', '')} findings={r.get('findings', [])} "
            f"proposed={r.get('proposed_hypotheses', [])}"
            for r in state.get("worker_reports", []))
        evidence = "\n".join(f"- {e['eid']} [{e.get('toolset', '')}] {e.get('excerpt', '')[:300]}"
                             for e in state.get("evidence", []))
        user = (
            f"Round {state.get('round', 1)} of 2. Case: {state.get('title', '')} "
            f"(kind {state.get('kind', 'incident')}, SEV-{state.get('severity', 3)}).\n"
            f"Board:\n" + "\n".join(
                f"- {h['hid']} [{h.get('status', 'open')} conf={h.get('confidence', 0)}] "
                f"{h['statement']}" for h in hypotheses) +
            f"\nWorker reports:\n{reports}\nEvidence:\n{evidence}\n"
            f"Human context notes: {list(state.get('context_notes', [])) + list(notes)}\n"
            "Degraded workers mean missing evidence: reflect that in confidence."
        )
        out = await call_llm_json(deps.models.chat(tier, "synthesize"), system=SYSTEM,
                                  user=user, schema=SynthesizeOut, audit=deps.audit,
                                  node="synthesize", case_id=case_id,
                                  model_id=model_id, pricing=pricing)

        by_hid = {h["hid"]: h for h in hypotheses}
        for entry in out.board:
            if entry.hid in by_hid:
                by_hid[entry.hid].update(status=entry.status, confidence=entry.confidence,
                                         note=entry.note)
        next_index = len(by_hid)
        for stmt in out.new_hypotheses:
            next_index += 1
            by_hid[f"H{next_index}"] = {"hid": f"H{next_index}", "statement": stmt,
                                        "status": "open", "confidence": 0.25, "note": ""}
        merged = list(by_hid.values())

        async with deps.sessionmaker() as s:
            for h in merged:
                existing = (await s.execute(
                    select(Hypothesis).where(Hypothesis.case_id == case_id,
                                             Hypothesis.hid == h["hid"]))).scalar_one_or_none()
                if existing:
                    existing.status, existing.confidence = h["status"], h["confidence"]
                    existing.round = state.get("round", 1)
                else:
                    s.add(Hypothesis(case_id=case_id, hid=h["hid"],
                                     statement=h["statement"], status=h["status"],
                                     confidence=h["confidence"],
                                     round=state.get("round", 1)))
            await s.commit()

        if out.status_update:
            await deps.channel.send(
                f"Early findings on {state.get('display_id', case_id)}: {out.status_update}")

        update: dict = {"hypotheses": merged, "need_more": out.need_more,
                        "context_notes": list(notes)}
        if out.failure_class:
            update["failure_class"] = out.failure_class
        return update

    return synthesize
```

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_node_synthesize.py -q`
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add gateway/src/sre_gateway/graph/nodes/synthesize.py gateway/tests
git commit -m "feat(sre-team): synthesize node with board updates, bounded rounds, escalation tiering"
```

### Task 18: RCA node and citation verifier

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/rca.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/verify.py`
- Create: `agentic-sre-team/gateway/tests/test_node_rca_verify.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/rca.json`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/verify.json`

**Interfaces:**
- Consumes: evidence + hypotheses (state and DB), `call_llm_json`, `Artifact` model.
- Produces:
  - `RcaOut` schema (in `nodes/rca.py`): `mitigation_md: str`, `causal_chain: list[{step, eids}]`, `blast_radius_md: str`, `timeline: list[{ts, text, eids}]`, `alternatives: list[{statement, why_rejected, eids}]`, `monitoring_gaps_md: str`, `claims: list[{text, eids}]`, `confidence: float`.
  - `render_rca_md(out: RcaOut) -> str` - deterministic renderer, mitigation first (Google IMAG), `[E#]` citation chips inline.
  - `make_rca(deps)`: reads all `EvidenceRow`s + board from DB; frontier tier; prompt includes reviewer rejection notes / verify failures from `context_notes`; persists `Artifact(kind="rca", version=prev+1, structured=..., body_md=render, model_id, cost_usd)` and returns `{"rca": {"artifact_id", "version", "structured", "confidence"}, "repair_used": bool(state.get("verification"))}`.
    - `repair_used` semantics: the first draft has never seen a verification (`False`); a redraft entered from a failed verification carries `True`, which makes `route_after_verify` stop after exactly one repair loop.
  - `make_verify(deps)`: small tier. Code pre-check first: every cited eid (claims, causal chain, timeline, alternatives) must exist for the case - missing ids become failures without any LLM call. Then one LLM call checks claim-vs-excerpt support (`VerifyOut: {results: [{idx, supported, reason}]}`). Persists `artifacts.verification = {"verified", "checked", "failures": [{claim, reason}]}` and returns `{"verification": ...}` plus, on failure, `context_notes` describing the failures for the redraft.

- [ ] **Step 1: Write script fixtures**

`gateway/tests/fixtures/scripts/incident_error_storm/rca.json` (two identical entries so the gate-rejection test in Task 20 can redraft; the happy path consumes only the first):

```json
[
  {
    "mitigation_md": "Revert PR #212 OR feature-flag role badges off. [E1]",
    "causal_chain": [
      {"step": "PR #212 adds per-user Admin API call in group listing", "eids": ["E1"]},
      {"step": "N+1 Keycloak Admin API calls inflate latency under load", "eids": ["E2"]}
    ],
    "blast_radius_md": "All admin-console user listing routes; login unaffected.",
    "timeline": [{"ts": "2026-07-11T14:02:00Z", "text": "5xx ratio exceeds 5%", "eids": ["E1"]}],
    "alternatives": [
      {"statement": "Host CPU saturation", "why_rejected": "host CPU flat at 22%", "eids": ["E2"]}
    ],
    "monitoring_gaps_md": "No per-route Admin API call-count metric.",
    "claims": [
      {"text": "The 5xx spike began at 14:02 and correlates with PR #212", "eids": ["E1"]},
      {"text": "Host CPU stayed flat, ruling out saturation", "eids": ["E2"]}
    ],
    "confidence": 0.81
  },
  { "mitigation_md": "Revert PR #212.", "causal_chain": [{"step": "same as v1", "eids": ["E1"]}],
    "blast_radius_md": "same", "timeline": [], "alternatives": [],
    "monitoring_gaps_md": "", "claims": [{"text": "5xx spike correlates with PR #212", "eids": ["E1"]}],
    "confidence": 0.8 }
]
```

`gateway/tests/fixtures/scripts/incident_error_storm/verify.json` (two entries, both passing):

```json
[
  {"results": [{"idx": 0, "supported": true, "reason": "excerpt shows 18% at 14:02"},
               {"idx": 1, "supported": true, "reason": "cpu flat in E2"}]},
  {"results": [{"idx": 0, "supported": true, "reason": "ok"}]}
]
```

- [ ] **Step 2: Write the failing tests**

`gateway/tests/test_node_rca_verify.py`:

```python
from sqlalchemy import select

from sre_gateway.db.models import Artifact, Case, EvidenceRow
from sre_gateway.graph.nodes.rca import make_rca, render_rca_md
from sre_gateway.graph.nodes.verify import make_verify


async def _seed(db, eids=("E1", "E2")):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error spike", severity=2)
        s.add(c)
        await s.flush()
        for eid in eids:
            s.add(EvidenceRow(case_id=c.id, eid=eid, worker="metrics",
                              toolset="prometheus", invocation="q", excerpt="18% at 14:02"))
        await s.commit()
        return c


async def test_rca_persists_versioned_artifact(deps, db):
    case = await _seed(db)
    update = await make_rca(deps)({"case_id": case.id, "title": case.title,
                                   "severity": 2, "hypotheses": [], "verification": None})
    assert update["rca"]["version"] == 1 and update["repair_used"] is False
    async with db() as s:
        art = (await s.execute(select(Artifact))).scalars().one()
    assert art.kind == "rca" and "Immediate mitigation" in art.body_md
    assert art.structured["confidence"] == 0.81


async def test_verify_passes_when_citations_exist(deps, db):
    case = await _seed(db)
    rca_update = await make_rca(deps)({"case_id": case.id, "title": "t", "severity": 2,
                                       "hypotheses": [], "verification": None})
    update = await make_verify(deps)({"case_id": case.id, **rca_update})
    assert update["verification"]["verified"] is True
    assert update["verification"]["checked"] == 2
    async with db() as s:
        art = await s.get(Artifact, rca_update["rca"]["artifact_id"])
    assert art.verification["verified"] is True


async def test_verify_fails_on_missing_eid_without_llm(deps, db):
    case = await _seed(db, eids=("E1",))  # E2 cited by the script but absent
    rca_update = await make_rca(deps)({"case_id": case.id, "title": "t", "severity": 2,
                                       "hypotheses": [], "verification": None})
    update = await make_verify(deps)({"case_id": case.id, **rca_update})
    v = update["verification"]
    assert v["verified"] is False
    assert any("E2" in f["reason"] for f in v["failures"])
    assert update["context_notes"]


def test_render_puts_mitigation_first():
    from sre_gateway.graph.nodes.rca import RcaOut

    out = RcaOut(mitigation_md="do X", causal_chain=[], blast_radius_md="",
                 claims=[], confidence=0.5)
    md = render_rca_md(out)
    assert md.index("Immediate mitigation") < md.index("Root cause")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_node_rca_verify.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement rca**

`src/sre_gateway/graph/nodes/rca.py`:

```python
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from sre_gateway.db.models import Artifact, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = (
    "You are the RCA agent. Produce a root-cause analysis. Order matters: immediate "
    "mitigation FIRST (a reviewer under pressure reads only that), then the root cause "
    "as a causal chain, blast radius, incident timeline, ranked alternatives with why "
    "they were rejected, and monitoring gaps. EVERY claim must cite evidence ids (eids) "
    "that exist in the evidence list. Confidence reflects the hypothesis board."
)


class CausalStep(BaseModel):
    step: str
    eids: list[str] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    ts: str
    text: str
    eids: list[str] = Field(default_factory=list)


class Alternative(BaseModel):
    statement: str
    why_rejected: str
    eids: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    eids: list[str] = Field(default_factory=list)


class RcaOut(BaseModel):
    mitigation_md: str
    causal_chain: list[CausalStep] = Field(default_factory=list)
    blast_radius_md: str = ""
    timeline: list[TimelineEntry] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    monitoring_gaps_md: str = ""
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


def _cite(eids: list[str]) -> str:
    return " ".join(f"[{e}]" for e in eids)


def render_rca_md(out: RcaOut) -> str:
    lines = ["## Immediate mitigation", out.mitigation_md, "", "## Root cause"]
    lines += [f"{i + 1}. {s.step} {_cite(s.eids)}" for i, s in enumerate(out.causal_chain)]
    lines += ["", "## Blast radius", out.blast_radius_md, "", "## Timeline"]
    lines += [f"- {t.ts} - {t.text} {_cite(t.eids)}" for t in out.timeline]
    lines += ["", "## Alternatives considered and rejected"]
    lines += [f"- {a.statement}: {a.why_rejected} {_cite(a.eids)}" for a in out.alternatives]
    lines += ["", "## Monitoring gaps", out.monitoring_gaps_md]
    return "\n".join(lines)


def make_rca(deps: GraphDeps):
    async def rca(state: dict) -> dict:
        case_id = state["case_id"]
        async with deps.sessionmaker() as s:
            evidence = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id)
                .order_by(EvidenceRow.eid))).scalars().all()
            prev = (await s.execute(
                select(func.max(Artifact.version)).where(Artifact.case_id == case_id,
                                                         Artifact.kind == "rca"))
                    ).scalar_one() or 0

        tier = deps.manifests["rca"].tier
        model_id, pricing = deps.models.describe(tier)
        ev_text = "\n".join(f"- {e.eid} [{e.toolset}] query: {e.invocation[:200]} -> "
                            f"{e.excerpt[:300]}" for e in evidence)
        board = "\n".join(f"- {h['hid']} [{h.get('status')}] conf={h.get('confidence')} "
                          f"{h['statement']}" for h in state.get("hypotheses", []))
        user = (f"Case: {state.get('title', '')} (SEV-{state.get('severity', 3)}, "
                f"kind {state.get('kind', 'incident')}).\nHypothesis board:\n{board}\n"
                f"Evidence:\n{ev_text}\n"
                f"Reviewer / verifier notes to address: {state.get('context_notes', [])}")
        out = await call_llm_json(deps.models.chat(tier, "rca"), system=SYSTEM, user=user,
                                  schema=RcaOut, audit=deps.audit, node="rca",
                                  case_id=case_id, model_id=model_id, pricing=pricing)

        async with deps.sessionmaker() as s:
            art = Artifact(case_id=case_id, kind="rca", version=prev + 1,
                           structured=out.model_dump(), body_md=render_rca_md(out),
                           model_id=model_id)
            s.add(art)
            await s.commit()
            artifact_id = art.id
        return {"rca": {"artifact_id": artifact_id, "version": prev + 1,
                        "structured": out.model_dump(), "confidence": out.confidence},
                "repair_used": bool(state.get("verification"))}

    return rca
```

- [ ] **Step 5: Implement verify**

`src/sre_gateway/graph/nodes/verify.py`:

```python
from pydantic import BaseModel, Field
from sqlalchemy import select

from sre_gateway.db.models import Artifact, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = ("You are the citation verifier. For each claim, decide whether the cited "
          "evidence excerpts actually support it. Be strict: unsupported means the "
          "excerpt does not state or imply the claim.")


class ClaimCheck(BaseModel):
    idx: int
    supported: bool
    reason: str = ""


class VerifyOut(BaseModel):
    results: list[ClaimCheck] = Field(default_factory=list)


def _cited_eids(structured: dict) -> set[str]:
    eids: set[str] = set()
    for key in ("causal_chain", "timeline", "alternatives", "claims"):
        for item in structured.get(key, []):
            eids.update(item.get("eids", []))
    return eids


def make_verify(deps: GraphDeps):
    async def verify(state: dict) -> dict:
        case_id = state["case_id"]
        structured = state["rca"]["structured"]
        async with deps.sessionmaker() as s:
            rows = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id))).scalars().all()
        by_eid = {r.eid: r.excerpt for r in rows}

        failures = [{"claim": f"citation {eid}",
                     "reason": f"cited evidence {eid} does not exist"}
                    for eid in sorted(_cited_eids(structured) - set(by_eid))]

        claims = structured.get("claims", [])
        if claims and not failures:
            tier = deps.manifests["verify"].tier
            model_id, pricing = deps.models.describe(tier)
            listing = "\n".join(
                f"{i}. CLAIM: {c['text']}\n   EVIDENCE: " +
                " | ".join(f"{e}: {by_eid.get(e, '')[:300]}" for e in c.get("eids", []))
                for i, c in enumerate(claims))
            out = await call_llm_json(deps.models.chat(tier, "verify"), system=SYSTEM,
                                      user=f"Verify each claim:\n{listing}",
                                      schema=VerifyOut, audit=deps.audit, node="verify",
                                      case_id=case_id, model_id=model_id, pricing=pricing)
            for r in out.results:
                if not r.supported and r.idx < len(claims):
                    failures.append({"claim": claims[r.idx]["text"], "reason": r.reason})

        verification = {"verified": not failures, "checked": len(claims),
                        "failures": failures}
        async with deps.sessionmaker() as s:
            art = await s.get(Artifact, state["rca"]["artifact_id"])
            art.verification = verification
            await s.commit()

        update: dict = {"verification": verification}
        if failures:
            update["context_notes"] = [
                "Citation verification failed; fix these in the redraft: "
                + "; ".join(f"{f['claim']} ({f['reason']})" for f in failures)]
        return update

    return verify
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/test_node_rca_verify.py -q`
Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
git add gateway/src/sre_gateway/graph/nodes gateway/tests
git commit -m "feat(sre-team): rca artifact node and citation verifier with single repair loop"
```

### Task 19: HITL gates, remediate, publish, park

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/gates.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/remediate.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/publish.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/park.py`
- Create: `agentic-sre-team/gateway/tests/test_node_remediate_publish.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/remediate.json`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/learnings.json`

**Interfaces:**
- Consumes: `interrupt` (langgraph), artifacts, `index_runbook`/`index_learning`, `Channel`.
- Produces:
  - `make_gate(deps, gate: "rca"|"runbook")`. **Interrupt semantics (critical):** on resume, LangGraph re-executes the node from the top, so everything before `interrupt()` must be idempotent (the status UPDATE is). Everything after `interrupt()` runs exactly once. Resume payload: `{"decision": "approve"|"approve_with_edits"|"reject", "decided_by": str, "channel": "ui"|"telegram", "edited_body_md": str | None, "annotation": str}`. After resume the node stores the `Approval` row (with a unified diff when edited), sets `artifacts.body_edited_md`, flips case status back to `open`, audits, and returns `{"gate_<gate>": decision}`; on reject it also returns `context_notes` with the annotation, and for gate 1 resets `{"verification": None, "repair_used": False}` so the redraft gets a fresh repair loop.
  - `make_remediate(deps)`: frontier tier; consumes the approved RCA (edited body when present) + evidence; produces `RunbookOut`: `pre_checks: list[str]`, `steps: list[{title, detail, command|None}]`, `post_checks: list[str]`, `rollback: list[str]`, `risk_notes_md: str`, `patch_files: list[{path, content}] | None` (required in the prompt for pipeline-failure cases). Persists `Artifact(kind="runbook")`, returns `{"runbook": {artifact_id, version, structured}}`. **No tools are bound to this node; it never executes anything** (spec section 4).
  - `make_publish(deps)`: sends both artifacts to the channel; indexes the approved runbook (`index_runbook`); writes the case learning via the small tier (`LearningOut: {signal_signature, confirmed_root_cause, decisive_queries, false_leads}` -> `index_learning`); closes the case (`status=closed, phase=closed, closed_at`); audits `publish`.
  - `make_park(deps)`: sets `status=needs_human`, `halt_reason` from `state["halt"]`, pages the channel, audits `budget`/`needs_human`.

- [ ] **Step 1: Write script fixtures**

`remediate.json`:

```json
[
  {
    "pre_checks": ["Confirm 5xx ratio still elevated on the Kong dashboard"],
    "steps": [
      {"title": "Feature-flag role badges off", "detail": "Set SHOW_ROLE_BADGES=false on admin-server", "command": "docker exec spectre-admin-server printenv SHOW_ROLE_BADGES"},
      {"title": "Or revert PR #212", "detail": "git revert then redeploy admin-server", "command": null}
    ],
    "post_checks": ["5xx ratio back under 1% for 10m"],
    "rollback": ["Re-enable the flag"],
    "risk_notes_md": "Read-only mitigation; no data migration involved.",
    "patch_files": null
  }
]
```

`learnings.json`:

```json
[
  {
    "signal_signature": "admin-server 5xx spike via Kong after group-listing change",
    "confirmed_root_cause": "N+1 Keycloak Admin API calls introduced by PR #212",
    "decisive_queries": ["kong_http_requests_total 5xx ratio", "github recent PR diff scan"],
    "false_leads": ["Host CPU saturation", "Kong upstream misconfiguration"]
  }
]
```

- [ ] **Step 2: Write the failing tests**

`gateway/tests/test_node_remediate_publish.py`:

```python
from sqlalchemy import select

from sre_gateway.db.models import Artifact, Case, CaseLearning, Runbook
from sre_gateway.graph.nodes.remediate import make_remediate
from sre_gateway.graph.nodes.publish import make_publish


async def _seed_with_rca(db, deps):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error spike", severity=2)
        s.add(c)
        await s.flush()
        art = Artifact(case_id=c.id, kind="rca", version=1, body_md="## rca",
                       structured={"claims": [], "confidence": 0.8})
        s.add(art)
        await s.commit()
        return c, art


async def test_remediate_persists_runbook(deps, db):
    case, rca_art = await _seed_with_rca(db, deps)
    update = await make_remediate(deps)({
        "case_id": case.id, "kind": "incident", "title": case.title,
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured}})
    assert update["runbook"]["version"] == 1
    async with db() as s:
        art = await s.get(Artifact, update["runbook"]["artifact_id"])
    assert art.kind == "runbook" and "Feature-flag role badges off" in art.body_md


async def test_publish_closes_indexes_and_learns(deps, db):
    case, rca_art = await _seed_with_rca(db, deps)
    rb_update = await make_remediate(deps)({
        "case_id": case.id, "kind": "incident", "title": case.title,
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured}})
    await make_publish(deps)({
        "case_id": case.id, "display_id": "CASE-0001", "title": case.title,
        "hypotheses": [{"hid": "H2", "statement": "n+1", "status": "supported",
                        "confidence": 0.8},
                       {"hid": "H3", "statement": "cpu", "status": "refuted",
                        "confidence": 0.05}],
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured},
        "runbook": rb_update["runbook"]})
    async with db() as s:
        refreshed = await s.get(Case, case.id)
        runbooks = (await s.execute(select(Runbook))).scalars().all()
        learnings = (await s.execute(select(CaseLearning))).scalars().all()
    assert refreshed.status == "closed" and refreshed.closed_at is not None
    assert len(runbooks) == 1 and runbooks[0].source_case_id == case.id
    assert len(learnings) == 1 and "N+1" in learnings[0].confirmed_root_cause
    assert any("published" in m["text"].lower() for m in deps.channel.sent)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_node_remediate_publish.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement gates**

`src/sre_gateway/graph/nodes/gates.py`:

```python
import difflib
from typing import Literal

from langgraph.types import interrupt
from sqlalchemy import update as sa_update

from sre_gateway.db.models import Approval, Artifact, Case
from sre_gateway.graph.deps import GraphDeps


def make_gate(deps: GraphDeps, gate: Literal["rca", "runbook"]):
    async def gate_node(state: dict) -> dict:
        case_id = state["case_id"]
        artifact_ref = state["rca" if gate == "rca" else "runbook"]

        # Everything before interrupt() re-runs on resume: keep it idempotent.
        async with deps.sessionmaker() as s:
            await s.execute(sa_update(Case).where(Case.id == case_id).values(
                status="waiting_approval", phase=f"gate_{gate}"))
            await s.commit()

        decision: dict = interrupt({
            "gate": gate, "case_id": case_id, "display_id": state.get("display_id", ""),
            "artifact_id": artifact_ref["artifact_id"], "version": artifact_ref["version"],
        })

        # From here on runs exactly once, after resume.
        verdict = decision.get("decision", "reject")
        async with deps.sessionmaker() as s:
            art = await s.get(Artifact, artifact_ref["artifact_id"])
            diff = None
            if verdict == "approve_with_edits" and decision.get("edited_body_md"):
                art.body_edited_md = decision["edited_body_md"]
                diff = "\n".join(difflib.unified_diff(
                    art.body_md.splitlines(), decision["edited_body_md"].splitlines(),
                    fromfile="drafted", tofile="edited", lineterm=""))
            s.add(Approval(case_id=case_id, artifact_id=art.id, gate=gate,
                           decision=verdict,
                           decided_by=decision.get("decided_by", "unknown"),
                           channel=decision.get("channel", "ui"),
                           annotation=decision.get("annotation", ""), diff=diff))
            await s.execute(sa_update(Case).where(Case.id == case_id)
                            .values(status="open"))
            await s.commit()
        await deps.audit.log("approval", actor=decision.get("decided_by", "unknown"),
                             case_id=case_id, gate=gate, decision=verdict,
                             channel=decision.get("channel", "ui"),
                             edited=verdict == "approve_with_edits")
        await deps.channel.send(
            f"{state.get('display_id', case_id)}: {gate} {verdict} "
            f"by {decision.get('decided_by', 'unknown')}.")

        result: dict = {f"gate_{gate}": decision}
        if verdict == "reject":
            result["context_notes"] = [
                f"Reviewer rejected the {gate}: {decision.get('annotation', '(no note)')}"]
            if gate == "rca":
                result["verification"] = None
                result["repair_used"] = False
        return result

    return gate_node
```

- [ ] **Step 5: Implement remediate, publish, park**

`src/sre_gateway/graph/nodes/remediate.py`:

```python
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from sre_gateway.db.models import Artifact, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json

SYSTEM = (
    "You are the remediation drafter. Draft a runbook for the approved RCA: pre-checks, "
    "steps (commands, config diffs), post-checks, rollback plan, risk notes. You NEVER "
    "execute anything; you only draft. For pipeline-failure cases include patch_files: "
    "the complete corrected content of each file to change (workflow YAML, "
    ".gitlab-ci.yml, or source files)."
)


class RunbookStep(BaseModel):
    title: str
    detail: str = ""
    command: str | None = None


class PatchFile(BaseModel):
    path: str
    content: str


class RunbookOut(BaseModel):
    pre_checks: list[str] = Field(default_factory=list)
    steps: list[RunbookStep] = Field(default_factory=list)
    post_checks: list[str] = Field(default_factory=list)
    rollback: list[str] = Field(default_factory=list)
    risk_notes_md: str = ""
    patch_files: list[PatchFile] | None = None


def render_runbook_md(out: RunbookOut) -> str:
    lines = ["## Pre-checks"] + [f"- {x}" for x in out.pre_checks] + ["", "## Steps"]
    for i, s in enumerate(out.steps, 1):
        lines.append(f"{i}. **{s.title}** - {s.detail}")
        if s.command:
            lines += ["```", s.command, "```"]
    lines += ["", "## Post-checks"] + [f"- {x}" for x in out.post_checks]
    lines += ["", "## Rollback"] + [f"- {x}" for x in out.rollback]
    lines += ["", "## Risk notes", out.risk_notes_md]
    if out.patch_files:
        lines += ["", "## Patch"]
        for p in out.patch_files:
            lines += [f"### `{p.path}`", "```", p.content, "```"]
    return "\n".join(lines)


def make_remediate(deps: GraphDeps):
    async def remediate(state: dict) -> dict:
        case_id = state["case_id"]
        async with deps.sessionmaker() as s:
            rca_art = await s.get(Artifact, state["rca"]["artifact_id"])
            evidence = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id)
                .order_by(EvidenceRow.eid))).scalars().all()
            prev = (await s.execute(
                select(func.max(Artifact.version)).where(Artifact.case_id == case_id,
                                                         Artifact.kind == "runbook"))
                    ).scalar_one() or 0
        rca_body = rca_art.body_edited_md or rca_art.body_md

        tier = deps.manifests["remediate"].tier
        model_id, pricing = deps.models.describe(tier)
        user = (f"Case: {state.get('title', '')} (kind {state.get('kind', 'incident')}, "
                f"failure_class {state.get('failure_class')}).\n"
                f"Approved RCA:\n{rca_body}\n\nEvidence index:\n" +
                "\n".join(f"- {e.eid} [{e.toolset}] {e.excerpt[:200]}" for e in evidence) +
                f"\nReviewer notes: {state.get('context_notes', [])}\n"
                + ("This is a pipeline-failure case: patch_files is REQUIRED."
                   if state.get("kind") == "pipeline_failure" else ""))
        out = await call_llm_json(deps.models.chat(tier, "remediate"), system=SYSTEM,
                                  user=user, schema=RunbookOut, audit=deps.audit,
                                  node="remediate", case_id=case_id,
                                  model_id=model_id, pricing=pricing)

        async with deps.sessionmaker() as s:
            art = Artifact(case_id=case_id, kind="runbook", version=prev + 1,
                           structured=out.model_dump(), body_md=render_runbook_md(out),
                           model_id=model_id)
            s.add(art)
            await s.commit()
            artifact_id = art.id
        return {"runbook": {"artifact_id": artifact_id, "version": prev + 1,
                            "structured": out.model_dump()}}

    return remediate
```

`src/sre_gateway/graph/nodes/publish.py`:

```python
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select, update

from sre_gateway.db.models import Artifact, Case, EvidenceRow
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.llm.json_call import call_llm_json
from sre_gateway.retrieval import index_learning, index_runbook

SYSTEM = ("Distill this closed case into a compact learning for future triage: the "
          "signal signature, the confirmed root cause, the queries/toolsets that "
          "produced decisive evidence, and the false leads.")


class LearningOut(BaseModel):
    signal_signature: str
    confirmed_root_cause: str
    decisive_queries: list[str] = Field(default_factory=list)
    false_leads: list[str] = Field(default_factory=list)


def make_publish(deps: GraphDeps):
    async def publish(state: dict) -> dict:
        case_id = state["case_id"]
        display = state.get("display_id", case_id)
        async with deps.sessionmaker() as s:
            rca = await s.get(Artifact, state["rca"]["artifact_id"])
            runbook = await s.get(Artifact, state["runbook"]["artifact_id"])
            evidence = (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id))).scalars().all()
        rca_body = rca.body_edited_md or rca.body_md
        rb_body = runbook.body_edited_md or runbook.body_md

        await deps.channel.send(f"{display} RCA published:\n{rca_body[:3000]}")
        await deps.channel.send(f"{display} runbook published:\n{rb_body[:3000]}")

        await index_runbook(deps.sessionmaker, deps.models.embed,
                            title=f"{display}: {state.get('title', '')}",
                            body_md=rb_body, source_case_id=case_id,
                            tags=[state.get("kind", "incident")])

        supported = [h for h in state.get("hypotheses", []) if h.get("status") == "supported"]
        refuted = [h["statement"] for h in state.get("hypotheses", [])
                   if h.get("status") == "refuted"]
        tier = deps.manifests["learnings"].tier
        model_id, pricing = deps.models.describe(tier)
        out = await call_llm_json(
            deps.models.chat(tier, "learnings"), system=SYSTEM,
            user=(f"Case {display}: {state.get('title', '')}\n"
                  f"Confirmed: {[h['statement'] for h in supported]}\nRefuted: {refuted}\n"
                  f"Evidence invocations: "
                  f"{[e.invocation[:120] for e in evidence][:20]}"),
            schema=LearningOut, audit=deps.audit, node="learnings", case_id=case_id,
            model_id=model_id, pricing=pricing)
        await index_learning(deps.sessionmaker, deps.models.embed, case_id=case_id,
                             signal_signature=out.signal_signature,
                             confirmed_root_cause=out.confirmed_root_cause,
                             decisive_queries=out.decisive_queries,
                             false_leads=out.false_leads)

        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(
                status="closed", phase="closed", closed_at=datetime.now(UTC)))
            await s.commit()
        await deps.audit.log("publish", actor="publish", case_id=case_id,
                             rca_version=rca.version, runbook_version=runbook.version)
        return {}

    return publish
```

`src/sre_gateway/graph/nodes/park.py`:

```python
from sqlalchemy import update

from sre_gateway.db.models import Case
from sre_gateway.graph.deps import GraphDeps


def make_park(deps: GraphDeps):
    async def park(state: dict) -> dict:
        case_id = state["case_id"]
        halt = state.get("halt") or {"reason": "manual escalation", "at_node": "unknown"}
        async with deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(
                status="needs_human", phase="parked", halt_reason=halt["reason"]))
            await s.commit()
        await deps.audit.log("budget", actor="park", case_id=case_id, **halt)
        await deps.channel.send(
            f"{state.get('display_id', case_id)} parked (needs human): {halt['reason']}. "
            f"Everything gathered so far is preserved; resume from the console.")
        return {}

    return park
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/test_node_remediate_publish.py -q`
Expected: `2 passed` (gates are exercised inside the assembled graph in Task 20 - `interrupt()` needs a real graph runtime).

- [ ] **Step 7: Commit**

```bash
git add gateway/src/sre_gateway/graph/nodes gateway/tests
git commit -m "feat(sre-team): hitl gates, remediation drafter, publish with learnings, park"
```

### Task 20: Graph assembly and full-lifecycle tests

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/build.py`
- Create: `agentic-sre-team/gateway/tests/test_graph_incident.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_two_rounds/` (triage, synthesize, rca, verify scripts - see Step 2)

**Interfaces:**
- Consumes: every node factory (Tasks 15-19), routers (Task 14), `make_checkpointer`.
- Produces: `build_graph(deps, checkpointer=None) -> CompiledStateGraph` with nodes `triage, plan, metrics_worker, logs_worker, infra_worker, changes_worker, ci_worker, synthesize, rca, verify_citations, gate_rca, remediate, gate_runbook, publish, park`. This compiled graph object is what the CaseRunner (Task 21) streams; thread config is `{"configurable": {"thread_id": case_id}}`.

- [ ] **Step 1: Implement build.py** (assembly is mechanical; write it, then let the tests judge it)

```python
from langgraph.graph import END, START, StateGraph

from sre_gateway.graph.deps import GraphDeps, guarded
from sre_gateway.graph.nodes.gates import make_gate
from sre_gateway.graph.nodes.park import make_park
from sre_gateway.graph.nodes.plan import make_plan
from sre_gateway.graph.nodes.publish import make_publish
from sre_gateway.graph.nodes.rca import make_rca
from sre_gateway.graph.nodes.remediate import make_remediate
from sre_gateway.graph.nodes.synthesize import make_synthesize
from sre_gateway.graph.nodes.triage import make_triage
from sre_gateway.graph.nodes.verify import make_verify
from sre_gateway.graph.nodes.workers import make_worker
from sre_gateway.graph.routers import (
    fan_out, route_after_gate_rca, route_after_gate_runbook, route_after_synthesize,
    route_after_triage, route_after_verify,
)
from sre_gateway.graph.state import CaseState

WORKER_NODES = {"metrics_worker": "metrics", "logs_worker": "logs",
                "infra_worker": "infra", "changes_worker": "changes", "ci_worker": "ci"}


def build_graph(deps: GraphDeps, checkpointer=None):
    g = StateGraph(CaseState)
    g.add_node("triage", guarded(deps, "triage", make_triage(deps)))
    g.add_node("plan", guarded(deps, "plan", make_plan(deps)))
    for node, domain in WORKER_NODES.items():
        g.add_node(node, make_worker(deps, domain))  # parallel branches; budget re-checked at synthesize
    g.add_node("synthesize", guarded(deps, "synthesize", make_synthesize(deps)))
    g.add_node("rca", guarded(deps, "rca", make_rca(deps)))
    g.add_node("verify_citations", guarded(deps, "verify_citations", make_verify(deps)))
    g.add_node("gate_rca", make_gate(deps, "rca"))
    g.add_node("remediate", guarded(deps, "remediate", make_remediate(deps)))
    g.add_node("gate_runbook", make_gate(deps, "runbook"))
    g.add_node("publish", guarded(deps, "publish", make_publish(deps)))
    g.add_node("park", make_park(deps))

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage,
                            {"plan": "plan", END: END, "park": "park"})
    g.add_conditional_edges("plan", fan_out, list(WORKER_NODES) + ["park"])
    for node in WORKER_NODES:
        g.add_edge(node, "synthesize")
    g.add_conditional_edges("synthesize", route_after_synthesize,
                            {"plan": "plan", "rca": "rca", "park": "park"})
    g.add_edge("rca", "verify_citations")
    g.add_conditional_edges("verify_citations", route_after_verify,
                            {"rca": "rca", "gate_rca": "gate_rca", "park": "park"})
    g.add_conditional_edges("gate_rca", route_after_gate_rca,
                            {"remediate": "remediate", "rca": "rca", "park": "park"})
    g.add_edge("remediate", "gate_runbook")
    g.add_conditional_edges("gate_runbook", route_after_gate_runbook,
                            {"publish": "publish", "remediate": "remediate", "park": "park"})
    g.add_edge("publish", END)
    g.add_edge("park", END)
    return g.compile(checkpointer=checkpointer)
```

Docs-check while writing this (Context7 `/langchain-ai/langgraph`): interrupt surfacing in `ainvoke` results (`result["__interrupt__"]`), `Command(resume=...)` as the input of the resuming call, and conditional-edge + `Send` combination on `plan`.

- [ ] **Step 2: Write the failing full-lifecycle tests**

`gateway/tests/test_graph_incident.py`:

```python
from langgraph.types import Command
from sqlalchemy import select

from sre_gateway.budget import BudgetEnforcer, CaseBudget
from sre_gateway.db.models import (
    Approval, Artifact, Case, CaseLearning, EvidenceRow, Hypothesis, Runbook, SignalRow,
)
from sre_gateway.graph import make_checkpointer
from sre_gateway.graph.build import build_graph


async def _seed(db):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="grafana:x",
                 thread_id="", title="raw alert")
        c.thread_id = c.id
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source="grafana", kind="incident", is_primary=True,
                        fingerprint="grafana:x",
                        summary="Error rate spike on admin-server /api/v1/users",
                        labels={"service": "admin-server"}))
        await s.commit()
        return c


APPROVE = {"decision": "approve", "decided_by": "alex.goh", "channel": "ui"}


async def test_full_incident_lifecycle(deps, db, pg_url):
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}

        result = await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        assert "__interrupt__" in result  # gate 1
        async with db() as s:
            refreshed = await s.get(Case, case.id)
            hypos = {h.hid: h for h in
                     (await s.execute(select(Hypothesis))).scalars().all()}
            rca_art = (await s.execute(select(Artifact).where(
                Artifact.kind == "rca"))).scalars().one()
        assert refreshed.status == "waiting_approval" and refreshed.phase == "gate_rca"
        assert hypos["H2"].status == "supported" and hypos["H3"].status == "refuted"
        assert rca_art.verification["verified"] is True

        result = await graph.ainvoke(Command(resume=APPROVE), cfg)
        assert "__interrupt__" in result  # gate 2

        # fresh graph instance: the gate-2 resume must come purely from the
        # checkpoint (gateway-restart survival, spec section 10)
        graph = build_graph(deps, saver)
        await graph.ainvoke(Command(resume=APPROVE), cfg)
        async with db() as s:
            closed = await s.get(Case, case.id)
            approvals = (await s.execute(select(Approval))).scalars().all()
            assert (await s.execute(select(Runbook))).scalars().one()
            assert (await s.execute(select(CaseLearning))).scalars().one()
        assert closed.status == "closed"
        assert {a.gate for a in approvals} == {"rca", "runbook"}
        assert any("runbook published" in m["text"].lower()
                   for m in deps.channel.sent)


async def test_gate1_rejection_redrafts_with_annotation(deps, db, pg_url):
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        result = await graph.ainvoke(Command(resume={
            "decision": "reject", "decided_by": "alex.goh", "channel": "ui",
            "annotation": "mitigation is wrong, check the flag name"}), cfg)
        assert "__interrupt__" in result  # back at gate 1 with rca v2
        async with db() as s:
            versions = [a.version for a in (await s.execute(
                select(Artifact).where(Artifact.kind == "rca"))).scalars().all()]
        assert sorted(versions) == [1, 2]


async def test_second_round_runs_when_synthesize_asks(deps_two_rounds, db, pg_url):
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps_two_rounds, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        result = await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        assert "__interrupt__" in result  # both bounded rounds ran, then gate 1
        async with db() as s:
            refreshed = await s.get(Case, case.id)
            evidence = (await s.execute(select(EvidenceRow))).scalars().all()
        assert refreshed.round == 2      # the second bounded round actually executed
        assert len(evidence) == 16       # 4 workers x 2 fixture tool calls x 2 rounds


async def test_budget_breach_parks_case(deps, db, pg_url):
    deps.budget = BudgetEnforcer(db, CaseBudget(tokens=10, tool_calls=60, wall_clock_s=900))
    case = await _seed(db)
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(deps, saver)
        cfg = {"configurable": {"thread_id": case.id}}
        result = await graph.ainvoke({"case_id": case.id, "kind": "incident"}, cfg)
        assert "__interrupt__" not in result
        async with db() as s:
            parked = await s.get(Case, case.id)
        assert parked.status == "needs_human"
        assert "budget" in (parked.halt_reason or "")
        assert any("parked" in m["text"] for m in deps.channel.sent)
```

Create the two-round scenario scripts and the `deps_two_rounds` conftest fixture (identical to `deps` except `script_dir=tests/fixtures/scripts/incident_two_rounds`; same holmes fixtures):

```bash
cd gateway/tests/fixtures/scripts && mkdir incident_two_rounds
cp incident_error_storm/triage.json incident_error_storm/rca.json \
   incident_error_storm/verify.json incident_two_rounds/
```

`incident_two_rounds/synthesize.json` (round 1 demands one more bounded round; round 2 concludes):

```json
[
  {"board": [{"hid": "H1", "status": "open", "confidence": 0.45, "note": "pool elevated, cause unclear"},
             {"hid": "H2", "status": "open", "confidence": 0.5, "note": "needs the PR diff correlation"},
             {"hid": "H3", "status": "refuted", "confidence": 0.05, "note": "cpu flat"},
             {"hid": "H4", "status": "open", "confidence": 0.1, "note": ""}],
   "new_hypotheses": [], "need_more": true, "focus": "correlate PR merge time with symptom onset",
   "failure_class": null, "status_update": "Evidence inconclusive; running one more bounded round."},
  {"board": [{"hid": "H1", "status": "open", "confidence": 0.31, "note": "explained by H2"},
             {"hid": "H2", "status": "supported", "confidence": 0.78, "note": "n+1 confirmed"},
             {"hid": "H3", "status": "refuted", "confidence": 0.05, "note": ""},
             {"hid": "H4", "status": "refuted", "confidence": 0.05, "note": ""}],
   "new_hypotheses": [], "need_more": false, "focus": null,
   "failure_class": null, "status_update": "N+1 admin API calls confirmed (0.78). RCA next."}
]
```

- [ ] **Step 3: Run to verify failure, then make it pass**

Run: `uv run pytest tests/test_graph_incident.py -q`
Expected first: FAIL (`build_graph` missing). After implementing Step 1: all 4 pass. Budget-breach note: triage runs first (its guard sees 0 tokens spent), consumes ~100 scripted tokens, then plan's guard halts and `fan_out` routes to `park` - that is the "checked between nodes" behavior under test.

- [ ] **Step 4: Full suite**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add gateway/src/sre_gateway/graph/build.py gateway/tests/test_graph_incident.py
git commit -m "feat(sre-team): assemble case graph; full lifecycle, rejection and budget-halt tests"
```

### Task 21: CaseRunner, SSE stream, decisions, governance and activity APIs

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/runner.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/decisions.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/cases.py` (detail joins, stream, decision, park, resume, context)
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/governance.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/activity.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/app.py` (full lifespan wiring)
- Create: `agentic-sre-team/gateway/tests/test_runner_api.py`

**Interfaces:**
- Consumes: `build_graph`, `make_checkpointer`, everything prior.
- Produces:
  - `CaseRunner(deps, graph)`:
    - `async start(case_id: str, initial: dict | None)` - spawns a tracked asyncio task streaming the graph (`initial=None` resumes from the checkpoint - used on gateway restart).
    - `async resume(case_id: str, payload: dict)` - streams `Command(resume=payload)`.
    - `async park(case_id: str, reason: str, actor: str)` - cancels the running task if any, sets `needs_human` + `halt_reason`, audits, pages, emits.
    - `subscribe(case_id) -> asyncio.Queue` / `unsubscribe(...)`; `running_count() -> int`.
    - `async relaunch_open_cases()` - on startup, `start(case_id, None)` for every case with `status="open"` (checkpoint resume; `waiting_approval` cases stay parked at their gate).
    - Internals: `_run` iterates `graph.astream(input, config, stream_mode=["updates", "custom", "messages"])`. Every `custom` event and every `updates` node-completion is persisted to `case_events` (per-case `seq` = max+1, held in memory per runner) and fanned out to subscriber queues; `messages` token chunks are fanned out live but **not** persisted (`{"type": "token", "node", "text"}`). On `updates` containing `__interrupt__`: emit `{"type": "gate_waiting", "gate", "artifact_id"}` and send the channel notification with inline buttons `[{"text": "Approve", "data": "dec:<case_id>:<gate>:approve"}, {"text": "Reject", "data": "dec:<case_id>:<gate>:reject"}]` (single notification per pause - this lives in the runner, not the gate node, because the gate node re-executes on resume). On exception: park the case with the error string.
  - `apply_decision(sessionmaker, runner, case_id, gate, *, decision, decided_by, channel="ui", edited_body_md=None, annotation="") -> None`: validates the case is `waiting_approval` at `gate_<gate>` (409 otherwise), then `runner.resume(...)`. Shared by the REST endpoint and (Task 34) Telegram callbacks.
  - Endpoints (all under `/api`):
    - `GET /cases/{id}` now also returns `hypotheses`, `evidence`, `artifacts` (with verification + edited body), `approvals`. Evidence items serialize `eid, worker, toolset, invocation, excerpt, source_url, observed_at, hypothesis_links` - the UI `Evidence` type (Task 27) mirrors this exactly.
    - `GET /cases/{id}/stream` - `EventSourceResponse`; replays persisted `case_events` with `seq >` `Last-Event-ID` (header or `?last_event_id=`, default: last 200), then live-relays the subscriber queue; each SSE message has `id=seq`, `event=type`, `data=json`.
    - `POST /cases/{id}/decision` body `{gate, decision, decided_by, channel?, edited_body_md?, annotation?}`.
    - `POST /cases/{id}/park` body `{reason, actor}`; `POST /cases/{id}/resume` body `{actor}` - clears `halt_reason`, sets `open`, `runner.start(id, None)`.
    - `POST /cases/{id}/context` body `{text, author}` - inserts a `SignalRow(attach_reason="human_context", source="human_api")`, audits, emits a `context_added` event (synthesize reads these rows each round).
    - `GET /governance` - `{paused, agents: [{agent, tier, tools, usd_per_day, spend_today}], suppression_24h: {dedup, debounce, burst, grouped, paused}, cases_opened_24h, running_cases}` (keys are the raw decision reasons; the UI maps them to display labels).
    - `POST /governance/pause` body `{paused: bool, actor}` (audited; intake + node guards already honor the flag).
    - `GET /governance/audit?limit=100` - newest-first audit rows.
    - `GET /activity?hours=24` - `{buckets: [{ts, signals, suppressed}] (30-min bins), cases: [{id, display_id, severity, kind, created_at}], annotations: [{ts, text, kind}]}`.
    - `POST /activity/annotations` body `{text, kind}` (audit event `event_type="annotation"`; chaos scripts call this).
  - `create_app` lifespan now wires: engine/sessionmaker/audit -> ModelFactory (profile-aware, `settings.fake_script_dir` override) -> manifests + `load_environment(settings.config_dir / "environment.yaml")` -> BudgetEnforcer -> HolmesClient(settings.holmes_url) -> channel (`LogChannel` now; Telegram replaces it in Task 34 when configured) -> checkpointer -> `build_graph` -> `CaseRunner` -> `IntakeService(on_case_opened=...)` whose hook is `async def _on_opened(cid): await runner.start(cid, {"case_id": cid})` (triage re-reads kind and everything else from the case row, so the hook needs only the id) -> `relaunch_open_cases()`. Health keys: `db`, plus later tasks add their components.

- [ ] **Step 1: Write the failing API tests**

`gateway/tests/test_runner_api.py` (uses the app-level `client` fixture from Task 8, now running the fake profile end to end):

```python
import asyncio
import json


async def _open_case(client) -> dict:
    from pathlib import Path

    body = (Path(__file__).parent / "fixtures/grafana_webhook.json").read_text()
    res = await client.post("/api/webhooks/grafana", content=body)
    return res.json()["results"][0]


async def _wait_status(client, case_id, status, timeout=30):
    for _ in range(timeout * 10):
        detail = (await client.get(f"/api/cases/{case_id}")).json()
        if detail["case"]["status"] == status:
            return detail
        await asyncio.sleep(0.1)
    raise AssertionError(f"case never reached {status}: {detail['case']}")


async def test_webhook_drives_case_to_gate1_and_decision_to_gate2(client):
    opened = await _open_case(client)
    detail = await _wait_status(client, opened["case_id"], "waiting_approval")
    assert detail["case"]["phase"] == "gate_rca"
    assert any(a["kind"] == "rca" and a["verification"]["verified"]
               for a in detail["artifacts"])
    assert {h["hid"] for h in detail["hypotheses"]} >= {"H1", "H2", "H3"}
    assert len(detail["evidence"]) == 8  # 4 workers x 2 fixture tool calls

    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "rca", "decision": "approve", "decided_by": "alex.goh"})
    assert res.status_code == 200
    detail = await _wait_status(client, opened["case_id"], "waiting_approval")
    assert detail["case"]["phase"] == "gate_runbook"

    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "runbook", "decision": "approve", "decided_by": "alex.goh"})
    detail = await _wait_status(client, opened["case_id"], "closed")
    assert detail["case"]["status"] == "closed"


async def test_decision_on_wrong_gate_is_409(client):
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval")
    res = await client.post(f"/api/cases/{opened['case_id']}/decision", json={
        "gate": "runbook", "decision": "approve", "decided_by": "x"})
    assert res.status_code == 409


async def test_stream_replays_events(client):
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval")
    async with client.stream("GET",
                             f"/api/cases/{opened['case_id']}/stream") as res:
        events = []
        async for line in res.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "gate_waiting" in events:
                break
    assert "node_start" in events and "tool_call" in events


async def test_governance_and_activity_read_models(client):
    opened = await _open_case(client)
    await _wait_status(client, opened["case_id"], "waiting_approval")
    gov = (await client.get("/api/governance")).json()
    assert gov["paused"] is False
    agents = {a["agent"]: a for a in gov["agents"]}
    assert agents["triage"]["spend_today"] > 0
    act = (await client.get("/api/activity?hours=24")).json()
    assert act["cases"][0]["display_id"] == "CASE-0001"
    assert sum(b["signals"] for b in act["buckets"]) >= 1
```

Update the shared `client` fixture (conftest) to run the fake profile: `Settings(database_url=pg_url, config_dir=<repo>/config, models_profile="fake", fake_script_dir=<tests>/fixtures/scripts/incident_error_storm, holmes_url="http://fake-holmes")`, and inside the fixture monkeypatch `FAKE_HOLMES_DIR` and patch the app's HolmesClient to use the ASGI transport against `sre_gateway.testing.fake_holmes.app` (inject via `app.state.holmes_client_factory` hook or set `app.state.deps.holmes = HolmesClient(..., client=ASGI...)` right after lifespan start - expose `app.state.deps` from `create_app` for exactly this).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner_api.py -q`
Expected: FAIL (runner/decisions/endpoints missing)

- [ ] **Step 3: Implement runner**

`src/sre_gateway/graph/runner.py`:

```python
import asyncio
import logging
from collections import defaultdict

from langgraph.types import Command
from sqlalchemy import func, select, update

from sre_gateway.db.models import Case, CaseEvent
from sre_gateway.graph.deps import GraphDeps

logger = logging.getLogger("sre.runner")


class CaseRunner:
    def __init__(self, deps: GraphDeps, graph) -> None:
        self.deps = deps
        self.graph = graph
        self.tasks: dict[str, asyncio.Task] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._seq: dict[str, int] = {}

    def running_count(self) -> int:
        return sum(1 for t in self.tasks.values() if not t.done())

    def subscribe(self, case_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.subscribers[case_id].add(q)
        return q

    def unsubscribe(self, case_id: str, q: asyncio.Queue) -> None:
        self.subscribers[case_id].discard(q)

    async def start(self, case_id: str, initial: dict | None) -> None:
        self.tasks[case_id] = asyncio.create_task(self._run(case_id, initial))

    async def resume(self, case_id: str, payload: dict) -> None:
        self.tasks[case_id] = asyncio.create_task(
            self._run(case_id, Command(resume=payload)))

    async def park(self, case_id: str, reason: str, actor: str) -> None:
        task = self.tasks.get(case_id)
        if task and not task.done():
            task.cancel()
        async with self.deps.sessionmaker() as s:
            await s.execute(update(Case).where(Case.id == case_id).values(
                status="needs_human", phase="parked", halt_reason=reason))
            await s.commit()
        await self.deps.audit.log("budget", actor=actor, case_id=case_id, reason=reason,
                                  manual=True)
        await self._emit(case_id, "parked", {"reason": reason, "actor": actor})
        await self.deps.channel.send(f"Case {case_id} escalated to human by {actor}: {reason}")

    async def relaunch_open_cases(self) -> None:
        async with self.deps.sessionmaker() as s:
            ids = (await s.execute(select(Case.id).where(Case.status == "open"))
                   ).scalars().all()
        for case_id in ids:
            await self.start(case_id, None)  # resume from checkpoint

    async def _next_seq(self, case_id: str) -> int:
        if case_id not in self._seq:
            async with self.deps.sessionmaker() as s:
                current = (await s.execute(
                    select(func.max(CaseEvent.seq)).where(CaseEvent.case_id == case_id))
                           ).scalar_one() or 0
            self._seq[case_id] = current
        self._seq[case_id] += 1
        return self._seq[case_id]

    async def _emit(self, case_id: str, type_: str, payload: dict,
                    persist: bool = True) -> None:
        event = {"type": type_, **payload}
        if persist:
            seq = await self._next_seq(case_id)
            event["seq"] = seq
            async with self.deps.sessionmaker() as s:
                s.add(CaseEvent(case_id=case_id, seq=seq, type=type_, payload=payload))
                await s.commit()
        for q in list(self.subscribers[case_id]):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self.subscribers[case_id].discard(q)

    async def _run(self, case_id: str, graph_input) -> None:
        cfg = {"configurable": {"thread_id": case_id}}
        try:
            async for mode, chunk in self.graph.astream(
                    graph_input, cfg, stream_mode=["updates", "custom", "messages"]):
                if mode == "custom":
                    payload = dict(chunk)
                    await self._emit(case_id, payload.pop("type", "custom"), payload)
                elif mode == "messages":
                    msg, meta = chunk
                    text = getattr(msg, "content", "")
                    if text:
                        await self._emit(case_id, "token",
                                         {"node": meta.get("langgraph_node", ""),
                                          "text": str(text)[:500]}, persist=False)
                elif mode == "updates":
                    if "__interrupt__" in chunk:
                        intr = chunk["__interrupt__"][0]
                        value = getattr(intr, "value", {}) or {}
                        await self._emit(case_id, "gate_waiting", dict(value))
                        gate = value.get("gate", "rca")
                        await self.deps.channel.send(
                            f"{value.get('display_id', case_id)}: {gate} ready for "
                            f"review (artifact v{value.get('version')}). Approve in the "
                            f"console or right here.",
                            buttons=[
                                {"text": "Approve", "data": f"dec:{case_id}:{gate}:approve"},
                                {"text": "Reject", "data": f"dec:{case_id}:{gate}:reject"},
                            ])
                    else:
                        for node, node_update in chunk.items():
                            keys = sorted(node_update or {})
                            await self._emit(case_id, "node_update",
                                             {"node": node, "keys": keys})
            await self._emit(case_id, "run_idle", {})
        except asyncio.CancelledError:
            raise
        except Exception as err:
            logger.exception("case %s runner failed", case_id)
            async with self.deps.sessionmaker() as s:
                await s.execute(update(Case).where(Case.id == case_id).values(
                    status="needs_human", phase="parked",
                    halt_reason=f"runner error: {err}"[:500]))
                await s.commit()
            await self._emit(case_id, "error", {"error": str(err)[:500]})
            await self.deps.channel.send(f"Case {case_id} parked on error: {err}")

    async def stop(self) -> None:
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
```

`src/sre_gateway/graph/decisions.py`:

```python
from fastapi import HTTPException

from sre_gateway.db.models import Case


async def apply_decision(sessionmaker, runner, case_id: str, gate: str, *,
                         decision: str, decided_by: str, channel: str = "ui",
                         edited_body_md: str | None = None, annotation: str = "") -> None:
    async with sessionmaker() as s:
        case = await s.get(Case, case_id)
    if case is None:
        raise HTTPException(404)
    if case.status != "waiting_approval" or case.phase != f"gate_{gate}":
        raise HTTPException(409, detail=f"case is at {case.phase} ({case.status}), "
                                        f"not waiting on gate_{gate}")
    await runner.resume(case_id, {"decision": decision, "decided_by": decided_by,
                                  "channel": channel, "edited_body_md": edited_body_md,
                                  "annotation": annotation})
```

- [ ] **Step 4: Implement the endpoints and wiring**

Extend `api/cases.py` with the detail joins and the new routes (SSE via `sse_starlette.EventSourceResponse`); add `api/governance.py` and `api/activity.py`; rewrite `create_app`'s lifespan per the Interfaces block (build `GraphDeps`, expose as `app.state.deps`, enter `make_checkpointer`, build graph + runner, hook intake, `relaunch_open_cases`, and on shutdown `runner.stop()`). Representative SSE endpoint:

```python
@router.get("/cases/{case_id}/stream")
async def stream_case(request: Request, case_id: str, last_event_id: int | None = None):
    runner = request.app.state.runner
    last = last_event_id or int(request.headers.get("Last-Event-ID", 0) or 0)

    async def gen():
        q = runner.subscribe(case_id)
        try:
            async with request.app.state.sessionmaker() as s:
                stmt = (select(CaseEvent).where(CaseEvent.case_id == case_id)
                        .order_by(CaseEvent.seq))
                stmt = stmt.where(CaseEvent.seq > last) if last else stmt.limit(200)
                replayed = last
                for row in (await s.execute(stmt)).scalars():
                    replayed = max(replayed, row.seq)
                    yield {"id": str(row.seq), "event": row.type,
                           "data": json.dumps(row.payload)}
            while True:
                event = await q.get()
                seq = event.get("seq")
                if seq is not None and seq <= replayed:
                    continue  # already sent in replay (subscribe-before-replay race)
                yield {"id": str(seq or ""), "event": event["type"],
                       "data": json.dumps({k: v for k, v in event.items()
                                           if k not in ("type", "seq")})}
        finally:
            runner.unsubscribe(case_id, q)

    return EventSourceResponse(gen(), ping=15)
```

Governance suppression stats come from one grouped query over `audit_events` (last 24h, `event_type IN ('suppression', 'intake')`, grouped by `payload->>'reason'`, dropping reason `opened`) so both suppressions (`debounce`, `burst`, `paused`) and attaches (`dedup`, `grouped`) are counted; agent cards join `manifests` + `BudgetEnforcer.agent_spend_today`. Activity buckets: 30-minute `date_trunc` bins over `signals.received_at` plus suppression counts from audit, cases from `cases.created_at`, annotations from `audit_events.event_type='annotation'`.

- [ ] **Step 5: Run tests, verify pass**

Run: `uv run pytest tests/test_runner_api.py -q` then the full suite `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add gateway/src/sre_gateway gateway/tests
git commit -m "feat(sre-team): case runner with sse replay, decision resume, governance and activity apis"
```

### Task 22: Smoke script, fake compose profile, make smoke

**Files:**
- Create: `agentic-sre-team/scripts/smoke.py`
- Modify: `agentic-sre-team/docker-compose.yml` (fake-holmes service, gateway migration command, env passthrough)
- Modify: `agentic-sre-team/Makefile` (smoke target)

**Interfaces:**
- Consumes: the full fake-profile stack.
- Produces: `make smoke` - brings up `postgres + gateway + fake-holmes` with `SRE_MODELS_PROFILE=fake`, posts the canned Grafana payload, drives gate 1 -> approve -> gate 2 -> approve -> closed, asserts the RCA artifact cites only existing evidence ids. Exit code 0 on pass.

- [ ] **Step 1: Compose changes**

In `docker-compose.yml`, change the gateway service to run migrations at boot and pass the profile envs through, and add the fake-holmes service:

```yaml
  gateway:
    build: ./gateway
    container_name: sre-gateway
    command: ["sh", "-c", "alembic upgrade head && uvicorn sre_gateway.main:app --host 0.0.0.0 --port 8080"]
    env_file: .env
    environment:
      SRE_DATABASE_URL: postgresql+asyncpg://sre:${SRE_PG_PASSWORD:-sre}@postgres:5432/sre
      SRE_CONFIG_DIR: /config
      SRE_MODELS_PROFILE: ${SRE_MODELS_PROFILE:-local}
      SRE_HOLMES_URL: ${SRE_HOLMES_URL:-http://holmes:5050}
      SRE_FAKE_SCRIPT_DIR: ${SRE_FAKE_SCRIPT_DIR:-}
    volumes:
      - ./config:/config:ro
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy

  fake-holmes:
    profiles: ["fake"]
    build: ./gateway
    container_name: sre-fake-holmes
    command: ["python", "-m", "sre_gateway.testing.fake_holmes"]
    environment:
      FAKE_HOLMES_DIR: /app/tests/fixtures/holmes/incident_error_storm
    ports:
      - "5050:5050"
```

Makefile target:

```makefile
smoke:
	SRE_MODELS_PROFILE=fake SRE_HOLMES_URL=http://fake-holmes:5050 \
	SRE_FAKE_SCRIPT_DIR=/app/tests/fixtures/scripts/incident_error_storm \
	$(COMPOSE) --profile fake up -d --build
	cd gateway && uv run python ../scripts/smoke.py
```

Leave `SRE_GRAFANA_WEBHOOK_SECRET` unset in the fake profile: the webhook endpoint skips HMAC verification when no secret is configured, and both `make smoke` and `make e2e` POST unsigned payloads (a set secret would 401 them).

- [ ] **Step 2: Write scripts/smoke.py**

```python
#!/usr/bin/env python3
"""E2E smoke (spec section 11): canned Grafana payload -> gate 1 -> approve -> gate 2
-> approve -> closed, on the fake profile. Asserts RCA citations resolve to evidence."""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

BASE = os.environ.get("SMOKE_BASE", "http://localhost:8080/api")
FIXTURE = Path(__file__).parents[1] / "gateway/tests/fixtures/grafana_webhook.json"


async def wait_for(client, case_id, predicate, label, timeout_s=90):
    for _ in range(timeout_s * 2):
        detail = (await client.get(f"{BASE}/cases/{case_id}")).json()
        if predicate(detail):
            return detail
        await asyncio.sleep(0.5)
    sys.exit(f"FAIL: timed out waiting for {label}; last: {detail['case']}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(60):  # wait for the gateway to come up
            try:
                if (await client.get(f"{BASE}/healthz")).status_code == 200:
                    break
            except httpx.TransportError:
                await asyncio.sleep(1)
        res = await client.post(f"{BASE}/webhooks/grafana", content=FIXTURE.read_text())
        res.raise_for_status()
        case_id = res.json()["results"][0]["case_id"]
        print(f"opened case {case_id}")

        detail = await wait_for(client, case_id,
                                lambda d: d["case"]["phase"] == "gate_rca", "gate 1")
        rca = next(a for a in detail["artifacts"] if a["kind"] == "rca")
        assert rca["verification"]["verified"], "citations must verify"
        eids = {e["eid"] for e in detail["evidence"]}
        cited = {e for c in rca["structured"]["claims"] for e in c["eids"]}
        assert cited <= eids, f"RCA cites unknown evidence: {cited - eids}"
        print(f"RCA v{rca['version']} verified, cites {sorted(cited)}")

        for gate in ("rca", "runbook"):
            res = await client.post(f"{BASE}/cases/{case_id}/decision", json={
                "gate": gate, "decision": "approve", "decided_by": "smoke"})
            res.raise_for_status()
            await wait_for(client, case_id,
                           lambda d, g=gate: d["case"]["phase"] != f"gate_{g}",
                           f"past gate {gate}")
        await wait_for(client, case_id, lambda d: d["case"]["status"] == "closed", "close")
        print("PASS: case closed with published artifacts")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run it**

```bash
cd agentic-sre-team && make smoke
```

Expected output ends with `PASS: case closed with published artifacts`. Then `make down`.

- [ ] **Step 4: Commit and open the phase PR**

```bash
git add scripts/smoke.py docker-compose.yml Makefile
git commit -m "feat(sre-team): e2e smoke over the fake profile via make smoke"
# PR: feat/sre-team-p3-case-graph -> main
```

---

## Phase 4 - Real integrations: Holmes sidecar, Grafana Cloud, Vertex, LangSmith

Branch: `feat/sre-team-p4-real-integrations`

### Task 23: HolmesGPT sidecar service and toolset manifest

**Files:**
- Create: `agentic-sre-team/config/holmes.yaml`
- Modify: `agentic-sre-team/docker-compose.yml` (holmes service)
- Modify: `agentic-sre-team/.env.example` (HOLMES_IMAGE resolved)
- Modify: `agentic-sre-team/Makefile` (holmes-check target)
- Possibly modify: `agentic-sre-team/gateway/src/sre_gateway/holmes/client.py` + `testing/fake_holmes.py` + fixtures (contract drift)

**Interfaces:**
- Consumes: `HolmesClient` (Task 13).
- Produces: running `holmes` compose service on the shared network; `config/holmes.yaml` as the evidence-layer permission manifest (spec section 8); `make holmes-check` proving `/api/chat` answers with a `tool_calls` transcript.

- [ ] **Step 1: Docs-check (mandatory, this is the pinned-contract task)**

Read https://holmesgpt.dev (server mode / HTTP API pages) and the image registry to resolve:
1. The current published server image and a pinned tag -> set `HOLMES_IMAGE` in `.env.example` (e.g. `HOLMES_IMAGE=robustadev/holmes:<pinned-tag>` - confirm the exact registry/repo from the docs; do not guess).
2. The config file mount path and the serve command/port.
3. The exact `/api/chat` request fields (`ask`, `model`, `stream`, `response_format`, conversation history) and response fields (`analysis`, `tool_calls[]` entry shape), plus SSE event names. Fetch `GET <holmes>/openapi.json` once the container runs and diff against `holmes/client.py` + `testing/fake_holmes.py`. **If they differ, update client, fake server, and fixtures together in this task** - the fake is the contract (spec section 12).
4. Toolset config keys against the per-toolset docs (user-supplied primary sources): prometheus, grafana/loki, grafana/tempo (https://holmesgpt.dev/latest/data-sources/builtin-toolsets/grafanatempo/), elasticsearch/data + elasticsearch/cluster (https://holmesgpt.dev/latest/data-sources/builtin-toolsets/elasticsearch/ - OpenSearch-compatible), the grafana MCP server (https://holmesgpt.dev/latest/data-sources/builtin-toolsets/grafana-mcp/ - note it is an `mcp_servers` entry, not a `toolsets` key, and its example instructions warn about overlapping with the native prometheus toolset: keep worker prompts scoped so PromQL goes to the native toolset and dashboards/alert-rules go to MCP), openshift/* (https://holmesgpt.dev/latest/data-sources/builtin-toolsets/openshift/ - needs oc CLI + kubeconfig; leave disabled for docker-compose targets), docker, github, gitlab, postgres.

- [ ] **Step 2: Write config/holmes.yaml**

Shape below follows the docs-check; keep every toolset read-only and this file in git - it is the evidence-layer manifest:

```yaml
# HolmesGPT toolset manifest - the permission boundary of the evidence layer.
# Changing this file is a reviewed git change (spec section 8). Read-only only:
# Holmes tool-approval stays off because no write-capable toolset is enabled.
# Endpoints reference env vars so the same manifest serves any target
# environment (locked decision 15); Spectre defaults live in .env.example.
model: vertex_ai/gemini-2.5-flash        # default; workers override per request
toolsets:
  prometheus:
    enabled: true
    config:
      prometheus_url: ${GRAFANA_PROM_URL}      # Grafana Cloud Mimir/Prom endpoint
      headers:
        Authorization: Bearer ${GRAFANA_SA_TOKEN}
  grafana/loki:
    enabled: true
    config:
      url: ${SRE_GRAFANA_URL}
      api_key: ${GRAFANA_SA_TOKEN}
  grafana/tempo:                               # traces: TraceQL + comparative
    enabled: true                              # fast/slow/typical trace sampling
    config:
      api_url: ${SRE_GRAFANA_URL}
      api_key: ${GRAFANA_SA_TOKEN}
      grafana_datasource_uid: ${GRAFANA_TEMPO_DS_UID}
  elasticsearch/data:                          # OpenSearch-compatible log/doc search
    enabled: true
    config:
      api_url: ${TARGET_OPENSEARCH_URL}
      verify_ssl: false                        # local dev cluster; true in prod
      # username: ${TARGET_OPENSEARCH_USER}    # enable when the cluster has auth
      # password: ${TARGET_OPENSEARCH_PASSWORD}
  elasticsearch/cluster:                       # cluster health, shard allocation,
    enabled: true                              # node/index stats, query latency
    config:
      api_url: ${TARGET_OPENSEARCH_URL}
      verify_ssl: false
  docker:
    enabled: true                              # read-only socket mount, see compose
  github:
    enabled: true
    config:
      token: ${SRE_GITHUB_TOKEN}
  gitlab:
    enabled: true
    config:
      url: ${SRE_GITLAB_BASE_URL}
      token: ${SRE_GITLAB_TOKEN}
  postgres:
    enabled: true
    config:
      connection_string: ${TARGET_PG_RO_URL}   # read-only role on the target DB
  # OpenShift-platform targets (environment.yaml platform: openshift) flip these
  # on as a reviewed git change. Tool inventory is oc get/describe/events/logs/
  # top/policy-can-i - read-only in effect. openshift/security exists too if
  # SCC/RBAC review is needed. Requires oc CLI + kubeconfig in the container.
  openshift/core:
    enabled: false
  openshift/logs:
    enabled: false
  openshift/live-metrics:
    enabled: false
mcp_servers:
  grafana:                                     # ~57 tools: dashboards, alert rules,
    description: "Grafana dashboards, alerting and datasource exploration"
    config:                                    # datasources, incidents, oncall
      url: ${GRAFANA_MCP_URL}                  # Grafana Cloud: https://<stack>.grafana.net/mcp
      mode: streamable-http
      extra_headers:
        X-Grafana-API-Key: ${GRAFANA_SA_TOKEN}
```

(Adjust key names to whatever the docs-check found; the enabled set and read-only stance are fixed. Self-hosted/air-gap Grafana needs a deployed grafana-mcp server instead of the Cloud `/mcp` endpoint - the URL env var is the only thing that changes.)

Append the evidence-layer block to `.env.example`:

```bash
# --- evidence layer (holmes.yaml references these) ---
GRAFANA_PROM_URL=                   # Grafana Cloud Prometheus/Mimir query endpoint
GRAFANA_SA_TOKEN=                   # service account token (Viewer), also used by the MCP server
GRAFANA_TEMPO_DS_UID=               # Tempo datasource uid in the Grafana stack
GRAFANA_MCP_URL=                    # e.g. https://<stack>.grafana.net/mcp
TARGET_OPENSEARCH_URL=http://spectre-opensearch:9200   # OpenSearch/ES of the target env
TARGET_PG_RO_URL=                   # read-only postgres role on the target DB
```

- [ ] **Step 3: Compose service**

Add to `docker-compose.yml`:

```yaml
  holmes:
    image: ${HOLMES_IMAGE}
    container_name: sre-holmes
    env_file: .env
    volumes:
      - ./config/holmes.yaml:/etc/holmes/config.yaml:ro   # path per docs-check
      - /var/run/docker.sock:/var/run/docker.sock:ro       # read-only socket
    ports:
      - "5050:5050"
    networks:
      - default
      - spectre

networks:
  spectre:
    external: true
    name: spectre_default
```

- [ ] **Step 4: Live check**

Makefile:

```makefile
holmes-check:
	curl -s -X POST localhost:5050/api/chat \
	  -H 'Content-Type: application/json' \
	  -d '{"ask": "Domain: infra\nList the state of the spectre containers", "model": "vertex_ai/gemini-2.5-flash"}' \
	  | python3 -m json.tool | head -60
```

Run with Spectre up (`cd ~/Code/spectre && docker compose up -d`, then `make up holmes-check` here). Expected: JSON containing `analysis` and a non-empty `tool_calls` list with docker toolset entries naming `keycloak`, `spectre-kong`, etc.

- [ ] **Step 5: Re-run the contract tests and commit**

Run: `uv run pytest tests/test_holmes_client.py tests/test_node_workers.py -q` (green after any drift fixes).

```bash
git checkout -b feat/sre-team-p4-real-integrations
git add config/holmes.yaml docker-compose.yml .env.example Makefile gateway
git commit -m "feat(sre-team): holmesgpt sidecar with read-only toolset manifest"
```

### Task 24: Grafana Cloud alert poller

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/poller_grafana.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/intake/grafana.py` (fingerprint from labels, shared by webhook + poller)
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/app.py` (start poller when enabled)
- Create: `agentic-sre-team/gateway/tests/test_poller_grafana.py`

**Interfaces:**
- Consumes: `IntakeService`, `Settings.grafana_*`.
- Produces:
  - `labels_fingerprint(labels: dict) -> str` in `intake/grafana.py`: `"grafana:" + sha256(sorted "k=v")[:32]`. **Both** the webhook normalizer and the poller now use it (replacing Grafana's own fingerprint field) so the two intake paths dedupe against each other (spec section 3). Update `test_intake_grafana.py`'s fingerprint assertion accordingly.
  - `GrafanaPoller(settings, intake, audit, health: dict)` with `async run()` - supervised loop: every `grafana_poll_interval_s` (default 30) GETs `{grafana_url}/api/prometheus/grafana/api/v1/alerts` with `Authorization: Bearer {grafana_sa_token}`, converts each `state in ("Alerting", "firing")` instance into a `Signal` (same labels/annotations mapping as the webhook path), and `intake.ingest`s it (noise control absorbs repeats). Exponential backoff to 300s on errors, `health["grafana_poller"] = "ok"|"error: ..."`, never crashes the app.
  - Lifespan: `if settings.grafana_poll_enabled and settings.grafana_url:` create the task; cancel on shutdown.
- Docs-check: Grafana alerting HTTP API - confirm the firing-instances path above and the response shape `{"data": {"alerts": [{"labels", "annotations", "state", "activeAt"}]}}` for Grafana Cloud stacks.

- [ ] **Step 1: Write the failing tests**

`gateway/tests/test_poller_grafana.py`:

```python
import httpx
import respx

from sre_gateway.audit import AuditWriter
from sre_gateway.intake.grafana import labels_fingerprint
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.poller_grafana import GrafanaPoller
from sre_gateway.intake.service import IntakeService
from sre_gateway.settings import Settings

ALERTS = {"data": {"alerts": [{
    "labels": {"alertname": "KeycloakDown", "service": "keycloak", "severity": "sev1"},
    "annotations": {"summary": "Keycloak is not responding"},
    "state": "Alerting", "activeAt": "2026-07-11T14:00:00Z", "value": "0"}]}}


def _poller(db, settings=None):
    audit = AuditWriter(db)
    intake = IntakeService(db, audit, NoiseControl(db, audit))
    s = settings or Settings(database_url="unused", grafana_url="https://stack.grafana.net",
                             grafana_sa_token="tok")
    return GrafanaPoller(s, intake, audit, health={})


@respx.mock
async def test_poll_opens_case_once_then_dedupes(db):
    route = respx.get(
        "https://stack.grafana.net/api/prometheus/grafana/api/v1/alerts"
    ).mock(return_value=httpx.Response(200, json=ALERTS))
    poller = _poller(db)
    r1 = await poller.poll_once()
    r2 = await poller.poll_once()
    assert route.called
    assert [x.action for x in r1] == ["open"]
    assert [x.action for x in r2] == ["suppress"]  # debounce window


def test_fingerprint_is_label_stable():
    a = labels_fingerprint({"alertname": "X", "service": "s"})
    b = labels_fingerprint({"service": "s", "alertname": "X"})
    assert a == b and a.startswith("grafana:")
```

- [ ] **Step 2: Run to verify failure, then implement**

Run: `uv run pytest tests/test_poller_grafana.py -q` -> `ModuleNotFoundError`.

Add to `intake/grafana.py` (and switch `normalize_grafana` to use it instead of `alert["fingerprint"]`):

```python
def labels_fingerprint(labels: dict) -> str:
    return "grafana:" + fingerprint_of(*sorted(f"{k}={v}" for k, v in labels.items()))
```

`src/sre_gateway/intake/poller_grafana.py`:

```python
import asyncio
import logging

import httpx

from sre_gateway.audit import AuditWriter
from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.grafana import labels_fingerprint
from sre_gateway.intake.service import IngestResult, IntakeService
from sre_gateway.settings import Settings

logger = logging.getLogger("sre.poller.grafana")
ALERTS_PATH = "/api/prometheus/grafana/api/v1/alerts"


class GrafanaPoller:
    def __init__(self, settings: Settings, intake: IntakeService, audit: AuditWriter,
                 health: dict) -> None:
        self.settings = settings
        self.intake = intake
        self.audit = audit
        self.health = health

    async def poll_once(self) -> list[IngestResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(
                f"{self.settings.grafana_url}{ALERTS_PATH}",
                headers={"Authorization": f"Bearer {self.settings.grafana_sa_token}"})
            res.raise_for_status()
        results: list[IngestResult] = []
        for alert in res.json().get("data", {}).get("alerts", []):
            if alert.get("state") not in ("Alerting", "firing"):
                continue
            labels = dict(alert.get("labels", {}))
            annotations = alert.get("annotations", {})
            results.append(await self.intake.ingest(Signal(
                source=SignalSource.grafana, reporter="grafana-poller",
                kind=CaseKind.incident, fingerprint=labels_fingerprint(labels),
                summary=annotations.get("summary") or labels.get("alertname", "alert"),
                labels=labels,
                payload={"labels": labels, "annotations": annotations,
                         "activeAt": alert.get("activeAt"), "via": "poller"})))
        return results

    async def run(self) -> None:
        backoff = self.settings.grafana_poll_interval_s
        while True:
            try:
                await self.poll_once()
                self.health["grafana_poller"] = "ok"
                backoff = self.settings.grafana_poll_interval_s
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.health["grafana_poller"] = f"error: {err}"[:120]
                logger.warning("grafana poll failed: %s", err)
                backoff = min(backoff * 2, 300)
            await asyncio.sleep(backoff)
```

Wire into the lifespan (store the task, cancel on shutdown, `health["grafana_poller"] = "disabled"` when off).

- [ ] **Step 3: Run tests, verify pass; live check**

Run: `uv run pytest -q` (including the updated grafana normalizer test).
Live: with `.env` filled (`SRE_GRAFANA_URL`, `SRE_GRAFANA_SA_TOKEN`, `SRE_GRAFANA_POLL_ENABLED=true`), `make up`, stop keycloak in Spectre, wait for a real alert to fire, watch `curl localhost:8080/api/cases` open a case (this is the phase demo - full run happens after Task 25 gives it real models).

- [ ] **Step 4: Commit**

```bash
git add gateway
git commit -m "feat(sre-team): grafana cloud alert poller with label fingerprint dedup"
```

### Task 25: Vertex model providers and LangSmith tracing

**Files:**
- Modify: `agentic-sre-team/gateway/pyproject.toml` (provider SDKs)
- Modify: `agentic-sre-team/docker-compose.yml` (Google ADC mount)
- Create: `agentic-sre-team/scripts/live_check.py`
- Modify: `agentic-sre-team/Makefile` (live-check target)

**Interfaces:**
- Consumes: `ModelFactory` (Task 9 wrote the provider code paths; this task makes them real).
- Produces: working `local` profile - small/medium on Gemini 2.5 Flash, frontier on Claude via Vertex, embeddings on `gemini-embedding-001`; LangSmith traces when `LANGSMITH_TRACING=true`.

- [ ] **Step 1: Add dependencies and docs-check**

```bash
cd agentic-sre-team/gateway
uv add "langchain-google-genai>=2.0" "langchain-google-vertexai>=2.0" "langchain-openai>=0.2"
```

Docs-check (Context7 `/langchain-ai/langchain-google`): confirm the constructor kwargs used in `llm/factory.py` - `ChatGoogleGenerativeAI(model=..., vertexai=True, project=..., location=...)`, `GoogleGenerativeAIEmbeddings(..., output_dimensionality=768)`, and `ChatAnthropicVertex(model_name=..., project=..., location=...)` - and the current Vertex Claude model id for `config/models.yaml` (`claude-sonnet-4-5@20250929` was current at plan time). Fix factory/config if the API moved.

- [ ] **Step 2: Compose + env**

In `docker-compose.yml` gateway service add the ADC mount (path documented in `.env.example`):

```yaml
    volumes:
      - ./config:/config:ro
      - ${GOOGLE_APPLICATION_CREDENTIALS:-/dev/null}:/secrets/gcp.json:ro
    environment:
      # (existing entries)
      GOOGLE_APPLICATION_CREDENTIALS: /secrets/gcp.json
```

LangSmith needs nothing beyond `.env` passthrough (`env_file: .env` already forwards `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`); LangGraph picks the env vars up natively. Air-gap: leave them unset.

- [ ] **Step 3: Live check script**

`scripts/live_check.py`:

```python
#!/usr/bin/env python3
"""Verifies Vertex credentials: one small-tier call and one embedding. Run from gateway/."""
import asyncio
from pathlib import Path

from sre_gateway.llm.factory import ModelFactory, load_models_config


async def main() -> None:
    cfg = load_models_config(Path("../config/models.yaml"))
    factory = ModelFactory(cfg)
    reply = await factory.chat("small", "live-check").ainvoke("Reply with the word: pong")
    print("small tier:", reply.content[:80])
    vec = (await factory.embed(["keycloak login outage"]))[0]
    print("embedding dim:", len(vec))
    assert len(vec) == 768
    reply = await factory.chat("frontier", "live-check").ainvoke("Reply with the word: pong")
    print("frontier tier:", reply.content[:80])


if __name__ == "__main__":
    asyncio.run(main())
```

Makefile: `live-check:\n\tcd gateway && uv run python ../scripts/live_check.py`

Run: `make live-check`. Expected: three lines, no exceptions (Vertex quota/Model Garden enablement issues surface here; falling back frontier to `gemini-2.5-pro` is a one-line `models.yaml` edit per spec section 12).

- [ ] **Step 4: Phase demo (manual, real everything)**

With Spectre + this stack up, real `.env`, `SRE_MODELS_PROFILE=local`, `SRE_HOLMES_URL=http://holmes:5050`:

```bash
docker stop keycloak    # crude chaos; scripts/chaos.sh arrives in Task 47
# wait for the Grafana alert -> poller opens a case
curl -s localhost:8080/api/cases | python3 -m json.tool
# watch it reach gate_rca; check the LangSmith project for the traced run
docker start keycloak
```

Expected: a real investigation with Holmes tool calls recorded as evidence, an RCA at gate 1, and (if enabled) a LangSmith trace covering every node.

- [ ] **Step 5: Commit**

```bash
git add gateway docker-compose.yml scripts/live_check.py Makefile
git commit -m "feat(sre-team): vertex providers live, adc mount, langsmith passthrough"
```

### Task 26: Grafana Explore deep links on evidence

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/graph/grafana_links.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/settings.py` (datasource UIDs)
- Modify: `agentic-sre-team/gateway/src/sre_gateway/graph/deps.py` + `nodes/workers.py` (attach `source_url`)
- Create: `agentic-sre-team/gateway/tests/test_grafana_links.py`

**Interfaces:**
- Consumes: `Settings.grafana_url`; new settings `grafana_prom_ds_uid: str | None`, `grafana_loki_ds_uid: str | None`.
- Produces: `LinkBuilder(settings)` with `url_for(toolset: str, invocation: str) -> str | None` - builds a Grafana Explore URL with the exact query pre-filled for `prometheus`/`loki` toolsets, `None` otherwise. `GraphDeps` gains `links: LinkBuilder | None = None`; workers set `EvidenceRow.source_url = deps.links.url_for(...)` when available (wireframe screen 2 note 11).

- [ ] **Step 1: Write the failing test**

`gateway/tests/test_grafana_links.py`:

```python
from urllib.parse import quote

from sre_gateway.graph.grafana_links import LinkBuilder
from sre_gateway.settings import Settings


def _links() -> LinkBuilder:
    return LinkBuilder(Settings(database_url="x", grafana_url="https://g.example.net",
                                grafana_prom_ds_uid="prom-uid",
                                grafana_loki_ds_uid="loki-uid"))


def test_prometheus_query_builds_explore_url():
    url = _links().url_for("prometheus", 'up{job="keycloak"}')
    assert url.startswith("https://g.example.net/explore?")
    assert "prom-uid" in url and quote('up{job="keycloak"}', safe="") in url


def test_unknown_toolset_returns_none():
    assert _links().url_for("docker", "docker ps") is None
    assert LinkBuilder(Settings(database_url="x")).url_for("prometheus", "up") is None
```

- [ ] **Step 2: Run to verify failure, then implement**

`src/sre_gateway/graph/grafana_links.py`:

```python
import json
from urllib.parse import quote

from sre_gateway.settings import Settings


class LinkBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def url_for(self, toolset: str, invocation: str) -> str | None:
        if not self.settings.grafana_url or not invocation:
            return None
        uid = {"prometheus": self.settings.grafana_prom_ds_uid,
               "grafana/loki": self.settings.grafana_loki_ds_uid,
               "loki": self.settings.grafana_loki_ds_uid}.get(toolset)
        if not uid:
            return None
        panes = {"sre": {"datasource": uid,
                         "queries": [{"refId": "A", "expr": invocation,
                                      "datasource": {"uid": uid}}],
                         "range": {"from": "now-1h", "to": "now"}}}
        return (f"{self.settings.grafana_url}/explore?schemaVersion=1"
                f"&panes={quote(json.dumps(panes), safe='')}")
```

Wire: `GraphDeps.links: LinkBuilder | None = None`; in `workers.py` set `source_url=deps.links.url_for(tc.toolset, tc.invocation) if deps.links else None` on both the row and the state dict; build `LinkBuilder(settings)` in the app lifespan. Docs-check: open one generated URL against the real Grafana Cloud stack and confirm Explore loads the query (the `panes` URL schema is stable in Grafana 10/11; adjust once here if the stack renders differently).

- [ ] **Step 3: Run tests, verify pass, commit**

Run: `uv run pytest -q`

```bash
git add gateway
git commit -m "feat(sre-team): grafana explore deep links on prometheus and loki evidence"
# PR: feat/sre-team-p4-real-integrations -> main
```

---

## Phase 5 - Ops console UI

Branch: `feat/sre-team-p5-ui`

All screens implement `docs/design/wireframes-v1.html` and its numbered rationale notes. Visual direction (wireframes final section): dark-first dense theme with an equal-care light theme, severity as a semantic scale separate from the single red accent, tabular numerals + mono for IDs/queries/metrics, no decorative animation - the only motion is real streaming state.

### Task 27: UI scaffold - Vite, router, query, theme, API client, SSE hook, nginx

**Files:**
- Create: `agentic-sre-team/ui/package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/theme.css`
- Create: `agentic-sre-team/ui/src/api/types.ts`, `src/api/client.ts`, `src/api/sse.ts`
- Create: `agentic-sre-team/ui/src/components/TopBar.tsx`
- Create: `agentic-sre-team/ui/src/test/setup.ts`, `src/api/client.test.ts`
- Create: `agentic-sre-team/ui/Dockerfile`, `nginx.conf`
- Modify: `agentic-sre-team/docker-compose.yml` (ui service), `Makefile` (test-ui, lint-ui)

**Interfaces:**
- Consumes: the gateway API (Tasks 8, 21).
- Produces:
  - `api<T>(path, init?) -> Promise<T>` fetch wrapper (throws on non-2xx), `apiPost(path, body)`.
  - Types mirroring the API JSON: `CaseSummary`, `CaseDetail` (`case`, `signals`, `hypotheses`, `evidence`, `artifacts`, `approvals`), `Hypothesis`, `Evidence`, `Artifact`, `Governance`, `Activity`.
  - `useCaseStream(caseId: string): {events: StreamEvent[], connected: boolean}` - native `EventSource` on `/api/cases/{id}/stream`, appends events, exposes reconnect state (the "Live stream reconnecting - showing last saved state" banner); `EventSource` auto-sends `Last-Event-ID` because the server sets `id:`.
  - `theme.css` design tokens (`--paper/--panel/--ink/--ink-2/--ink-3/--line/--accent` + `--sev1..--sev4`), dark default via `:root`, light via `@media (prefers-color-scheme: light)`; `.mono`, `.num` (tabular numerals) utilities.
  - Routes: `/` -> redirect `/cases`; `/cases`, `/cases/:id`, `/cases/:id/artifact/:kind`, `/governance`, `/chat` (placeholder until Task 45). `TopBar` on every screen: product chip, `env: local-docker` chip (from healthz), fleet status chip (from `/api/governance` - `agents: N idle · M running`), `PAUSE ALL` button (confirm dialog -> `POST /api/governance/pause`, audit-logged) - wireframe notes 1-2.
  - nginx: serve static build, proxy `/api/` to `gateway:8080` with `proxy_buffering off` (SSE) and long read timeout; compose service `ui` on host port 8088.

- [ ] **Step 1: Scaffold**

```bash
cd agentic-sre-team && npm create vite@latest ui -- --template react-ts
cd ui && npm i @tanstack/react-query react-router-dom
npm i -D vitest @testing-library/react @testing-library/user-event @testing-library/jest-dom jsdom
```

Set `vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8080" } },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    globals: true,
  },
});
```

`src/test/setup.ts`: `import "@testing-library/jest-dom/vitest";`
`package.json` scripts: `"test": "vitest run", "lint": "tsc --noEmit"`.

- [ ] **Step 2: Write the failing client test**

`src/api/client.test.ts`:

```ts
import { afterEach, expect, test, vi } from "vitest";
import { api } from "./client";

afterEach(() => vi.unstubAllGlobals());

test("api returns parsed json", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: 1 }))));
  expect(await api<{ ok: number }>("/api/healthz")).toEqual({ ok: 1 });
});

test("api throws on http error with body detail", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ detail: "bad gate" }), { status: 409 })));
  await expect(api("/api/x")).rejects.toThrow(/bad gate/);
});
```

Run: `npm test` -> FAIL (`client` missing).

- [ ] **Step 3: Implement client, types, sse, theme, app shell**

`src/api/client.ts`:

```ts
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep statusText */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const apiPost = <T,>(path: string, body: unknown): Promise<T> =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" },
                 body: JSON.stringify(body) });
```

`src/api/types.ts` (mirror the gateway JSON exactly):

```ts
export interface CaseSummary {
  id: string; display_id: string; kind: "incident" | "pipeline_failure";
  status: "open" | "waiting_approval" | "needs_human" | "closed";
  phase: string; title: string; severity: 1 | 2 | 3 | 4; effort: string; round: number;
  failure_class: string | null; spend_usd: number; halt_reason: string | null;
  created_at: string; updated_at: string; closed_at: string | null;
}
export interface SignalItem { id: string; source: string; reporter: string; summary: string;
  is_primary: boolean; attach_reason: string; received_at: string; labels: Record<string, string>; }
export interface Hypothesis { hid: string; statement: string;
  status: "open" | "supported" | "refuted"; confidence: number;
  evidence_for: string[]; evidence_against: string[]; }
export interface Evidence { eid: string; worker: string; toolset: string; invocation: string;
  excerpt: string; source_url: string | null; observed_at: string;
  hypothesis_links: { hid: string; direction: "for" | "against" }[]; }
export interface Artifact { id: string; kind: "rca" | "runbook"; version: number;
  body_md: string; body_edited_md: string | null; structured: Record<string, unknown>;
  verification: { verified: boolean; checked: number;
                  failures: { claim: string; reason: string }[] } | null;
  model_id: string; cost_usd: number; created_at: string; }
export interface Approval { gate: string; decision: string; decided_by: string;
  channel: string; annotation: string; decided_at: string; }
export interface CaseDetail { case: CaseSummary; signals: SignalItem[];
  hypotheses: Hypothesis[]; evidence: Evidence[]; artifacts: Artifact[];
  approvals: Approval[]; }
export interface Governance { paused: boolean; scm_draft_mr: boolean; running_cases: number;
  agents: { agent: string; tier: string; tools: string[]; usd_per_day: number;
            spend_today: number }[];
  suppression_24h: Record<string, number>; cases_opened_24h: number; }
export interface Activity { buckets: { ts: string; signals: number; suppressed: number }[];
  cases: { id: string; display_id: string; severity: number; kind: string;
           created_at: string }[];
  annotations: { ts: string; text: string; kind: string }[]; }
export interface StreamEvent { type: string; seq?: number; [k: string]: unknown; }
```

`src/api/sse.ts`:

```ts
import { useEffect, useRef, useState } from "react";
import type { StreamEvent } from "./types";

export function useCaseStream(caseId: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const source = new EventSource(`/api/cases/${caseId}/stream`);
    sourceRef.current = source;
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const push = (type: string) => (e: MessageEvent) =>
      setEvents((prev) => [...prev.slice(-500), { type, ...JSON.parse(e.data) }]);
    for (const t of ["node_start", "node_end", "plan", "tool_call", "worker_warning",
                     "gate_waiting", "node_update", "token", "parked", "error",
                     "context_added", "run_idle"]) {
      source.addEventListener(t, push(t));
    }
    return () => { source.close(); setConnected(false); };
  }, [caseId]);

  return { events, connected };
}
```

`src/theme.css` (tokens only; component classes accrete in later tasks):

```css
:root {
  --paper: #131619; --panel: #1b1f24; --ink: #dde2e7; --ink-2: #9aa4ad; --ink-3: #667077;
  --line: #333b43; --line-2: #262d34; --accent: #e0685c; --accent-soft: rgba(224,104,92,.12);
  --sev1: #e0685c; --sev2: #e09a5c; --sev3: #d9c46a; --sev4: #7fa6b8;
  --ok: #7fb88a;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  --sans: ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: light) {
  :root { --paper: #f4f5f6; --panel: #fff; --ink: #21262b; --ink-2: #5b646d;
          --ink-3: #8a939c; --line: #d4d9de; --line-2: #e4e8eb; --accent: #c2453a;
          --accent-soft: rgba(194,69,58,.09); }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink);
       font: 14px/1.5 var(--sans); }
.mono { font-family: var(--mono); font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
.dim { color: var(--ink-3); }
button { font: inherit; cursor: pointer; }
```

`src/App.tsx` (router + top bar; screens are placeholders replaced by their tasks):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import "./theme.css";

const qc = new QueryClient({ defaultOptions: { queries: { refetchInterval: 3000 } } });

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <TopBar />
        <main style={{ maxWidth: 1280, margin: "0 auto", padding: "0 16px" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/cases" replace />} />
            <Route path="/cases" element={<div>queue (Task 28)</div>} />
            <Route path="/cases/:id" element={<div>detail (Tasks 29-30)</div>} />
            <Route path="/cases/:id/artifact/:kind" element={<div>artifact (Task 31)</div>} />
            <Route path="/governance" element={<div>governance (Task 32)</div>} />
            <Route path="/chat" element={<div>chat (Task 45)</div>} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

`src/components/TopBar.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, apiPost } from "../api/client";
import type { Governance } from "../api/types";

export function TopBar() {
  const { data: gov, refetch } = useQuery({
    queryKey: ["governance"],
    queryFn: () => api<Governance>("/api/governance"),
  });
  const idle = gov ? Math.max(0, gov.agents.length - gov.running_cases) : 0;
  const pause = async () => {
    const next = !gov?.paused;
    if (window.confirm(next ? "Pause ALL agents? Intake and running cases halt at the "
                              + "next node. Audit-logged." : "Resume all agents?")) {
      await apiPost("/api/governance/pause", { paused: next, actor: "console" });
      refetch();
    }
  };
  return (
    <header style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 16px",
                     borderBottom: "1px solid var(--line)" }}>
      <Link to="/cases" style={{ color: "var(--ink)", fontWeight: 700,
                                 textDecoration: "none" }}>SRE TEAM</Link>
      <span className="mono dim">env: local-docker</span>
      <Link to="/chat" className="mono dim">chat</Link>
      <span style={{ flex: 1 }} />
      <Link to="/governance" className="mono dim">
        agents: {idle} idle · {gov?.running_cases ?? 0} running
      </Link>
      <button onClick={pause} className="mono"
              style={{ color: "var(--accent)", border: "1px solid var(--accent)",
                       background: gov?.paused ? "var(--accent-soft)" : "transparent",
                       padding: "4px 10px" }}>
        {gov?.paused ? "PAUSED - RESUME" : "PAUSE ALL"}
      </button>
    </header>
  );
}
```

- [ ] **Step 4: nginx + Dockerfile + compose**

`ui/nginx.conf`:

```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  location /api/ {
    proxy_pass http://gateway:8080;
    proxy_buffering off;           # SSE
    proxy_read_timeout 1h;
    proxy_set_header Connection "";
    proxy_http_version 1.1;
  }
  location / { try_files $uri /index.html; }
}
```

`ui/Dockerfile`:

```dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
```

Compose service:

```yaml
  ui:
    build: ./ui
    container_name: sre-ui
    ports:
      - "8088:80"
    depends_on:
      - gateway
```

Makefile: `test-ui:\n\tcd ui && npm test` and `lint-ui:\n\tcd ui && npm run lint`; extend `test:` to run both suites.

- [ ] **Step 5: Verify and commit**

Run: `npm test && npm run lint` (ui), then `make up-fake` and open `http://localhost:8088` - top bar renders with live fleet chip.

```bash
git checkout -b feat/sre-team-p5-ui
git add ui docker-compose.yml Makefile
git commit -m "feat(sre-team): ui scaffold with api client, sse hook, theme tokens, nginx"
```

### Task 28: Case queue screen with activity timeline strip

**Files:**
- Create: `agentic-sre-team/ui/src/components/{SevPill,PhaseChip,LiveDot,TimelineStrip,Skeleton}.tsx`
- Create: `agentic-sre-team/ui/src/screens/QueueScreen.tsx`
- Create: `agentic-sre-team/ui/src/screens/QueueScreen.test.tsx`
- Modify: `agentic-sre-team/ui/src/App.tsx` (mount route)

**Interfaces:**
- Consumes: `GET /api/cases`, `GET /api/activity`, `GET /api/healthz`.
- Produces: `/cases` per wireframe screen 1 - tabs `Needs you / Active / Needs human / Closed` with counts (default **Needs you**, notes 3); rows: severity stripe (`--sev{n}`; kind badge `PIPELINE` instead of stripe for pipeline cases, note 8), display id (mono), title, SEV pill, failure-class chip with trailing `?` when confidence is low (note 9), phase chip, live dot for `status=open` (note 6), source, waiting/elapsed time, per-case spend (note 5), primary action (`Review RCA` -> `/cases/:id/artifact/rca`, `Review runbook` -> `.../runbook`, else `Watch` -> detail). `TimelineStrip`: 24h signal-density bars (suppressed shown dimmer within the bar), case-open markers, annotation ticks (note 10). Empty state proves liveness: "No active cases... Intake is healthy: webhook OK, poller OK, telegram OK" from healthz components. Loading: skeleton rows, no spinners.

- [ ] **Step 1: Write the failing test**

`src/screens/QueueScreen.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { QueueScreen } from "./QueueScreen";

const CASES = { cases: [
  { id: "c1", display_id: "CASE-0142", kind: "incident", status: "waiting_approval",
    phase: "gate_rca", title: "Error rate spike on admin-server", severity: 2,
    effort: "medium", round: 1, failure_class: null, spend_usd: 0.87, halt_reason: null,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    closed_at: null },
  { id: "c2", display_id: "CASE-0139", kind: "pipeline_failure", status: "open",
    phase: "ci_worker", title: "CI failing: test job on main", severity: 3,
    effort: "medium", round: 1, failure_class: "flaky", spend_usd: 0.09,
    halt_reason: null, created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(), closed_at: null },
]};

function mount() {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo) => {
    const path = String(url);
    if (path.startsWith("/api/cases")) return new Response(JSON.stringify(CASES));
    if (path.startsWith("/api/activity"))
      return new Response(JSON.stringify({ buckets: [], cases: [], annotations: [] }));
    return new Response(JSON.stringify({ status: "ok", components: {} }));
  }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter>
    <QueueScreen /></MemoryRouter></QueryClientProvider>);
}

test("needs-you tab is default and shows the waiting case with its action", async () => {
  mount();
  expect(await screen.findByText("CASE-0142")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /review rca/i }))
    .toHaveAttribute("href", "/cases/c1/artifact/rca");
  expect(screen.queryByText("CASE-0139")).not.toBeInTheDocument(); // active tab only
});

test("pipeline case shows kind badge and failure class on the active tab", async () => {
  mount();
  (await screen.findByRole("button", { name: /active/i })).click();
  expect(await screen.findByText("PIPELINE")).toBeInTheDocument();
  expect(screen.getByText(/class: flaky/i)).toBeInTheDocument();
});
```

Run: `npm test` -> FAIL (screen missing).

- [ ] **Step 2: Implement components and screen**

`src/components/SevPill.tsx`:

```tsx
export const SevPill = ({ severity }: { severity: number }) => (
  <span className="mono" style={{ border: `1px solid var(--sev${severity})`,
    color: `var(--sev${severity})`, padding: "1px 8px" }}>SEV-{severity}</span>
);
```

`src/components/PhaseChip.tsx`:

```tsx
const LABELS: Record<string, string> = {
  triage: "Triaging", plan: "Planning", metrics_worker: "Investigating",
  logs_worker: "Investigating", infra_worker: "Investigating",
  changes_worker: "Investigating", ci_worker: "Investigating",
  synthesize: "Synthesizing", rca: "Drafting RCA", verify_citations: "Verifying",
  gate_rca: "RCA awaiting review", remediate: "Drafting runbook",
  gate_runbook: "Runbook awaiting review", publish: "Publishing",
  closed: "Closed", parked: "Needs human", queued: "Queued",
};
export const PhaseChip = ({ phase }: { phase: string }) => (
  <span className="mono" style={{ border: "1px solid var(--line)", padding: "1px 8px",
    color: "var(--ink-2)" }}>{LABELS[phase] ?? phase}</span>
);
```

`src/components/LiveDot.tsx`:

```tsx
export const LiveDot = () => (
  <span className="mono" style={{ color: "var(--accent)" }}>● live</span>
);
```

`src/components/Skeleton.tsx`:

```tsx
export const Skeleton = ({ width = "100%" }: { width?: string | number }) => (
  <div style={{ height: 10, width, background: "var(--line-2)", margin: "12px 0" }} />
);
```

`src/components/TimelineStrip.tsx`:

```tsx
import type { Activity } from "../api/types";

export function TimelineStrip({ activity }: { activity: Activity }) {
  const max = Math.max(1, ...activity.buckets.map((b) => b.signals + b.suppressed));
  const w = 1200, h = 42, bw = w / Math.max(1, activity.buckets.length);
  const first = Date.parse(activity.buckets[0]?.ts ?? new Date().toISOString());
  const span = Math.max(1, Date.now() - first);
  const x = (iso: string) => ((Date.parse(iso) - first) / span) * w;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h,
        borderBottom: "1px solid var(--line-2)" }} aria-label="environment activity timeline">
      {activity.buckets.map((b, i) => {
        const total = ((b.signals + b.suppressed) / max) * (h - 14);
        const solid = (b.signals / max) * (h - 14);
        return (
          <g key={b.ts}>
            <rect x={i * bw + 1} y={h - 8 - total} width={bw - 2} height={total}
                  fill="var(--line)" />
            <rect x={i * bw + 1} y={h - 8 - solid} width={bw - 2} height={solid}
                  fill="var(--ink-3)" />
          </g>
        );
      })}
      {activity.cases.map((c) => (
        <circle key={c.id} cx={x(c.created_at)} cy={6} r={3}
                fill={`var(--sev${c.severity})`} />
      ))}
      {activity.annotations.map((a, i) => (
        <rect key={i} x={x(a.ts)} y={0} width={1.5} height={h} fill="var(--accent)" />
      ))}
    </svg>
  );
}
```

`src/screens/QueueScreen.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Activity, CaseSummary } from "../api/types";
import { LiveDot } from "../components/LiveDot";
import { PhaseChip } from "../components/PhaseChip";
import { SevPill } from "../components/SevPill";
import { Skeleton } from "../components/Skeleton";
import { TimelineStrip } from "../components/TimelineStrip";

const TABS = [
  ["needs_you", "Needs you", (c: CaseSummary) => c.status === "waiting_approval"],
  ["active", "Active", (c: CaseSummary) => c.status === "open"],
  ["needs_human", "Needs human", (c: CaseSummary) => c.status === "needs_human"],
  ["closed", "Closed", (c: CaseSummary) => c.status === "closed"],
] as const;

const mins = (iso: string) =>
  `${Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))}m`;

function action(c: CaseSummary) {
  if (c.phase === "gate_rca") return { label: "Review RCA", to: `/cases/${c.id}/artifact/rca` };
  if (c.phase === "gate_runbook")
    return { label: "Review runbook", to: `/cases/${c.id}/artifact/runbook` };
  return { label: "Watch", to: `/cases/${c.id}` };
}

export function QueueScreen() {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("needs_you");
  const cases = useQuery({ queryKey: ["cases"],
    queryFn: () => api<{ cases: CaseSummary[] }>("/api/cases") });
  const activity = useQuery({ queryKey: ["activity"],
    queryFn: () => api<Activity>("/api/activity?hours=24") });
  const health = useQuery({ queryKey: ["healthz"],
    queryFn: () => api<{ components: Record<string, string> }>("/api/healthz") });

  if (cases.isPending) return <div>{[80, 65, 72].map((w) => <Skeleton key={w} width={`${w}%`} />)}</div>;
  const all = cases.data?.cases ?? [];
  const rows = all.filter(TABS.find(([k]) => k === tab)![2])
    .sort((a, b) => (a.status === "waiting_approval" ? -1 : 1) - (b.status === "waiting_approval" ? -1 : 1));

  return (
    <section>
      <nav style={{ display: "flex", gap: 8, padding: "10px 0" }}>
        {TABS.map(([key, label, pred]) => (
          <button key={key} onClick={() => setTab(key)} className="mono"
            style={{ border: "1px solid var(--line)", padding: "3px 10px",
              background: tab === key ? "var(--line-2)" : "transparent",
              color: "var(--ink-2)" }}>
            {label} ({all.filter(pred).length})
          </button>
        ))}
      </nav>
      {activity.data && <TimelineStrip activity={activity.data} />}
      {rows.length === 0 && (
        <p className="dim">No cases here. Last case closed{" "}
          {all.find((c) => c.closed_at)?.closed_at ? mins(all.find((c) => c.closed_at)!.closed_at!) + " ago" : "never"}.
          Intake is healthy:{" "}
          {Object.entries(health.data?.components ?? {}).map(([k, v]) => `${k} ${v}`).join(", ") || "starting"}.
        </p>
      )}
      {rows.map((c) => {
        const act = action(c);
        const waiting = c.status === "waiting_approval";
        return (
          <div key={c.id} style={{ display: "flex", gap: 12, alignItems: "center",
            padding: "10px 8px", borderBottom: "1px solid var(--line-2)",
            background: waiting ? "var(--accent-soft)" : "transparent" }}>
            {c.kind === "pipeline_failure"
              ? <span className="mono" style={{ border: "1px solid var(--line)", padding: "1px 6px" }}>PIPELINE</span>
              : <span style={{ width: 4, alignSelf: "stretch", background: `var(--sev${c.severity})` }} />}
            <span className="mono dim">{c.display_id}</span>
            <Link to={`/cases/${c.id}`} style={{ color: "var(--ink)", textDecoration: "none" }}>{c.title}</Link>
            <SevPill severity={c.severity} />
            {c.failure_class && <span className="mono dim">class: {c.failure_class}</span>}
            <PhaseChip phase={c.phase} />
            {c.status === "open" && <LiveDot />}
            <span style={{ flex: 1 }} />
            <span className="mono dim num">{waiting ? `waiting ${mins(c.updated_at)}` : `${mins(c.created_at)} elapsed`}</span>
            <span className="mono dim num">${c.spend_usd.toFixed(2)}</span>
            <Link to={act.to} className="mono" style={{ border: "1px solid var(--line)",
              padding: "3px 10px", color: "var(--ink)", textDecoration: "none" }}>{act.label}</Link>
          </div>
        );
      })}
    </section>
  );
}
```

Mount in `App.tsx`: `<Route path="/cases" element={<QueueScreen />} />`.

- [ ] **Step 3: Run tests, verify, commit**

Run: `npm test` -> both tests pass. Visual check against `make up-fake` + `make smoke` data at `localhost:8088/cases`.

```bash
git add ui
git commit -m "feat(sre-team): case queue with tabs, activity timeline strip, empty and loading states"
```

### Task 29: Case detail - live progress ledger

**Files:**
- Create: `agentic-sre-team/ui/src/components/Ledger.tsx`
- Create: `agentic-sre-team/ui/src/screens/CaseDetailScreen.tsx`
- Create: `agentic-sre-team/ui/src/components/Ledger.test.tsx`
- Modify: `agentic-sre-team/ui/src/App.tsx`

**Interfaces:**
- Consumes: `useCaseStream`, `GET /api/cases/{id}`, `POST /api/cases/{id}/park|context`.
- Produces: `/cases/:id` shell per wireframe screen 2: header (display id, title, SEV pill, `Investigating · round N of 2` counter - note 1, `Open in Grafana` when any evidence has a source_url, `Escalate to human` -> park - note 2, `Pause case` -> park), three panes (ledger | board | evidence; board+evidence filled by Task 30), docked decision bar (note 12: "No decision needed yet... You will be pinged" vs a `Review <artifact>` link when waiting), reconnect banner when `connected=false` ("Live stream reconnecting - showing last saved state"), `Add context for the agents` prompt -> `POST .../context` (note 13). `Ledger` renders `StreamEvent[]`: one entry per node (`node_start`..`node_end` pairs; live entry highlighted with its latest `token` text as intent), `plan` events show the fan-out decision (note 4), `tool_call` events render as collapsed one-liners `holmes:<toolset> · <description> +E?` (note 5), `worker_warning` as a visible degradation line, `gate_waiting`/`parked`/`error` as terminal markers.

- [ ] **Step 1: Failing Ledger test**

`src/components/Ledger.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Ledger } from "./Ledger";

test("groups events into node entries with tool lines", () => {
  render(<Ledger events={[
    { type: "node_start", node: "triage" },
    { type: "node_end", node: "triage" },
    { type: "plan", workers: ["metrics_worker", "logs_worker"], effort: "medium", round: 1 },
    { type: "node_start", node: "synthesize" },
    { type: "tool_call", worker: "metrics", phase: "tool_result",
      tool_name: "prometheus_query_range", toolset: "prometheus",
      description: "p95 by route via Kong" },
  ]} />);
  expect(screen.getByText(/Triage/)).toBeInTheDocument();
  expect(screen.getByText(/fan-out: metrics_worker, logs_worker/i)).toBeInTheDocument();
  expect(screen.getByText(/holmes:prometheus/)).toBeInTheDocument();
  expect(screen.getByText(/synthesize/i).closest("[data-live]")).toBeTruthy();
});
```

Run: `npm test` -> FAIL.

- [ ] **Step 2: Implement Ledger + screen shell**

`src/components/Ledger.tsx`:

```tsx
import { Fragment } from "react";
import type { StreamEvent } from "../api/types";

const NAMES: Record<string, string> = {
  triage: "Triage", plan: "Plan", metrics_worker: "Metrics worker",
  logs_worker: "Logs worker", infra_worker: "Infra worker",
  changes_worker: "Changes worker", ci_worker: "CI worker",
  synthesize: "Synthesize", rca: "RCA", verify_citations: "Verify citations",
  remediate: "Remediate", publish: "Publish", park: "Park",
};

export function Ledger({ events }: { events: StreamEvent[] }) {
  const open = new Set<string>();
  const entries: { key: string; title: string; live: boolean; lines: StreamEvent[] }[] = [];
  const byNode: Record<string, (typeof entries)[number]> = {};
  for (const e of events) {
    if (e.type === "node_start") {
      const node = String(e.node);
      const entry = { key: `${node}-${entries.length}`, title: NAMES[node] ?? node,
                      live: true, lines: [] as StreamEvent[] };
      entries.push(entry); byNode[node] = entry; open.add(node);
    } else if (e.type === "node_end") {
      const node = String(e.node);
      if (byNode[node]) byNode[node].live = false;
      open.delete(node);
    } else if (e.type === "plan") {
      entries.push({ key: `plan-${entries.length}`, title: "Plan · deterministic",
        live: false, lines: [e] });
    } else if (e.type === "tool_call" && e.phase === "tool_result") {
      const target = entries.filter((x) => x.live).at(-1) ?? entries.at(-1);
      target?.lines.push(e);
    } else if (["worker_warning", "gate_waiting", "parked", "error", "token",
                "context_added"].includes(e.type)) {
      const target = entries.filter((x) => x.live).at(-1) ?? entries.at(-1);
      target?.lines.push(e);
    }
  }
  return (
    <div>
      {entries.map((entry) => (
        <div key={entry.key} data-live={entry.live || undefined}
             style={{ borderLeft: `2px solid ${entry.live ? "var(--accent)" : "var(--line)"}`,
                      padding: "2px 0 10px 12px", marginLeft: 4 }}>
          <b style={{ fontSize: 12 }}>{entry.title}{entry.live ? " · running" : ""}</b>
          {entry.lines.map((line, i) => (
            <Fragment key={i}>
              {line.type === "plan" && (
                <div className="mono dim">fan-out: {(line.workers as string[]).join(", ")}
                  {" "}(effort {String(line.effort)}, round {String(line.round)})</div>)}
              {line.type === "tool_call" && (
                <div className="mono dim" style={{ border: "1px dashed var(--line)",
                    padding: "3px 8px", marginTop: 4 }}>
                  holmes:{String(line.toolset)} · {String(line.description)}</div>)}
              {line.type === "token" && (
                <div className="dim" style={{ fontSize: 12 }}>{String(line.text)}</div>)}
              {line.type === "worker_warning" && (
                <div className="mono" style={{ color: "var(--sev2)" }}>
                  degraded: {String(line.worker)} - {String(line.error)}</div>)}
              {line.type === "gate_waiting" && (
                <div className="mono" style={{ color: "var(--accent)" }}>
                  waiting on gate: {String(line.gate)}</div>)}
              {(line.type === "parked" || line.type === "error") && (
                <div className="mono" style={{ color: "var(--accent)" }}>
                  {line.type}: {String(line.reason ?? line.error ?? "")}</div>)}
            </Fragment>
          ))}
        </div>
      ))}
    </div>
  );
}
```

`src/screens/CaseDetailScreen.tsx` (shell; panes 2-3 land in Task 30):

```tsx
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, apiPost } from "../api/client";
import { useCaseStream } from "../api/sse";
import type { CaseDetail } from "../api/types";
import { Ledger } from "../components/Ledger";
import { PhaseChip } from "../components/PhaseChip";
import { SevPill } from "../components/SevPill";

export function CaseDetailScreen() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { events, connected } = useCaseStream(id);
  const { data } = useQuery({ queryKey: ["case", id],
    queryFn: () => api<CaseDetail>(`/api/cases/${id}`) });
  if (!data) return null;
  const c = data.case;
  const waitingGate = c.phase === "gate_rca" ? "rca"
    : c.phase === "gate_runbook" ? "runbook" : null;
  const grafana = data.evidence.find((e) => e.source_url)?.source_url;

  const park = async (reason: string) => {
    await apiPost(`/api/cases/${id}/park`, { reason, actor: "console" });
    qc.invalidateQueries({ queryKey: ["case", id] });
  };
  const addContext = async () => {
    const text = window.prompt("Context for the agents (lands at the next node):");
    if (text) await apiPost(`/api/cases/${id}/context`, { text, author: "console" });
  };

  return (
    <section>
      {!connected && (
        <div className="mono" style={{ background: "var(--accent-soft)", padding: "4px 10px" }}>
          Live stream reconnecting - showing last saved state.</div>)}
      <header style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 0" }}>
        <span className="mono dim">{c.display_id}</span>
        <b>{c.title}</b>
        <SevPill severity={c.severity} />
        <PhaseChip phase={c.phase} />
        {c.status === "open" && <span className="mono dim">round {c.round} of 2</span>}
        <span style={{ flex: 1 }} />
        {grafana && <a className="mono dim" href={grafana} target="_blank" rel="noreferrer">Open in Grafana</a>}
        <button className="mono" onClick={() => park("manual escalation")}>Escalate to human</button>
        <button className="mono" style={{ color: "var(--accent)" }}
                onClick={() => park("paused by operator")}>Pause case</button>
      </header>
      <div style={{ display: "grid", gridTemplateColumns: "33% 1fr 30%", gap: 0,
                    border: "1px solid var(--line)", minHeight: 430 }}>
        <div style={{ padding: 12 }}>
          <h4 className="mono dim">PROGRESS LEDGER</h4>
          <Ledger events={events} />
        </div>
        <div style={{ padding: 12, borderLeft: "1px solid var(--line-2)" }} data-pane="board" />
        <div style={{ padding: 12, borderLeft: "1px solid var(--line-2)" }} data-pane="evidence" />
      </div>
      <footer style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 12px",
                       borderTop: "1.5px dashed var(--accent)", background: "var(--accent-soft)" }}>
        {waitingGate ? (
          <Link to={`/cases/${id}/artifact/${waitingGate}`} className="mono"
                style={{ color: "var(--accent)" }}>
            Decision needed: review the {waitingGate} now</Link>
        ) : c.status === "needs_human" ? (
          <>
            <span className="mono" style={{ color: "var(--accent)" }}>
              Parked: {c.halt_reason}</span>
            <button className="mono" onClick={async () => {
              await apiPost(`/api/cases/${id}/resume`, { actor: "console" });
              qc.invalidateQueries({ queryKey: ["case", id] });
            }}>Resume</button>
          </>
        ) : (
          <span className="mono dim">No decision needed yet. Next gate: RCA review.
            You will be pinged on Telegram.</span>
        )}
        <span style={{ flex: 1 }} />
        <button className="mono" onClick={addContext}>Add context for the agents</button>
      </footer>
    </section>
  );
}
```

Mount the route in `App.tsx`.

- [ ] **Step 3: Run tests, verify pass, commit**

Run: `npm test`

```bash
git add ui
git commit -m "feat(sre-team): case detail shell with live progress ledger and docked decision bar"
```

### Task 30: Case detail - hypothesis board and evidence panes

**Files:**
- Create: `agentic-sre-team/ui/src/components/{HypoCard,EvidenceItem}.tsx`
- Create: `agentic-sre-team/ui/src/components/HypoCard.test.tsx`
- Modify: `agentic-sre-team/ui/src/screens/CaseDetailScreen.tsx` (fill panes, cross-linking, refetch on stream events)

**Interfaces:**
- Consumes: `CaseDetail.hypotheses/evidence`; stream events trigger `invalidateQueries(["case", id])` on `node_end`/`gate_waiting`.
- Produces: board sorted by confidence (note 7), each card: `H# · STATUS` pill, statement, confidence bar, `evidence: N for · M against · E2 E4` chips that highlight the evidence pane item on click (note 8); refuted cards dimmed at 55% opacity with the refuting note visible (note 9). Evidence items: `E#` pill, toolset + timestamp, excerpt, query line, `open in Grafana ->` when `source_url` (notes 10-11); a `selectedEid` highlight synchronizes chips and pane.

- [ ] **Step 1: Failing test**

`src/components/HypoCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { HypoCard } from "./HypoCard";

const H = { hid: "H3", statement: "Host CPU saturation", status: "refuted" as const,
  confidence: 0.05, evidence_for: [], evidence_against: ["E2"] };

test("refuted hypothesis is dimmed and lists refuting evidence", () => {
  const onEid = vi.fn();
  render(<HypoCard h={H} onEid={onEid} />);
  expect(screen.getByText(/H3 · REFUTED/)).toBeInTheDocument();
  const card = screen.getByText(/Host CPU saturation/).closest("div[data-hypo]")!;
  expect(card).toHaveStyle({ opacity: "0.55" });
  screen.getByRole("button", { name: "E2" }).click();
  expect(onEid).toHaveBeenCalledWith("E2");
});
```

Run: `npm test` -> FAIL.

- [ ] **Step 2: Implement**

`src/components/HypoCard.tsx`:

```tsx
import type { Hypothesis } from "../api/types";

export function HypoCard({ h, onEid }: { h: Hypothesis; onEid: (eid: string) => void }) {
  const chips = [...h.evidence_for, ...h.evidence_against];
  return (
    <div data-hypo style={{ border: "1px solid var(--line)", padding: "10px 12px",
        marginBottom: 10, opacity: h.status === "refuted" ? 0.55 : 1 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span className="mono" style={{ border: "1px solid var(--line)", padding: "1px 8px",
          background: h.status === "supported" ? "var(--line-2)" : "transparent" }}>
          {h.hid} · {h.status.toUpperCase()}</span>
        <span className="mono dim num">confidence {h.confidence.toFixed(2)}</span>
      </div>
      <div className="dim" style={{ margin: "6px 0" }}>{h.statement}</div>
      <div style={{ height: 6, background: "var(--line-2)" }}>
        <div style={{ height: 6, width: `${h.confidence * 100}%`,
                      background: h.status === "refuted" ? "var(--ink-3)" : "var(--accent)" }} />
      </div>
      <div className="mono dim" style={{ marginTop: 6 }}>
        evidence: {h.evidence_for.length} for · {h.evidence_against.length} against{" "}
        {chips.map((eid) => (
          <button key={eid} onClick={() => onEid(eid)} className="mono"
            style={{ border: "1px solid var(--line)", background: "none",
                     color: "var(--ink-2)", marginLeft: 4, padding: "0 4px" }}>{eid}</button>
        ))}
      </div>
    </div>
  );
}
```

`src/components/EvidenceItem.tsx`:

```tsx
import type { Evidence } from "../api/types";

export function EvidenceItem({ e, selected }: { e: Evidence; selected: boolean }) {
  return (
    <div id={`ev-${e.eid}`} style={{ borderBottom: "1px solid var(--line-2)", padding: "8px 0",
        background: selected ? "var(--accent-soft)" : "transparent" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <span className="mono" style={{ border: "1px solid var(--line)", padding: "0 6px",
          background: "var(--line-2)" }}>{e.eid}</span>
        <span className="mono dim">{e.toolset} · {new Date(e.observed_at).toLocaleTimeString()}</span>
      </div>
      <div className="dim" style={{ fontSize: 13, margin: "4px 0" }}>{e.excerpt}</div>
      <div className="mono dim">query: {e.invocation.slice(0, 120)}{" "}
        {e.source_url && <a href={e.source_url} target="_blank" rel="noreferrer"
          style={{ color: "var(--accent)" }}>open in Grafana -&gt;</a>}</div>
    </div>
  );
}
```

In `CaseDetailScreen`: hold `const [selectedEid, setSelectedEid] = useState<string | null>(null)`; hypotheses derive `evidence_for/against` from `hypothesis_links` on evidence when the API's hypothesis rows lack them (compute a memoized map eid->links); render board pane `data.hypotheses.sort((a, b) => b.confidence - a.confidence).map(h => <HypoCard ... onEid={(eid) => setSelectedEid(eid)} />)` and evidence pane `data.evidence.map(e => <EvidenceItem e={e} selected={e.eid === selectedEid} />)`; scroll the selected item into view (`document.getElementById("ev-" + eid)?.scrollIntoView()`); add a `useEffect` over `events` that calls `qc.invalidateQueries({queryKey: ["case", id]})` whenever the latest event is `node_end` or `gate_waiting`.

- [ ] **Step 3: Run tests, verify pass, commit**

Run: `npm test`

```bash
git add ui
git commit -m "feat(sre-team): hypothesis board and evidence receipts with cross-linking"
```

### Task 31: Artifact review screen (both gates)

**Files:**
- Create: `agentic-sre-team/ui/src/screens/ArtifactScreen.tsx`
- Create: `agentic-sre-team/ui/src/components/CitationChip.tsx`
- Create: `agentic-sre-team/ui/src/screens/ArtifactScreen.test.tsx`
- Modify: `agentic-sre-team/ui/src/App.tsx`

**Interfaces:**
- Consumes: `CaseDetail`, `POST /api/cases/{id}/decision`, `Governance.scm_draft_mr`.
- Produces: `/cases/:id/artifact/:kind` per wireframe screen 3. Header: display id, `RCA v2 · <title>`, verification badge `citations verified N/N` (click lists failures - note 1), failure-class chip for pipeline cases (variant note a), provenance strip `drafted by frontier tier · <model_id> · $<cost>` (note 2). Left pane renders **from `artifact.structured`** (no markdown lib): RCA = mitigation block first (note 3), causal chain as arrowed boxes with citation chips per hop (note 4), blast radius + timeline, dashed "Alternatives considered and rejected" (note 5), monitoring gaps; runbook = pre-checks, numbered steps with command blocks, post-checks, rollback, risk notes, patch files as diff-styled blocks (variant note b). Every `[E#]`/`eids` renders a `CitationChip`; clicking loads that evidence into the right-pane citation inspector with excerpt + Grafana link (note 6) plus the verifier line `Verifier: all claims cite evidence; 0 unsupported; confidence 0.81` (note 7). Approval bar: `Approve` (primary), `Approve with edits` (inline textarea prefilled with `body_md`, diff stored server-side - note 8), `Reject` (annotation prompt), outcome preview text per gate and per `scm_draft_mr` (notes 9, c), reviewer identity from `localStorage["reviewer"]` (prompt once; shown as `reviewer: <name> · logged` - note 10). Buttons disabled unless the case is actually waiting at this gate.

- [ ] **Step 1: Failing test** (outcome preview + decision post)

`src/screens/ArtifactScreen.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { ArtifactScreen } from "./ArtifactScreen";

const DETAIL = {
  case: { id: "c1", display_id: "CASE-0142", kind: "incident", status: "waiting_approval",
    phase: "gate_rca", title: "Error spike", severity: 2, effort: "medium", round: 1,
    failure_class: null, spend_usd: 0.87, halt_reason: null,
    created_at: "", updated_at: "", closed_at: null },
  signals: [], approvals: [],
  hypotheses: [], evidence: [{ eid: "E1", worker: "metrics", toolset: "prometheus",
    invocation: "q", excerpt: "18% at 14:02", source_url: null, observed_at: "",
    hypothesis_links: [] }],
  artifacts: [{ id: "a1", kind: "rca", version: 2, body_md: "## Immediate mitigation",
    body_edited_md: null, model_id: "claude-sonnet-4-5@20250929", cost_usd: 0.44,
    created_at: "",
    structured: { mitigation_md: "Revert PR #212", causal_chain: [
      { step: "PR #212", eids: ["E1"] }], blast_radius_md: "", timeline: [],
      alternatives: [], monitoring_gaps_md: "", claims: [
      { text: "spike at 14:02", eids: ["E1"] }], confidence: 0.81 },
    verification: { verified: true, checked: 1, failures: [] } }],
};

test("shows verification badge, outcome preview, posts approve decision", async () => {
  localStorage.setItem("reviewer", "alex.goh");
  const fetchMock = vi.fn(async (url: RequestInfo, init?: RequestInit) => {
    if (String(url).includes("/decision")) return new Response("{}");
    if (String(url).includes("/governance"))
      return new Response(JSON.stringify({ paused: false, scm_draft_mr: false,
        running_cases: 0, agents: [], suppression_24h: {}, cases_opened_24h: 0 }));
    return new Response(JSON.stringify(DETAIL));
  });
  vi.stubGlobal("fetch", fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={["/cases/c1/artifact/rca"]}>
      <Routes><Route path="/cases/:id/artifact/:kind" element={<ArtifactScreen />} /></Routes>
    </MemoryRouter></QueryClientProvider>);
  expect(await screen.findByText(/citations verified 1\/1/)).toBeInTheDocument();
  expect(screen.getByText(/publishes this RCA .* does not change any system/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));
  const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/decision"))!;
  expect(JSON.parse(String(call[1]!.body))).toMatchObject({
    gate: "rca", decision: "approve", decided_by: "alex.goh" });
});
```

Run: `npm test` -> FAIL.

- [ ] **Step 2: Implement**

`src/components/CitationChip.tsx`:

```tsx
export const CitationChip = ({ eid, onClick }: { eid: string; onClick: (e: string) => void }) => (
  <button onClick={() => onClick(eid)} className="mono"
    style={{ border: "1px solid var(--line)", background: "none", color: "var(--ink-3)",
             fontSize: 10, padding: "0 4px", verticalAlign: "super" }}>{eid}</button>
);
```

`src/screens/ArtifactScreen.tsx` - implement per the Interfaces block. Key excerpts (write the full file):

```tsx
const PREVIEWS: Record<string, (draftMr: boolean) => string> = {
  rca: () => "Approving publishes this RCA to the ops Telegram group and starts runbook "
             + "drafting. It does not change any system.",
  runbook: (draftMr) => draftMr
    ? "Approving publishes the runbook to Telegram and opens a DRAFT PR/MR with the patch "
      + "on a new branch. The draft is never merged automatically."
    : "Approving publishes the runbook to Telegram and closes the case. It does not "
      + "change any system.",
};

const decide = (decision: string) => {
  const reviewer = localStorage.getItem("reviewer")
    ?? window.prompt("Reviewer identity (logged with the approval):") ?? "unknown";
  localStorage.setItem("reviewer", reviewer);
  const annotation = decision === "reject"
    ? window.prompt("Why is this rejected? (goes back to the drafter)") ?? "" : "";
  return apiPost(`/api/cases/${id}/decision`, {
    gate: kind, decision, decided_by: reviewer, channel: "ui",
    edited_body_md: decision === "approve_with_edits" ? edited : undefined,
    annotation });
};
```

Structure: `useQuery` detail + governance; `artifact = detail.artifacts.filter(a => a.kind === kind).sort((a, b) => b.version - a.version)[0]`; `waitingHere = case.status === "waiting_approval" && case.phase === "gate_" + kind`; state `selectedEid`, `editing` (bool) + `edited` (string, init `artifact.body_md`); render blocks from `structured` per artifact kind with `CitationChip`s; right pane shows the selected evidence + verifier summary; approval bar with the three buttons (disabled when `!waitingHere`), outcome preview `PREVIEWS[kind](gov.scm_draft_mr)`, reviewer line. After a decision resolves, `navigate("/cases")`.

- [ ] **Step 3: Run tests, verify pass, commit**

Run: `npm test`

```bash
git add ui
git commit -m "feat(sre-team): artifact review with citation inspector and outcome-preview approvals"
```

### Task 32: Governance screen

**Files:**
- Create: `agentic-sre-team/ui/src/components/BudgetBar.tsx`
- Create: `agentic-sre-team/ui/src/screens/GovernanceScreen.tsx`
- Create: `agentic-sre-team/ui/src/screens/GovernanceScreen.test.tsx`
- Modify: `agentic-sre-team/ui/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/governance`, `GET /api/governance/audit`, `POST /api/governance/pause`.
- Produces: `/governance` per wireframe screen 4: agent cards (name, tier, budget bar `spend_today / usd_per_day` - note 1, `tools: N · manifest` expanding to the declared tool list - note 2, frontier cards visually distinguished with a stronger border - note 3), noise-control counter row (`signals in 24h / deduped / burst-suppressed / grouped / cases opened` + "every suppression logged" - note 4), readable audit stream newest-first (`ts · case · type · actor · summary` - note 5), `PAUSE ALL AGENTS` mirroring the top bar.

- [ ] **Step 1: Failing test** (budget bar math + audit rows render):

```tsx
test("agent card shows spend vs cap and audit rows render", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo) => {
    if (String(url).includes("/audit")) return new Response(JSON.stringify({ events: [
      { ts: "2026-07-11T14:22:04Z", case_id: "c1", actor: "alex.goh",
        event_type: "approval", payload: { gate: "rca", decision: "approve" } }] }));
    return new Response(JSON.stringify({ paused: false, scm_draft_mr: false,
      running_cases: 1, cases_opened_24h: 9,
      agents: [{ agent: "rca", tier: "frontier", tools: [], usd_per_day: 6,
                 spend_today: 4.2 }],
      suppression_24h: { dedup: 41, debounce: 22, grouped: 6 } }));
  }));
  // render GovernanceScreen inside providers, then:
  expect(await screen.findByText(/\$4\.20 \/ \$6\.00 today/)).toBeInTheDocument();
  expect(screen.getByText(/approval/)).toBeInTheDocument();
  expect(screen.getByText(/deduped: 41/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Implement** `BudgetBar` (filled ratio div, accent when > 80%) and the screen: cards grid (`gridTemplateColumns: repeat(auto-fit, minmax(180px, 1fr))`, frontier cards `borderColor: var(--ink)`), counters row from `suppression_24h`, audit list (`useQuery` on `/api/governance/audit?limit=100`, mono rows `14:22:04 · CASE · approval · rca approved by alex.goh`).

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add ui
git commit -m "feat(sre-team): governance screen with budget bars, suppression counters, audit stream"
```

### Task 33: Playwright smoke (queue -> detail -> approve)

**Files:**
- Create: `agentic-sre-team/ui/e2e/playwright.config.ts`
- Create: `agentic-sre-team/ui/e2e/smoke.spec.ts`
- Modify: `agentic-sre-team/Makefile` (e2e target)

**Interfaces:**
- Consumes: the running fake-profile stack (`make up-fake` with the smoke env vars from Task 22).
- Produces: one browser smoke proving the spec's UI test requirement (section 11).

- [ ] **Step 1: Setup**

```bash
cd agentic-sre-team/ui && npm i -D @playwright/test && npx playwright install chromium
```

`e2e/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  use: { baseURL: process.env.UI_BASE ?? "http://localhost:8088" },
  timeout: 120_000,
});
```

- [ ] **Step 2: Write the smoke**

`e2e/smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("alert -> queue -> detail -> approve RCA -> approve runbook -> closed", async ({ page, request }) => {
  const fixture = JSON.parse(JSON.stringify(
    require("../../gateway/tests/fixtures/grafana_webhook.json")));
  fixture.alerts[0].labels.alertname = `E2E-${Date.now()}`;   // fresh fingerprint
  const res = await request.post("http://localhost:8080/api/webhooks/grafana",
                                 { data: fixture });
  expect(res.ok()).toBeTruthy();

  await page.goto("/cases");
  const row = page.getByText("Error rate spike on admin-server /api/v1/users").first();
  await expect(row).toBeVisible();

  await page.getByRole("link", { name: /review rca/i }).first()
    .click({ timeout: 90_000 });
  await expect(page.getByText(/citations verified/i)).toBeVisible();
  page.on("dialog", (d) => d.accept("e2e"));
  await page.getByRole("button", { name: /^approve$/i }).click();

  await page.goto("/cases");
  await page.getByRole("link", { name: /review runbook/i }).first()
    .click({ timeout: 90_000 });
  await page.getByRole("button", { name: /^approve$/i }).click();

  await page.goto("/cases");
  await page.getByRole("button", { name: /closed/i }).click();
  await expect(page.getByText(/CASE-/).first()).toBeVisible();
});
```

Makefile:

```makefile
e2e:
	SRE_MODELS_PROFILE=fake SRE_HOLMES_URL=http://fake-holmes:5050 \
	SRE_FAKE_SCRIPT_DIR=/app/tests/fixtures/scripts/incident_error_storm \
	$(COMPOSE) --profile fake up -d --build
	cd ui && npx playwright test --config e2e/playwright.config.ts
```

- [ ] **Step 3: Run it**

Run: `make e2e`
Expected: 1 passed. This is the phase demo; also click through all four screens manually against the same stack and hold them to the wireframes (per-pixel scrutiny: alignment, mono/tabular numerals, dark and light themes).

- [ ] **Step 4: Commit and open the phase PR**

```bash
git add ui Makefile
git commit -m "test(sre-team): playwright smoke over queue, artifact review and approvals"
# PR: feat/sre-team-p5-ui -> main
```

---

## Phase 6 - Telegram companion

Branch: `feat/sre-team-p6-telegram`

### Task 34: TelegramChannel - long polling, inline approvals, report intake, LLM scorer

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/channels/telegram.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/scorer_llm.py`
- Create: `agentic-sre-team/gateway/tests/test_telegram.py`

**Interfaces:**
- Consumes: Telegram Bot API (docs-check: https://core.telegram.org/bots/api - `getUpdates` long polling, `sendMessage` with `reply_markup.inline_keyboard`, `answerCallbackQuery`, `callback_query` update shape), `apply_decision`, `IntakeService`, `IncidentScorer`.
- Produces:
  - `TelegramChannel(settings, on_decision, on_report, health)` implementing `Channel`:
    - `async send(text, *, buttons=None, chat_id=None) -> str | None` - `POST /bot{token}/sendMessage`; `chat_id` defaults to `settings.telegram_chat_id` (the group) for outbound notifications and gate buttons, and is passed explicitly to reply into a DM. `buttons` (`[{text, data}]`) map to one inline-keyboard row (`callback_data=data`). Returns message id. (The `Channel` protocol only requires `send(text, *, buttons=None)`; `chat_id` is an extra optional param used by the Telegram report path.)
    - `async run_polling()` - supervised loop: `GET /getUpdates?timeout=50&offset=<n>` (httpx timeout 60), advances offset past every processed update, exponential backoff to 60s on errors, `health["telegram"]` status.
    - Callback handling: `callback_query.data` of form `dec:<case_id>:<gate>:<approve|reject>`; **only user ids in `settings.telegram_allowed_user_ids` may decide** - others get an `answerCallbackQuery` "not authorized". Authorized: `await on_decision(case_id, gate, decision, decided_by=@username-or-id)` and answer with its returned text ("Recorded" / error detail). The identity of the tapper is what lands in the `Approval` row (wireframe Telegram note 3).
    - Report intake (**DM-only**): a plain-text message in a **private chat** (`message.chat.type == "private"`) -> `await on_report(text, reporter)`; the reply string is sent back **to that DM** (`send(reply, chat_id=<dm chat id>)`) - the ack with case id, "merged into CASE-X as supporting signal" for attach (Telegram note 5), or the canned low-value reply. Messages in the configured group are ignored for intake (the group is the notification + approval surface only); this is also why Bot API privacy mode is a non-issue - DMs are always delivered. Reports are not restricted to `telegram_allowed_user_ids` (a reporter need not be an approver, per the wireframe); the `LlmScorer` + `INCIDENT_THRESHOLD` is the low-value filter.
  - `LlmScorer(models: ModelFactory, audit)` in `intake/scorer_llm.py` implementing `IncidentScorer`: small-tier `call_llm_json` returning `{"score": float}` (system prompt: "Score 0..1 how likely this chat message reports a real production incident"); falls back to `HeuristicScorer` on any exception. Wired into the report path so low-value chatter costs one small-tier call at most, then a canned reply (spec section 3).
  - App wiring changes live in Task 35.

- [ ] **Step 1: Write the failing tests**

`gateway/tests/test_telegram.py`:

```python
import httpx
import respx

from sre_gateway.channels.telegram import TelegramChannel
from sre_gateway.settings import Settings

API = "https://api.telegram.org/bottok123"


def _channel(decisions, reports):
    async def on_decision(case_id, gate, decision, decided_by):
        decisions.append((case_id, gate, decision, decided_by))
        return "Recorded"

    async def on_report(text, reporter):
        reports.append((text, reporter))
        return "Opened CASE-0002"

    settings = Settings(database_url="x", telegram_bot_token="tok123",
                        telegram_chat_id="-10042", telegram_allowed_user_ids=[7])
    return TelegramChannel(settings, on_decision=on_decision, on_report=on_report,
                           health={})


@respx.mock
async def test_send_carries_inline_buttons():
    route = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 5}}))
    ch = _channel([], [])
    msg_id = await ch.send("RCA ready", buttons=[
        {"text": "Approve", "data": "dec:c1:rca:approve"}])
    assert msg_id == "5"
    body = route.calls[0].request.read().decode()
    assert "inline_keyboard" in body and "dec:c1:rca:approve" in body


@respx.mock
async def test_authorized_callback_applies_decision():
    respx.post(f"{API}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    decisions, ch = [], None
    ch = _channel(decisions, [])
    await ch.handle_update({"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": 7, "username": "alex"},
        "data": "dec:c1:rca:approve"}})
    assert decisions == [("c1", "rca", "approve", "@alex")]


@respx.mock
async def test_unauthorized_callback_is_refused():
    answered = respx.post(f"{API}/answerCallbackQuery").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    decisions = []
    ch = _channel(decisions, [])
    await ch.handle_update({"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"id": 999, "username": "mallory"},
        "data": "dec:c1:rca:approve"}})
    assert decisions == []
    assert b"authorized" in answered.calls[0].request.read().lower()


@respx.mock
async def test_dm_becomes_report_with_reply_to_dm():
    sent = respx.post(f"{API}/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 6}}))
    reports = []
    ch = _channel([], reports)
    await ch.handle_update({"update_id": 2, "message": {
        "chat": {"id": 4242, "type": "private"}, "from": {"id": 4242, "username": "minli"},
        "text": "admin console feels slow since noon"}})
    assert reports == [("admin console feels slow since noon", "@minli")]
    body = sent.calls[0].request.read()
    assert b"CASE-0002" in body
    # the reply goes back to the DM chat, not the configured group chat
    assert b'"chat_id": 4242' in body or b'"chat_id":4242' in body


@respx.mock
async def test_group_message_is_not_a_report():
    reports = []
    ch = _channel([], reports)
    await ch.handle_update({"update_id": 3, "message": {
        "chat": {"id": -10042, "type": "supergroup"}, "from": {"username": "minli"},
        "text": "admin console feels slow since noon"}})
    assert reports == []
```

- [ ] **Step 2: Run to verify failure, then implement**

Run: `uv run pytest tests/test_telegram.py -q` -> `ModuleNotFoundError`.

`src/sre_gateway/channels/telegram.py`:

```python
import asyncio
import logging
from typing import Awaitable, Callable

import httpx

from sre_gateway.settings import Settings

logger = logging.getLogger("sre.telegram")

OnDecision = Callable[[str, str, str, str], Awaitable[str]]
OnReport = Callable[[str, str], Awaitable[str]]


class TelegramChannel:
    def __init__(self, settings: Settings, *, on_decision: OnDecision,
                 on_report: OnReport, health: dict) -> None:
        self.settings = settings
        self.on_decision = on_decision
        self.on_report = on_report
        self.health = health
        self._base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def send(self, text: str, *, buttons: list[dict] | None = None,
                   chat_id: str | int | None = None) -> str | None:
        payload: dict = {"chat_id": chat_id or self.settings.telegram_chat_id,
                         "text": text[:4000]}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[
                {"text": b["text"], "callback_data": b["data"][:64]} for b in buttons]]}
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(f"{self._base}/sendMessage", json=payload)
            res.raise_for_status()
            return str(res.json().get("result", {}).get("message_id", ""))

    async def _answer(self, callback_id: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            await client.post(f"{self._base}/answerCallbackQuery",
                              json={"callback_query_id": callback_id, "text": text[:200]})

    async def handle_update(self, update: dict) -> None:
        if cq := update.get("callback_query"):
            user = cq.get("from", {})
            who = f"@{user.get('username')}" if user.get("username") else str(user.get("id"))
            data = cq.get("data", "")
            if user.get("id") not in self.settings.telegram_allowed_user_ids:
                await self._answer(cq["id"], "Not authorized to decide gates")
                return
            if data.startswith("dec:"):
                _, case_id, gate, decision = data.split(":", 3)
                try:
                    result = await self.on_decision(case_id, gate, decision, who)
                except Exception as err:
                    result = f"Failed: {err}"[:180]
                await self._answer(cq["id"], result)
            return
        message = update.get("message") or {}
        text = message.get("text", "")
        chat = message.get("chat", {})
        # Report intake is DM-only: a private chat with the bot. Group messages
        # (the notification + approval surface) are ignored for intake, which also
        # means Bot API privacy mode never blocks us - DMs are always delivered.
        if text and chat.get("type") == "private":
            frm = message.get("from", {})
            reporter = f"@{frm['username']}" if frm.get("username") else str(frm.get("id"))
            reply = await self.on_report(text, reporter)
            if reply:
                await self.send(reply, chat_id=chat.get("id"))

    async def run_polling(self) -> None:
        offset: int | None = None
        backoff = 1
        while True:
            try:
                params: dict = {"timeout": 50}
                if offset is not None:
                    params["offset"] = offset
                async with httpx.AsyncClient(timeout=60) as client:
                    res = await client.get(f"{self._base}/getUpdates", params=params)
                    res.raise_for_status()
                for update in res.json().get("result", []):
                    offset = update["update_id"] + 1
                    await self.handle_update(update)
                self.health["telegram"] = "ok"
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.health["telegram"] = f"error: {err}"[:120]
                logger.warning("telegram polling error: %s", err)
                await asyncio.sleep(min(backoff := backoff * 2, 60))
```

`src/sre_gateway/intake/scorer_llm.py`:

```python
import logging

from pydantic import BaseModel, Field

from sre_gateway.audit import AuditWriter
from sre_gateway.intake.scorer import HeuristicScorer
from sre_gateway.llm.factory import ModelFactory
from sre_gateway.llm.json_call import call_llm_json

logger = logging.getLogger("sre.scorer")


class ScoreOut(BaseModel):
    score: float = Field(ge=0, le=1)


class LlmScorer:
    def __init__(self, models: ModelFactory, audit: AuditWriter) -> None:
        self.models = models
        self.audit = audit
        self._fallback = HeuristicScorer()

    async def score(self, text: str) -> float:
        try:
            model_id, pricing = self.models.describe("small")
            out = await call_llm_json(
                self.models.chat("small", "intake-scorer"),
                system=("Score how likely this chat message reports a real production "
                        "incident or outage, 0..1. Greetings, questions and chatter "
                        "score below 0.2."),
                user=text[:1000], schema=ScoreOut, audit=self.audit,
                node="intake-scorer", case_id=None, model_id=model_id, pricing=pricing)
            return out.score
        except Exception as err:
            logger.warning("llm scorer failed, using heuristic: %s", err)
            return await self._fallback.score(text)
```

- [ ] **Step 3: Run tests, verify pass**

Run: `uv run pytest tests/test_telegram.py -q`
Expected: `5 passed`

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/sre-team-p6-telegram
git add gateway
git commit -m "feat(sre-team): telegram channel with inline gate approvals and llm report scoring"
```

### Task 35: Wire Telegram into the app; live end-to-end gates

**Files:**
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/app.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/reports.py`
- Create: `agentic-sre-team/gateway/tests/test_reports.py`

**Interfaces:**
- Consumes: everything from Task 34.
- Produces:
  - `handle_report(intake, scorer, text, reporter) -> str` in `intake/reports.py`: scores the text; below `INCIDENT_THRESHOLD` returns the canned reply ("Doesn't look like an incident; not opening a case. Reply with more detail if it is one.") without touching intake; otherwise builds `Signal(source=telegram, kind=incident, fingerprint=fingerprint_of("telegram", <normalized text>), summary=text[:200], reporter=reporter)`, ingests, and returns the ack / merge notice per the `IngestResult` (`open` -> "Opened CASE-x, investigating", `attach` -> "Merged into CASE-x as supporting signal (matching symptoms, same window)", `suppress` -> "Already tracked; suppressed as a duplicate").
  - Lifespan: when `telegram_bot_token` and `telegram_chat_id` are set, `deps.channel = TelegramChannel(settings, on_decision=..., on_report=...)` (replacing `LogChannel`) and a supervised `run_polling` task starts; `on_decision` wraps `apply_decision(sessionmaker, runner, case_id, gate, decision=..., decided_by=..., channel="telegram")` returning "Recorded - publishing next" or the 409 detail; `on_report` wraps `handle_report` with the `LlmScorer` (fake profile: heuristic - `LlmScorer` only when `models_profile != "fake"` to keep smoke deterministic). Health key `telegram`.

- [ ] **Step 1: Write the failing report tests**

`gateway/tests/test_reports.py`:

```python
from sre_gateway.audit import AuditWriter
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.reports import handle_report
from sre_gateway.intake.scorer import HeuristicScorer
from sre_gateway.intake.service import IntakeService


def _intake(db):
    audit = AuditWriter(db)
    return IntakeService(db, audit, NoiseControl(db, audit))


async def test_incident_like_report_opens_case(db):
    reply = await handle_report(_intake(db), HeuristicScorer(),
                                "admin console is down, 500 errors everywhere", "@minli")
    assert "Opened CASE-0001" in reply


async def test_chatter_gets_canned_reply_and_no_case(db):
    intake = _intake(db)
    reply = await handle_report(intake, HeuristicScorer(), "lunch anyone?", "@minli")
    assert "not opening a case" in reply.lower()
    from sqlalchemy import func, select

    from sre_gateway.db.models import Case

    async with db() as s:
        count = (await s.execute(select(func.count(Case.id)))).scalar_one()
    assert count == 0
```

- [ ] **Step 2: Run to verify failure, then implement**

`src/sre_gateway/intake/reports.py`:

```python
from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal, fingerprint_of
from sre_gateway.intake.scorer import INCIDENT_THRESHOLD, IncidentScorer
from sre_gateway.intake.service import IntakeService

CANNED = ("Doesn't look like an incident; not opening a case. "
          "Reply with more detail if it is one.")


async def handle_report(intake: IntakeService, scorer: IncidentScorer,
                        text: str, reporter: str) -> str:
    if await scorer.score(text) < INCIDENT_THRESHOLD:
        return CANNED
    normalized = " ".join(text.lower().split())[:120]
    result = await intake.ingest(Signal(
        source=SignalSource.telegram, reporter=reporter, kind=CaseKind.incident,
        fingerprint=fingerprint_of("telegram", normalized),
        summary=f"Report from {reporter}: {text[:180]}",
        payload={"text": text, "reporter": reporter}))
    if result.action == "open":
        return (f"Report received. Opened {result.display_id}, triaging now - "
                f"you will get updates here.")
    if result.action == "attach":
        return ("Your report was merged into an existing case as a supporting signal "
                "(matching symptoms, same window).")
    return "Already tracked; suppressed as a duplicate of an open case."
```

Wire the lifespan per the Interfaces block (channel selection, polling task start/cancel, `on_decision`/`on_report` closures).

- [ ] **Step 3: Run tests, then the live checklist (phase demo)**

Run: `uv run pytest -q`.

Live (real Telegram, fake pipeline for determinism): create the bot with @BotFather, add it to a test group, fill `SRE_TELEGRAM_*` in `.env` (allowed user ids = your id), then `make smoke` env but without auto-approval - instead run the stack, post the webhook manually and walk the checklist:

1. Ack message arrives with case id and severity (wireframe TG note 1).
2. Early-findings status update arrives at synthesize (note 2).
3. Gate-1 message shows Approve / Reject buttons; tap Approve from the allowed account; verify the Approval row records your @username and `channel=telegram` (note 3), and the decision echo posts (note 4).
4. DM the bot "admin console feels slow" twice (report intake is DM-only; the bot replies in the DM): the first opens a case, the second attaches, and the merge notice matches note 5. (A message posted in the group is NOT treated as a report.)
5. Tap a gate button from a non-allowed account: refused.
6. Gate-2 approve; both artifacts arrive; case closes.

- [ ] **Step 4: Commit and open the phase PR**

```bash
git add gateway
git commit -m "feat(sre-team): wire telegram channel, report intake and gate decisions end to end"
# PR: feat/sre-team-p6-telegram -> main
```

---

## Phase 7 - Pipeline-failure cases (GitHub + GitLab)

Branch: `feat/sre-team-p7-pipeline-failures`

### Task 36: ScmProvider contract and GitHub implementation

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/scm/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/scm/base.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/scm/github.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scm/github_workflow_run.json`
- Create: `agentic-sre-team/gateway/tests/test_scm_contract.py`

**Interfaces:**
- Consumes: GitHub REST (docs-check: https://docs.github.com/en/rest/actions - runs list, run jobs, contents, git refs, pulls; webhook `workflow_run` + `X-Hub-Signature-256`).
- Produces (in `scm/base.py`):
  - `JobRef` dataclass: `id: str, name: str, web_url: str`.
  - `PipelineFailure` dataclass: `provider, repo, pipeline_id, workflow_name, branch, sha, web_url, failed_jobs: list[JobRef], event_ts: datetime, payload: dict`.
  - `ScmProvider` protocol: `provider: str`; `verify_webhook(headers: Mapping[str, str], body: bytes) -> bool`; `parse_webhook(payload: dict) -> PipelineFailure | None`; `async poll_failures(repo: str, cursor: dict) -> tuple[list[PipelineFailure], dict]`; `async fetch_file(repo: str, path: str, ref: str) -> str`; `async create_branch(repo: str, branch: str, from_ref: str) -> None`; `async commit_files(repo: str, branch: str, files: list[tuple[str, str]], message: str) -> str`; `async open_draft_change(repo: str, branch: str, base: str, title: str, body: str) -> str` (returns the MR/PR URL; **draft only, never merge - no merge method exists on the protocol at all**).
  - `failure_to_signal(f: PipelineFailure) -> Signal`: `kind=pipeline_failure`, `source=f.provider`, `fingerprint=fingerprint_of(f.provider, f.repo, f.workflow_name, f.branch)` (repeat failures of the same workflow+branch attach to the open case), `summary=f"CI failing: {f.workflow_name} on {f.branch} ({f.repo})"`, `labels={"service": f.repo, "component": f.workflow_name, "provider": f.provider}`, `payload` carrying repo/sha/run url/failed job names **so the ci worker's prompt can name them**.
  - `GithubProvider(token: str, webhook_secret: str | None)` implementing the protocol against `https://api.github.com` (auth `Bearer`, `X-GitHub-Api-Version` header). Webhook: HMAC-SHA256 `sha256=<hex>` compare; parse only `action=completed` + `conclusion=failure`. Poll: `GET /repos/{repo}/actions/runs?status=failure&per_page=20`, keep runs with `run_started_at > cursor["since"]`, enrich each with failed jobs (`GET .../runs/{id}/jobs`), new cursor = newest `run_started_at`. `commit_files`: `PUT /repos/{repo}/contents/{path}` per file (base64 body, `sha` looked up first for updates). `open_draft_change`: `POST /repos/{repo}/pulls` with `draft: true`.
- The contract test suite is **shared**: it takes `(provider, fixtures)` parameters and asserts identical behavior; Task 37 re-runs it for GitLab (spec section 11's SCM contract tests).

- [ ] **Step 1: Webhook fixture**

`gateway/tests/fixtures/scm/github_workflow_run.json` (trimmed real shape):

```json
{
  "action": "completed",
  "workflow_run": {
    "id": 9912233,
    "name": "ci",
    "head_branch": "main",
    "head_sha": "abc1234def",
    "conclusion": "failure",
    "html_url": "https://github.com/alexgoh/spectre/actions/runs/9912233",
    "run_started_at": "2026-07-11T15:00:00Z",
    "path": ".github/workflows/ci.yml"
  },
  "repository": {"full_name": "alexgoh/spectre"}
}
```

- [ ] **Step 2: Write the shared contract tests (failing)**

`gateway/tests/test_scm_contract.py`:

```python
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
import respx

from sre_gateway.scm.base import failure_to_signal
from sre_gateway.scm.github import GithubProvider

FIXTURES = Path(__file__).parent / "fixtures/scm"


def _github() -> GithubProvider:
    return GithubProvider(token="tok", webhook_secret="whsec")


class TestGithubContract:
    provider = staticmethod(_github)
    webhook_fixture = "github_workflow_run.json"
    sig_header = "X-Hub-Signature-256"

    def _signed_headers(self, body: bytes) -> dict:
        sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        return {self.sig_header: f"sha256={sig}"}

    def test_webhook_verify_and_parse(self):
        body = (FIXTURES / self.webhook_fixture).read_bytes()
        p = self.provider()
        assert p.verify_webhook(self._signed_headers(body), body)
        assert not p.verify_webhook({self.sig_header: "sha256=bad"}, body)
        failure = p.parse_webhook(json.loads(body))
        assert failure and failure.repo == "alexgoh/spectre"
        assert failure.workflow_name == "ci" and failure.branch == "main"

    def test_success_events_parse_to_none(self):
        payload = json.loads((FIXTURES / self.webhook_fixture).read_text())
        payload["workflow_run"]["conclusion"] = "success"
        assert self.provider().parse_webhook(payload) is None

    def test_signal_envelope_is_stable(self):
        body = json.loads((FIXTURES / self.webhook_fixture).read_text())
        failure = self.provider().parse_webhook(body)
        signal = failure_to_signal(failure)
        assert signal.kind == "pipeline_failure"
        assert signal.labels == {"service": "alexgoh/spectre", "component": "ci",
                                 "provider": "github"}
        assert signal.fingerprint == failure_to_signal(failure).fingerprint  # deterministic


@respx.mock
async def test_github_poll_advances_cursor():
    runs = {"workflow_runs": [{"id": 1, "name": "ci", "head_branch": "main",
        "head_sha": "abc", "conclusion": "failure", "run_started_at": "2026-07-11T15:00:00Z",
        "html_url": "https://x", "path": ".github/workflows/ci.yml"}]}
    respx.get("https://api.github.com/repos/alexgoh/spectre/actions/runs").mock(
        return_value=httpx.Response(200, json=runs))
    respx.get("https://api.github.com/repos/alexgoh/spectre/actions/runs/1/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [
            {"id": 11, "name": "test", "conclusion": "failure", "html_url": "https://j"}]}))
    p = _github()
    failures, cursor = await p.poll_failures("alexgoh/spectre", {})
    assert failures[0].failed_jobs[0].name == "test"
    assert cursor["since"] == "2026-07-11T15:00:00Z"
    failures2, _ = await p.poll_failures("alexgoh/spectre", cursor)
    assert failures2 == []


@respx.mock
async def test_github_draft_pr_flow_never_merges():
    respx.get("https://api.github.com/repos/o/r/git/ref/heads/main").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "base"}}))
    branch = respx.post("https://api.github.com/repos/o/r/git/refs").mock(
        return_value=httpx.Response(201, json={}))
    respx.get("https://api.github.com/repos/o/r/contents/.github/workflows/ci.yml").mock(
        return_value=httpx.Response(200, json={"sha": "filesha"}))
    put = respx.put("https://api.github.com/repos/o/r/contents/.github/workflows/ci.yml").mock(
        return_value=httpx.Response(200, json={"commit": {"sha": "c1"}}))
    pr = respx.post("https://api.github.com/repos/o/r/pulls").mock(
        return_value=httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7"}))
    p = _github()
    await p.create_branch("o/r", "fix/case-0139", "main")
    await p.commit_files("o/r", "fix/case-0139",
                         [(".github/workflows/ci.yml", "fixed: yes\n")], "fix: pin dep")
    url = await p.open_draft_change("o/r", "fix/case-0139", "main", "Draft fix", "body")
    assert url.endswith("/pull/7")
    assert branch.called and put.called
    assert json.loads(pr.calls[0].request.read())["draft"] is True
```

- [ ] **Step 3: Run to verify failure, then implement**

`src/sre_gateway/scm/base.py`:

```python
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Mapping, Protocol

from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal, fingerprint_of


@dataclass
class JobRef:
    id: str
    name: str
    web_url: str = ""


@dataclass
class PipelineFailure:
    provider: str
    repo: str
    pipeline_id: str
    workflow_name: str
    branch: str
    sha: str
    web_url: str
    failed_jobs: list[JobRef] = field(default_factory=list)
    event_ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: dict = field(default_factory=dict)


class ScmProvider(Protocol):
    provider: str

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool: ...
    def parse_webhook(self, payload: dict) -> PipelineFailure | None: ...
    async def poll_failures(self, repo: str, cursor: dict) -> tuple[list[PipelineFailure], dict]: ...
    async def fetch_file(self, repo: str, path: str, ref: str) -> str: ...
    async def create_branch(self, repo: str, branch: str, from_ref: str) -> None: ...
    async def commit_files(self, repo: str, branch: str, files: list[tuple[str, str]],
                           message: str) -> str: ...
    async def open_draft_change(self, repo: str, branch: str, base: str,
                                title: str, body: str) -> str: ...


def hmac_sha256_ok(secret: str, body: bytes, header_value: str | None,
                   prefix: str = "") -> bool:
    if not header_value:
        return False
    expected = prefix + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)


def failure_to_signal(f: PipelineFailure) -> Signal:
    return Signal(
        source=SignalSource(f.provider), reporter=f"{f.provider}-ci",
        kind=CaseKind.pipeline_failure,
        fingerprint=fingerprint_of(f.provider, f.repo, f.workflow_name, f.branch),
        summary=f"CI failing: {f.workflow_name} on {f.branch} ({f.repo})",
        labels={"service": f.repo, "component": f.workflow_name, "provider": f.provider},
        payload={"repo": f.repo, "provider": f.provider, "pipeline_id": f.pipeline_id,
                 "workflow_name": f.workflow_name, "branch": f.branch, "sha": f.sha,
                 "web_url": f.web_url,
                 "failed_jobs": [{"id": j.id, "name": j.name, "web_url": j.web_url}
                                 for j in f.failed_jobs]},
        received_at=f.event_ts)
```

`src/sre_gateway/scm/github.py`:

```python
import base64
from datetime import datetime
from typing import Mapping

import httpx

from sre_gateway.scm.base import JobRef, PipelineFailure, hmac_sha256_ok

API = "https://api.github.com"


class GithubProvider:
    provider = "github"

    def __init__(self, token: str, webhook_secret: str | None = None) -> None:
        self.token = token
        self.webhook_secret = webhook_secret

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=API, timeout=30, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool:
        return hmac_sha256_ok(self.webhook_secret or "", body,
                              headers.get("X-Hub-Signature-256"), prefix="sha256=")

    def parse_webhook(self, payload: dict) -> PipelineFailure | None:
        run = payload.get("workflow_run") or {}
        if payload.get("action") != "completed" or run.get("conclusion") != "failure":
            return None
        return PipelineFailure(
            provider=self.provider, repo=payload["repository"]["full_name"],
            pipeline_id=str(run["id"]), workflow_name=run.get("name", "workflow"),
            branch=run.get("head_branch", ""), sha=run.get("head_sha", ""),
            web_url=run.get("html_url", ""),
            event_ts=datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00")),
            payload={"workflow_path": run.get("path", "")})

    async def poll_failures(self, repo: str, cursor: dict) -> tuple[list[PipelineFailure], dict]:
        since = cursor.get("since", "")
        async with self._client() as client:
            res = await client.get(f"/repos/{repo}/actions/runs",
                                   params={"status": "failure", "per_page": 20})
            res.raise_for_status()
            failures: list[PipelineFailure] = []
            newest = since
            for run in res.json().get("workflow_runs", []):
                started = run.get("run_started_at", "")
                if since and started <= since:
                    continue
                newest = max(newest, started)
                jobs_res = await client.get(f"/repos/{repo}/actions/runs/{run['id']}/jobs")
                jobs = [JobRef(str(j["id"]), j["name"], j.get("html_url", ""))
                        for j in jobs_res.json().get("jobs", [])
                        if j.get("conclusion") == "failure"]
                failures.append(PipelineFailure(
                    provider=self.provider, repo=repo, pipeline_id=str(run["id"]),
                    workflow_name=run.get("name", "workflow"),
                    branch=run.get("head_branch", ""), sha=run.get("head_sha", ""),
                    web_url=run.get("html_url", ""), failed_jobs=jobs,
                    event_ts=datetime.fromisoformat(started.replace("Z", "+00:00")),
                    payload={"workflow_path": run.get("path", "")}))
        return failures, ({"since": newest} if newest else cursor)

    async def fetch_file(self, repo: str, path: str, ref: str) -> str:
        async with self._client() as client:
            res = await client.get(f"/repos/{repo}/contents/{path}", params={"ref": ref},
                                   headers={"Accept": "application/vnd.github.raw+json"})
            res.raise_for_status()
            return res.text

    async def create_branch(self, repo: str, branch: str, from_ref: str) -> None:
        async with self._client() as client:
            base = await client.get(f"/repos/{repo}/git/ref/heads/{from_ref}")
            base.raise_for_status()
            res = await client.post(f"/repos/{repo}/git/refs", json={
                "ref": f"refs/heads/{branch}", "sha": base.json()["object"]["sha"]})
            res.raise_for_status()

    async def commit_files(self, repo: str, branch: str, files: list[tuple[str, str]],
                           message: str) -> str:
        last = ""
        async with self._client() as client:
            for path, content in files:
                body: dict = {"message": message, "branch": branch,
                              "content": base64.b64encode(content.encode()).decode()}
                existing = await client.get(f"/repos/{repo}/contents/{path}",
                                            params={"ref": branch})
                if existing.status_code == 200:
                    body["sha"] = existing.json()["sha"]
                res = await client.put(f"/repos/{repo}/contents/{path}", json=body)
                res.raise_for_status()
                last = res.json().get("commit", {}).get("sha", "")
        return last

    async def open_draft_change(self, repo: str, branch: str, base: str,
                                title: str, body: str) -> str:
        async with self._client() as client:
            res = await client.post(f"/repos/{repo}/pulls", json={
                "title": title, "head": branch, "base": base, "body": body, "draft": True})
            res.raise_for_status()
            return res.json()["html_url"]
```

- [ ] **Step 4: Run tests, verify pass, commit**

Run: `uv run pytest tests/test_scm_contract.py -q` -> all pass.

```bash
git checkout -b feat/sre-team-p7-pipeline-failures
git add gateway
git commit -m "feat(sre-team): scm provider contract and github implementation"
```

### Task 37: GitLab provider passing the same contract

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/scm/gitlab.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scm/gitlab_pipeline.json`
- Modify: `agentic-sre-team/gateway/tests/test_scm_contract.py` (add the GitLab class + poll/draft tests)

**Interfaces:**
- Consumes: GitLab REST v4 (docs-check: pipelines list, pipeline jobs, repository files raw, branches, commits-with-actions, merge requests; webhook `Pipeline Hook` + `X-Gitlab-Token` static-secret compare).
- Produces: `GitlabProvider(base_url, token, webhook_secret)` implementing `ScmProvider`. Differences captured inside the provider, invisible above the seam: repo slug is URL-encoded (`urllib.parse.quote(repo, safe="")`); webhook auth is constant-time equality on `X-Gitlab-Token` (not HMAC); parse `object_kind == "pipeline"` + `object_attributes.status == "failed"` with `builds[]` failures as jobs; poll `GET /api/v4/projects/{id}/pipelines?status=failed&order_by=id&sort=desc` with `cursor={"last_id": int}` + jobs via `.../pipelines/{id}/jobs?scope[]=failed`; `commit_files` uses one `POST .../repository/commits` with `actions` (`update` when `fetch_file` finds the file, else `create`); `open_draft_change` posts a merge request titled `Draft: <title>` and returns `web_url`.

- [ ] **Step 1: Fixture**

`gateway/tests/fixtures/scm/gitlab_pipeline.json`:

```json
{
  "object_kind": "pipeline",
  "object_attributes": {"id": 5511, "ref": "main", "sha": "def5678",
    "status": "failed", "created_at": "2026-07-11T15:10:00Z",
    "url": "https://gitlab.com/alexgoh/spectre-mirror/-/pipelines/5511"},
  "project": {"path_with_namespace": "alexgoh/spectre-mirror"},
  "builds": [
    {"id": 771, "name": "test", "status": "failed"},
    {"id": 772, "name": "lint", "status": "success"}
  ]
}
```

- [ ] **Step 2: Extend the contract suite (failing)**

Add to `test_scm_contract.py` a `TestGitlabContract(TestGithubContract)` subclass overriding: `provider = staticmethod(lambda: GitlabProvider("https://gitlab.com", token="tok", webhook_secret="whsec"))`, `webhook_fixture = "gitlab_pipeline.json"`, `sig_header = "X-Gitlab-Token"`, `_signed_headers = lambda self, body: {"X-Gitlab-Token": "whsec"}`, and adjusting the parse assertions (`repo == "alexgoh/spectre-mirror"`, `workflow_name == "pipeline"`, one failed job named `test`; the signal-envelope test stays inherited and must pass unchanged - that is the contract). Also add `test_gitlab_poll_advances_cursor` and `test_gitlab_draft_mr_flow` mirroring the GitHub ones against `https://gitlab.com/api/v4/projects/alexgoh%2Fspectre-mirror/...` routes, asserting the MR title starts with `Draft:`.

- [ ] **Step 3: Implement**

`src/sre_gateway/scm/gitlab.py`:

```python
import hmac
from datetime import datetime
from typing import Mapping
from urllib.parse import quote

import httpx

from sre_gateway.scm.base import JobRef, PipelineFailure


class GitlabProvider:
    provider = "gitlab"

    def __init__(self, base_url: str, token: str, webhook_secret: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.webhook_secret = webhook_secret

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=f"{self.base_url}/api/v4", timeout=30,
                                 headers={"PRIVATE-TOKEN": self.token})

    @staticmethod
    def _pid(repo: str) -> str:
        return quote(repo, safe="")

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> bool:
        supplied = headers.get("X-Gitlab-Token", "")
        return bool(self.webhook_secret) and hmac.compare_digest(
            self.webhook_secret, supplied)

    def parse_webhook(self, payload: dict) -> PipelineFailure | None:
        attrs = payload.get("object_attributes") or {}
        if payload.get("object_kind") != "pipeline" or attrs.get("status") != "failed":
            return None
        jobs = [JobRef(str(b["id"]), b["name"])
                for b in payload.get("builds", []) if b.get("status") == "failed"]
        return PipelineFailure(
            provider=self.provider,
            repo=payload["project"]["path_with_namespace"],
            pipeline_id=str(attrs["id"]), workflow_name="pipeline",
            branch=attrs.get("ref", ""), sha=attrs.get("sha", ""),
            web_url=attrs.get("url", ""), failed_jobs=jobs,
            event_ts=datetime.fromisoformat(
                attrs["created_at"].replace("Z", "+00:00")))

    async def poll_failures(self, repo: str, cursor: dict) -> tuple[list[PipelineFailure], dict]:
        last_id = int(cursor.get("last_id", 0))
        async with self._client() as client:
            res = await client.get(f"/projects/{self._pid(repo)}/pipelines",
                                   params={"status": "failed", "order_by": "id",
                                           "sort": "desc", "per_page": 20})
            res.raise_for_status()
            failures: list[PipelineFailure] = []
            newest = last_id
            for p in res.json():
                if p["id"] <= last_id:
                    continue
                newest = max(newest, p["id"])
                jobs_res = await client.get(
                    f"/projects/{self._pid(repo)}/pipelines/{p['id']}/jobs",
                    params={"scope[]": "failed"})
                jobs = [JobRef(str(j["id"]), j["name"], j.get("web_url", ""))
                        for j in jobs_res.json()]
                failures.append(PipelineFailure(
                    provider=self.provider, repo=repo, pipeline_id=str(p["id"]),
                    workflow_name="pipeline", branch=p.get("ref", ""),
                    sha=p.get("sha", ""), web_url=p.get("web_url", ""),
                    failed_jobs=jobs,
                    event_ts=datetime.fromisoformat(
                        p["created_at"].replace("Z", "+00:00"))))
        return failures, {"last_id": newest}

    async def fetch_file(self, repo: str, path: str, ref: str) -> str:
        async with self._client() as client:
            res = await client.get(
                f"/projects/{self._pid(repo)}/repository/files/{quote(path, safe='')}/raw",
                params={"ref": ref})
            res.raise_for_status()
            return res.text

    async def create_branch(self, repo: str, branch: str, from_ref: str) -> None:
        async with self._client() as client:
            res = await client.post(f"/projects/{self._pid(repo)}/repository/branches",
                                    params={"branch": branch, "ref": from_ref})
            res.raise_for_status()

    async def commit_files(self, repo: str, branch: str, files: list[tuple[str, str]],
                           message: str) -> str:
        actions = []
        for path, content in files:
            try:
                await self.fetch_file(repo, path, branch)
                action = "update"
            except httpx.HTTPStatusError:
                action = "create"
            actions.append({"action": action, "file_path": path, "content": content})
        async with self._client() as client:
            res = await client.post(f"/projects/{self._pid(repo)}/repository/commits",
                                    json={"branch": branch, "commit_message": message,
                                          "actions": actions})
            res.raise_for_status()
            return res.json().get("id", "")

    async def open_draft_change(self, repo: str, branch: str, base: str,
                                title: str, body: str) -> str:
        async with self._client() as client:
            res = await client.post(f"/projects/{self._pid(repo)}/merge_requests",
                                    json={"source_branch": branch, "target_branch": base,
                                          "title": f"Draft: {title}", "description": body})
            res.raise_for_status()
            return res.json()["web_url"]
```

- [ ] **Step 4: Run the whole contract suite, verify both providers pass, commit**

Run: `uv run pytest tests/test_scm_contract.py -q`

```bash
git add gateway
git commit -m "feat(sre-team): gitlab provider satisfying the shared scm contract"
```

### Task 38: SCM webhooks, repo registry, failure poller

**Files:**
- Create: `agentic-sre-team/config/repos.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/scm_intake.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/intake/poller_scm.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/webhooks.py` (github + gitlab endpoints)
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/app.py` (providers, repo seeding, poller task)
- Create: `agentic-sre-team/gateway/tests/test_scm_intake.py`

**Interfaces:**
- Consumes: providers (Tasks 36-37), `IntakeService`, `Repo` model.
- Produces:
  - `config/repos.yaml`:

    ```yaml
    repos:
      - provider: github
        slug: alexgoh/spectre        # adjust to the real Spectre remote at execution time
        default_branch: main
        watch: true
      - provider: gitlab
        slug: alexgoh/spectre-mirror # minimal mirror repo on gitlab.com (spec section 9)
        default_branch: main
        watch: true
    ```

  - `sync_repos(sessionmaker, path)` - upserts `Repo` rows from the file at startup.
  - `POST /api/webhooks/github` and `POST /api/webhooks/gitlab`: 401 unless `verify_webhook` passes; parse; non-failure events -> `{"results": []}`; failures -> `intake.ingest(failure_to_signal(f))`.
  - `ScmPoller(providers: dict[str, ScmProvider], sessionmaker, intake, health)` - every `scm_poll_interval_s` iterates watched repos, `poll_failures(slug, row.poll_cursor)`, ingests, persists the advanced cursor + `last_poll_at`. Supervised like the Grafana poller. Enabled by `scm_poll_enabled`.
  - Lifespan: build `providers = {"github": GithubProvider(...), "gitlab": GitlabProvider(...)}` from settings (only those with tokens), store on `app.state.scm`, seed repos, start the poller when enabled; `GraphDeps.scm` gets the same dict (used by Tasks 40-41).

- [ ] **Step 1: Failing tests** - `tests/test_scm_intake.py`: (a) posting the signed GitHub fixture to `/api/webhooks/github` opens a case with `kind=pipeline_failure` and `display_id CASE-000x`; (b) same payload again attaches (fingerprint dedup); (c) bad signature -> 401; (d) `ScmPoller.poll_once` with a stub provider returning one failure ingests it and saves `poll_cursor` on the `Repo` row. Write them in the style of Tasks 8/24 (app `client` fixture + respx/stub provider).

- [ ] **Step 2: Implement** per the Interfaces block. Webhook endpoint shape:

```python
@router.post("/webhooks/{provider_name}")
async def scm_webhook(request: Request, provider_name: str) -> dict:
    providers = request.app.state.scm
    if provider_name not in ("github", "gitlab") or provider_name not in providers:
        raise HTTPException(404)
    provider = providers[provider_name]
    body = await request.body()
    if not provider.verify_webhook(request.headers, body):
        raise HTTPException(401, detail="bad signature")
    failure = provider.parse_webhook(json.loads(body))
    if failure is None:
        return {"results": []}
    res = await request.app.state.intake.ingest(failure_to_signal(failure))
    return {"results": [{"action": res.action, "case_id": res.case_id,
                         "display_id": res.display_id}]}
```

(Keep the existing `/webhooks/grafana` route registered before this catch-all or use an explicit route list.) `ScmPoller.poll_once` iterates `select(Repo).where(Repo.watch)` rows, matches `providers[row.provider]`, ingests each failure, writes `row.poll_cursor, row.last_poll_at`.

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add config/repos.yaml gateway
git commit -m "feat(sre-team): scm webhooks, watched-repo registry and failure poller"
```

### Task 39: Pipeline-failure graph scenario (both providers)

**Files:**
- Create: `agentic-sre-team/gateway/tests/fixtures/holmes/pipeline_dep_typo/{ci,changes}.json`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/pipeline_dep_typo/{triage,synthesize,rca,verify,remediate,learnings}.json`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/synthesize.py` (persist `failure_class` to the case row when revised)
- Create: `agentic-sre-team/gateway/tests/test_graph_pipeline.py`

**Interfaces:**
- Consumes: the whole graph (Task 20) + SCM intake (Task 38).
- Produces: proof that case kinds route to different worker sets and that classification flows triage -> synthesize -> case row (spec sections 4, 11).

- [ ] **Step 1: Fixtures.** Scenario "dependency pin typo broke `ci.yml` test job":
  - `holmes/pipeline_dep_typo/ci.json`: two tool calls (failed job log excerpt showing `npm error notarget No matching version found for express@5.99.99` with exit code 1; run history showing the job green for 10 previous runs - not flaky), findings for `H1` (dependency) and against `H2` (flaky), `needs_infra: false`.
  - `holmes/pipeline_dep_typo/changes.json`: one tool call (the triggering diff showing `-"express": "^5.2.1"` / `+"express": "^5.99.99"` in `admin-server/package.json`), finding for `H1`.
  - `scripts/pipeline_dep_typo/triage.json`: `kind` pipeline case titled "CI failing: ci on main (alexgoh/spectre)", severity 3, effort medium, `failure_class: "dependency"`, hypotheses `["dependency pin typo in package.json", "flaky test job", "runner outage"]`.
  - `synthesize.json`: H1 supported 0.9, H2 refuted (run history), H3 refuted, `failure_class: "dependency"`, `need_more: false`.
  - `rca.json` / `verify.json`: claims citing E1/E2/E3, all supported.
  - `remediate.json`: **must include** `patch_files: [{"path": "admin-server/package.json", "content": "{\n  \"dependencies\": {\"express\": \"^5.2.1\"}\n}\n"}]` plus normal steps.
  - `learnings.json`: signature "ci test job fails after dependency bump", cause "nonexistent express version pinned".

- [ ] **Step 2: Failing test**

`gateway/tests/test_graph_pipeline.py`:

```python
import json
from pathlib import Path

from langgraph.types import Command
from sqlalchemy import select

from sre_gateway.db.models import Artifact, Case, EvidenceRow
from sre_gateway.graph import make_checkpointer
from sre_gateway.graph.build import build_graph
from sre_gateway.scm.base import failure_to_signal
from sre_gateway.scm.github import GithubProvider
from sre_gateway.scm.gitlab import GitlabProvider

FIXTURES = Path(__file__).parent / "fixtures"
APPROVE = {"decision": "approve", "decided_by": "alex.goh", "channel": "ui"}


async def _open_pipeline_case(db, intake, provider, fixture):
    payload = json.loads((FIXTURES / f"scm/{fixture}").read_text())
    failure = provider.parse_webhook(payload)
    return await intake.ingest(failure_to_signal(failure))


async def test_pipeline_case_routes_ci_plus_changes_and_classifies(
        pipeline_deps, db, pg_url, intake):
    provider = GithubProvider(token="t")
    opened = await _open_pipeline_case(db, intake, provider, "github_workflow_run.json")
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(pipeline_deps, saver)
        cfg = {"configurable": {"thread_id": opened.case_id}}
        result = await graph.ainvoke(
            {"case_id": opened.case_id, "kind": "pipeline_failure"}, cfg)
        assert "__interrupt__" in result
        async with db() as s:
            case = await s.get(Case, opened.case_id)
            workers = {e.worker for e in (await s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == opened.case_id))
                ).scalars().all()}
        assert workers == {"ci", "changes"}          # kind-routed worker set
        assert case.failure_class == "dependency"    # classification on the case row

        await graph.ainvoke(Command(resume=APPROVE), cfg)   # gate 1
        result = await graph.ainvoke(Command(resume=APPROVE), cfg)  # gate 2 -> publish
        async with db() as s:
            runbook = (await s.execute(select(Artifact).where(
                Artifact.kind == "runbook"))).scalars().one()
        patch = runbook.structured["patch_files"]
        assert patch and patch[0]["path"] == "admin-server/package.json"


async def test_gitlab_webhook_drives_the_same_scenario(pipeline_deps, db, pg_url, intake):
    provider = GitlabProvider("https://gitlab.com", token="t")
    opened = await _open_pipeline_case(db, intake, provider, "gitlab_pipeline.json")
    async with make_checkpointer(pg_url) as saver:
        graph = build_graph(pipeline_deps, saver)
        cfg = {"configurable": {"thread_id": opened.case_id}}
        result = await graph.ainvoke(
            {"case_id": opened.case_id, "kind": "pipeline_failure"}, cfg)
        assert "__interrupt__" in result
        async with db() as s:
            case = await s.get(Case, opened.case_id)
        assert case.kind == "pipeline_failure" and case.failure_class == "dependency"
```

Add a `pipeline_deps` conftest fixture: same as `deps` but `script_dir=.../scripts/pipeline_dep_typo` and `FAKE_HOLMES_DIR=.../holmes/pipeline_dep_typo`; plus an `intake` fixture (`IntakeService` without the runner hook).

- [ ] **Step 3: Make it pass.** The only production change: in `synthesize.py`, when `out.failure_class` is set, persist it (`UPDATE cases SET failure_class=...`) alongside the state update; triage already persists its initial classification.

Run: `uv run pytest tests/test_graph_pipeline.py -q` -> `2 passed`.

- [ ] **Step 4: Commit**

```bash
git add gateway
git commit -m "test(sre-team): pipeline-failure scenarios for github and gitlab with classification"
```

### Task 40: Patch diffs on runbook artifacts

**Files:**
- Modify: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/remediate.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/graph/deps.py` (`scm: dict | None = None`)
- Modify: `agentic-sre-team/ui/src/screens/ArtifactScreen.tsx` (render `patch_diffs` with +/- coloring)
- Create: `agentic-sre-team/gateway/tests/test_patch_diff.py`

**Interfaces:**
- Consumes: `ScmProvider.fetch_file`, remediate output.
- Produces: after the LLM call, for pipeline cases with `patch_files` and a configured provider, remediate deterministically computes `structured["patch_diffs"] = [{path, diff}]` via `difflib.unified_diff(base_content, new_content)` where base content comes from `deps.scm[provider].fetch_file(repo, path, sha)` (repo/provider/sha from the case's primary signal payload). Fetch failures degrade to no diff (never block drafting). This is a gateway-side deterministic action, not an LLM tool - the manifest stance is unchanged. The reviewer sees a true diff before gate 2 (wireframe pipeline-variant note b).

- [ ] **Step 1: Failing test** - `tests/test_patch_diff.py`: stub provider whose `fetch_file` returns the original `package.json`; run `make_remediate(pipeline_deps)` on a pipeline case seeded with a primary signal payload `{provider: "github", repo: "alexgoh/spectre", sha: "abc"}`; assert `structured["patch_diffs"][0]["diff"]` contains `-` old pin and `+` new pin lines; second test: `fetch_file` raising -> artifact persists with `patch_diffs == []` and no exception.

- [ ] **Step 2: Implement** in `remediate.py` after persisting-out is computed (before the artifact insert):

```python
        patch_diffs: list[dict] = []
        if out.patch_files and deps.scm and state.get("kind") == "pipeline_failure":
            async with deps.sessionmaker() as s:
                primary = (await s.execute(
                    select(SignalRow).where(SignalRow.case_id == case_id,
                                            SignalRow.is_primary))).scalars().first()
            meta = (primary.payload if primary else {}) or {}
            provider = deps.scm.get(meta.get("provider", ""))
            if provider:
                import difflib

                for pf in out.patch_files:
                    try:
                        base = await provider.fetch_file(meta["repo"], pf.path,
                                                         meta.get("sha", "main"))
                        diff = "\n".join(difflib.unified_diff(
                            base.splitlines(), pf.content.splitlines(),
                            fromfile=f"a/{pf.path}", tofile=f"b/{pf.path}", lineterm=""))
                        patch_diffs.append({"path": pf.path, "diff": diff})
                    except Exception:
                        continue
        structured = out.model_dump() | {"patch_diffs": patch_diffs}
```

UI: in the runbook rendering, when `structured.patch_diffs` is non-empty render each as a mono block, lines starting `+` in `var(--ok)`, `-` in `var(--accent)`.

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add gateway ui
git commit -m "feat(sre-team): true patch diffs on pipeline runbooks for gate-2 review"
```

### Task 41: Gated draft-MR/PR publish action

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/publish_scm.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/settings.py` (`github_publish_token`, `gitlab_publish_token`)
- Modify: `agentic-sre-team/gateway/src/sre_gateway/graph/nodes/publish.py` (call the action)
- Modify: `agentic-sre-team/gateway/src/sre_gateway/api/governance.py` (expose `scm_draft_mr`)
- Create: `agentic-sre-team/gateway/tests/test_publish_scm.py`

**Interfaces:**
- Consumes: `ScmProvider` write methods, `Settings.scm_draft_mr`.
- Produces: `async publish_draft_change(deps, case_id, state) -> str | None`:
  - Runs **only** when all hold: `settings.scm_draft_mr` is true, case kind is `pipeline_failure`, the approved runbook has `patch_files`, and a **publish-scoped credential** exists for the case's provider (`SRE_GITHUB_PUBLISH_TOKEN` / `SRE_GITLAB_PUBLISH_TOKEN` - a separate credential scoped to branch creation, per spec section 8; the intake tokens are never used to write).
  - Branch `fix/<display_id lowercased>` from the repo's default branch; commits the patch files (`fix(<display_id>): <case title>` message); opens a **draft** PR/MR whose body links the case and runbook; returns the URL. The publish node calls it after the channel sends and posts "Draft PR opened: <url> - never merged automatically" when a URL comes back; failures are audited and reported to the channel but never block case closure.
  - Audit event `publish` with `{draft_url, branch, repo}`. **This is a gateway publish action - it is not in `TOOL_REGISTRY` and no node can invoke it as a tool.**

- [ ] **Step 1: Failing tests** - `tests/test_publish_scm.py` with respx (GitHub route set from Task 36's draft-PR test): (a) flag off -> returns `None`, zero HTTP calls; (b) flag on + publish token + patch_files -> branch created from `main`, files committed, draft PR opened, URL returned, audit row written; (c) incident-kind case -> `None` even with the flag on; (d) provider API failure -> returns `None`, audit row `payload["error"]` set, no exception.

- [ ] **Step 2: Implement** `publish_scm.py` (constructs a provider from the publish token - not the intake provider instance), wire the call into `make_publish` right before closing the case, add the settings fields, and include `"scm_draft_mr": settings.scm_draft_mr` in the `/api/governance` payload (the UI outcome preview from Task 31 already consumes it).

- [ ] **Step 3: Run the full suite, verify pass**

Run: `uv run pytest -q && uv run ruff check .`

- [ ] **Step 4: Commit and open the phase PR**

```bash
git add gateway
git commit -m "feat(sre-team): gated draft-mr publish action with dedicated scoped credential"
# PR: feat/sre-team-p7-pipeline-failures -> main
```

---

## Phase 8 - Chat surface (Ask the team)

Branch: `feat/sre-team-p8-chat`

### Task 42: Chat service and threads API (ad-hoc mode, budget-capped)

**Files:**
- Create: `agentic-sre-team/gateway/src/sre_gateway/chat/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/chat/service.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/api/chat.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/settings.py` (`chat_message_cost_estimate_usd: float = 0.05`)
- Create: `agentic-sre-team/gateway/tests/fixtures/holmes/incident_error_storm/chat.json`
- Create: `agentic-sre-team/gateway/tests/test_chat.py`

**Interfaces:**
- Consumes: `HolmesClient`, `ChatThread/ChatMessage` (Task 3), `AuditWriter`.
- Produces:
  - `ChatService(sessionmaker, holmes, models, audit, settings, environment)`:
    - `async create_thread(title: str = "", context_case_id: str | None = None) -> dict`.
    - `async stream_message(thread_id: str, text: str) -> AsyncIterator[dict]` - yields `{"type": "budget_denied"}` / `{"type": "tool_start"|"tool_result", ...}` / `{"type": "answer", "text", "message_id"}`. Behavior: budget first - `spend_usd_today` resets when `budget_date != today (UTC)`; at or over `chat_thread_daily_usd_cap` yields `budget_denied` and stops (429 at the API layer). Otherwise persists the user `ChatMessage`, builds the ask (`Domain: chat` first line + environment preamble; case grounding added in Task 43), relays `holmes.chat(..., model=medium holmes model, on_event=queue)` streaming tool events, then persists the assistant message with `tool_ledger` = the tool calls, adds `chat_message_cost_estimate_usd` to the thread's daily spend (flat estimate; revisit if the Task 23 docs-check shows Holmes returns usage), audits `event_type="chat"`.
    - Chat runs on the same read-only Holmes toolsets and **cannot approve gates or publish** - no such code path exists here; decisions stay on `/cases/{id}/decision` (spec 6a guardrails).
  - API: `POST /api/chat/threads` `{title?, context_case_id?}`; `GET /api/chat/threads`; `GET /api/chat/threads/{id}` (thread + messages + spend); `POST /api/chat/threads/{id}/messages` `{text}` -> SSE (`EventSourceResponse` relaying `stream_message`, 429 on budget); `PATCH /api/chat/threads/{id}` `{context_case_id}` (attach case - Task 43 consumes it).
  - Fixture `chat.json`: two tool calls (prometheus keycloak p95, docker keycloak stats) + analysis text "Keycloak p95 is 4x baseline since 14:05... correlates with admin API calls [E1] [E2]".

- [ ] **Step 1: Write the failing tests**

`gateway/tests/test_chat.py`:

```python
from sre_gateway.chat.service import ChatService
from sre_gateway.db.models import ChatMessage, ChatThread


async def _collect(gen):
    return [e async for e in gen]


async def test_message_relays_tools_and_persists_ledger(chat_service, db):
    thread = await chat_service.create_thread(title="Why is Keycloak slow right now?")
    events = await _collect(chat_service.stream_message(
        thread["id"], "Why is Keycloak slow right now?"))
    types = [e["type"] for e in events]
    assert types.count("tool_result") == 2 and types[-1] == "answer"
    async with db() as s:
        msgs = (await s.execute(
            __import__("sqlalchemy").select(ChatMessage).order_by(ChatMessage.created_at)
        )).scalars().all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert len(msgs[1].tool_ledger) == 2


async def test_daily_budget_cap_denies(chat_service, db):
    thread = await chat_service.create_thread(title="t")
    async with db() as s:
        row = await s.get(ChatThread, thread["id"])
        row.budget_date = __import__("datetime").datetime.now(
            __import__("datetime").UTC).date().isoformat()
        row.spend_usd_today = 99.0
        await s.commit()
    events = await _collect(chat_service.stream_message(thread["id"], "hi"))
    assert len(events) == 1 and events[0]["type"] == "budget_denied"
```

Add a `chat_service` conftest fixture building `ChatService` with the fake-holmes ASGI client and fake models.

- [ ] **Step 2: Run to verify failure, then implement** `chat/service.py` and `api/chat.py` per the Interfaces block. Core of `stream_message`:

```python
    async def stream_message(self, thread_id: str, text: str):
        today = datetime.now(UTC).date().isoformat()
        async with self._sm() as s:
            thread = await s.get(ChatThread, thread_id)
            if thread.budget_date != today:
                thread.budget_date, thread.spend_usd_today = today, 0.0
            if thread.spend_usd_today >= self.settings.chat_thread_daily_usd_cap:
                await s.commit()
                yield {"type": "budget_denied",
                       "detail": f"thread budget "
                                 f"${self.settings.chat_thread_daily_usd_cap:.2f}/day spent"}
                return
            s.add(ChatMessage(thread_id=thread_id, role="user", content=text))
            await s.commit()
            context_case_id = thread.context_case_id

        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(e: dict) -> None:
            await queue.put(e)

        ask = await self._build_ask(text, context_case_id)
        task = asyncio.create_task(self.holmes.chat(
            ask, model=self.models.holmes_model("medium"), on_event=on_event))
        while not task.done() or not queue.empty():
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.2)
            except TimeoutError:
                continue
        answer = task.result()
        async with self._sm() as s:
            msg = ChatMessage(thread_id=thread_id, role="assistant", content=answer.text,
                              tool_ledger=[t.__dict__ for t in answer.tool_calls])
            s.add(msg)
            thread = await s.get(ChatThread, thread_id)
            thread.spend_usd_today += self.settings.chat_message_cost_estimate_usd
            await s.commit()
            message_id = msg.id
        await self.audit.log("chat", actor="chat", thread_id=thread_id,
                             tool_calls=len(answer.tool_calls))
        yield {"type": "answer", "text": answer.text, "message_id": message_id}
```

`_build_ask` (ad-hoc): `f"Domain: chat\nYou are the ops chat of an SRE team.\n{self.environment.prompt_block()}\nAnswer with evidence from your read-only toolsets; cite what you ran.\n\nQuestion: {text}"` (`ChatService` takes the `EnvironmentConfig` in its constructor - same locked-decision-15 rule as the workers).

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git checkout -b feat/sre-team-p8-chat
git add gateway
git commit -m "feat(sre-team): chat service with holmes relay, daily thread budget, audit"
```

### Task 43: Case-context grounding and attach-case

**Files:**
- Modify: `agentic-sre-team/gateway/src/sre_gateway/chat/service.py` (`_build_ask` case grounding)
- Modify: `agentic-sre-team/gateway/tests/test_chat.py`

**Interfaces:**
- Consumes: `CaseDetail` data (signals, hypotheses, evidence).
- Produces: when the thread has `context_case_id`, `_build_ask` prepends the case record - display id, title, severity, status, hypothesis board (hid/status/confidence/statement), evidence index (eid/toolset/excerpt first 200 chars) - "Robusta's chat-about-an-issue with the alert payload, generalized to our case model" (spec 6a). `PATCH /api/chat/threads/{id}` switches grounding mid-conversation (wireframe note 6). "Ask about this" UI entry points pass `context_case_id` at thread creation.

- [ ] **Step 1: Failing test** - create a case with one hypothesis + one evidence row, create a thread with `context_case_id`, monkeypatch-capture the `ask` sent to `HolmesClient.chat`, assert it contains the display id, `H1`, and `E1`. Second test: PATCH the thread to a different case id and assert the next ask reflects it.

- [ ] **Step 2: Implement** `_build_ask` case branch (query the three tables, format compactly, cap at ~4000 chars) and keep the PATCH endpoint from Task 42 wired to it.

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add gateway
git commit -m "feat(sre-team): case-context chat grounding with mid-thread attach"
```

### Task 44: Promote thread to case (workflow kickoff)

**Files:**
- Modify: `agentic-sre-team/gateway/src/sre_gateway/chat/service.py` + `api/chat.py`
- Modify: `agentic-sre-team/gateway/src/sre_gateway/graph/runner.py` (phase postbacks into linked threads)
- Create: `agentic-sre-team/gateway/tests/test_chat_promote.py`
- Create: `agentic-sre-team/gateway/tests/fixtures/scripts/incident_error_storm/promote.json`

**Interfaces:**
- Consumes: `IntakeService`, small tier, `ChatThread.promoted_case_id`.
- Produces:
  - `POST /api/chat/threads/{id}/promote` with `{"confirm": false}` -> **preview only** (spec 6a, wireframe note 7): small-tier `PromoteOut {title, severity, kind}` from the thread transcript, returned as `{preview: {title, severity, kind, context: "<thread title + last answer excerpt>"}}` - nothing created.
  - With `{"confirm": true, "title"?: ..., "severity"?: ...}` (operator overrides allowed): builds `Signal(source=chat, kind=<preview.kind>, fingerprint=fingerprint_of("chat", thread_id), summary=title, payload={thread_id, transcript_tail})`, ingests it (the standard case graph runs with all gates - chat is a first-class intake path, spec section 3 path 2a), sets `thread.promoted_case_id`, audits, returns `{case_id, display_id}`.
  - **Cross-linking postbacks**: in `CaseRunner._emit`, after persisting an event of type `gate_waiting`, `parked`, or `error`, and on `node_update` with `node == "publish"`, look up `ChatThread.promoted_case_id == case_id` and insert a system `ChatMessage` ("Case CASE-0144 reached gate: rca review", "artifacts published, case closed", ...). The thread stays a truthful record of the case (wireframe note 3).
  - `promote.json` script fixture: `{"title": "Keycloak latency degradation", "severity": 3, "kind": "incident"}`.

- [ ] **Step 1: Failing tests** - `test_chat_promote.py`: (a) preview returns the scripted title/severity and creates no case; (b) confirm creates a `source=chat` signal + case (assert `SignalRow.source == "chat"`, thread linked); (c) after the promoted case's runner emits `gate_waiting` (invoke `runner._emit` directly), a system chat message exists in the thread.

- [ ] **Step 2: Implement** per the Interfaces block (`PromoteOut` pydantic; the confirm path reuses `app.state.intake` so the runner hook fires).

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add gateway
git commit -m "feat(sre-team): promote chat threads to gated cases with phase postbacks"
```

### Task 45: Chat screen

**Files:**
- Create: `agentic-sre-team/ui/src/api/postSse.ts`
- Create: `agentic-sre-team/ui/src/screens/ChatScreen.tsx`
- Create: `agentic-sre-team/ui/src/screens/ChatScreen.test.tsx`
- Modify: `agentic-sre-team/ui/src/App.tsx`

**Interfaces:**
- Consumes: the chat API (Tasks 42-44).
- Produces: `/chat` per wireframe screen 5: threads pane (title, date, linked-case chip - note 3, `+ New thread`), message pane (user bubbles; assistant bubbles rendering the **same tool-ledger style** as case detail - collapsed `holmes:<toolset> · <description>` lines while streaming, note 4), context chip `context: none | CASE-x` (note 1) with `attach case` (prompt for case id -> PATCH, note 6), thread budget line `$0.14 / $1.00 today` (note 2), input box, and on every assistant answer the `Investigate properly` button -> promote preview rendered in the docked bar with the outcome-preview wording ("creates CASE-x (SEV-n proposed, kind: incident) with this thread attached... Nothing is investigated beyond read-only queries until triage runs", note 7) -> confirm -> navigate to the new case. Budget-denied events render as a visible bar. `postSse(path, body, onEvent)` parses the fetch `ReadableStream` SSE (POST endpoints cannot use `EventSource`).

- [ ] **Step 1: Failing test** - render with stubbed fetch: thread list loads; sending a message streams two `tool_result` events then an `answer` (stub `postSse` via injected transport or stub `fetch` with a `ReadableStream` body); "Investigate properly" click posts `{confirm: false}` and shows the preview text; confirm posts `{confirm: true}`.

- [ ] **Step 2: Implement** `postSse` (~25 lines: `fetch`, `body.getReader()`, split on `\n\n`, parse `event:`/`data:`) and the screen (two-pane grid, TanStack Query for threads/messages, local state for the streaming message, promote flow).

- [ ] **Step 3: Verify in the browser** against the fake stack (`make up-fake` env): ask a question, watch the tool ledger stream, promote it, land on the case. Run `npm test`.

- [ ] **Step 4: Commit and open the phase PR**

```bash
git add ui
git commit -m "feat(sre-team): chat screen with streaming tool ledger and promote-to-case"
# PR: feat/sre-team-p8-chat -> main
```

---

## Phase 9 - Chaos, provisioning, acceptance demos

Branch: `feat/sre-team-p9-chaos-acceptance` (plus one PR in `~/Code/spectre`)

### Task 46: Spectre chaos middleware (separate PR in ~/Code/spectre)

**Files (all in `~/Code/spectre`):**
- Create: `admin-server/src/middlewares/chaosMiddleware.ts`
- Create: `admin-server/test/middlewares/chaos.test.ts`
- Modify: `admin-server/src/index.ts` (env-gated mount)
- Modify: `docker-compose.yml` (`CHAOS_ENABLED` env line on admin-server)
- Modify: `admin-server/README.md` or `docs/` (one paragraph on chaos mode)

**Interfaces:**
- Consumes: Spectre's Express 5 admin-server (middlewares live in `src/middlewares/`, tests in `test/middlewares/`, Vitest).
- Produces: mounted **only when `CHAOS_ENABLED=true`** (default off; never in the production profile): `chaosMiddleware` (modes `error-storm` - inject 503 on a percentage of API responses, `latency` - delay, `cpu` - event-loop burn per request, `memory` - bounded heap growth) and `chaosControlRouter` (`GET/POST /internal/chaos`, no auth, mounted before auth middleware - reachable only from inside the container/compose network since admin-server sits behind Kong). Exports `getChaosState`, `resetChaos` for tests. This PR is the "origin commit" the changes worker should trace symptoms to (spec section 9) - write the commit message accordingly.

- [ ] **Step 1: Branch per Spectre's conventions**

```bash
cd ~/Code/spectre && cat CONTRIBUTING.md   # confirm base branch (gitflow: develop if present)
git checkout -b feat/admin-server-chaos-middleware <base>
```

- [ ] **Step 2: Write the failing tests**

`admin-server/test/middlewares/chaos.test.ts` (match the existing middleware-test style - mock req/res, no new deps):

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  chaosControlRouter, chaosMiddleware, getChaosState, resetChaos, setChaos,
} from '../../src/middlewares/chaosMiddleware';

const mockRes = () => {
  const res: any = { statusCode: 200 };
  res.status = vi.fn((code: number) => { res.statusCode = code; return res; });
  res.json = vi.fn(() => res);
  return res;
};

describe('chaosMiddleware', () => {
  beforeEach(() => resetChaos());

  it('passes through when off', () => {
    const next = vi.fn();
    chaosMiddleware({} as any, mockRes(), next);
    expect(next).toHaveBeenCalledOnce();
  });

  it('error-storm at rate 1 injects 503 and never calls next', () => {
    setChaos({ mode: 'error-storm', rate: 1 });
    const res = mockRes();
    const next = vi.fn();
    chaosMiddleware({} as any, res, next);
    expect(res.status).toHaveBeenCalledWith(503);
    expect(next).not.toHaveBeenCalled();
  });

  it('latency mode defers next', async () => {
    setChaos({ mode: 'latency', latencyMs: 10 });
    const next = vi.fn();
    chaosMiddleware({} as any, mockRes(), next);
    expect(next).not.toHaveBeenCalled();
    await new Promise((r) => setTimeout(r, 40));
    expect(next).toHaveBeenCalledOnce();
  });

  it('control route updates state', () => {
    const res = mockRes();
    const layer: any = chaosControlRouter().stack.find(
      (l: any) => l.route?.path === '/internal/chaos'
        && l.route.methods.post);
    layer.route.stack[0].handle(
      { body: { mode: 'error-storm', rate: 0.5 } } as any, res, vi.fn());
    expect(getChaosState()).toMatchObject({ mode: 'error-storm', rate: 0.5 });
  });
});
```

Run: `cd admin-server && npm test -- chaos` -> FAIL (module missing).

- [ ] **Step 3: Implement**

`admin-server/src/middlewares/chaosMiddleware.ts`:

```ts
import { NextFunction, Request, Response, Router } from 'express';

export type ChaosMode = 'off' | 'error-storm' | 'latency' | 'cpu' | 'memory';

export interface ChaosState {
  mode: ChaosMode;
  rate: number;      // error-storm: share of requests to fail (0..1)
  latencyMs: number; // latency: added delay per request
  cpuMs: number;     // cpu: busy-loop per request
  memoryMb: number;  // memory: heap grabbed per request, capped at 500MB total
}

const state: ChaosState = { mode: 'off', rate: 0.5, latencyMs: 800, cpuMs: 120, memoryMb: 20 };
const leaks: Buffer[] = [];

export const getChaosState = (): ChaosState => ({ ...state });
export const setChaos = (patch: Partial<ChaosState>): ChaosState => {
  Object.assign(state, patch);
  if (state.mode === 'off') leaks.length = 0;
  return getChaosState();
};
export const resetChaos = (): void => { setChaos({ mode: 'off' }); };

export function chaosMiddleware(req: Request, res: Response, next: NextFunction): void {
  switch (state.mode) {
    case 'error-storm':
      if (Math.random() < state.rate) {
        res.status(503).json({ error: 'chaos: injected failure' });
        return;
      }
      break;
    case 'latency': {
      const jitter = state.latencyMs * 0.5 * Math.random();
      setTimeout(next, state.latencyMs + jitter);
      return;
    }
    case 'cpu': {
      const end = Date.now() + state.cpuMs;
      while (Date.now() < end) { /* event-loop burn */ }
      break;
    }
    case 'memory':
      if (leaks.length * state.memoryMb < 500) {
        leaks.push(Buffer.alloc(state.memoryMb * 1024 * 1024, 1));
      }
      break;
  }
  next();
}

export function chaosControlRouter(): Router {
  const router = Router();
  router.get('/internal/chaos', (_req, res) => { res.json(getChaosState()); });
  router.post('/internal/chaos', (req, res) => {
    res.json(setChaos((req.body ?? {}) as Partial<ChaosState>));
  });
  return router;
}
```

In `src/index.ts`, after the JSON body parser and before auth/routes (read the file to place it precisely):

```ts
if (process.env.CHAOS_ENABLED === 'true') {
  app.use(chaosControlRouter());
  app.use(chaosMiddleware);
}
```

In Spectre's `docker-compose.yml` admin-server service environment: `CHAOS_ENABLED: ${CHAOS_ENABLED:-false}`.

- [ ] **Step 4: Run Spectre's checks and open the PR**

Run: `cd admin-server && npm test && npm run lint`
Expected: all green, including the four new tests.

```bash
git add admin-server docker-compose.yml
git commit -m "feat(admin-server): env-gated chaos injection middleware for resilience testing"
git push -u origin feat/admin-server-chaos-middleware
gh pr create --title "feat(admin-server): env-gated chaos injection middleware" \
  --body "Adds CHAOS_ENABLED-gated middleware (error-storm/latency/cpu/memory) with an internal-only control endpoint, for the agentic-sre-team acceptance demos. Default off; no production-profile impact."
```

Merge this PR, then restart Spectre with `CHAOS_ENABLED=true` before running the error-storm demo (the changes worker should find this commit as the origin).

### Task 47: Docker-level chaos script

**Files:**
- Create: `agentic-sre-team/scripts/chaos.sh`
- Modify: `agentic-sre-team/Makefile` (`chaos-%` pattern target)

**Interfaces:**
- Consumes: Spectre's real container names (verified: `keycloak`, `keycloak-db`, `spectre-opensearch`, `spectre-kong`, `spectre-admin-server`), the chaos control endpoint (Task 46), `POST /api/activity/annotations` (Task 21).
- Produces: `make chaos-error-storm|latency|cpu|memory|kc-down|kc-db-down|opensearch-down|kong-pause|restore`. Every mode posts a `chaos` annotation so the queue timeline shows the injection moment.

- [ ] **Step 1: Verify the admin-server internal port** - read Spectre's compose/admin-server config for the listen port (`docker exec spectre-admin-server printenv PORT` or the compose file); set it as `ADMIN_PORT` default below.

- [ ] **Step 2: Write scripts/chaos.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-help}"
GATEWAY="${GATEWAY_URL:-http://localhost:8080}"
ADMIN_CONTAINER="${ADMIN_CONTAINER:-spectre-admin-server}"
ADMIN_PORT="${ADMIN_PORT:-3001}"   # verified against spectre compose in Task 47 step 1

annotate() {
  curl -s -X POST "$GATEWAY/api/activity/annotations" \
    -H 'Content-Type: application/json' \
    -d "{\"text\": \"chaos: $1\", \"kind\": \"chaos\"}" >/dev/null || true
}

chaos_api() {  # app-level chaos via the internal control endpoint (Task 46)
  docker exec "$ADMIN_CONTAINER" node -e "
    fetch('http://localhost:${ADMIN_PORT}/internal/chaos', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '$1'
    }).then(r => r.json()).then(j => console.log(JSON.stringify(j)))
      .catch(e => { console.error(String(e)); process.exit(1); })"
}

case "$MODE" in
  error-storm)     chaos_api '{"mode":"error-storm","rate":0.5}'; annotate error-storm ;;
  latency)         chaos_api '{"mode":"latency","latencyMs":900}'; annotate latency ;;
  cpu)             chaos_api '{"mode":"cpu","cpuMs":150}'; annotate cpu ;;
  memory)          chaos_api '{"mode":"memory","memoryMb":25}'; annotate memory ;;
  kc-down)         docker stop keycloak; annotate kc-down ;;
  kc-db-down)      docker stop keycloak-db; annotate kc-db-down ;;
  opensearch-down) docker stop spectre-opensearch; annotate opensearch-down ;;
  kong-pause)      docker pause spectre-kong; annotate kong-pause ;;
  restore)
    chaos_api '{"mode":"off"}' 2>/dev/null || true
    docker start keycloak keycloak-db spectre-opensearch 2>/dev/null || true
    docker unpause spectre-kong 2>/dev/null || true
    annotate restore ;;
  *)
    echo "usage: chaos.sh {error-storm|latency|cpu|memory|kc-down|kc-db-down|opensearch-down|kong-pause|restore}"
    exit 1 ;;
esac
echo "chaos: $MODE done"
```

Makefile: `chaos-%:\n\t./scripts/chaos.sh $*` (plus `chmod +x scripts/chaos.sh`).

- [ ] **Step 3: Verify each infra mode manually** (Spectre up): `make chaos-kc-down` stops keycloak; `make chaos-restore` brings everything back; the timeline strip shows the annotations. App modes need the merged Task 46 PR + `CHAOS_ENABLED=true`.

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/sre-team-p9-chaos-acceptance
git add scripts/chaos.sh Makefile
git commit -m "feat(sre-team): docker and app-level chaos script with timeline annotations"
```

### Task 48: Grafana Cloud provisioning one-shot

**Files:**
- Create: `agentic-sre-team/config/alerts/rules.yaml`
- Create: `agentic-sre-team/gateway/src/sre_gateway/provision/__init__.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/provision/grafana.py`
- Create: `agentic-sre-team/gateway/src/sre_gateway/provision/__main__.py`
- Modify: `agentic-sre-team/docker-compose.yml` (provision one-shot service, profile `provision`)
- Modify: `agentic-sre-team/Makefile` (provision target)
- Create: `agentic-sre-team/gateway/tests/test_provision.py`

**Interfaces:**
- Consumes: Grafana provisioning HTTP API (docs-check: `/api/v1/provisioning/alert-rules` GET/POST/PUT with `X-Disable-Provenance`, `/api/v1/provisioning/contact-points`, `/api/folders`), `Settings.grafana_url/sa_token`, new `grafana_prom_ds_uid`.
- Produces:
  - `config/alerts/rules.yaml` - Spectre-failure-mode rules; every `expr` carries a `# MUST-VERIFY` comment until step 3 confirms the metric names:

    ```yaml
    folder: agentic-sre-team
    group: spectre
    interval: 1m
    contact_point:
      name: sre-gateway-webhook          # created only when webhook_url set
      webhook_url: ${SRE_GRAFANA_WEBHOOK_URL}
      hmac_secret: ${SRE_GRAFANA_WEBHOOK_SECRET}
    rules:
      - title: AdminServerHighErrorRate
        expr: >-                          # MUST-VERIFY metric names against the stack
          sum(rate(kong_http_requests_total{code=~"5.."}[5m]))
          / clamp_min(sum(rate(kong_http_requests_total[5m])), 1e-9) > 0.05
        for: 2m
        labels: {service: admin-server, component: api, severity: sev2}
        annotations: {summary: "Error rate spike on admin-server via Kong"}
      - title: AdminServerP95Latency
        expr: >-                          # MUST-VERIFY (OTel http server duration histogram)
          histogram_quantile(0.95, sum by (le)
          (rate(http_server_request_duration_seconds_bucket{service_name="admin-server"}[5m]))) > 1
        for: 3m
        labels: {service: admin-server, component: api, severity: sev3}
        annotations: {summary: "p95 latency climbing on admin-server"}
      - title: KeycloakDown
        expr: 'up{job=~".*keycloak.*"} == 0'   # MUST-VERIFY job label
        for: 1m
        labels: {service: keycloak, component: auth, severity: sev1}
        annotations: {summary: "Keycloak is not responding"}
      - title: OpenSearchIndexingLag
        expr: 'rate(fluentbit_output_retries_total[5m]) > 0'   # MUST-VERIFY
        for: 3m
        labels: {service: opensearch, component: audit-pipeline, severity: sev3}
        annotations: {summary: "Audit pipeline backpressure (Fluent Bit retries)"}
      - title: ContainerDown
        expr: 'up == 0'
        for: 2m
        labels: {service: spectre, component: host, severity: sev2}
        annotations: {summary: "A scraped Spectre target is down"}
    ```

  - `provision/grafana.py`: `build_rule_payload(rule, folder_uid, group, prom_ds_uid) -> dict` (grafana-managed rule: query `A` = the PromQL against the prom datasource, `C` = `__expr__` threshold `A > 0`, `condition: "C"`, `noDataState: NoData`, `execErrState: Error`, `for`, labels, annotations) and `async apply(settings, config) -> dict` - ensure folder (idempotent by title), GET existing rules, match by title -> PUT else POST (`X-Disable-Provenance: true` header so operators can still edit in the UI), upsert the webhook contact point when `webhook_url` is set (docs-check whether the stack's Grafana version supports HMAC on webhook contact points; if not, fall back to an `Authorization` header secret and adjust `verify_grafana_hmac` usage note). Prints a created/updated/unchanged summary. Idempotent: running twice changes nothing.
  - Compose service (profile `provision`, gateway image, `command: ["python", "-m", "sre_gateway.provision"]`); Makefile `provision: $(COMPOSE) --profile provision run --rm provision`.

- [ ] **Step 1: Failing unit tests** - `tests/test_provision.py`: (a) `build_rule_payload` output has `title`, `for`, both query nodes, `condition == "C"`, labels/annotations preserved; (b) with respx: existing rule with same title -> PUT called, no POST; missing -> POST; (c) no `webhook_url` -> no contact-point call.

- [ ] **Step 2: Implement + run tests.**

- [ ] **Step 3: Metric-name verification (live, MUST-VERIFY resolution)** - list what the stack actually ships and finalize every `expr`:

```bash
curl -s -H "Authorization: Bearer $SRE_GRAFANA_SA_TOKEN" \
  "$SRE_GRAFANA_URL/api/datasources/proxy/uid/$SRE_GRAFANA_PROM_DS_UID/api/v1/label/__name__/values" \
  | python3 -c "import json,sys; [print(n) for n in json.load(sys.stdin)['data'] if any(k in n for k in ('kong','keycloak','http_server','fluentbit','up'))]"
```

Update `rules.yaml` exprs to the real names, delete the MUST-VERIFY comments, re-run `make provision`, then verify in the Grafana UI that all five rules exist in folder `agentic-sre-team` and evaluate.

- [ ] **Step 4: Live fire test** - `make chaos-kc-down`, wait, confirm `KeycloakDown` fires in Grafana and the poller opens a case; `make chaos-restore`.

- [ ] **Step 5: Commit**

```bash
git add config/alerts gateway docker-compose.yml Makefile
git commit -m "feat(sre-team): idempotent grafana cloud alert-rule and contact-point provisioning"
```

### Task 49: Seeded CI failure flow (chaos-ci) and GitLab mirror validation

**Files:**
- Create: `agentic-sre-team/scripts/chaos_ci.sh`
- Modify: `agentic-sre-team/Makefile` (chaos-ci, chaos-ci-clean)
- Create: `agentic-sre-team/docs/gitlab-mirror.md`

**Interfaces:**
- Consumes: the Spectre repo (`~/Code/spectre`), `gh` CLI, the SCM poller (Task 38).
- Produces: `make chaos-ci` pushes a branch with a seeded failure and opens a **draft PR marked as chaos** so `ci.yml` runs and fails; the poller opens a `pipeline_failure` case. `make chaos-ci-clean` closes the PR and deletes the branch. `docs/gitlab-mirror.md` documents the one-time mirror setup validating the GitLab path live (contract tests already cover it; spec section 9 asks for a minimal live mirror run).

- [ ] **Step 1: Verify Spectre CI triggers** - read `~/Code/spectre/.github/workflows/ci.yml`: confirm it runs on `pull_request` (or push to branches). The script below assumes PR-triggered CI; adjust to a bare push if that is what the workflow keys on.

- [ ] **Step 2: Write scripts/chaos_ci.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
SPECTRE_DIR="${SPECTRE_DIR:-$HOME/Code/spectre}"
KIND="${1:-dep}"          # dep = dependency pin typo | test = failing vitest case
TS="$(date +%s)"
BRANCH="chaos/ci-fail-${KIND}-${TS}"

cd "$SPECTRE_DIR"
git fetch origin
git checkout -b "$BRANCH" origin/main

case "$KIND" in
  dep)
    node -e "
      const fs = require('fs');
      const p = 'admin-server/package.json';
      const j = JSON.parse(fs.readFileSync(p));
      j.dependencies.express = '^5.99.99';   // nonexistent version: install fails
      fs.writeFileSync(p, JSON.stringify(j, null, 2) + '\n');" ;;
  test)
    cat > admin-server/test/chaos-seeded.test.ts <<'EOF'
import { describe, expect, it } from 'vitest';

describe('chaos seeded failure', () => {
  it('fails intentionally (agentic-sre-team demo)', () => {
    expect('chaos').toBe('calm');
  });
});
EOF
    ;;
  *) echo "usage: chaos_ci.sh {dep|test}"; exit 1 ;;
esac

git add -A
git commit -m "chore: chaos-ci seeded ${KIND} failure (${TS}) - safe to close"
git push -u origin "$BRANCH"
gh pr create --draft --title "chaos-ci: seeded ${KIND} failure (${TS})" \
  --body "Seeded by agentic-sre-team scripts/chaos_ci.sh to exercise the pipeline-failure loop. Never merge; clean up with make chaos-ci-clean."
echo "Seeded ${KIND} failure on ${BRANCH}. CI will fail; the poller opens a case."
echo "BRANCH=${BRANCH}" > /tmp/chaos-ci-last
```

Makefile:

```makefile
chaos-ci:
	./scripts/chaos_ci.sh $(or $(KIND),dep)

chaos-ci-clean:
	cd $${SPECTRE_DIR:-$$HOME/Code/spectre} && \
	BRANCH=$$(cut -d= -f2 /tmp/chaos-ci-last) && \
	gh pr close "$$BRANCH" --delete-branch || git push origin --delete "$$BRANCH"
```

- [ ] **Step 3: GitLab mirror doc** - `docs/gitlab-mirror.md`: create `spectre-mirror` on gitlab.com; push Spectre's `main`; add a minimal `.gitlab-ci.yml`:

```yaml
test:
  image: node:22
  script:
    - cd admin-server
    - npm ci
    - npm test
```

Set `SRE_GITLAB_TOKEN` (+ webhook secret or poller), add the repo to `config/repos.yaml` (already listed), seed the same `dep` failure on a branch there, and verify: pipeline fails -> case opens with `kind=pipeline_failure`, `source=gitlab`, classified `dependency`, RCA cites the job log and diff.

- [ ] **Step 4: Live run (DevSecOps demo rehearsal)** - `make chaos-ci` against the real Spectre repo, watch the case: classification, RCA citing the job-log lines + workflow config + diff, runbook with the corrected `package.json` patch, gate-2 approve; with `SRE_SCM_DRAFT_MR=true` + publish token, confirm the draft PR appears and is never merged. `make chaos-ci-clean` afterwards.

- [ ] **Step 5: Commit**

```bash
git add scripts/chaos_ci.sh Makefile docs/gitlab-mirror.md
git commit -m "feat(sre-team): seeded ci-failure chaos flow and gitlab mirror validation guide"
```

### Task 50: Demo runner, README, acceptance checklists

**Files:**
- Create: `agentic-sre-team/scripts/demo.sh`
- Create: `agentic-sre-team/README.md`
- Modify: `agentic-sre-team/Makefile` (demo target)

**Interfaces:**
- Consumes: everything.
- Produces: `make demo` (the spec section 9 acceptance demo, timed) and the project README.

- [ ] **Step 1: scripts/demo.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
GATEWAY="${GATEWAY_URL:-http://localhost:8080}"
START="$(date +%s)"

echo "== preflight"
curl -sf "$GATEWAY/api/healthz" >/dev/null || { echo "gateway down: make up"; exit 1; }
docker inspect -f '{{.State.Running}}' keycloak >/dev/null 2>&1 \
  || { echo "spectre not running: cd ~/Code/spectre && docker compose up -d"; exit 1; }
BASELINE=$(curl -s "$GATEWAY/api/cases" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['cases']))")

echo "== injecting error storm (CHAOS_ENABLED=true required on admin-server)"
./scripts/chaos.sh error-storm

echo "== waiting for the alert -> case (poller interval + alert 'for' period)"
CASE_ID=""
for _ in $(seq 1 120); do
  CASE_ID=$(curl -s "$GATEWAY/api/cases" | python3 -c "
import json, sys
cases = json.load(sys.stdin)['cases']
fresh = [c for c in cases if c['status'] != 'closed']
print(fresh[0]['id'] if len(fresh) > ${BASELINE:-0} or fresh else '')" 2>/dev/null) || true
  [ -n "$CASE_ID" ] && break
  sleep 5
done
[ -n "$CASE_ID" ] || { echo "no case opened - check grafana rules + poller"; exit 1; }
echo "case: $CASE_ID  -> watch it live: http://localhost:8088/cases/$CASE_ID"

echo "== waiting for gate 1 (approve in Telegram or the console)"
for _ in $(seq 1 240); do
  STATUS=$(curl -s "$GATEWAY/api/cases/$CASE_ID" | python3 -c "import json,sys; c=json.load(sys.stdin)['case']; print(c['status'] + ':' + c['phase'])")
  echo "  $STATUS ($(( $(date +%s) - START ))s elapsed)"
  case "$STATUS" in closed:*) break ;; esac
  sleep 5
done

./scripts/chaos.sh restore
echo "== done in $(( $(date +%s) - START ))s (target: under ~300s to close)"
```

Makefile: `demo:\n\t./scripts/demo.sh`

- [ ] **Step 2: Write README.md** - sections: what this is (one paragraph + pointer to the spec), architecture sketch (services table from spec section 3), prerequisites (Docker, uv, node, Spectre repo, Grafana Cloud stack + SA token, Vertex project + ADC, Telegram bot, GitHub/GitLab tokens), setup (`cp .env.example .env`, fill, `make up provision`), the make-target table (`up, up-fake, down, migrate, test, lint, e2e, smoke, live-check, holmes-check, provision, chaos-*, chaos-ci, demo`), profile matrix (fake / local / air-gap: what swaps where, per spec section 7), a **Bring your own environment** section (Spectre is only the reference SUT: swap `config/environment.yaml`, the holmes.yaml endpoint env vars, `config/repos.yaml`, and `config/alerts/rules.yaml` to manage any stack on the same platform family - no code changes; chaos scripts and the seeded-failure flow are Spectre demo assets to replicate per target), and the two acceptance checklists:

**Incident acceptance (spec section 9, target under ~5 minutes):**
1. `make chaos-error-storm` -> Grafana Cloud alert fires.
2. Case opens; Telegram ack with case id + severity.
3. Parallel Holmes-backed investigation visible live in the console ledger.
4. RCA with verified citations reaches gate 1 -> approve in Telegram.
5. Runbook reaches gate 2 -> approve in the console.
6. Both artifacts in Telegram; runbook indexed; case learning written; case closed.
7. `make chaos-restore`; timeline strip shows the chaos annotation and case marker.

**DevSecOps acceptance (spec section 9):**
1. `make chaos-ci` (dependency pin typo on a branch + draft PR).
2. Poller opens a `pipeline_failure` case, classified (`dependency`).
3. RCA cites failed job log lines, `ci.yml` config, and the triggering diff.
4. Runbook leads with the corrected `package.json` patch (true diff at gate 2).
5. Approve gate 2; with `SRE_SCM_DRAFT_MR=true`, a draft PR opens and is never merged.
6. GitLab mirror re-run per `docs/gitlab-mirror.md` (poller path, same flow).
7. `make chaos-ci-clean`.

- [ ] **Step 3: Full verification sweep**

Run: `make test lint test-ui lint-ui && make smoke && make e2e` - all green; then the two live acceptance runs above, timed.

- [ ] **Step 4: Commit and open the final phase PR**

```bash
git add scripts/demo.sh README.md Makefile
git commit -m "docs(sre-team): readme, demo runner and acceptance checklists"
# PR: feat/sre-team-p9-chaos-acceptance -> main
```

---

## Spec coverage map

| Spec section | Tasks |
|---|---|
| 3 services + compose | 2, 13, 22, 23, 27, 48 |
| 3 intake paths (webhook, poller, chat kickoff, telegram, pipelines) | 5, 8, 24, 44, 34-35, 38 |
| 3 noise control + correlation grouping | 6, 7, 8, 35 |
| 4 graph: triage/plan/workers/synthesize/rca/verify/gates/remediate/publish, budgets between nodes, learnings | 14-21, 12 |
| 4 case kinds -> worker sets, failure classification | 14, 16, 39 |
| 5 data model + API (incl. SSE replay) | 3, 8, 21, 42 |
| 6 UI screens 1-5 + system states | 27-33, 45 |
| 6a chat modes + guardrails | 42-45 |
| 7 model tiers, holmes model strings, air-gap seam | 9, 10, 25 |
| 8 permission manifests, holmes.yaml, single gated write | 11, 23, 41 |
| 9 Spectre chaos, provisioning, both demos | 46-50 |
| 10 error handling (restart resume, retries, degraded workers, parked cases, /healthz) | 10, 16, 21, 24, 34 |
| 11 tests (unit, graph, SCM contract, API/UI, playwright, smoke, live) | throughout; 20, 22, 33, 36-39 |
| 12 risks (holmes drift -> fake contract; vertex fallback) | 13, 23, 25 |
| 13 Robusta adoptions (grouping, learnings, chat, timeline) | 7, 21 (activity), 19/15 (learnings), 42-45 |

## Execution notes for the implementer

- Phases must land in order; each phase's PR merges before the next starts. Within a phase, tasks are ordered by dependency.
- Every task ends with the full gateway suite green (`uv run pytest -q && uv run ruff check .`), not just the task's own tests.
- The `deps` / `deps_two_rounds` / `client` / `pipeline_deps` / `chat_service` pytest fixtures accrete in `tests/conftest.py`; keep them there, not copied per file.
- Docs-check steps are load-bearing: this plan encodes best-known external API shapes (HolmesGPT, Grafana provisioning, langchain-google kwargs, Vertex model ids); the checks are where drift is caught and fixed, and the fake-Holmes fixtures are the recorded contract to update alongside.
- If a fixture or scripted response drifts from a schema change you make, fix the fixture in the same commit - the fake profile is the regression net for everything above it.







