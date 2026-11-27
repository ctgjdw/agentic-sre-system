# Local Laptop Docker Compose Stack, Service Configs & Reference SUT Specification

> **Status:** Approved Infrastructure & Config Contract
> **Date:** 2026-11-27
> **Target Host:** Windows 10/11 (`10.0.26300`, WSL2, Docker Engine `29.5.3`, 12 logical CPUs, 63.8 GB physical RAM, NVIDIA Quadro RTX 3000 6 GB GDDR6 VRAM, 201 GB free disk)
> **Companion Specs:**
> - System Architecture Spec: [`2026-11-27-airgap-platform-design.md`](2026-11-27-airgap-platform-design.md)
> - Phased Implementation Plan: [`../plans/2026-11-27-airgap-compose-implementation-plan.md`](../plans/2026-11-27-airgap-compose-implementation-plan.md)

---

## 1. Compose Profiles & Non-Colliding Port Matrix

### 1.1 Profile Architecture

Every profile is additive and preserves existing `fake` and `ui` behaviors so `make smoke` and `make e2e` never regress:

| Profile | Services Started | When Used |
|---|---|---|
| *(core, always on)* | `postgres`, `gateway` | Base database + API/LangGraph control plane |
| `fake` | `fake-holmes` | Offline deterministic CI (`smoke`, `e2e`) -- zero GPU, zero network |
| `ui` | `ui` | React 19 Ops Console on `:8088` |
| `local-gpu` | `ollama`, `ollama-pull`, `agentgateway`, `lgtm`, `mcp-grafana`, `mcp-gitlab`, `holmes` | Primary local self-hosted AI + LGTM + MCP stack on RTX 3000 |
| `litellm` | `litellm` | Optional drop-in LLM gateway parity test (`SRE_LLM_GATEWAY_URL=http://litellm:4000/v1`) |
| `sut` | `sut-db`, `demo-sut` | Self-contained OTel-instrumented microservice SUT + chaos target |
| `provision` | `provision` | One-shot idempotent Grafana folder, alert-rule, and webhook provisioning |
| `mattermost` | `mattermost` | Self-hosted chat notifications, interactive gate buttons, and DM intake |
| `auth` | `keycloak` | Pre-seeded OIDC SSO provider (`sre` realm) for JWT RBAC verification |
| `langfuse` | `clickhouse`, `langfuse-redis`, `langfuse-minio`, `langfuse-worker`, `langfuse-web` | Optional self-hosted Langfuse v3 LLM observability (`TELEMETRY_ENABLED=false`) |
| `live` | *(legacy cloud profile kept optional via `docker-compose.cloud.yml` if ever needed)* | Deprecated in favor of `local-gpu` |

### 1.2 Host & Internal Port Allocation (Zero Collisions)

| Service | Container Hostname : Port | Host Loopback Binding | Purpose |
|---|---|---|---|
| `postgres` | `postgres:5432` | `127.0.0.1:5433:5432` | `sre`, `mattermost`, and `langfuse` databases |
| `gateway` | `gateway:8080` | `127.0.0.1:8080:8080` | FastAPI REST + SSE + Webhooks |
| `ui` | `ui:80` | `127.0.0.1:8088:80` | Ops Console SPA (nginx proxies `/api/` -> `gateway:8080`) |
| `ollama` | `ollama:11434` | `127.0.0.1:11434:11434` | Local CUDA GGUF inference + embeddings |
| `agentgateway` (LLM) | `agentgateway:4000` | `127.0.0.1:4000:4000` | OpenAI-compatible LLM router + admin UI |
| `agentgateway` (MCP) | `agentgateway:3000` | `127.0.0.1:3003:3000` | CEL-filtered Streamable-HTTP MCP gateway (host `3003` avoids Grafana `3000`) |
| `litellm` | `litellm:4000` | `127.0.0.1:4001:4000` | Interchangeable OpenAI-compatible LLM proxy |
| `lgtm` (Grafana) | `lgtm:3000` | `127.0.0.1:3000:3000` | Grafana UI & Alerting API (`admin` / `admin`) |
| `lgtm` (Prometheus) | `lgtm:9090` | `127.0.0.1:9090:9090` | Prometheus metrics API |
| `lgtm` (Loki) | `lgtm:3100` | `127.0.0.1:3100:3100` | Loki logs API |
| `lgtm` (Tempo) | `lgtm:3200` | `127.0.0.1:3200:3200` | Tempo traces API (`gen_ai.*` spans) |
| `lgtm` (OTLP) | `lgtm:4317`, `lgtm:4318` | `127.0.0.1:4317`, `127.0.0.1:4318` | OTLP gRPC & HTTP ingestion |
| `mcp-grafana` | `mcp-grafana:8000` | *(internal only)* | Upstream Grafana MCP server (fronted by `agentgateway`) |
| `mcp-gitlab` | `mcp-gitlab:3002` | *(internal only)* | Upstream GitLab MCP server pointing to `gitlab.com/api/v4` |
| `holmes` / `fake-holmes` | `holmes:5050` / `fake-holmes:5050` | `127.0.0.1:5050:5050` | HolmesGPT 0.43.0 sidecar (or fake fixture server) |
| `demo-sut` | `demo-sut:8090` | `127.0.0.1:8090:8090` | Reference OTel-instrumented SUT + `/internal/chaos` |
| `mattermost` | `mattermost:8065` | `127.0.0.1:8065:8065` | Self-hosted Mattermost Team Edition |
| `keycloak` | `keycloak:8180` | `127.0.0.1:8180:8180` | Keycloak 26 OIDC SSO (`sre` realm) |
| `langfuse-web` | `langfuse-web:3000` | `127.0.0.1:3030:3000` | Self-hosted Langfuse v3 UI & OTel sink (host `3030` avoids Grafana `3000`) |

---

## 2. Windows / WSL2 / Sandboxed CLI Engineering Rules

Any agentic orchestrator or developer MUST enforce these five Windows-specific rules when writing files and running commands:

1. **Never Mount `/dev/null` in `docker-compose.yml`:**
   Existing `docker-compose.yml` lines 41 & 77 mounted `${GOOGLE_APPLICATION_CREDENTIALS:-/dev/null}:/secrets/gcp.json:ro`. On Windows Docker Desktop, `/dev/null` resolves to `C:\dev\null`, creating a directory where a JSON file is expected or failing container start. Remove all `/dev/null` bind mounts completely from the main `docker-compose.yml`.
2. **Enforce `LF` Line Endings via Root `.gitattributes`:**
   Create `.gitattributes` at repository root before adding any `.sh`, `.sql`, `.py`, or `Dockerfile` files so Windows Git checkout never injects `CRLF` (`\r`) into container entrypoints:
   ```gitattributes
   * text=auto eol=lf
   *.bat text eol=crlf
   *.ps1 text eol=crlf
   ```
3. **Cross-Platform CLI Runner (`scripts/cli.py`) over GNU `make` Env Syntax:**
   Windows `make.exe` invokes `cmd.exe` unless `SHELL := sh` is set, causing inline `SRE_MODELS_PROFILE=fake docker compose ...` lines to fail in PowerShell/cmd. Both update `Makefile` (`SHELL := sh` when Git Bash exists) **AND** create `agentic-sre-team/scripts/cli.py` (stdlib Python `argparse` + `subprocess.run(..., env={**os.environ, ...})`) so every workflow (`python scripts/cli.py smoke`, `e2e`, `up-local`, `down`, `provision`, `test`, `lint`) runs identically on Windows PowerShell, macOS, and Linux.
4. **Sandboxed CLI & Docker Config Permissions Note:**
   When running inside a restricted agent terminal sandbox on Windows, `C:\Users\admin\.docker\config.json` may sit outside the allowed workspace, causing `docker compose` plugin discovery to report `Access is denied` unless either:
   - `DOCKER_CONFIG` is pointed to a workspace-local directory (`$env:DOCKER_CONFIG = "$PWD/.docker-tmp"`), OR
   - `docker-compose.exe` (`C:\Program Files\Docker\Docker\resources\bin\docker-compose.exe`) is invoked directly, OR
   - Host-level execution permissions are granted for commands talking to the Docker Desktop daemon socket (`docker build`, `docker compose up`, `pytest` with `testcontainers`).
   In `scripts/cli.py`, automatically set `DOCKER_CONFIG` to a writable `.docker-config` temp directory if `~/.docker/config.json` raises `PermissionError`, and auto-detect `docker compose` vs `docker-compose`.
5. **Python 3.12 + `uv` Execution on This Host:**
   Host global Python is `3.10`, whereas `gateway/` targets Python `3.12`. Either install `uv` (`winget` / `~/.local/bin/uv.exe` which auto-downloads standalone Python 3.12 via `uv sync --python 3.12`) OR run gateway pytest/ruff inside a `gateway-dev` container (`docker build -f gateway/Dockerfile.dev` or `uv` image). Installing `uv` locally (`uv python install 3.12 && uv sync`) is fastest for iterative `pytest` + `testcontainers`.

---

## 3. Complete `docker-compose.yml` Blueprint (`agentic-sre-team/docker-compose.yml`)

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
      - "127.0.0.1:5433:5432"
    volumes:
      - sre-pg:/var/lib/postgresql/data
      - ./config/postgres/init-extra-dbs.sql:/docker-entrypoint-initdb.d/10-init-extra-dbs.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sre -d sre"]
      interval: 5s
      timeout: 3s
      retries: 20
    deploy: {resources: {limits: {memory: 1024M}}}

  gateway:
    build:
      context: ./gateway
      dockerfile: Dockerfile
    container_name: sre-gateway
    command: ["sh", "-c", "alembic upgrade head && uvicorn sre_gateway.main:app --host 0.0.0.0 --port 8080"]
    env_file:
      - path: .env
        required: false
    environment:
      SRE_DATABASE_URL: postgresql+asyncpg://sre:${SRE_PG_PASSWORD:-sre}@postgres:5432/sre
      SRE_CONFIG_DIR: /config
      SRE_ENVIRONMENT_FILE: ${SRE_ENVIRONMENT_FILE:-environment.yaml}
      SRE_MODELS_PROFILE: ${SRE_MODELS_PROFILE:-local-gpu}
      SRE_LLM_GATEWAY_URL: ${SRE_LLM_GATEWAY_URL:-http://agentgateway:4000/v1}
      SRE_LLM_API_KEY: ${SRE_LLM_API_KEY:-local-offline-key}
      SRE_LOCAL_CHAT_MODEL: ${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
      SRE_LOCAL_EMBED_MODEL: ${SRE_LOCAL_EMBED_MODEL:-nomic-embed-text}
      SRE_HOLMES_URL: ${SRE_HOLMES_URL:-http://holmes:5050}
      SRE_FAKE_SCRIPT_DIR: ${SRE_FAKE_SCRIPT_DIR:-}
      SRE_PREFLIGHT_PROBES_ENABLED: ${SRE_PREFLIGHT_PROBES_ENABLED:-false}
      SRE_PREFLIGHT_PROM_URL: ${SRE_PREFLIGHT_PROM_URL:-http://lgtm:9090}
      SRE_PREFLIGHT_LOKI_URL: ${SRE_PREFLIGHT_LOKI_URL:-http://lgtm:3100}
      SRE_GRAFANA_URL: ${SRE_GRAFANA_URL:-http://lgtm:3000}
      SRE_GRAFANA_PUBLIC_URL: ${SRE_GRAFANA_PUBLIC_URL:-http://localhost:3000}
      SRE_GRAFANA_POLL_ENABLED: ${SRE_GRAFANA_POLL_ENABLED:-false}
      SRE_OTEL_ENABLED: ${SRE_OTEL_ENABLED:-false}
      SRE_OTEL_EXPORTER_ENDPOINT: ${SRE_OTEL_EXPORTER_ENDPOINT:-http://lgtm:4318/v1/traces}
      SRE_TELEGRAM_ENABLED: ${SRE_TELEGRAM_ENABLED:-false}
      SRE_MATTERMOST_ENABLED: ${SRE_MATTERMOST_ENABLED:-false}
      SRE_AUTH_ENABLED: ${SRE_AUTH_ENABLED:-false}
      SRE_SCM_POLL_ENABLED: ${SRE_SCM_POLL_ENABLED:-false}
      SRE_SCM_DRAFT_MR: ${SRE_SCM_DRAFT_MR:-false}
      SRE_GITLAB_BASE_URL: ${SRE_GITLAB_BASE_URL:-https://gitlab.com}
    volumes:
      - ./config:/config:ro
    ports:
      - "127.0.0.1:8080:8080"
    depends_on:
      postgres: {condition: service_healthy}
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/healthz')\""]
      interval: 10s
      timeout: 5s
      retries: 15
    deploy: {resources: {limits: {memory: 1024M}}}

  ui:
    profiles: ["ui"]
    build: ./ui
    container_name: sre-ui
    ports:
      - "127.0.0.1:8088:80"
    depends_on:
      - gateway
    deploy: {resources: {limits: {memory: 256M}}}

  fake-holmes:
    profiles: ["fake"]
    build: ./gateway
    container_name: sre-fake-holmes
    command: ["python", "-m", "sre_gateway.testing.fake_holmes"]
    environment:
      FAKE_HOLMES_DIR: /app/tests/fixtures/holmes/incident_error_storm
    ports:
      - "127.0.0.1:5050:5050"

  # --- Local GPU Inference (NVIDIA Quadro RTX 3000 6GB GDDR6 + 64GB RAM) ---
  ollama:
    profiles: ["local-gpu"]
    image: ollama/ollama:latest
    container_name: sre-ollama
    environment:
      OLLAMA_KEEP_ALIVE: "-1"
      OLLAMA_MAX_LOADED_MODELS: "2"
      OLLAMA_NUM_PARALLEL: "2"
      OLLAMA_FLASH_ATTENTION: "1"
      OLLAMA_KV_CACHE_TYPE: "q8_0"
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - sre-ollama:/root/.ollama
    deploy:
      resources:
        limits:
          memory: 12G
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 10s
      timeout: 5s
      retries: 20

  ollama-pull:
    profiles: ["local-gpu"]
    image: ollama/ollama:latest
    container_name: sre-ollama-pull
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_HOST: http://ollama:11434
      CHAT_MODEL: ${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
      EMBED_MODEL: ${SRE_LOCAL_EMBED_MODEL:-nomic-embed-text}
    entrypoint: ["sh", "-c", "ollama pull $$CHAT_MODEL && ollama pull $$EMBED_MODEL"]
    restart: "no"

  # --- Self-Hosted Observability (Grafana + Prometheus + Loki + Tempo + OTel Collector) ---
  lgtm:
    profiles: ["local-gpu"]
    image: grafana/otel-lgtm:latest
    container_name: sre-lgtm
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: "Viewer"
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${SRE_GRAFANA_ADMIN_PASSWORD:-admin}
    ports:
      - "127.0.0.1:3000:3000"
      - "127.0.0.1:4317:4317"
      - "127.0.0.1:4318:4318"
      - "127.0.0.1:9090:9090"
      - "127.0.0.1:3100:3100"
      - "127.0.0.1:3200:3200"
    volumes:
      - sre-lgtm:/data
      - ./config/lgtm/prometheus-extra.yaml:/otel-lgtm/prometheus-extra.yaml:ro
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://127.0.0.1:3000/api/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 20
    deploy: {resources: {limits: {memory: 2048M}}}

  # --- Upstream Read-Only MCP Servers (Fronted Exclusively by agentgateway) ---
  mcp-grafana:
    profiles: ["local-gpu"]
    image: grafana/mcp-grafana:latest
    container_name: sre-mcp-grafana
    command: ["-t", "streamable-http", "--address", "0.0.0.0:8000", "--endpoint-path", "/mcp", "--disable-write"]
    environment:
      GRAFANA_URL: http://lgtm:3000
      GRAFANA_USERNAME: admin
      GRAFANA_PASSWORD: ${SRE_GRAFANA_ADMIN_PASSWORD:-admin}
    depends_on:
      lgtm: {condition: service_healthy}
    deploy: {resources: {limits: {memory: 256M}}}

  mcp-gitlab:
    profiles: ["local-gpu"]
    image: zereight050/gitlab-mcp:latest
    container_name: sre-mcp-gitlab
    environment:
      HOST: "0.0.0.0"
      PORT: "3002"
      STREAMABLE_HTTP: "true"
      GITLAB_READ_ONLY_MODE: "true"
      GITLAB_API_URL: "${SRE_GITLAB_BASE_URL:-https://gitlab.com}/api/v4"
      GITLAB_PERSONAL_ACCESS_TOKEN: ${SRE_GITLAB_TOKEN:-unused-local}
      STREAMABLE_HTTP_AUTH_TOKEN: ${SRE_MCP_INTERNAL_TOKEN:-sre-mcp-internal}
    deploy: {resources: {limits: {memory: 512M}}}

  # --- Unified Rust AI + MCP Gateway (LLM Routing :4000 + CEL MCP Filtering :3000) ---
  agentgateway:
    profiles: ["local-gpu"]
    image: cr.agentgateway.dev/agentgateway:v1.7.0
    container_name: sre-agentgateway
    command: ["-f", "/config/config.yaml"]
    environment:
      OPENAI_API_KEY: ${SRE_LLM_API_KEY:-ollama}
      MCP_INTERNAL_TOKEN: ${SRE_MCP_INTERNAL_TOKEN:-sre-mcp-internal}
    volumes:
      - ./config/agentgateway/config.yaml:/config/config.yaml:ro
      - sre-agw:/data
    ports:
      - "127.0.0.1:4000:4000"
      - "127.0.0.1:3003:3000"
    depends_on:
      - ollama
      - mcp-grafana
      - mcp-gitlab
    deploy: {resources: {limits: {memory: 512M}}}

  # --- Optional LiteLLM Gateway (Parity Swap Target via SRE_LLM_GATEWAY_URL) ---
  litellm:
    profiles: ["litellm"]
    image: ghcr.io/berriai/litellm:main-stable
    container_name: sre-litellm
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    environment:
      LITELLM_MASTER_KEY: ${SRE_LLM_API_KEY:-local-offline-key}
    volumes:
      - ./config/litellm/config.yaml:/app/config.yaml:ro
    ports:
      - "127.0.0.1:4001:4000"
    deploy: {resources: {limits: {memory: 768M}}}

  # --- HolmesGPT 0.43.0 Evidence Sidecar ---
  holmes:
    profiles: ["local-gpu"]
    image: ${HOLMES_IMAGE:-robustadev/holmes:0.43.0}
    container_name: sre-holmes
    entrypoint: ["python", "server.py"]
    environment:
      OPENAI_API_BASE: ${SRE_LLM_GATEWAY_URL:-http://agentgateway:4000/v1}
      OPENAI_API_KEY: ${SRE_LLM_API_KEY:-local-offline-key}
      SRE_LOCAL_CHAT_MODEL: ${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
      LGTM_GRAFANA_URL: http://lgtm:3000
      LGTM_PROM_URL: http://lgtm:9090
      AGENTGATEWAY_MCP_URL: http://agentgateway:3000/mcp
      OTEL_EXPORTER_OTLP_ENDPOINT: http://lgtm:4318
      OTEL_SERVICE_NAME: sre-holmes
    volumes:
      - ./config/holmes.local.yaml:/root/.holmes/config.yaml:ro
      - ./config/holmes-skills:/etc/holmes/skills:ro
    ports:
      - "127.0.0.1:5050:5050"
    depends_on:
      - agentgateway
      - lgtm
    deploy: {resources: {limits: {memory: 1536M}}}

  # --- Self-Contained Reference SUT (--profile sut) ---
  sut-db:
    profiles: ["sut"]
    image: postgres:16-alpine
    container_name: sre-sut-db
    environment:
      POSTGRES_DB: orders
      POSTGRES_USER: sut
      POSTGRES_PASSWORD: sut
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sut -d orders"]
      interval: 5s
      timeout: 3s
      retries: 10
    deploy: {resources: {limits: {memory: 256M}}}

  demo-sut:
    profiles: ["sut"]
    build: ./demo-sut
    container_name: sre-demo-sut
    environment:
      SUT_DATABASE_URL: postgresql://sut:sut@sut-db:5432/orders
      OTEL_EXPORTER_OTLP_ENDPOINT: http://lgtm:4318
      OTEL_SERVICE_NAME: orders-api
      CHAOS_ENABLED: "true"
    ports:
      - "127.0.0.1:8090:8090"
    depends_on:
      sut-db:
        condition: service_healthy
    deploy: {resources: {limits: {memory: 512M}}}

  # --- Grafana Alert Rule & Webhook Provisioner (--profile provision) ---
  provision:
    profiles: ["provision"]
    build: ./gateway
    container_name: sre-provision
    command: ["python", "-m", "sre_gateway.provision"]
    environment:
      SRE_CONFIG_DIR: /config
      SRE_GRAFANA_URL: ${SRE_GRAFANA_URL:-http://lgtm:3000}
      SRE_GRAFANA_ADMIN_USER: admin
      SRE_GRAFANA_ADMIN_PASSWORD: ${SRE_GRAFANA_ADMIN_PASSWORD:-admin}
      SRE_GRAFANA_WEBHOOK_URL: http://gateway:8080/api/webhooks/grafana
      SRE_GRAFANA_WEBHOOK_SECRET: ${SRE_GRAFANA_WEBHOOK_SECRET:-local-wh-secret}
      SRE_ALERT_RULES_FILE: ${SRE_ALERT_RULES_FILE:-alerts/rules.local.yaml}
    volumes:
      - ./config:/config:ro
    depends_on:
      lgtm: {condition: service_healthy}

  # --- Mattermost Air-Gap Chat & Interactive Approvals (--profile mattermost) ---
  mattermost:
    profiles: ["mattermost"]
    image: mattermost/mattermost-team-edition:latest
    container_name: sre-mattermost
    environment:
      MM_SQLSETTINGS_DRIVERNAME: postgres
      MM_SQLSETTINGS_DATASOURCE: postgres://sre:${SRE_PG_PASSWORD:-sre}@postgres:5432/mattermost?sslmode=disable&connect_timeout=10
      MM_SERVICESETTINGS_SITEURL: http://localhost:8065
      MM_SERVICESETTINGS_ALLOWEDUNTRUSTEDINTERNALCONNECTIONS: "gateway,localhost,127.0.0.1,172.16.0.0/12,192.168.0.0/16"
      MM_SERVICESETTINGS_ENABLEBOTACCOUNTCREATION: "true"
      MM_SERVICESETTINGS_ENABLEPOSTACTIONINTEGRATION: "true"
      MM_TEAMSETTINGS_ENABLEOPENSERVER: "true"
    ports:
      - "127.0.0.1:8065:8065"
    volumes:
      - sre-mm-data:/mattermost/data
      - sre-mm-config:/mattermost/config
    depends_on:
      postgres: {condition: service_healthy}
    deploy: {resources: {limits: {memory: 1024M}}}

  # --- Toggleable Keycloak 26 OIDC SSO (--profile auth) ---
  keycloak:
    profiles: ["auth"]
    image: quay.io/keycloak/keycloak:26.0
    container_name: sre-keycloak
    command: ["start-dev", "--http-port=8180", "--import-realm"]
    environment:
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${SRE_KC_ADMIN_PASSWORD:-admin}
      JAVA_OPTS_APPEND: "-Xms256m -Xmx512m"
    volumes:
      - ./config/keycloak:/opt/keycloak/data/import:ro
    ports:
      - "127.0.0.1:8180:8180"
    deploy: {resources: {limits: {memory: 1024M}}}

  # --- Optional Self-Hosted Langfuse v3 + ClickHouse (--profile langfuse) ---
  clickhouse:
    profiles: ["langfuse"]
    image: clickhouse/clickhouse-server:24.8-alpine
    container_name: sre-clickhouse
    environment:
      CLICKHOUSE_DB: default
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: ${SRE_CLICKHOUSE_PASSWORD:-clickhouse}
    volumes:
      - sre-ch:/var/lib/clickhouse
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://127.0.0.1:8123/ping"]
      interval: 5s
      timeout: 3s
      retries: 15
    deploy: {resources: {limits: {memory: 1536M}}}

  langfuse-redis:
    profiles: ["langfuse"]
    image: redis:7-alpine
    container_name: sre-langfuse-redis
    command: ["--maxmemory", "128mb", "--maxmemory-policy", "allkeys-lru"]
    deploy: {resources: {limits: {memory: 192M}}}

  langfuse-minio:
    profiles: ["langfuse"]
    image: minio/minio:latest
    container_name: sre-langfuse-minio
    entrypoint: ["sh", "-c", "mkdir -p /data/langfuse /data/sre-audit-worm && minio server --address ':9000' /data"]
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: ${SRE_MINIO_PASSWORD:-miniosecret}
    volumes:
      - sre-minio:/data
    deploy: {resources: {limits: {memory: 384M}}}

  langfuse-worker:
    profiles: ["langfuse"]
    image: langfuse/langfuse-worker:3
    container_name: sre-langfuse-worker
    depends_on:
      postgres: {condition: service_healthy}
      clickhouse:
        condition: service_healthy
      langfuse-redis:
        condition: service_started
      langfuse-minio:
        condition: service_started
    environment: &langfuse-env
      DATABASE_URL: postgresql://sre:${SRE_PG_PASSWORD:-sre}@postgres:5432/langfuse
      SALT: ${SRE_LANGFUSE_SALT:-local-airgap-salt-change-in-prod}
      ENCRYPTION_KEY: ${SRE_LANGFUSE_ENCRYPTION_KEY:-0000000000000000000000000000000000000000000000000000000000000000}
      TELEMETRY_ENABLED: "false"
      CLICKHOUSE_MIGRATION_URL: clickhouse://clickhouse:9000
      CLICKHOUSE_URL: http://clickhouse:8123
      CLICKHOUSE_USER: clickhouse
      CLICKHOUSE_PASSWORD: ${SRE_CLICKHOUSE_PASSWORD:-clickhouse}
      CLICKHOUSE_CLUSTER_ENABLED: "false"
      REDIS_HOST: langfuse-redis
      REDIS_PORT: "6379"
      LANGFUSE_S3_EVENT_UPLOAD_BUCKET: langfuse
      LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://langfuse-minio:9000
      LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID: minio
      LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY: ${SRE_MINIO_PASSWORD:-miniosecret}
      LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
      LANGFUSE_S3_EVENT_UPLOAD_REGION: us-east-1
    deploy: {resources: {limits: {memory: 768M}}}

  langfuse-web:
    profiles: ["langfuse"]
    image: langfuse/langfuse:3
    container_name: sre-langfuse-web
    depends_on:
      - langfuse-worker
    ports:
      - "127.0.0.1:3030:3000"
    environment:
      <<: *langfuse-env
      NEXTAUTH_URL: http://localhost:3030
      NEXTAUTH_SECRET: ${SRE_LANGFUSE_NEXTAUTH_SECRET:-local-nextauth-secret-change-in-prod}
      LANGFUSE_INIT_ORG_ID: sre-org
      LANGFUSE_INIT_ORG_NAME: Agentic-SRE
      LANGFUSE_INIT_PROJECT_ID: sre-team
      LANGFUSE_INIT_PROJECT_NAME: agentic-sre-team
      LANGFUSE_INIT_PROJECT_PUBLIC_KEY: ${SRE_LANGFUSE_PUBLIC_KEY:-pk-lf-local}
      LANGFUSE_INIT_PROJECT_SECRET_KEY: ${SRE_LANGFUSE_SECRET_KEY:-sk-lf-local}
      LANGFUSE_INIT_USER_EMAIL: admin@sre.local
      LANGFUSE_INIT_USER_NAME: Admin
      LANGFUSE_INIT_USER_PASSWORD: ${SRE_LANGFUSE_ADMIN_PASSWORD:-admin1234}
    deploy: {resources: {limits: {memory: 1024M}}}

volumes:
  sre-pg:
  sre-ollama:
  sre-lgtm:
  sre-agw:
  sre-mm-data:
  sre-mm-config:
  sre-ch:
  sre-minio:
```

### 3.1 Shared Postgres Init Script (`agentic-sre-team/config/postgres/init-extra-dbs.sql`)
```sql
SELECT 'CREATE DATABASE mattermost OWNER sre'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mattermost')\gexec

SELECT 'CREATE DATABASE langfuse OWNER sre'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
```

---

## 4. Exact Service Configuration Blueprints

### 4.1 `agentic-sre-team/config/models.local-gpu.yaml`
```yaml
# Local RTX 3000 (6GB GDDR6 VRAM + 64GB RAM) profile.
# Uses one pinned hot GGUF chat model + native 768-dim nomic-embed-text to avoid VRAM swap thrashing.
# Gateway URL swaps cleanly between agentgateway (:4000/v1), litellm (:4000/v1), or direct ollama (:11434/v1).
tiers:
  small:
    provider: openai-compatible
    model: ${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
    base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway:4000/v1}
    api_key_env: SRE_LLM_API_KEY
    structured_output: json_schema
    timeout_s: 90
    params:
      temperature: 0.0
      max_tokens: 2048
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  medium:
    provider: openai-compatible
    model: ${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
    base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway:4000/v1}
    api_key_env: SRE_LLM_API_KEY
    structured_output: json_schema
    timeout_s: 120
    params:
      temperature: 0.1
      max_tokens: 4096
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
  frontier:
    provider: openai-compatible
    model: ${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
    base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway:4000/v1}
    api_key_env: SRE_LLM_API_KEY
    structured_output: json_schema
    timeout_s: 180
    params:
      temperature: 0.15
      max_tokens: 6144

embeddings:
  provider: openai-compatible
  model: ${SRE_LOCAL_EMBED_MODEL:-nomic-embed-text}
  dim: 768
  send_dimensions: false
  base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway:4000/v1}
  api_key_env: SRE_LLM_API_KEY

holmes:
  small: openai/${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
  medium: openai/${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}
  frontier: openai/${SRE_LOCAL_CHAT_MODEL:-qwen3:4b}

pricing: {}
```

### 4.2 `agentic-sre-team/config/models.airgap.yaml`
```yaml
# Production multi-GPU air-gapped cluster profile (llm-d + vLLM w/ XGrammar).
tiers:
  small:
    provider: openai-compatible
    model: ${SRE_AIRGAP_SMALL_MODEL:-Qwen/Qwen3.6-35B-A3B}
    base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway.ai-system.svc:4000/v1}
    api_key_env: SRE_LLM_API_KEY
    structured_output: json_schema
    timeout_s: 60
    params: {temperature: 0.0, max_tokens: 2048}
  medium:
    provider: openai-compatible
    model: ${SRE_AIRGAP_MEDIUM_MODEL:-Qwen/Qwen3.6-27B}
    base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway.ai-system.svc:4000/v1}
    api_key_env: SRE_LLM_API_KEY
    structured_output: json_schema
    timeout_s: 120
    params: {temperature: 0.1, max_tokens: 4096}
  frontier:
    provider: openai-compatible
    model: ${SRE_AIRGAP_FRONTIER_MODEL:-deepseek-ai/DeepSeek-V4}
    base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway.ai-system.svc:4000/v1}
    api_key_env: SRE_LLM_API_KEY
    structured_output: json_schema
    timeout_s: 180
    params: {temperature: 0.15, max_tokens: 8192}

embeddings:
  provider: openai-compatible
  model: ${SRE_AIRGAP_EMBED_MODEL:-Qwen/Qwen3-Embedding-4B}
  dim: 768
  send_dimensions: true
  base_url: ${SRE_LLM_GATEWAY_URL:-http://agentgateway.ai-system.svc:4000/v1}
  api_key_env: SRE_LLM_API_KEY

holmes:
  small: openai/${SRE_AIRGAP_SMALL_MODEL:-Qwen/Qwen3.6-35B-A3B}
  medium: openai/${SRE_AIRGAP_MEDIUM_MODEL:-Qwen/Qwen3.6-27B}
  frontier: openai/${SRE_AIRGAP_FRONTIER_MODEL:-deepseek-ai/DeepSeek-V4}

pricing: {}
```

### 4.3 `agentic-sre-team/config/agentgateway/config.yaml`

> **Docs-Check Requirement at Task Execution:** When starting `cr.agentgateway.dev/agentgateway:v1.7.0`, run `docker run --rm cr.agentgateway.dev/agentgateway:v1.7.0 --help` and inspect startup logs to verify exact field casing against `v1.7.0`'s schema validator before marking Wave 5 complete.

```yaml
# yaml-language-server: $schema=https://agentgateway.dev/schema/config
config:
  database:
    url: sqlite:///data/agentgateway.db

gateways:
  default:
    port: 4000
    ui:
      gateways:
        - default

llm:
  models:
    - name: "*"
      provider: openai
      base_url: "http://ollama:11434/v1"

mcp:
  port: 3000
  targets:
    - name: grafana
      mcp:
        host: "http://mcp-grafana:8000/mcp"
    - name: gitlab
      mcp:
        host: "http://mcp-gitlab:3002/mcp"
        headers:
          Authorization: "Bearer $MCP_INTERNAL_TOKEN"
  policies:
    mcpAuthorization:
      rules:
        # Hard deny any state-changing or write-like MCP tool name across all targets
        - deny: |
            mcp.tool.name.contains("create") || mcp.tool.name.contains("update") ||
            mcp.tool.name.contains("delete") || mcp.tool.name.contains("write") ||
            mcp.tool.name.contains("merge") || mcp.tool.name.contains("push") ||
            mcp.tool.name.contains("trigger") || mcp.tool.name.contains("cancel") ||
            mcp.tool.name.contains("retry") || mcp.tool.name.contains("patch") ||
            mcp.tool.name.contains("add_") || mcp.tool.name.contains("post_")
        # Explicit read-only allowlist for Grafana MCP
        - allow: |
            mcp.tool.name == "list_datasources" ||
            mcp.tool.name == "get_datasource_by_uid" ||
            mcp.tool.name == "query_prometheus" ||
            mcp.tool.name == "list_prometheus_metric_names" ||
            mcp.tool.name == "list_prometheus_label_values" ||
            mcp.tool.name == "query_loki_logs" ||
            mcp.tool.name == "list_loki_label_values" ||
            mcp.tool.name == "search_dashboards" ||
            mcp.tool.name == "get_dashboard_by_uid" ||
            mcp.tool.name == "list_alert_rules" ||
            mcp.tool.name == "get_alert_rule_by_uid"
        # Explicit read-only allowlist for GitLab MCP (gitlab.com or self-hosted)
        - allow: |
            mcp.tool.name == "get_project" ||
            mcp.tool.name == "list_commits" ||
            mcp.tool.name == "get_commit" ||
            mcp.tool.name == "get_commit_diff" ||
            mcp.tool.name == "get_file_contents" ||
            mcp.tool.name == "list_merge_requests" ||
            mcp.tool.name == "get_merge_request" ||
            mcp.tool.name == "get_merge_request_diffs" ||
            mcp.tool.name == "list_pipelines" ||
            mcp.tool.name == "get_pipeline" ||
            mcp.tool.name == "list_pipeline_jobs" ||
            mcp.tool.name == "get_pipeline_job_output" ||
            mcp.tool.name == "search_repositories"
```

### 4.4 `agentic-sre-team/config/litellm/config.yaml` (Interchangeable Gateway Parity)
```yaml
model_list:
  - model_name: "*"
    litellm_params:
      model: openai/*
      api_base: http://ollama:11434/v1
      api_key: ollama

general_settings:
  disable_spend_logs: true
litellm_settings:
  telemetry: false
  drop_params: true
```

### 4.5 `agentic-sre-team/config/holmes.local.yaml`
*(Note: Keep strict YAML block-style mappings everywhere -- HolmesGPT's `benedict` loader rejects inline `{k: v}` dicts.)*
```yaml
model: "openai/{{ env.SRE_LOCAL_CHAT_MODEL }}"

custom_skill_paths:
  - /etc/holmes/skills

toolsets:
  prometheus/metrics:
    enabled: true
    config:
      prometheus_url: "{{ env.LGTM_PROM_URL }}"
  grafana/loki:
    enabled: true
    config:
      url: "{{ env.LGTM_GRAFANA_URL }}"
      api_key: ""
  grafana/tempo:
    enabled: true
    config:
      url: "{{ env.LGTM_GRAFANA_URL }}"
      api_key: ""
      grafana_datasource_uid: "tempo"
  docker/core:
    enabled: false
  openshift/core:
    enabled: false

mcp_servers:
  sre_readonly_gateway:
    description: "CEL-filtered read-only Grafana and GitLab MCP tools via agentgateway"
    config:
      url: "{{ env.AGENTGATEWAY_MCP_URL }}"
      mode: streamable-http
```

### 4.6 `agentic-sre-team/config/keycloak/sre-realm.json`
Pre-seeded Keycloak 26 realm (`sre`) with:
- Public OIDC SPA client `sre-console` (`redirectUris: ["http://localhost:8088/*"]`, `webOrigins: ["http://localhost:8088"]`, `directAccessGrantsEnabled: true` so automated CLI/pytest integration checks can obtain real JWTs via password grant).
- Realm role `sre-approver`.
- Seeded operator user `alex.goh` / `sre-local-pass` with role `sre-approver`, plus viewer user `viewer.user` / `viewer-pass` without `sre-approver` (to verify 403 RBAC rejection).

---

## 5. Self-Contained Reference SUT (`agentic-sre-team/demo-sut/`)

Because the external macOS `~/Code/spectre` repository is not guaranteed to exist on every workstation, ship a lightweight, deterministic **Reference SUT (`demo-sut/`)** inside `agentic-sre-team/demo-sut/` (while keeping `config/environment.yaml` untouched for Spectre and existing unit tests, and loading `config/environment.local.yaml` when `--profile sut` runs):

1. **Stack (`demo-sut/`):**
   - Python 3.12 + FastAPI + `psycopg` + `prometheus-client` + `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` + background synthetic traffic generator loop (2 req/s against `/api/v1/orders` and `/api/v1/auth/verify` so baseline traffic, histograms, traces, and structured logs flow continuously into `lgtm` without external load generators!).
2. **Endpoints:**
   - `GET /healthz` -> checks `sut-db` connectivity (`200` healthy, `503` if DB down or chaos `db-disconnect` active).
   - `GET /metrics` -> Prometheus scrape endpoint (`http_requests_total{service="orders-api",route,status}`, `http_request_duration_seconds_bucket`). Also pushed via OTLP to `http://lgtm:4318`.
   - `GET /api/v1/orders` -> queries `sut-db`, logs structured JSON + OTel trace to `lgtm`.
   - `POST /internal/chaos` & `GET /internal/chaos` -> toggles deterministic failure modes:
     - `{"mode": "error-storm", "rate": 0.65}` -> returns HTTP 503 with realistic traceback `PoolTimeoutError: downstream auth-token-cache pool exhausted after upstream retry burst` logged to Loki.
     - `{"mode": "latency", "latency_ms": 1800}` -> injects 1.8s DB/lock wait + slow span in Tempo.
     - `{"mode": "off"}` -> restores healthy 200 responses immediately.
3. **Matched Local Alert Rules (`config/alerts/rules.local.yaml`):**
   - `OrdersApiHighErrorRate`: `sum(rate(http_requests_total{service="orders-api",status=~"5.."}[1m])) / clamp_min(sum(rate(http_requests_total{service="orders-api"}[1m])), 1e-9) > 0.10` (`for: 30s`, `labels: {service: "orders-api", component: "api", severity: "sev2"}`)
   - `OrdersApiHighP95Latency`: `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="orders-api"}[1m]))) > 1.0` (`for: 30s`, `labels: {service: "orders-api", component: "api", severity: "sev3"}`)
   - `SutTargetDown`: `up{job="demo-sut"} == 0` (`for: 30s`, `labels: {service: "orders-api", component: "infra", severity: "sev1"}`)
   - Provisioned with evaluation interval `10s` and webhook contact point `http://gateway:8080/api/webhooks/grafana` (HMAC-signed with `SRE_GRAFANA_WEBHOOK_SECRET`), so `python scripts/chaos.py error-storm` triggers a real Grafana alert -> HMAC webhook -> `CASE-0001` in **~40 seconds**!
