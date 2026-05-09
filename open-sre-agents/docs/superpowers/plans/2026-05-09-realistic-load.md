# OpenSRE MVP — Plan 4: Realistic-Load Preparation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Prepare the SUT and the OpenSRE host so Plan 5's `cpu-load-burst` FIS template can drive realistic, multi-endpoint REST traffic that produces access-log evidence the agent can correlate with CPU saturation. End state: from the OpenSRE host, `python3 /opt/opensre/load_runner.py http://<sut-eip>:8080 --duration 60 --ramp 10 --max-vus 50` causes the SUT's `/ecs/opensre-demo-sut` log group to fill with varied-IP, mixed-endpoint Uvicorn access entries and ECS service `CPUUtilization` to climb past 80%.

**Architecture:** Three additive layers on top of Plans 1–3. (1) **SUT API expansion** — four new FastAPI endpoints (`/posts/{id}`, `/posts/search`, `/users/{username}/posts`, `POST /posts/{id}/like`) plus Uvicorn `--proxy-headers --forwarded-allow-ips='*'` so external `X-Forwarded-For` headers populate the access log's source-IP field. (2) **DB-side preparation** — bump the seed to 10 000 rows from a fixed 50-username pool, add `posts_author_idx`, leave `content` deliberately un-indexed so `/posts/search` is CPU-bound under concurrency. (3) **Load tooling on the OpenSRE host** — `scripts/load_runner.py` (httpx + asyncio, weighted-endpoint mixed traffic with a fake-IP pool) installed at `/opt/opensre/load_runner.py` via user_data, with Python 3 + httpx pre-installed.

**Tech Stack:** Python 3.12 · FastAPI · asyncpg · httpx · uv · pytest · psycopg2 · Docker · Terraform 1.9+ AWS provider 5.x · AWS SSM RunCommand · CloudWatch Logs

---

## Prerequisites

- **Plans 1, 2, 3 fully applied** with `opensre_host_enabled = true` and Plan 3's smoke tests passing. Confirm:

```bash
cd infra
terraform output sut_api_url                # http://<eip>:8080
terraform output sut_instance_id             # i-...  (used for SSM port-forward seeding)
terraform output opensre_host_instance_id    # i-...  (must be non-null)
terraform output ingest_alarm_function_name  # opensre-demo-ingest-alarm
```

If `opensre_host_instance_id` is `null`, flip `opensre_host_enabled = true` in `terraform.tfvars` and `terraform apply` first.

- **Local toolchain:** `uv ≥ 0.5`, Docker (running), `aws` CLI v2, `psql` or `psycopg2` (the seed script vendors `psycopg2-binary` via `uv run` PEP 723).
- **Existing data state:** the `posts` table has 1 000 rows from Plan 1's seed. Plan 4's Task 6 bumps the seed to 10 000 and adds the `posts_author_idx`; the additional 9 000 rows are inserted, the existing 1 000 are kept (mixed authorship, fine for demo).

**Doc-verification:** Before Task 9, confirm `httpx`'s current async patterns at https://www.python-httpx.org (we lock to `httpx>=0.28`, which is already on the local backend's dev-deps). Before Task 10, re-read `opensre_host/user_data.sh.tftpl` end-to-end so the new install block lands in a sensible place — the existing script's logging/TOKEN/REGION setup at the top is shared infrastructure and must not be duplicated.

---

## File Structure

Files this plan creates:

```
open-sre-agents/
└── scripts/
    └── load_runner.py                     # NEW: httpx+asyncio mixed REST load runner (PEP 723 inline-deps)
```

Files this plan modifies:

```
open-sre-agents/
├── backend/
│   ├── src/app/main.py                    # MODIFY: add 4 endpoints, allow POST in CORS
│   ├── tests/test_posts.py                # MODIFY: cases for the 4 new endpoints
│   └── Dockerfile                         # MODIFY: add --proxy-headers --forwarded-allow-ips='*'
├── scripts/
│   └── seed_posts.py                      # MODIFY: 10 000 rows, 50-username pool, posts_author_idx
└── opensre_host/
    └── user_data.sh.tftpl                 # MODIFY: install python3-pip + httpx, copy load_runner.py to /opt/opensre/
```

Note: the OpenSRE EC2 has `user_data_replace_on_change = true` in `infra/opensre_host.tf:138`, so editing `user_data.sh.tftpl` will **replace the EC2 instance** on the next `terraform apply`. The new instance will re-bootstrap (including a new "hello" Telegram message). Plan 3's Lambda picks up the new instance ID automatically because it's a Terraform output.

---

## Task 1: SUT — `GET /posts/{id}` (single-row fetch)

**Files:**
- Modify: `backend/tests/test_posts.py` (append new test)
- Modify: `backend/src/app/main.py:34-42` (add new route below the existing `/posts` handler)

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_posts.py`:

```python
def test_get_post_by_id_returns_single_post(mock_pool_factory, fixed_now):
    rows = [
        {"id": 7, "author": "alice", "content": "hello", "likes": 5, "created_at": fixed_now},
    ]

    def make_pool(rows):
        from unittest.mock import AsyncMock, MagicMock

        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=rows[0] if rows else None)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        return pool

    app.dependency_overrides[get_pool] = lambda: make_pool(rows)
    try:
        client = TestClient(app)
        response = client.get("/posts/7")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 7
        assert body["author"] == "alice"
    finally:
        app.dependency_overrides.clear()


def test_get_post_by_id_returns_404_when_missing(mock_pool_factory):
    from unittest.mock import AsyncMock, MagicMock

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)

    app.dependency_overrides[get_pool] = lambda: pool
    try:
        client = TestClient(app)
        response = client.get("/posts/99999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
```

- [x] **Step 2: Run the tests and confirm failure**

```bash
cd backend && uv run pytest tests/test_posts.py::test_get_post_by_id_returns_single_post -v
```

Expected: 404 from FastAPI's "Not Found" route handler (no `/posts/{id}` registered yet) — assertion fails on `response.status_code == 200`.

- [x] **Step 3: Implement the route**

Edit `backend/src/app/main.py`. Add `HTTPException` to the FastAPI import, then append below the existing `/posts` handler:

```python
from fastapi import Depends, FastAPI, HTTPException
```

```python
@app.get("/posts/{post_id}")
async def post_by_id(post_id: int, pool=Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, author, content, likes, created_at "
            "FROM posts WHERE id = $1",
            post_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return dict(row)
```

- [x] **Step 4: Run the tests and confirm pass**

```bash
cd backend && uv run pytest tests/test_posts.py -v
```

Expected: all four tests pass (the two existing + the two new).

- [x] **Step 5: Commit**

```bash
git add backend/src/app/main.py backend/tests/test_posts.py
git commit -m "feat(backend): add GET /posts/{id} single-row fetch endpoint"
```

---

## Task 2: SUT — `GET /posts/search` with Python-side fuzzy scoring

**Files:**
- Modify: `backend/tests/test_posts.py` (append)
- Modify: `backend/src/app/main.py` (append handler)

The handler runs a non-indexed `WHERE content ILIKE '%q%'` then loops in Python to count case-insensitive occurrences of `q` in each match's `content`, sorts by count desc, returns top `limit`. **Both the SQL scan and the Python scoring are deliberately CPU-bound at concurrency** — this is the endpoint that drives saturation in Plan 5.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_posts.py`:

```python
def test_search_orders_by_match_count_desc(fixed_now):
    rows = [
        {"id": 1, "author": "alice", "content": "rust rust rust",  "likes": 0, "created_at": fixed_now},
        {"id": 2, "author": "bob",   "content": "rust",            "likes": 0, "created_at": fixed_now},
        {"id": 3, "author": "carol", "content": "RuSt rust",       "likes": 0, "created_at": fixed_now},
    ]

    def make_pool():
        from unittest.mock import AsyncMock, MagicMock

        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=rows)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=cm)
        return pool

    app.dependency_overrides[get_pool] = lambda: make_pool()
    try:
        client = TestClient(app)
        response = client.get("/posts/search?q=rust&limit=10")
        assert response.status_code == 200
        body = response.json()
        ids = [p["id"] for p in body["posts"]]
        # alice (3 occurrences) before carol (2, case-insensitive) before bob (1)
        assert ids == [1, 3, 2]
    finally:
        app.dependency_overrides.clear()
```

- [x] **Step 2: Run the test and confirm failure**

```bash
cd backend && uv run pytest tests/test_posts.py::test_search_orders_by_match_count_desc -v
```

Expected: 404 (route not yet registered) — assertion fails.

- [x] **Step 3: Implement the handler**

Append to `backend/src/app/main.py`:

```python
@app.get("/posts/search")
async def posts_search(q: str, limit: int = 50, pool=Depends(get_pool)) -> dict:
    """Non-indexed ILIKE filter + Python-side fuzzy scoring.

    Both legs are deliberately CPU-bound under concurrency: the SQL scans
    every row in `posts` because there is no index on `content`, and the
    Python loop counts case-insensitive substring occurrences for each
    match before sorting. Plan-5 cpu-load-burst exploits this.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, author, content, likes, created_at "
            "FROM posts WHERE content ILIKE $1",
            f"%{q}%",
        )
    needle = q.lower()
    scored: list[tuple[int, dict]] = []
    for r in rows:
        haystack = r["content"].lower()
        count = 0
        pos = 0
        while True:
            pos = haystack.find(needle, pos)
            if pos == -1:
                break
            count += 1
            pos += 1
        scored.append((count, dict(r)))
    scored.sort(key=lambda t: t[0], reverse=True)
    return {"posts": [post for _, post in scored[:limit]]}
```

- [x] **Step 4: Run tests and confirm pass**

```bash
cd backend && uv run pytest tests/test_posts.py -v
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add backend/src/app/main.py backend/tests/test_posts.py
git commit -m "feat(backend): add GET /posts/search with Python-side fuzzy scoring"
```

---

## Task 3: SUT — `GET /users/{username}/posts`

**Files:**
- Modify: `backend/tests/test_posts.py` (append)
- Modify: `backend/src/app/main.py` (append handler)

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_posts.py`:

```python
def test_posts_by_user_filters_by_author(fixed_now):
    rows = [
        {"id": 11, "author": "user1", "content": "a", "likes": 0, "created_at": fixed_now},
        {"id": 12, "author": "user1", "content": "b", "likes": 0, "created_at": fixed_now},
    ]
    captured = {}

    def make_pool():
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

    app.dependency_overrides[get_pool] = lambda: make_pool()
    try:
        client = TestClient(app)
        response = client.get("/users/user1/posts?limit=25")
        assert response.status_code == 200
        body = response.json()
        assert len(body["posts"]) == 2
        assert captured["args"] == ("user1", 25)
        assert "author = $1" in captured["query"]
    finally:
        app.dependency_overrides.clear()
```

- [x] **Step 2: Run the test, confirm failure**

```bash
cd backend && uv run pytest tests/test_posts.py::test_posts_by_user_filters_by_author -v
```

- [x] **Step 3: Implement**

Append to `backend/src/app/main.py`:

```python
@app.get("/users/{username}/posts")
async def posts_by_user(
    username: str, limit: int = 50, pool=Depends(get_pool)
) -> dict:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, author, content, likes, created_at "
            "FROM posts WHERE author = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            username,
            limit,
        )
    return {"posts": [dict(r) for r in rows]}
```

- [x] **Step 4: Run tests, confirm pass**

```bash
cd backend && uv run pytest tests/test_posts.py -v
```

- [x] **Step 5: Commit**

```bash
git add backend/src/app/main.py backend/tests/test_posts.py
git commit -m "feat(backend): add GET /users/{username}/posts filtered list"
```

---

## Task 4: SUT — `POST /posts/{id}/like`

**Files:**
- Modify: `backend/tests/test_posts.py` (append)
- Modify: `backend/src/app/main.py` (append handler + allow POST in CORS)

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_posts.py`:

```python
def test_like_post_increments_likes_count():
    from unittest.mock import AsyncMock, MagicMock

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 42, "likes": 6})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)

    app.dependency_overrides[get_pool] = lambda: pool
    try:
        client = TestClient(app)
        response = client.post("/posts/42/like")
        assert response.status_code == 200
        body = response.json()
        assert body == {"id": 42, "likes": 6}
    finally:
        app.dependency_overrides.clear()


def test_like_post_returns_404_when_missing():
    from unittest.mock import AsyncMock, MagicMock

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)

    app.dependency_overrides[get_pool] = lambda: pool
    try:
        client = TestClient(app)
        response = client.post("/posts/99999/like")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
```

- [x] **Step 2: Run the failing tests**

```bash
cd backend && uv run pytest tests/test_posts.py::test_like_post_increments_likes_count tests/test_posts.py::test_like_post_returns_404_when_missing -v
```

Expected: 405 Method Not Allowed (no POST handler) → assertion fails on `response.status_code == 200`. (Or 404 — the route doesn't exist either way.)

- [x] **Step 3: Implement and allow `POST` in CORS**

Edit `backend/src/app/main.py`:

In the existing `app.add_middleware(CORSMiddleware, ...)` call, change `allow_methods=["GET"]` to `allow_methods=["GET", "POST"]`.

Append the handler at the bottom of the file:

```python
@app.post("/posts/{post_id}/like")
async def like_post(post_id: int, pool=Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE posts SET likes = likes + 1 WHERE id = $1 "
            "RETURNING id, likes",
            post_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return {"id": row["id"], "likes": row["likes"]}
```

- [x] **Step 4: Run all tests, confirm pass**

```bash
cd backend && uv run pytest -v
```

Expected: every test in `tests/test_posts.py` and `tests/test_health.py` passes (8 tests total: 2 original + 6 new).

- [x] **Step 5: Commit**

```bash
git add backend/src/app/main.py backend/tests/test_posts.py
git commit -m "feat(backend): add POST /posts/{id}/like increment endpoint"
```

---

## Task 5: SUT — Dockerfile: enable proxy headers

**Files:**
- Modify: `backend/Dockerfile:18` (the `CMD` line)

- [x] **Step 1: Edit the CMD**

Find the existing CMD in `backend/Dockerfile`:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Replace with:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
```

`--proxy-headers` tells Uvicorn to honour `X-Forwarded-For`/`X-Forwarded-Proto`. `--forwarded-allow-ips=*` is required because by default Uvicorn only trusts forwarded headers from `127.0.0.1`; we need it to trust traffic from the OpenSRE host EIP. This is intentionally permissive — the SUT is a demo, behind no proxy, and the access log is the only artefact that benefits.

- [x] **Step 2: Build locally to confirm the image still builds**

```bash
cd backend && docker build -t opensre-demo-sut:plan-4-local .
```

Expected: build succeeds; the final image's `CMD` reflects the new flags.

- [x] **Step 3: Commit**

```bash
git add backend/Dockerfile
git commit -m "feat(backend): start uvicorn with --proxy-headers for X-Forwarded-For"
```

---

## Task 6: Seed — 10 000 rows, 50-username pool, `posts_author_idx`

**Files:**
- Modify: `scripts/seed_posts.py`

The existing 1 000 rows stay; the seed adds 9 000 more drawn from a fixed 50-username pool. `posts_author_idx` is added via `CREATE INDEX IF NOT EXISTS` so the change is idempotent. **No `posts_content_idx`** — `/posts/search` is intentionally CPU-bound.

- [x] **Step 1: Edit `scripts/seed_posts.py`**

Replace the entire file contents with:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "psycopg2-binary>=2.9",
#   "faker>=30",
# ]
# ///
"""Seed the demo `posts` table with 10 000 rows from a fixed 50-username pool.

Idempotent: skips if the row count already meets ROW_COUNT. Always
ensures the index exists.

Run via SSM Session Manager port-forward (see Plan 1, Task 13):
    SEED_DATABASE_URL='postgresql://opensre:<pw>@localhost:5432/opensre_demo' \\
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
CREATE INDEX IF NOT EXISTS posts_author_idx     ON posts (author);
-- No index on `content`: /posts/search is intentionally CPU-bound under concurrency.
"""

ROW_COUNT = 10_000

# Fixed 50-username pool. /users/{username}/posts must return useful results
# for any of these names; load_runner.py's USERNAMES list mirrors this.
USERNAMES = [f"user{i}" for i in range(1, 51)]


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
                    random.choice(USERNAMES),
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

(Diffs from the prior version: `ROW_COUNT = 10_000`, new `USERNAMES` list, `random.choice(USERNAMES)` instead of `fake.user_name()`, additional `CREATE INDEX IF NOT EXISTS posts_author_idx`.)

- [x] **Step 2: Lint**

```bash
uv run --with python python -m py_compile scripts/seed_posts.py
```

Expected: no output (clean compile).

- [x] **Step 3: Commit**

```bash
git add scripts/seed_posts.py
git commit -m "feat(seed): expand to 10k rows from 50-user pool, add posts_author_idx"
```

---

## Task 7: Build, push, and roll the new SUT image

The new endpoints can't serve traffic until the running ECS task is replaced with one running the new image.

- [x] **Step 1: ECR login**

```bash
REGION=$(cd infra && terraform output -raw aws_region)
ECR_URL=$(cd infra && terraform output -raw ecr_repository_url)
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ECR_URL"
```

Expected: `Login Succeeded`.

- [x] **Step 2: Build for linux/amd64 (matches the t3.micro target)**

```bash
cd backend
docker build --platform linux/amd64 -t "$ECR_URL:latest" .
```

Expected: build succeeds.

- [x] **Step 3: Push**

```bash
docker push "$ECR_URL:latest"
cd ..
```

Expected: layers push; final digest reported.

- [x] **Step 4: Force ECS to roll the task to the new image**

`force_new_deployment = true` is already set on `aws_ecs_service.sut`, but Terraform won't re-apply it without a config change. Use the ECS API directly:

```bash
aws ecs update-service \
  --region "$REGION" \
  --cluster opensre-demo \
  --service opensre-demo-sut \
  --force-new-deployment >/dev/null
```

Wait ~30–60 s for the rolling deployment.

- [x] **Step 5: Verify the new endpoints respond**

```bash
SUT_API=$(cd infra && terraform output -raw sut_api_url)

# Existing endpoints still work
curl -fsS "$SUT_API/health" | jq .

# New endpoints
curl -fsS "$SUT_API/posts/1" | jq '.id, .author'                  # single fetch
curl -fsS "$SUT_API/posts/search?q=the&limit=3" | jq '.posts | length'  # fuzzy search
curl -fsS "$SUT_API/users/user1/posts?limit=5" | jq '.posts | length'   # by-user (will be 0 until Task 8 re-seeds)
curl -fsS -X POST "$SUT_API/posts/1/like" | jq .                  # like
```

Expected: each call returns 200 with a JSON body. `/users/user1/posts` will return zero posts because Plan 1's seed used `faker.user_name()`, not the pool — that's fine; Task 8 fixes it.

- [x] **Step 6: No commit** — image push and ECS rollout don't produce git artefacts.

---

## Task 8: Re-seed RDS (1 k → 10 k rows)

`scripts/seed_posts.py` is idempotent and additive: existing rows stay, the script only inserts the gap (9 000 rows from the 50-username pool) and ensures `posts_author_idx` exists.

- [x] **Step 1: Open an SSM port-forward to RDS via the SUT host**

In **terminal A** (leave running):

```bash
SUT_INSTANCE=$(cd infra && terraform output -raw sut_instance_id)
RDS_ADDR=$(cd infra && terraform output -raw rds_address)
REGION=$(cd infra && terraform output -raw aws_region)

aws ssm start-session \
  --region "$REGION" \
  --target "$SUT_INSTANCE" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "host=$RDS_ADDR,portNumber=5432,localPortNumber=5432"
```

- [x] **Step 2: Run the seed script (terminal B)**

```bash
DB_PW=$(grep '^db_password' infra/terraform.tfvars | sed 's/.*=[[:space:]]*"\(.*\)"/\1/')
SEED_DATABASE_URL="postgresql://opensre:${DB_PW}@localhost:5432/opensre_demo" \
  uv run scripts/seed_posts.py
```

Expected: `Seeded 9000 posts (table now has 10000).` If you see `posts already has N rows — skipping seed.` with N≥10 000, the seed has already run; that's fine.

- [x] **Step 3: Spot-check the new data**

In terminal B (port-forward still up):

```bash
PGPASSWORD="$DB_PW" psql -h localhost -p 5432 -U opensre -d opensre_demo \
  -c "SELECT count(*) FROM posts;" \
  -c "SELECT author, count(*) FROM posts WHERE author LIKE 'user%' GROUP BY author ORDER BY count(*) DESC LIMIT 5;" \
  -c "\\d posts"
```

Expected:
- `count = 10000`
- 50 distinct `userN` authors with row counts ranging roughly 150–230
- `\d posts` lists `posts_author_idx` and `posts_created_at_idx`; **no** index on `content`

- [x] **Step 4: Verify the by-user endpoint returns rows now**

In terminal B:

```bash
SUT_API=$(cd infra && terraform output -raw sut_api_url)
curl -fsS "$SUT_API/users/user1/posts?limit=5" | jq '.posts | length'
```

Expected: a number in the range ~100–250 (capped to limit if you raise it).

- [x] **Step 5: Close the port-forward (Ctrl-C in terminal A)**

- [x] **Step 6: No commit** — runtime data, not code.

---

## Task 9: `scripts/load_runner.py`

This is the heart of Plan 4. PEP 723 inline-deps so it's runnable via `uv run` locally for sanity tests, and via plain `python3` on the OpenSRE host (which Task 10 prepares with `httpx` system-installed).

**Files:**
- Create: `scripts/load_runner.py`

- [x] **Step 1: Create `scripts/load_runner.py`**

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28"]
# ///
"""Realistic mixed-traffic load runner for the OpenSRE demo SUT.

Drives weighted REST traffic with a ramp-up of virtual users (VUs) over a
configurable window. Spreads requests across many "source IPs" via the
X-Forwarded-For header so Uvicorn (--proxy-headers --forwarded-allow-ips='*')
logs entries as if from many clients.

Invoked by the cpu-load-burst FIS template via aws:ssm:send-command:
    python3 /opt/opensre/load_runner.py http://<sut-eip>:8080 \\
        --duration 180 --ramp 30 --max-vus 200

Endpoint mix (weights match spec §4 + plan 4.5):
    60% GET /posts?limit=N
    20% GET /posts/{id}
    15% GET /posts/search?q=<term>
     5% POST /posts/{id}/like
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from urllib.parse import quote

import httpx

# 22 common Latin lorem-ipsum tokens. All appear in faker.text() output, so
# /posts/search will return non-empty result sets.
VOCAB = [
    "the", "lorem", "ipsum", "dolor", "sit", "amet", "consectetur",
    "adipiscing", "elit", "morbi", "vivamus", "donec", "etiam", "fusce",
    "magna", "nibh", "tristique", "egestas", "luctus", "vehicula",
    "fermentum", "porttitor",
]

# Mirrors the seed-script's USERNAMES pool.
USERNAMES = [f"user{i}" for i in range(1, 51)]

# 50 fake source IPs in TEST-NET-3 (RFC 5737); safe to use anywhere.
FAKE_IPS = [f"203.0.113.{i}" for i in range(1, 51)]

ENDPOINTS: list[tuple[int, str]] = [
    (60, "list"),
    (20, "detail"),
    (15, "search"),
    (5, "like"),
]
WEIGHTS = [w for w, _ in ENDPOINTS]
KINDS = [k for _, k in ENDPOINTS]


async def make_request(client: httpx.AsyncClient, kind: str, max_id: int) -> None:
    headers = {"X-Forwarded-For": random.choice(FAKE_IPS)}
    if kind == "list":
        limit = random.choice([10, 25, 50, 100])
        await client.get(f"/posts?limit={limit}", headers=headers)
    elif kind == "detail":
        await client.get(f"/posts/{random.randint(1, max_id)}", headers=headers)
    elif kind == "search":
        q = random.choice(VOCAB)
        # /users/{username}/posts is folded into the same 15% search slot at
        # 1-in-3 odds so the access log shows path variety beyond search.
        if random.random() < 0.33:
            user = random.choice(USERNAMES)
            await client.get(f"/users/{user}/posts?limit=25", headers=headers)
        else:
            await client.get(f"/posts/search?q={quote(q)}", headers=headers)
    elif kind == "like":
        await client.post(f"/posts/{random.randint(1, max_id)}/like", headers=headers)


async def virtual_user(
    client: httpx.AsyncClient, stop_event: asyncio.Event, max_id: int
) -> None:
    while not stop_event.is_set():
        kind = random.choices(KINDS, weights=WEIGHTS, k=1)[0]
        try:
            await make_request(client, kind, max_id)
        except Exception:  # noqa: BLE001 — never let one failed request stop a VU
            pass
        # Random think-time so requests don't perfectly synchronise.
        await asyncio.sleep(random.uniform(0.1, 0.4))


async def run(
    base_url: str, duration: int, ramp: int, max_vus: int, max_id: int
) -> None:
    stop_event = asyncio.Event()
    spawn_interval = ramp / max(1, max_vus)
    print(
        f"[load_runner] target={base_url} duration={duration}s "
        f"ramp={ramp}s max_vus={max_vus} max_id={max_id}",
        flush=True,
    )
    start = time.monotonic()
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        tasks: list[asyncio.Task] = []
        for _ in range(max_vus):
            tasks.append(asyncio.create_task(virtual_user(client, stop_event, max_id)))
            await asyncio.sleep(spawn_interval)
        elapsed = time.monotonic() - start
        remaining = max(0.0, duration - elapsed)
        print(
            f"[load_runner] {max_vus} VUs spawned in {elapsed:.1f}s; "
            f"holding {remaining:.1f}s",
            flush=True,
        )
        await asyncio.sleep(remaining)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    print("[load_runner] completed", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base_url", help="e.g. http://1.2.3.4:8080")
    p.add_argument("--duration", type=int, default=180, help="total run time in seconds")
    p.add_argument("--ramp", type=int, default=30, help="ramp-up duration in seconds")
    p.add_argument("--max-vus", type=int, default=200, help="peak concurrent virtual users")
    p.add_argument(
        "--max-id",
        type=int,
        default=10_000,
        help="upper bound for random post id selection (matches seed ROW_COUNT)",
    )
    args = p.parse_args()
    asyncio.run(run(args.base_url, args.duration, args.ramp, args.max_vus, args.max_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 2: Make it executable + lint**

```bash
chmod +x scripts/load_runner.py
python3 -m py_compile scripts/load_runner.py
```

Expected: no output.

- [x] **Step 3: Local smoke test (short run, low concurrency)**

```bash
SUT_API=$(cd infra && terraform output -raw sut_api_url)
uv run scripts/load_runner.py "$SUT_API" --duration 15 --ramp 3 --max-vus 5 --max-id 10000
```

Expected: prints `target=...`, then a "VUs spawned" line, then `completed`. While running, in another terminal:

```bash
aws logs tail /ecs/opensre-demo-sut --since 1m --region "$(cd infra && terraform output -raw aws_region)" --format short
```

You should see Uvicorn access lines for `/posts`, `/posts/{id}`, `/posts/search`, `/users/userN/posts`, `POST /posts/{id}/like`, **with varied source IPs from the `203.0.113.X` pool** (because `--proxy-headers` is now active from Task 5).

- [x] **Step 4: Commit**

```bash
git add scripts/load_runner.py
git commit -m "feat(scripts): add load_runner.py — httpx+asyncio mixed REST load runner"
```

---

## Task 10: OpenSRE host — install Python 3 + httpx + load_runner.py

**Files:**
- Modify: `opensre_host/user_data.sh.tftpl` (insert a new section between Task-3-defined env-file write and Task-4-defined integrations-verify; line ~93)

The bootstrap installs `python3` (already present on Ubuntu 24.04, but `python3-pip` is not), uses `pip3 install httpx` to make the script's only third-party dep available system-wide, then writes the load runner via heredoc to `/opt/opensre/load_runner.py` (chmod 755).

We embed the load runner inline in user_data so we don't need to upload it from S3 or fetch it from a remote URL. **Keep the inline contents in sync with `scripts/load_runner.py` whenever it changes** — the plan's Final Validation includes a `diff` check.

- [x] **Step 1: Edit `opensre_host/user_data.sh.tftpl`**

Find the `--- 4. Source for this script + verify integrations ---` comment block (around line 94). Insert the following block **immediately above** it:

```bash
# --- 3b. Install python3-pip + httpx + load_runner.py for FIS cpu-load-burst ---
echo "[$(date -u +%FT%TZ)] Installing python3-pip + httpx..."
apt-get install -y python3-pip
# Ubuntu 24.04 enforces PEP 668 — use --break-system-packages because the
# host is single-purpose and not running other Python apps.
pip3 install --break-system-packages "httpx>=0.28"

mkdir -p /opt/opensre
cat > /opt/opensre/load_runner.py <<'LOADRUNNEREOF'
#!/usr/bin/env python3
"""Realistic mixed-traffic load runner. Mirrors scripts/load_runner.py.

Invoked by the cpu-load-burst FIS template via aws:ssm:send-command. Keep
in sync with scripts/load_runner.py — Plan 4 final validation diffs them.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from urllib.parse import quote

import httpx

VOCAB = [
    "the", "lorem", "ipsum", "dolor", "sit", "amet", "consectetur",
    "adipiscing", "elit", "morbi", "vivamus", "donec", "etiam", "fusce",
    "magna", "nibh", "tristique", "egestas", "luctus", "vehicula",
    "fermentum", "porttitor",
]
USERNAMES = [f"user{i}" for i in range(1, 51)]
FAKE_IPS = [f"203.0.113.{i}" for i in range(1, 51)]
ENDPOINTS = [(60, "list"), (20, "detail"), (15, "search"), (5, "like")]
WEIGHTS = [w for w, _ in ENDPOINTS]
KINDS = [k for _, k in ENDPOINTS]


async def make_request(client, kind, max_id):
    headers = {"X-Forwarded-For": random.choice(FAKE_IPS)}
    if kind == "list":
        limit = random.choice([10, 25, 50, 100])
        await client.get(f"/posts?limit={limit}", headers=headers)
    elif kind == "detail":
        await client.get(f"/posts/{random.randint(1, max_id)}", headers=headers)
    elif kind == "search":
        q = random.choice(VOCAB)
        if random.random() < 0.33:
            user = random.choice(USERNAMES)
            await client.get(f"/users/{user}/posts?limit=25", headers=headers)
        else:
            await client.get(f"/posts/search?q={quote(q)}", headers=headers)
    elif kind == "like":
        await client.post(f"/posts/{random.randint(1, max_id)}/like", headers=headers)


async def virtual_user(client, stop_event, max_id):
    while not stop_event.is_set():
        kind = random.choices(KINDS, weights=WEIGHTS, k=1)[0]
        try:
            await make_request(client, kind, max_id)
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.1, 0.4))


async def run(base_url, duration, ramp, max_vus, max_id):
    stop_event = asyncio.Event()
    spawn_interval = ramp / max(1, max_vus)
    print(
        f"[load_runner] target={base_url} duration={duration}s "
        f"ramp={ramp}s max_vus={max_vus} max_id={max_id}",
        flush=True,
    )
    start = time.monotonic()
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        tasks = []
        for _ in range(max_vus):
            tasks.append(asyncio.create_task(virtual_user(client, stop_event, max_id)))
            await asyncio.sleep(spawn_interval)
        elapsed = time.monotonic() - start
        remaining = max(0.0, duration - elapsed)
        print(
            f"[load_runner] {max_vus} VUs spawned in {elapsed:.1f}s; "
            f"holding {remaining:.1f}s",
            flush=True,
        )
        await asyncio.sleep(remaining)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    print("[load_runner] completed", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("base_url")
    p.add_argument("--duration", type=int, default=180)
    p.add_argument("--ramp", type=int, default=30)
    p.add_argument("--max-vus", type=int, default=200)
    p.add_argument("--max-id", type=int, default=10_000)
    args = p.parse_args()
    asyncio.run(run(args.base_url, args.duration, args.ramp, args.max_vus, args.max_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
LOADRUNNEREOF
chmod 755 /opt/opensre/load_runner.py

# Sanity-check the runner imports and parses --help on this box.
python3 /opt/opensre/load_runner.py --help >/dev/null

```

(The blank line before `# --- 4. ...` keeps separation in the resulting bash file.)

- [x] **Step 2: Apply Terraform — replaces the OpenSRE EC2**

```bash
cd infra && terraform plan -out=plan-4-10.tfplan
```

Expected diff: `aws_instance.opensre[0]` to be **destroyed and re-created** (`user_data_replace_on_change = true` triggers the replace). Lambda's `aws_lambda_function.ingest_alarm` should NOT replace, but its env var (the new instance ID) will update in place.

```bash
terraform apply plan-4-10.tfplan
```

Confirm. Expect ~2 min for the new EC2 to boot + bootstrap.

- [x] **Step 3: Wait for bootstrap and confirm**

```bash
NEW_HOST=$(terraform output -raw opensre_host_instance_id)
REGION=$(terraform output -raw aws_region)

# Poll until SSM marks it Online (typically ~60-90 s after the apply finishes).
for i in $(seq 1 24); do
  STATUS=$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$NEW_HOST" \
    --region "$REGION" --query 'InstanceInformationList[0].PingStatus' \
    --output text 2>/dev/null || echo "MISSING")
  echo "[$i] $NEW_HOST PingStatus=$STATUS"
  [ "$STATUS" = "Online" ] && break
  sleep 10
done
```

Expected: `PingStatus=Online` within ~2 min. Also: a **fresh "[OpenSRE bootstrap] host i-… online …"** message in the configured Telegram group (re-posted by the new host's bootstrap).

- [x] **Step 4: Verify load_runner.py is installed and httpx imports**

```bash
aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$NEW_HOST" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["test -x /opt/opensre/load_runner.py && python3 -c \"import httpx; print(httpx.__version__)\" && python3 /opt/opensre/load_runner.py --help | head -5"]' \
  --query 'Command.CommandId' --output text > /tmp/cmd.txt
sleep 5
aws ssm get-command-invocation \
  --region "$REGION" \
  --command-id "$(cat /tmp/cmd.txt)" \
  --instance-id "$NEW_HOST" \
  --query '{status:Status,stdout:StandardOutputContent,stderr:StandardErrorContent}'
```

Expected: `Status=Success`; stdout contains an httpx version (e.g. `0.28.x`) and the argparse help banner.

- [x] **Step 5: Commit**

```bash
git add opensre_host/user_data.sh.tftpl
git commit -m "feat(opensre-host): install python3-pip + httpx + load_runner.py for cpu-load-burst"
rm -f infra/plan-4-10.tfplan
```

---

## Task 11: End-to-end smoke test from the OpenSRE host

This is the **headline check for Plan 4**: dispatching `load_runner.py` from the OpenSRE host (the same path Plan 5's FIS template will use) produces realistic-looking access-log entries on the SUT and visibly drives CPU.

- [x] **Step 1: Dispatch a short load burst via SSM RunCommand**

```bash
NEW_HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
SUT_API=$(cd infra && terraform output -raw sut_api_url)
REGION=$(cd infra && terraform output -raw aws_region)

CMD_ID=$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$NEW_HOST" \
  --document-name AWS-RunShellScript \
  --parameters "commands=[\"python3 /opt/opensre/load_runner.py $SUT_API --duration 60 --ramp 10 --max-vus 50 --max-id 10000\"]" \
  --timeout-seconds 600 \
  --query 'Command.CommandId' --output text)
echo "Command: $CMD_ID"
```

The SSM command itself returns immediately; the load runs for ~60 s on the host.

- [x] **Step 2: Tail the SUT log group during the burst**

```bash
aws logs tail /ecs/opensre-demo-sut --since 1m --region "$REGION" --format short --follow
```

Run for ~90 s (cover the 60 s burst + ~30 s drain), then Ctrl-C.

Expected: a flood of Uvicorn access lines like:

```
INFO:     203.0.113.17:0 - "GET /posts?limit=25 HTTP/1.1" 200 OK
INFO:     203.0.113.04:0 - "GET /posts/4123 HTTP/1.1" 200 OK
INFO:     203.0.113.31:0 - "GET /posts/search?q=lorem HTTP/1.1" 200 OK
INFO:     203.0.113.02:0 - "GET /users/user12/posts?limit=25 HTTP/1.1" 200 OK
INFO:     203.0.113.45:0 - "POST /posts/8231/like HTTP/1.1" 200 OK
```

The leftmost column is the **client IP** Uvicorn now logs from `X-Forwarded-For`, so each line shows a different `203.0.113.X`. Path/method mix should look roughly consistent with the 60/20/15/5 weights.

- [x] **Step 3: Confirm CPU climbed (CloudWatch Metrics)**

```bash
START=$(date -u -v-5M +%FT%TZ 2>/dev/null || date -u -d '-5 min' +%FT%TZ)
END=$(date -u +%FT%TZ)
aws cloudwatch get-metric-statistics \
  --region "$REGION" \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions "Name=ClusterName,Value=opensre-demo" "Name=ServiceName,Value=opensre-demo-sut" \
  --start-time "$START" --end-time "$END" \
  --period 60 --statistics Maximum \
  --query 'Datapoints[].[Timestamp,Maximum]' --output text | sort
```

Expected: a contiguous sequence of `Maximum` datapoints during the burst window with a **peak ≥ 50 %** (50 VUs is intentionally below saturation; Plan 5 ramps to 200). If the peak is below ~30 %, increase `--max-vus` and re-run.

- [x] **Step 4: Confirm `/posts/search` was the top CPU consumer (Logs Insights)**

```bash
aws logs start-query \
  --region "$REGION" \
  --log-group-name /ecs/opensre-demo-sut \
  --start-time $(($(date +%s) - 600)) \
  --end-time $(date +%s) \
  --query-string 'parse @message /\"(?<method>GET|POST) (?<path>\S+) / | stats count(*) as c by method, path | sort c desc | limit 10' \
  --query 'queryId' --output text > /tmp/qid.txt
sleep 5
aws logs get-query-results --region "$REGION" --query-id "$(cat /tmp/qid.txt)" \
  --query 'results[].[field0:[?field==`method`].value | [0], field1:[?field==`path`].value | [0], count:[?field==`c`].value | [0]]'
```

Expected: roughly 60 % of requests on `GET /posts`, ~20 % on `GET /posts/{N}`, ~10 % on `GET /posts/search?...`, ~5 % on `GET /users/{user}/posts`, ~5 % on `POST /posts/{N}/like`. Exact ratios will drift with the random seed — within ±3 percentage points each is fine.

- [x] **Step 5: No commit** — verification only.

---

## Task 12: README — Plan 4 quick-start

**Files:**
- Modify: `README.md` (insert a "Plan 4 quick-start" section between Plan 3 and Teardown — or, if no Plan-3 section exists yet, insert after the Plan-2 section)

- [x] **Step 1: Append the section**

Find the `## Teardown` heading. Insert immediately above:

````markdown
## Plan 4 quick-start (realistic-load preparation)

Builds on Plans 1–3. Adds the SUT endpoints and OpenSRE-host load tooling that Plan 5's `cpu-load-burst` FIS template needs.

```bash
# 1. Backend tests + image build + push
cd backend && uv run pytest -v && cd ..
REGION=$(cd infra && terraform output -raw aws_region)
ECR_URL=$(cd infra && terraform output -raw ecr_repository_url)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URL"
cd backend && docker build --platform linux/amd64 -t "$ECR_URL:latest" . && docker push "$ECR_URL:latest" && cd ..

# 2. Roll the ECS service to the new image
aws ecs update-service --region "$REGION" --cluster opensre-demo --service opensre-demo-sut --force-new-deployment >/dev/null
sleep 60

# 3. Re-seed RDS to 10 000 rows (in another terminal: aws ssm start-session ... port-forward 5432).
DB_PW=$(grep '^db_password' infra/terraform.tfvars | sed 's/.*=[[:space:]]*"\(.*\)"/\1/')
SEED_DATABASE_URL="postgresql://opensre:${DB_PW}@localhost:5432/opensre_demo" uv run scripts/seed_posts.py

# 4. Apply terraform — replaces the OpenSRE host with one that has python3-pip + httpx + load_runner.py
cd infra && terraform apply && cd ..

# 5. Smoke test: drive 50 VUs for 60 s from the OpenSRE host and tail SUT logs.
NEW_HOST=$(cd infra && terraform output -raw opensre_host_instance_id)
SUT_API=$(cd infra && terraform output -raw sut_api_url)
aws ssm send-command --region "$REGION" --instance-ids "$NEW_HOST" \
  --document-name AWS-RunShellScript \
  --parameters "commands=[\"python3 /opt/opensre/load_runner.py $SUT_API --duration 60 --ramp 10 --max-vus 50\"]" \
  --query 'Command.CommandId' --output text
aws logs tail /ecs/opensre-demo-sut --since 1m --region "$REGION" --format short --follow
```

After this plan, Plan 5 (`fis-chaos.md`) wires the `cpu-load-burst` FIS template to dispatch the same load runner — so the operator runs `aws fis start-experiment` and the SUT log group fills with the same kind of traffic, but at peak (200 VUs / 3 min) and synchronised with the alarm pipeline.
````

- [x] **Step 2: Verify code-fence balance**

```bash
grep -c '^```' README.md
```

Expected: an even number.

- [x] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(plan-4): add realistic-load preparation quick-start"
```

---

## Final validation checklist

Plan 4 is complete when every box ticks.

- [x] `cd backend && uv run pytest -v` — all tests pass (≥ 8 in `test_posts.py`).
- [x] `cd infra && terraform plan` — **No changes** (everything from Tasks 5, 6, 10 is applied).
- [x] The running ECS task serves the new endpoints:
  - `curl -fsS "$SUT_API/posts/1" | jq .id` → `1`
  - `curl -fsS "$SUT_API/posts/search?q=the&limit=3" | jq '.posts | length'` → `3` (or fewer if `the` is rare)
  - `curl -fsS "$SUT_API/users/user1/posts?limit=5" | jq '.posts | length'` → ≥ 1
  - `curl -fsS -X POST "$SUT_API/posts/1/like" | jq .likes` → an incrementing integer
- [x] `psql … -c "SELECT count(*) FROM posts;"` → `10000`.
- [x] `psql … -c "\\d posts"` lists `posts_author_idx` and `posts_created_at_idx`; **no** `posts_content_idx`.
- [x] OpenSRE host:
  - `aws ssm describe-instance-information --filters Key=InstanceIds,Values=$(terraform output -raw opensre_host_instance_id) --query 'InstanceInformationList[0].PingStatus'` → `Online`.
  - The OpenSRE host's `/opt/opensre/load_runner.py` runs `--help` cleanly (verified in Task 10 Step 4).
- [x] `diff <(grep -A99999 'LOADRUNNEREOF' opensre_host/user_data.sh.tftpl | sed -n '/^#!\/usr\/bin\/env python3/,/^LOADRUNNEREOF$/p' | sed '/^LOADRUNNEREOF$/d') <(sed -n '/^#!\/usr\/bin\/env python3/,$p' scripts/load_runner.py | sed '/^# \/\/\//,/^# \/\/\//d')` shows only intentional differences (the host-side copy drops the PEP-723 inline-deps header and the type hints; behaviour is identical).
- [x] Telegram group received a fresh "[OpenSRE bootstrap]" message after Task 10's host replacement.
- [x] `aws ssm send-command … python3 /opt/opensre/load_runner.py … --duration 60 --ramp 10 --max-vus 50` produces a contiguous burst of access-log lines on `/ecs/opensre-demo-sut` with **varied `203.0.113.X` source IPs** and a path mix matching the configured weights ±3 %.
- [x] ECS service `CPUUtilization` peaks ≥ 50 % during the 60 s × 50 VU smoke burst.

If every box ticks, the SUT, the seed, and the OpenSRE host are ready for Plan 5's FIS chaos templates to drive a realistic 200-VU `cpu-load-burst` end-to-end.

---

*End of Plan 4. Continue to Plan 5 (`2026-05-08-fis-chaos.md`) for the FIS templates and the full alarm-to-RCA chaos demo.*
