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
