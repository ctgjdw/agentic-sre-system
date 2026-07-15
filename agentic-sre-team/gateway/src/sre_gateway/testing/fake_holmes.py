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
            yield _event("start_tool_calling", {"tool_name": tc["tool_name"],
                                                 "toolset_name": tc.get("toolset_name", ""),
                                                 "description": tc.get("description", "")})
            await asyncio.sleep(0)
            yield _event("tool_calling_result", tc)
        # Real Holmes doesn't include tool_calls in the final event.
        yield _event("ai_answer_end", {"analysis": fixture["analysis"]})

    return StreamingResponse(sse(), media_type="text/event-stream")


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5050)
