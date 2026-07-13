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
