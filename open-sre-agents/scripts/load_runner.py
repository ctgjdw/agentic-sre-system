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
