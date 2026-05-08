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
