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
