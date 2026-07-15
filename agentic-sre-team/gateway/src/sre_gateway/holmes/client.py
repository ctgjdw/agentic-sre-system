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
    """Parse a real ToolCallResult (result is a nested StructuredToolResult with the
    output text in .data and the invocation in .invocation); tolerate a plain-string
    result and legacy key names (arguments/toolset) for the fake and any old callers."""
    result = entry.get("result", {})
    if isinstance(result, dict):
        data = result.get("data") or ""   # present-but-null -> "" (not json.dumps(None)="null")
        text = data if isinstance(data, str) else json.dumps(data, default=str)
        invocation = result.get("invocation") or ""
    else:
        text, invocation = str(result), ""
    return HolmesToolCall(
        tool_name=entry.get("tool_name", entry.get("name", "unknown")),
        toolset=entry.get("toolset_name", entry.get("toolset", "")),
        description=entry.get("description", ""),
        invocation=str(invocation or entry.get("invocation", "") or entry.get("description", "")),
        result=str(text)[:4000],
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
            # workers.py passes the raw model_json_schema(); wrap it here in Holmes's
            # json_schema envelope so this module stays the one place that knows the
            # wire format. strict=false: Vertex structured-output is picky about
            # strict + additionalProperties.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "FindingsOut", "strict": False,
                                "schema": response_format},
            }
        if on_event is None:
            res = await self._client.post("/api/chat", json=payload, timeout=timeout_s)
            res.raise_for_status()
            body = res.json()
            return HolmesAnswer(
                text=str(body.get("analysis") or ""),
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
                    # Real Holmes SSE event names; internal on_event payload types
                    # ("tool_start"/"tool_result") stay as-is - workers.py and the
                    # client test depend on those.
                    if event_name == "start_tool_calling":
                        await on_event({"type": "tool_start", **data})
                    elif event_name == "tool_calling_result":
                        tc = _parse_tool_call(data)
                        answer.tool_calls.append(tc)
                        await on_event({"type": "tool_result", "tool_name": tc.tool_name,
                                        "toolset": tc.toolset,
                                        "description": tc.description})
                    elif event_name == "ai_answer_end":
                        # No tool_calls in this payload; they're accumulated above
                        # from tool_calling_result events as they stream in.
                        answer.text = str(data.get("analysis") or "")
                        answer.raw = data
                    elif event_name == "error":
                        # Surface the real upstream failure instead of letting an empty
                        # answer.text degrade downstream as a confusing JSON parse error.
                        msg = data.get("msg") or data.get("description") or "unknown error"
                        raise RuntimeError(f"holmes stream error: {msg}")
        if not answer.text:
            raise RuntimeError("holmes stream ended without an answer (no ai_answer_end)")
        return answer
