#!/usr/bin/env python3
"""Verifies Vertex credentials end to end: one small-tier chat call, one embedding,
and one frontier-tier chat call. Run from gateway/ (`make live-check`)."""
import asyncio
from pathlib import Path

from sre_gateway.llm.factory import ModelFactory, load_models_config


async def main() -> None:
    cfg = load_models_config(Path("../config/models.yaml"))
    factory = ModelFactory(cfg)
    reply = await factory.chat("small", "live-check").ainvoke("Reply with the word: pong")
    print("small tier:", str(reply.content)[:80])
    vec = (await factory.embed(["keycloak login outage"]))[0]
    print("embedding dim:", len(vec))
    assert len(vec) == 768, f"expected 768-dim embedding, got {len(vec)}"
    reply = await factory.chat("frontier", "live-check").ainvoke("Reply with the word: pong")
    print("frontier tier:", str(reply.content)[:80])
    print("PASS: vertex providers reachable")


if __name__ == "__main__":
    asyncio.run(main())
