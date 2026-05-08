# OpenSRE MVP — Foundation + SUT + UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the demo backbone — a Next.js UI on S3 fetches `/posts` from a FastAPI service running on ECS-on-EC2, backed by RDS PostgreSQL with 1 000 seeded rows. No alerting, chaos, or agents yet (those land in Plans 2–4).

**Architecture:** Terraform-managed AWS Free Tier resources (VPC, RDS, ECR, ECS-on-EC2, S3) host a containerised FastAPI app + a static-exported Next.js UI. RDS lives in private subnets; the SUT EC2 sits in a public subnet with a stable EIP so the UI's baked-in `NEXT_PUBLIC_API_URL` works. Deploy is two `terraform apply` cycles bracketing image push + DB seed; SSM Session Manager port-forwards through the SUT host for seeding without ever exposing RDS publicly.

**Tech Stack:** Terraform 1.9+ with AWS provider 5.x · Python 3.12 + FastAPI + asyncpg + uv · Next.js 15 (App Router, `output: 'export'`) + Tailwind v4 + shadcn/ui · Docker · AWS CLI v2

---

## Prerequisites

Before starting, confirm the following on the operator machine:

- AWS CLI v2 configured with a profile that has admin or sufficient permissions in the target account (`aws sts get-caller-identity` works).
- Terraform `>= 1.9` (`terraform version`).
- Docker daemon running (`docker info`).
- `uv` installed (`uv --version`); if not, `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- Node `>= 20` and `npm` available (`node -v`).
- An S3-website-region of choice — default `us-east-1` per spec §8.
- An empty AWS account (or scratch account) — Free Tier 12-month window is assumed.

**Naming conventions used throughout:** project tag `opensre-demo`; resource names prefixed `opensre-demo-…`; ECS cluster `opensre-demo`; service `opensre-demo-sut`.

**Doc verification:** Tailwind v4 and shadcn/ui both shipped breaking changes in 2025. Before starting Tasks 15–17, run `find-docs` (or the `ctx7` CLI per `~/.claude/rules/context7.md`) for current install steps. Per CLAUDE.md: always check current docs before acting.

---

## File Structure

Files this plan creates:

```
open-sre-agents/
├── backend/
│   ├── pyproject.toml                  # FastAPI + asyncpg deps, pytest config
│   ├── .python-version                 # 3.12
│   ├── .dockerignore
│   ├── Dockerfile                      # multi-stage build with uv
│   ├── src/app/
│   │   ├── __init__.py
│   │   ├── settings.py                 # Pydantic Settings: DATABASE_URL, CORS_ORIGIN
│   │   ├── db.py                       # asyncpg pool init/close
│   │   └── main.py                     # FastAPI app + /health + /posts + lifespan + CORS
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                 # mock pool fixture
│       ├── test_health.py
│       └── test_posts.py
├── infra/
│   ├── versions.tf                     # terraform + provider version pins
│   ├── providers.tf                    # AWS provider config
│   ├── variables.tf                    # region, project, db_password, sut_ingress_cidr, ui_bucket_suffix, sut_desired_count
│   ├── outputs.tf                      # SUT EIP, RDS endpoint, ECR URL, S3 site URL, ECS instance ID
│   ├── network.tf                      # VPC, 2 public + 2 private subnets, IGW, RTs, SGs
│   ├── ecr.tf                          # ECR repo for backend image
│   ├── s3.tf                           # UI hosting bucket + website config + public-read policy
│   ├── rds.tf                          # subnet group, parameter group, db.t3.micro instance
│   ├── ecs.tf                          # cluster, IAM roles/profiles, EC2 host, EIP
│   ├── ecs_service.tf                  # CW log group, task def, service (desired_count via var)
│   ├── terraform.tfvars.example
│   └── .gitignore                      # *.tfstate, .terraform/
├── scripts/
│   └── seed_posts.py                   # PEP 723 inline-deps seed script (psycopg2 + faker)
├── ui/
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts                  # output: 'export'
│   ├── postcss.config.mjs
│   ├── components.json                 # shadcn/ui config
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                    # PostsTable + Refresh + Skeleton
│   │   └── globals.css                 # Tailwind v4 imports + tokens
│   ├── components/
│   │   ├── posts-table.tsx
│   │   └── ui/                         # shadcn-generated: button, table, skeleton
│   └── lib/
│       ├── api.ts                      # fetchPosts() against NEXT_PUBLIC_API_URL
│       └── utils.ts                    # cn() helper from shadcn
├── .gitignore                          # repo-level
└── README.md                           # update with Plan 1 demo runbook
```

---

## Task 1: Bootstrap backend project + `/health` endpoint (TDD)

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`
- Create: `backend/src/app/__init__.py`
- Create: `backend/src/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Create `backend/.python-version`**

```
3.12
```

- [ ] **Step 2: Create `backend/pyproject.toml`**

```toml
[project]
name = "opensre-demo-sut"
version = "0.1.0"
description = "OpenSRE demo SUT — FastAPI service backed by RDS"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "asyncpg>=0.30",
    "pydantic-settings>=2.6",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.28",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/app"]
```

- [ ] **Step 3: Create empty package files**

```
# backend/src/app/__init__.py    → empty
# backend/tests/__init__.py      → empty
```

- [ ] **Step 4: Sync deps**

Run: `cd backend && uv sync`
Expected: creates `backend/.venv/` and `backend/uv.lock`; no errors.

- [ ] **Step 5: Write the failing test for `/health`**

`backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    # TestClient without `with` skips lifespan, so DB pool init does not run.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 7: Write minimal `app/main.py`**

`backend/src/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/test_health.py -v`
Expected: 1 passed.

- [ ] **Step 9: Commit**

```bash
git add backend/.python-version backend/pyproject.toml backend/uv.lock \
        backend/src/app/__init__.py backend/src/app/main.py \
        backend/tests/__init__.py backend/tests/test_health.py
git commit -m "feat(backend): bootstrap FastAPI app with /health endpoint"
```

---

## Task 2: Settings, DB pool, and `/posts` endpoint (TDD)

**Files:**
- Create: `backend/src/app/settings.py`
- Create: `backend/src/app/db.py`
- Modify: `backend/src/app/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_posts.py`

- [ ] **Step 1: Create `app/settings.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://localhost:5432/opensre_demo"
    cors_origin: str = "*"


settings = Settings()
```

- [ ] **Step 2: Create `app/db.py`**

```python
from typing import Any

import asyncpg

# `app.state.pool` is the canonical home for the asyncpg pool.
# `get_pool` is a FastAPI dependency so tests can override it.

_pool: asyncpg.Pool | None = None


async def init_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> Any:
    if _pool is None:
        raise RuntimeError("DB pool not initialised")
    return _pool
```

- [ ] **Step 3: Update `main.py` with lifespan, `/posts`, and dependency**

Replace `backend/src/app/main.py` with:

```python
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .db import close_pool, get_pool, init_pool
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool(settings.database_url)
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/posts")
async def posts(limit: int = 50, pool=Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, author, content, likes, created_at "
            "FROM posts ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return {"posts": [dict(r) for r in rows]}
```

- [ ] **Step 4: Write the failing test for `/posts`**

`backend/tests/conftest.py`:

```python
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_pool_factory():
    """Returns a callable: rows -> mock pool whose acquire() yields a conn whose fetch() returns rows."""

    def make(rows):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=rows)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=None)

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        return pool

    return make


@pytest.fixture
def fixed_now():
    return datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
```

`backend/tests/test_posts.py`:

```python
from fastapi.testclient import TestClient

from app.db import get_pool
from app.main import app


def test_posts_returns_rows_in_envelope(mock_pool_factory, fixed_now):
    rows = [
        {"id": 1, "author": "alice", "content": "hello", "likes": 5, "created_at": fixed_now},
        {"id": 2, "author": "bob", "content": "world", "likes": 1, "created_at": fixed_now},
    ]
    app.dependency_overrides[get_pool] = lambda: mock_pool_factory(rows)
    try:
        client = TestClient(app)
        response = client.get("/posts?limit=10")
        assert response.status_code == 200
        body = response.json()
        assert list(body.keys()) == ["posts"]
        assert len(body["posts"]) == 2
        assert body["posts"][0]["author"] == "alice"
        # FastAPI's default JSON encoder serialises datetime as ISO 8601 with `+00:00`,
        # not `Z`. Match the prefix to stay tolerant of either suffix.
        assert body["posts"][0]["created_at"].startswith("2026-05-01T12:00:00")
    finally:
        app.dependency_overrides.clear()


def test_posts_default_limit_is_50(mock_pool_factory):
    captured = {}

    def make_pool(rows):
        from unittest.mock import AsyncMock, MagicMock

        conn = MagicMock()

        async def fetch(query, *args):
            captured["query"] = query
            captured["args"] = args
            return rows

        conn.fetch = fetch
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        return pool

    app.dependency_overrides[get_pool] = lambda: make_pool([])
    try:
        client = TestClient(app)
        response = client.get("/posts")
        assert response.status_code == 200
        assert captured["args"] == (50,)
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && uv run pytest -v`
Expected: 3 passed (the original `test_health` + the two new tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/app/settings.py backend/src/app/db.py backend/src/app/main.py \
        backend/tests/conftest.py backend/tests/test_posts.py backend/uv.lock
git commit -m "feat(backend): add /posts endpoint backed by asyncpg pool"
```

---

## Task 3: CORS middleware + Dockerfile

**Files:**
- Modify: `backend/src/app/main.py`
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`

- [ ] **Step 1: Add CORS test**

Append to `backend/tests/test_health.py`:

```python
def test_cors_allows_configured_origin(monkeypatch):
    # Module already imported; we reload to pick up the new env var if needed,
    # but for this smoke we just confirm the middleware echoes Access-Control-Allow-Origin.
    client = TestClient(app)
    response = client.get(
        "/health",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in {k.lower() for k in response.headers.keys()}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_health.py::test_cors_allows_configured_origin -v`
Expected: FAIL — `access-control-allow-origin` header not present.

- [ ] **Step 3: Add `CORSMiddleware` to `main.py`**

Insert near the top of `backend/src/app/main.py` after `app = FastAPI(lifespan=lifespan)`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

(Keep imports tidy — move `from fastapi.middleware.cors import CORSMiddleware` up with the other `fastapi` imports.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest -v`
Expected: 4 passed.

- [ ] **Step 5: Create `backend/.dockerignore`**

```
.venv
__pycache__
*.pyc
.pytest_cache
tests
.python-version
```

- [ ] **Step 6: Create `backend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build

# Install uv from its official image — pin a known-good release.
COPY --from=ghcr.io/astral-sh/uv:0.5.7 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 7: Build the image locally to verify the Dockerfile**

Run: `cd backend && docker build -t opensre-demo-sut:dev .`
Expected: build completes; output ends with `naming to docker.io/library/opensre-demo-sut:dev`.

- [ ] **Step 8: Smoke-run the container (no DB; expect /health 200, /posts 500)**

Run:
```bash
docker run --rm -d --name sut-smoke -p 8080:8080 \
  -e DATABASE_URL=postgresql://nonexistent:5432/x opensre-demo-sut:dev
sleep 3
curl -fsS http://localhost:8080/health
docker stop sut-smoke
```
Expected: lifespan logs DB connect failure (expected — there's no DB), but the server stays up; `curl` to `/health` returns `{"status":"ok"}`.

> If the container exits because lifespan raises before serving, that's a hint to make pool init non-fatal. For Plan 1 we accept lifespan failure here and validate properly post-deploy. Skip this step if the container won't stay up.

- [ ] **Step 9: Commit**

```bash
git add backend/src/app/main.py backend/tests/test_health.py \
        backend/Dockerfile backend/.dockerignore
git commit -m "feat(backend): add CORS middleware and Dockerfile"
```

---

## Task 4: Seed script (PEP 723 inline-deps Python)

**Files:**
- Create: `scripts/seed_posts.py`

- [ ] **Step 1: Write `scripts/seed_posts.py`**

```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "psycopg2-binary>=2.9",
#   "faker>=30",
# ]
# ///
"""Seed the demo `posts` table with 1 000 rows. Idempotent: skips if >= 1 000 rows exist.

Run via SSM Session Manager port-forward (see Task 13):
    SEED_DATABASE_URL='postgresql://opensre:<pw>@localhost:5432/opensre_demo' \
        uv run scripts/seed_posts.py
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
from faker import Faker

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS posts (
    id           SERIAL PRIMARY KEY,
    author       TEXT NOT NULL,
    content      TEXT NOT NULL,
    likes        INT  NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS posts_created_at_idx ON posts (created_at DESC);
"""

ROW_COUNT = 1_000


def main() -> int:
    dsn = os.environ.get("SEED_DATABASE_URL")
    if not dsn:
        print("SEED_DATABASE_URL not set", file=sys.stderr)
        return 2

    fake = Faker()
    Faker.seed(42)
    random.seed(42)

    with psycopg2.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute("SELECT count(*) FROM posts;")
            existing = cur.fetchone()[0]
            if existing >= ROW_COUNT:
                print(f"posts already has {existing} rows — skipping seed.")
                conn.commit()
                return 0

            now = datetime.now(timezone.utc)
            rows = [
                (
                    fake.user_name(),
                    fake.text(max_nb_chars=200),
                    random.randint(0, 500),
                    now - timedelta(seconds=random.randint(0, 30 * 86_400)),
                )
                for _ in range(ROW_COUNT - existing)
            ]
            cur.executemany(
                "INSERT INTO posts (author, content, likes, created_at) VALUES (%s, %s, %s, %s)",
                rows,
            )
        conn.commit()
    print(f"Seeded {ROW_COUNT - existing} posts (table now has {ROW_COUNT}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-run against a local docker postgres (optional)**

If docker is available and convenient, run:
```bash
docker run --rm -d --name pgseed -e POSTGRES_PASSWORD=demo \
  -e POSTGRES_DB=opensre_demo -p 5432:5432 postgres:16
sleep 5
SEED_DATABASE_URL='postgresql://postgres:demo@localhost:5432/opensre_demo' \
  uv run scripts/seed_posts.py
SEED_DATABASE_URL='postgresql://postgres:demo@localhost:5432/opensre_demo' \
  uv run scripts/seed_posts.py   # idempotency check
docker stop pgseed
```
Expected first run: `Seeded 1000 posts (table now has 1000).`
Expected second run: `posts already has 1000 rows — skipping seed.`

If docker isn't convenient, defer this validation to Task 13 (real RDS).

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_posts.py
git commit -m "feat(scripts): add idempotent seed_posts.py"
```

---

## Task 5: Terraform skeleton (versions, providers, variables, outputs)

**Files:**
- Create: `infra/versions.tf`
- Create: `infra/providers.tf`
- Create: `infra/variables.tf`
- Create: `infra/outputs.tf`
- Create: `infra/terraform.tfvars.example`
- Create: `infra/.gitignore`
- Create: `.gitignore` (repo-root)

- [ ] **Step 1: Repo-root `.gitignore`**

```
# Python
__pycache__/
*.pyc
.venv/
backend/.venv/

# Node / Next.js
ui/node_modules/
ui/.next/
ui/out/

# Terraform
infra/.terraform/
infra/.terraform.lock.hcl
infra/*.tfstate
infra/*.tfstate.*
infra/terraform.tfvars
infra/.terraform.tfstate.lock.info

# OS
.DS_Store
```

- [ ] **Step 2: `infra/.gitignore`**

```
.terraform/
*.tfstate
*.tfstate.*
terraform.tfvars
.terraform.lock.hcl
```

- [ ] **Step 3: `infra/versions.tf`**

```hcl
terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
```

- [ ] **Step 4: `infra/providers.tf`**

```hcl
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}
```

- [ ] **Step 5: `infra/variables.tf`**

```hcl
variable "region" {
  description = "AWS region. us-east-1 default per spec §8."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project tag and resource-name prefix."
  type        = string
  default     = "opensre-demo"
}

variable "db_password" {
  description = "RDS master password. Provide via TF_VAR_db_password or terraform.tfvars."
  type        = string
  sensitive   = true
}

variable "sut_ingress_cidr" {
  description = "CIDR allowed to hit the SUT EC2 on port 8080. Default 0.0.0.0/0 for demo; tighten to operator IP for safety."
  type        = string
  default     = "0.0.0.0/0"
}

variable "ui_bucket_suffix" {
  description = "Random suffix appended to the UI bucket name to avoid global collisions."
  type        = string
}

variable "sut_desired_count" {
  description = "ECS service desired count. Set to 0 for the first apply (no image yet); flip to 1 once the image is pushed."
  type        = number
  default     = 0
}
```

- [ ] **Step 6: `infra/outputs.tf`**

```hcl
output "sut_public_ip" {
  description = "Stable EIP attached to the SUT EC2 host."
  value       = aws_eip.sut.public_ip
}

output "sut_api_url" {
  description = "Backend base URL for the UI's NEXT_PUBLIC_API_URL."
  value       = "http://${aws_eip.sut.public_ip}:8080"
}

output "sut_instance_id" {
  description = "EC2 instance ID — pass to `aws ssm start-session` for port-forwarding."
  value       = aws_instance.sut.id
}

output "rds_endpoint" {
  description = "RDS endpoint host:port."
  value       = aws_db_instance.demo.endpoint
}

output "rds_address" {
  description = "RDS endpoint host (no port)."
  value       = aws_db_instance.demo.address
}

output "ecr_repository_url" {
  description = "Push backend images here."
  value       = aws_ecr_repository.sut.repository_url
}

output "ui_bucket" {
  description = "Sync the Next.js export here."
  value       = aws_s3_bucket.ui.bucket
}

output "ui_website_url" {
  description = "Public S3 website URL."
  value       = "http://${aws_s3_bucket_website_configuration.ui.website_endpoint}"
}
```

- [ ] **Step 7: `infra/terraform.tfvars.example`**

```hcl
region            = "us-east-1"
project           = "opensre-demo"
db_password       = "REPLACE_ME_LONG_RANDOM"
sut_ingress_cidr  = "0.0.0.0/0"   # tighten to your home IP for safety
ui_bucket_suffix  = "abc123def"   # 6+ random alphanumeric chars
sut_desired_count = 0             # flip to 1 after image push
```

- [ ] **Step 8: Initialise**

Run: `cd infra && terraform init`
Expected: `Terraform has been successfully initialized!`

> `terraform validate` will fail until the resources referenced by `outputs.tf` exist. That's fine — the next tasks add them.

- [ ] **Step 9: Commit**

```bash
git add .gitignore infra/.gitignore infra/versions.tf infra/providers.tf \
        infra/variables.tf infra/outputs.tf infra/terraform.tfvars.example
git commit -m "feat(infra): scaffold terraform project (providers, variables, outputs)"
```

---

## Task 6: Network (VPC, subnets, IGW, RTs, security groups)

**Files:**
- Create: `infra/network.tf`

- [ ] **Step 1: Write `infra/network.tf`**

```hcl
# Two AZs because RDS subnet groups require multi-AZ even in single-AZ instance mode.
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  az_a = data.aws_availability_zones.available.names[0]
  az_b = data.aws_availability_zones.available.names[1]
}

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.project}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.1.0/24"
  availability_zone       = local.az_a
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.project}-public-a" }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.2.0/24"
  availability_zone       = local.az_b
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.project}-public-b" }
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.11.0/24"
  availability_zone = local.az_a
  tags              = { Name = "${var.project}-private-a" }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.12.0/24"
  availability_zone = local.az_b
  tags              = { Name = "${var.project}-private-b" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project}-public-rt" }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# Private subnets get a route table with no internet route. RDS doesn't need outbound;
# no NAT Gateway by design (spec §4 cost note).
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-private-rt" }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# --- Security groups ---

resource "aws_security_group" "sut_host" {
  name        = "${var.project}-sut-host"
  description = "SUT EC2 host: 8080 from operator CIDR; egress all"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "FastAPI from operator/UI"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.sut_ingress_cidr]
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-sut-host" }
}

resource "aws_security_group" "rds" {
  name        = "${var.project}-rds"
  description = "RDS: 5432 from SUT host SG only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from SUT host"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.sut_host.id]
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-rds" }
}
```

- [ ] **Step 2: Format and validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.` (validate may still fail because `aws_eip.sut`, `aws_instance.sut`, etc. referenced in outputs are not yet defined — that's expected; subsequent tasks add them. If validate fails on those lines specifically, proceed.)

- [ ] **Step 3: Commit**

```bash
git add infra/network.tf
git commit -m "feat(infra): add VPC, subnets, IGW, route tables, and security groups"
```

---

## Task 7: ECR repo + S3 UI bucket

**Files:**
- Create: `infra/ecr.tf`
- Create: `infra/s3.tf`

- [ ] **Step 1: `infra/ecr.tf`**

```hcl
resource "aws_ecr_repository" "sut" {
  name                 = "${var.project}-sut"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true   # demo: allow `terraform destroy` to wipe images.
}
```

- [ ] **Step 2: `infra/s3.tf`**

```hcl
resource "aws_s3_bucket" "ui" {
  bucket        = "${var.project}-ui-${var.ui_bucket_suffix}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket = aws_s3_bucket.ui.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

# Public-read bucket policy. Public website hosting requires either CloudFront
# (out of scope) or a public bucket policy.
data "aws_iam_policy_document" "ui_public_read" {
  statement {
    sid    = "PublicReadGetObject"
    effect = "Allow"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ui.arn}/*"]
  }
}

resource "aws_s3_bucket_policy" "ui" {
  bucket = aws_s3_bucket.ui.id
  policy = data.aws_iam_policy_document.ui_public_read.json

  depends_on = [aws_s3_bucket_public_access_block.ui]
}
```

- [ ] **Step 3: Format and validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: still references undefined `aws_instance.sut` etc. — OK, subsequent tasks add them.

- [ ] **Step 4: Commit**

```bash
git add infra/ecr.tf infra/s3.tf
git commit -m "feat(infra): add ECR repo and public-read S3 UI bucket"
```

---

## Task 8: RDS PostgreSQL

**Files:**
- Create: `infra/rds.tf`

- [ ] **Step 1: Write `infra/rds.tf`**

```hcl
resource "aws_db_subnet_group" "demo" {
  name        = "${var.project}-db-subnet-group"
  description = "Private subnets for the demo RDS instance"
  subnet_ids  = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = { Name = "${var.project}-db-subnet-group" }
}

resource "aws_db_parameter_group" "demo" {
  name        = "${var.project}-pg16"
  family      = "postgres16"
  description = "Postgres 16 default parameters for the demo"
}

resource "aws_db_instance" "demo" {
  identifier              = "${var.project}-db"
  engine                  = "postgres"
  engine_version          = "16.4"
  instance_class          = "db.t3.micro"
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = "opensre_demo"
  username                = "opensre"
  password                = var.db_password
  port                    = 5432
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 0
  skip_final_snapshot     = true

  db_subnet_group_name   = aws_db_subnet_group.demo.name
  parameter_group_name   = aws_db_parameter_group.demo.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  apply_immediately = true

  tags = { Name = "${var.project}-db" }
}
```

- [ ] **Step 2: Format and validate**

Run: `cd infra && terraform fmt && terraform validate`

Confirm via `find-docs`/`ctx7` that `engine_version = "16.4"` is still a supported `db.t3.micro` minor at apply time. If not, bump to a current 16.x minor in the AWS docs. Per CLAUDE.md.

- [ ] **Step 3: Commit**

```bash
git add infra/rds.tf
git commit -m "feat(infra): add RDS PostgreSQL db.t3.micro in private subnets"
```

---

## Task 9: ECS cluster + IAM + EC2 host with EIP

**Files:**
- Create: `infra/ecs.tf`

- [ ] **Step 1: Write `infra/ecs.tf`**

```hcl
# --- Cluster ---

resource "aws_ecs_cluster" "demo" {
  name = var.project
}

# --- IAM: ECS task execution role (pulls image from ECR, ships logs) ---

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${var.project}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- IAM: SUT EC2 instance role (joins ECS, ships logs, SSM-managed for port-forward) ---

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sut_host" {
  name               = "${var.project}-sut-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "sut_host_ecs" {
  role       = aws_iam_role.sut_host.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "sut_host_ssm" {
  role       = aws_iam_role.sut_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "sut_host" {
  name = "${var.project}-sut-host"
  role = aws_iam_role.sut_host.name
}

# --- ECS-optimised AMI lookup ---

data "aws_ssm_parameter" "ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

# --- SUT EC2 host (registers itself to the ECS cluster) ---

resource "aws_eip" "sut" {
  domain = "vpc"
  tags   = { Name = "${var.project}-sut-eip" }
}

resource "aws_instance" "sut" {
  ami                    = data.aws_ssm_parameter.ecs_ami.value
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.public_a.id
  vpc_security_group_ids = [aws_security_group.sut_host.id]
  iam_instance_profile   = aws_iam_instance_profile.sut_host.name

  user_data = <<-EOT
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.demo.name}" >> /etc/ecs/ecs.config
    echo "ECS_AVAILABLE_LOGGING_DRIVERS=[\"json-file\",\"awslogs\"]" >> /etc/ecs/ecs.config
  EOT

  tags = {
    Name    = "${var.project}-sut-host"
    Project = var.project
  }
}

resource "aws_eip_association" "sut" {
  instance_id   = aws_instance.sut.id
  allocation_id = aws_eip.sut.id
}
```

- [ ] **Step 2: Format and validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: success (all referenced resources now exist; the `aws_ecs_service` referenced indirectly via `sut_desired_count` is added in the next task — `validate` may pass anyway since no other resource references the service yet).

- [ ] **Step 3: Commit**

```bash
git add infra/ecs.tf
git commit -m "feat(infra): add ECS cluster, IAM roles, SUT EC2 host with EIP"
```

---

## Task 10: ECS task definition + service + log group

**Files:**
- Create: `infra/ecs_service.tf`

- [ ] **Step 1: Write `infra/ecs_service.tf`**

```hcl
resource "aws_cloudwatch_log_group" "sut" {
  name              = "/ecs/${var.project}-sut"
  retention_in_days = 7
}

locals {
  sut_image = "${aws_ecr_repository.sut.repository_url}:latest"

  sut_database_url = "postgresql://opensre:${var.db_password}@${aws_db_instance.demo.address}:5432/opensre_demo"
  ui_origin        = "http://${aws_s3_bucket_website_configuration.ui.website_endpoint}"
}

resource "aws_ecs_task_definition" "sut" {
  family             = "${var.project}-sut"
  network_mode       = "bridge"
  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  cpu                = "256"
  memory             = "256"

  container_definitions = jsonencode([
    {
      name      = "sut"
      image     = local.sut_image
      essential = true
      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "DATABASE_URL", value = local.sut_database_url },
        { name = "CORS_ORIGIN", value = local.ui_origin },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.sut.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "sut"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "sut" {
  name            = "${var.project}-sut"
  cluster         = aws_ecs_cluster.demo.id
  task_definition = aws_ecs_task_definition.sut.arn
  desired_count   = var.sut_desired_count
  launch_type     = "EC2"

  # Allow Terraform to roll the deployment on task-definition or env changes.
  force_new_deployment = true

  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  # The SUT EC2 must be registered to the cluster before this service tries to place tasks.
  depends_on = [aws_instance.sut]
}
```

- [ ] **Step 2: Format and validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/ecs_service.tf
git commit -m "feat(infra): add CloudWatch log group, ECS task def, and service"
```

---

## Task 11: First terraform apply

**Goal:** Provision all infra. ECS service starts at `desired_count = 0`, so the missing image isn't a problem yet.

- [ ] **Step 1: Choose and write `terraform.tfvars`**

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set db_password to a long random string, set ui_bucket_suffix
# (e.g. `openssl rand -hex 4`), keep sut_desired_count = 0.
```

- [ ] **Step 2: Plan**

Run: `cd infra && terraform plan -out=plan-1.tfplan`
Expected: ~30+ resources to add. Skim for surprises (no destroys, no replacements). Note RDS creation takes ~5 min on apply.

- [ ] **Step 3: Apply**

Run: `cd infra && terraform apply plan-1.tfplan`
Expected: ~6–10 minutes. Final outputs show `sut_public_ip`, `rds_endpoint`, `ecr_repository_url`, `ui_bucket`, `ui_website_url`, `sut_instance_id`.

- [ ] **Step 4: Capture outputs into shell**

```bash
cd infra
# Region isn't a Terraform output; read it from tfvars (or default).
export AWS_REGION=$(grep -E '^region' terraform.tfvars 2>/dev/null | sed -E 's/.*= *"(.*)"/\1/' || true)
export AWS_REGION=${AWS_REGION:-us-east-1}
export ECR_URL=$(terraform output -raw ecr_repository_url)
export SUT_IP=$(terraform output -raw sut_public_ip)
export SUT_INSTANCE=$(terraform output -raw sut_instance_id)
export RDS_HOST=$(terraform output -raw rds_address)
export UI_BUCKET=$(terraform output -raw ui_bucket)
export UI_URL=$(terraform output -raw ui_website_url)
export API_URL=$(terraform output -raw sut_api_url)
echo "ECR=$ECR_URL  SUT=$SUT_IP  INSTANCE=$SUT_INSTANCE  RDS=$RDS_HOST  UI=$UI_URL  API=$API_URL"
```

- [ ] **Step 5: Verify the SUT EC2 has joined the ECS cluster**

Run:
```bash
aws ecs list-container-instances --cluster opensre-demo --region "$AWS_REGION"
aws ecs describe-container-instances \
  --cluster opensre-demo \
  --container-instances $(aws ecs list-container-instances --cluster opensre-demo --region "$AWS_REGION" --query 'containerInstanceArns[0]' --output text) \
  --region "$AWS_REGION" \
  --query 'containerInstances[0].{status:status,agentConnected:agentConnected,runningTasks:runningTasksCount}'
```
Expected: one container instance, `status: ACTIVE`, `agentConnected: true`, `runningTasks: 0`. If empty, wait 60s — the EC2 needs ECS agent boot time — and retry.

- [ ] **Step 6: Commit (no code change, but record the apply checkpoint)**

```bash
# Nothing to commit; this is a manual verification step. Move on.
```

---

## Task 12: Build and push the backend Docker image

- [ ] **Step 1: Authenticate Docker against ECR**

Run:
```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"
```
Expected: `Login Succeeded`.

- [ ] **Step 2: Build for linux/amd64 (the EC2 host is x86_64)**

Run:
```bash
cd backend
docker buildx build --platform linux/amd64 -t "$ECR_URL:latest" --load .
```
Expected: build completes; final layer pushed to local Docker.

> If `buildx` isn't set up, run `docker buildx create --name ci --use` first.

- [ ] **Step 3: Push**

Run: `docker push "$ECR_URL:latest"`
Expected: layers upload; final digest printed.

- [ ] **Step 4: Verify**

Run: `aws ecr list-images --repository-name opensre-demo-sut --region "$AWS_REGION"`
Expected: at least one image with tag `latest`.

- [ ] **Step 5: Commit (none needed)**

No code changes. Move on.

---

## Task 13: Seed RDS via SSM Session Manager port-forward

- [ ] **Step 1: Confirm SSM Session Manager plugin is installed locally**

Run: `session-manager-plugin --version`
Expected: a version string. If missing, install per AWS docs (check via `find-docs aws-cli "Install Session Manager plugin"`).

- [ ] **Step 2: Start the port-forward in the background**

Run:
```bash
aws ssm start-session \
  --target "$SUT_INSTANCE" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$RDS_HOST\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"15432\"]}" \
  --region "$AWS_REGION" &
SSM_PID=$!
sleep 5
```
Expected: `Waiting for connections...` then `Connection accepted` once a client connects. Local port `15432` forwards to RDS port `5432` via the SUT EC2.

> Why 15432 not 5432? Avoids conflict with any local Postgres.

- [ ] **Step 3: Run the seed script**

Run:
```bash
DB_PASSWORD=$(grep '^db_password' infra/terraform.tfvars | sed -E 's/.*= *"(.*)"/\1/')
SEED_DATABASE_URL="postgresql://opensre:${DB_PASSWORD}@localhost:15432/opensre_demo" \
  uv run scripts/seed_posts.py
```
Expected: `Seeded 1000 posts (table now has 1000).`

- [ ] **Step 4: Re-run for idempotency**

Run: same command as Step 3.
Expected: `posts already has 1000 rows — skipping seed.`

- [ ] **Step 5: Stop the port-forward**

Run: `kill $SSM_PID 2>/dev/null; wait $SSM_PID 2>/dev/null; true`

- [ ] **Step 6: Commit (none needed)**

No code changes. Move on.

---

## Task 14: Scale ECS service to 1 and verify backend reachability

- [ ] **Step 1: Update tfvars and re-apply**

Edit `infra/terraform.tfvars`: change `sut_desired_count = 0` → `sut_desired_count = 1`.

Run:
```bash
cd infra
terraform apply -auto-approve
```
Expected: `Plan: 0 to add, 1 to change, 0 to destroy.` Service updates.

- [ ] **Step 2: Wait for the task to be RUNNING**

Run:
```bash
for i in {1..30}; do
  STATUS=$(aws ecs describe-services --cluster opensre-demo --services opensre-demo-sut \
            --region "$AWS_REGION" \
            --query 'services[0].deployments[0].{rolloutState:rolloutState,running:runningCount,desired:desiredCount}' \
            --output json)
  echo "$STATUS"
  echo "$STATUS" | grep -q '"rolloutState": "COMPLETED"' && break
  sleep 10
done
```
Expected: `rolloutState: COMPLETED`, `running: 1`, `desired: 1` within ~3 minutes.

- [ ] **Step 3: Curl `/health`**

Run: `curl -fsS "$API_URL/health"`
Expected: `{"status":"ok"}`.

- [ ] **Step 4: Curl `/posts?limit=3`**

Run: `curl -fsS "$API_URL/posts?limit=3" | jq '.posts | length'`
Expected: `3`.

- [ ] **Step 5: Curl `/posts` and inspect a row**

Run: `curl -fsS "$API_URL/posts?limit=1" | jq '.posts[0]'`
Expected: an object with `id`, `author`, `content`, `likes`, `created_at`.

- [ ] **Step 6: Commit (only the tfvars bump if you want to record it; otherwise skip — tfvars is gitignored)**

Skip — `terraform.tfvars` is gitignored.

---

## Task 15: UI scaffold — Next.js 15 + Tailwind v4 + shadcn/ui

> **Doc check (per CLAUDE.md):** Before this task, run `find-docs Next.js "static export with output: export"` and `find-docs shadcn/ui "init Next.js Tailwind v4"`. The exact CLI flags below were correct as of late 2025; verify them.

**Files (high level — generators create most of these):**
- Create: `ui/` tree via `create-next-app` and `shadcn` CLI
- Modify: `ui/next.config.ts`, `ui/app/globals.css`, `ui/app/page.tsx`, `ui/app/layout.tsx`
- Create: `ui/lib/api.ts`

- [ ] **Step 1: Generate the Next.js project**

Run from repo root (answer "No" to any prompts not covered by the flags below — defaults are fine):
```bash
npx create-next-app@latest ui \
  --ts \
  --app \
  --tailwind \
  --eslint \
  --import-alias="@/*" \
  --use-npm \
  --skip-install \
  --yes
cd ui && npm install
```
Expected: `ui/` populated with App Router scaffold; Tailwind v4 set up. If `--yes` isn't recognised by the installed `create-next-app` version, drop it and accept defaults at the prompts.

- [ ] **Step 2: Set static export in `ui/next.config.ts`**

Replace `ui/next.config.ts` with:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
```

- [ ] **Step 3: Install shadcn/ui**

Run: `cd ui && npx shadcn@latest init`
Choose defaults; when prompted for the base colour pick `Slate`. Confirm `components.json` is written.

- [ ] **Step 4: Add the shadcn primitives we need**

Run: `cd ui && npx shadcn@latest add table button skeleton`
Expected: `ui/components/ui/{table.tsx,button.tsx,skeleton.tsx}` and `ui/lib/utils.ts` exist.

- [ ] **Step 5: Smoke-build to confirm the scaffold compiles**

Run: `cd ui && npm run build`
Expected: build completes; `ui/out/` is created.

- [ ] **Step 6: Commit**

```bash
git add ui/
git commit -m "feat(ui): scaffold Next.js 15 with Tailwind v4 and shadcn/ui"
```

---

## Task 16: API client + PostsTable component + page assembly

**Files:**
- Create: `ui/lib/api.ts`
- Create: `ui/components/posts-table.tsx`
- Modify: `ui/app/page.tsx`
- Modify: `ui/app/layout.tsx`

- [ ] **Step 1: API client `ui/lib/api.ts`**

```ts
export type Post = {
  id: number;
  author: string;
  content: string;
  likes: number;
  created_at: string;
};

export type PostsResponse = { posts: Post[] };

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function fetchPosts(limit = 50): Promise<Post[]> {
  if (!API_BASE) throw new Error("NEXT_PUBLIC_API_URL is not set at build time.");
  const res = await fetch(`${API_BASE}/posts?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetch /posts failed: ${res.status}`);
  const body = (await res.json()) as PostsResponse;
  return body.posts;
}
```

- [ ] **Step 2: PostsTable component `ui/components/posts-table.tsx`**

```tsx
"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Post } from "@/lib/api";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function PostsTable({ posts }: { posts: Post[] }) {
  if (posts.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">No posts yet.</p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">ID</TableHead>
          <TableHead className="w-40">Author</TableHead>
          <TableHead>Content</TableHead>
          <TableHead className="w-20 text-right">Likes</TableHead>
          <TableHead className="w-48">Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {posts.map((p) => (
          <TableRow key={p.id}>
            <TableCell>{p.id}</TableCell>
            <TableCell>{p.author}</TableCell>
            <TableCell className="max-w-xl truncate">{p.content}</TableCell>
            <TableCell className="text-right">{p.likes}</TableCell>
            <TableCell>{formatDate(p.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 3: Page `ui/app/page.tsx`**

Replace the file with:

```tsx
"use client";

import { useEffect, useState, useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PostsTable } from "@/components/posts-table";
import { fetchPosts, type Post } from "@/lib/api";

export default function HomePage() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await fetchPosts(50);
      setPosts(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">OpenSRE Demo · Posts</h1>
          <p className="text-sm text-muted-foreground">
            Live data from the SUT (FastAPI on ECS-on-EC2 · RDS Postgres)
          </p>
        </div>
        <Button onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </Button>
      </header>

      {error && (
        <div className="rounded border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          Failed to load posts: {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : (
        <PostsTable posts={posts} />
      )}
    </main>
  );
}
```

- [ ] **Step 4: Layout `ui/app/layout.tsx`** — keep generated content, just confirm metadata title

Update `ui/app/layout.tsx` so `metadata.title` reads:

```ts
export const metadata: Metadata = {
  title: "OpenSRE Demo",
  description: "Posts table demo backed by FastAPI on ECS-on-EC2",
};
```

- [ ] **Step 5: Local dev smoke (optional but recommended)**

Run:
```bash
cd ui
NEXT_PUBLIC_API_URL="$API_URL" npm run dev
# In another shell, open http://localhost:3000
# Confirm the table renders with rows from RDS.
# Ctrl-C when done.
```
Expected: posts visible in browser.

- [ ] **Step 6: Build for export**

Run: `cd ui && NEXT_PUBLIC_API_URL="$API_URL" npm run build`
Expected: `ui/out/` populated; `out/index.html` exists.

- [ ] **Step 7: Commit**

```bash
git add ui/lib/api.ts ui/components/posts-table.tsx ui/app/page.tsx ui/app/layout.tsx
git commit -m "feat(ui): add posts table page with refresh and skeleton states"
```

---

## Task 17: Deploy UI to S3 and end-to-end verification

**Files:**
- Create: `scripts/deploy_ui.sh`
- Modify: `README.md`

- [ ] **Step 1: Write `scripts/deploy_ui.sh`**

```bash
#!/usr/bin/env bash
# Build the Next.js export and sync it to the S3 UI bucket.
# Reads outputs from terraform; pass --skip-build to deploy an existing ./ui/out.

set -euo pipefail

cd "$(dirname "$0")/.."

SKIP_BUILD=0
if [[ "${1:-}" == "--skip-build" ]]; then SKIP_BUILD=1; fi

API_URL=$(cd infra && terraform output -raw sut_api_url)
UI_BUCKET=$(cd infra && terraform output -raw ui_bucket)
UI_URL=$(cd infra && terraform output -raw ui_website_url)

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  cd ui
  NEXT_PUBLIC_API_URL="$API_URL" npm run build
  cd ..
fi

aws s3 sync ui/out/ "s3://${UI_BUCKET}/" --delete

echo
echo "API : $API_URL"
echo "UI  : $UI_URL"
```

- [ ] **Step 2: Make it executable and run it**

Run:
```bash
chmod +x scripts/deploy_ui.sh
./scripts/deploy_ui.sh
```
Expected: build runs, `aws s3 sync` reports uploads, prints API + UI URLs.

- [ ] **Step 3: Open the UI URL in a browser**

Run: `open "$UI_URL"` (macOS) or `xdg-open` (Linux).
Expected:
- Page loads with the title "OpenSRE Demo · Posts".
- Skeleton flashes briefly.
- Table renders 50 rows from RDS.
- "Refresh" button re-fetches.

- [ ] **Step 4: Browser-verify CORS**

Open the browser devtools Network tab → reload the page. Confirm the request to `${API_URL}/posts?limit=50` succeeds (status 200) with `access-control-allow-origin` echoing the S3 website origin.

- [ ] **Step 5: Update `README.md` with the demo runbook**

Replace `README.md` with (creating it if absent):

```markdown
# OpenSRE MVP

A demo that proves the loop: chaos event → CloudWatch alarm → OpenSRE investigates → RCA in Slack.

This branch ships **Plan 1 only** — the demo backbone (UI + SUT + RDS). Plans 2–4 add the OpenSRE host, alert pipeline, and FIS chaos.

## Plan 1 quick start

```bash
# 0. Prereqs: AWS CLI v2, Terraform 1.9+, Docker, uv, Node 20+, session-manager-plugin

# 1. Configure infra/terraform.tfvars (copy from .example, set db_password and ui_bucket_suffix)

# 2. Provision (with sut_desired_count = 0 for the first apply)
cd infra && terraform init && terraform apply

# 3. Build & push the backend image
export ECR_URL=$(terraform output -raw ecr_repository_url)
export AWS_REGION=$(grep -E '^region' terraform.tfvars 2>/dev/null | sed -E 's/.*= *"(.*)"/\1/' || echo us-east-1)
export AWS_REGION=${AWS_REGION:-us-east-1}
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${ECR_URL%/*}"
cd ../backend && docker buildx build --platform linux/amd64 -t "$ECR_URL:latest" --load .
docker push "$ECR_URL:latest"

# 4. Seed RDS via SSM port-forward
cd ../infra
SUT=$(terraform output -raw sut_instance_id)
RDS=$(terraform output -raw rds_address)
aws ssm start-session --target "$SUT" --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$RDS\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"15432\"]}" &
sleep 5
DB_PASSWORD=$(grep '^db_password' terraform.tfvars | sed -E 's/.*= *"(.*)"/\1/')
SEED_DATABASE_URL="postgresql://opensre:${DB_PASSWORD}@localhost:15432/opensre_demo" \
  uv run ../scripts/seed_posts.py
kill %1

# 5. Scale ECS to 1 and deploy the UI
sed -i.bak 's/sut_desired_count = 0/sut_desired_count = 1/' terraform.tfvars
terraform apply -auto-approve
cd .. && ./scripts/deploy_ui.sh
```

Open the printed UI URL.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_ui.sh README.md
git commit -m "feat: add UI deploy script and Plan 1 quickstart README"
```

---

## Final validation checklist

Run through these end-to-end before declaring Plan 1 done:

- [ ] `terraform plan` shows no drift (run from `infra/`).
- [ ] `cd backend && uv run pytest -v` → 4 passed.
- [ ] `curl -fsS "$API_URL/health"` → `{"status":"ok"}`.
- [ ] `curl -fsS "$API_URL/posts?limit=1" | jq '.posts | length'` → `1`.
- [ ] Browser `$UI_URL` → table shows ≥50 rows; Refresh button re-fetches.
- [ ] CloudWatch log group `/ecs/opensre-demo-sut` contains app logs.
- [ ] RDS is **not** publicly reachable: `nc -zv "$RDS_HOST" 5432` from outside the VPC fails (timeout).
- [ ] `git status` clean.

Once all green, Plan 1 is complete and Plan 2 (OpenSRE host + Slack) can begin.

---

## Teardown (when done with the demo cadence)

To stop incurring (small) charges:

```bash
cd infra && terraform destroy
```
Confirm with `yes`. RDS deletion takes ~5 min.

---

*End of Plan 1.*
