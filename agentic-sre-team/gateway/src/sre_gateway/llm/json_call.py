import asyncio
import hashlib
import json
import re
import time
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from sre_gateway.audit import AuditWriter

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


class LlmJsonError(Exception):
    pass


def extract_json(text: str) -> dict:
    cleaned = _FENCE.sub("", text).strip().strip("`")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LlmJsonError(f"no JSON object in response: {text[:200]!r}")
    return json.loads(cleaned[start:end + 1])


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def call_llm_json(model: BaseChatModel, *, system: str, user: str, schema: type[T],
                        audit: AuditWriter, node: str, case_id: str | None,
                        model_id: str = "", pricing: tuple[float, float] = (0.0, 0.0)) -> T:
    prompt = (f"{user}\n\nReturn ONLY a JSON object matching this JSON Schema "
              f"(no prose, no code fences):\n{json.dumps(schema.model_json_schema())}")
    messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
    last_err: Exception | None = None
    for _attempt in range(2):
        t0 = time.monotonic()
        response = None
        for retry in range(3):  # provider errors: tiered retry with backoff (spec 10);
            try:                # final failure propagates and the runner parks the case
                response = await model.ainvoke(messages)
                break
            except Exception:
                if retry == 2:
                    raise
                await asyncio.sleep(2**retry)
        usage = getattr(response, "usage_metadata", None) or {}
        tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        await audit.log_llm(
            case_id, node=node, model_id=model_id, tokens_in=tin, tokens_out=tout,
            cost_usd=(tin * pricing[0] + tout * pricing[1]) / 1_000_000,
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_hash=_h("".join(str(m.content) for m in messages)),
            response_hash=_h(str(response.content)))
        try:
            return schema.model_validate(extract_json(str(response.content)))
        except (LlmJsonError, ValidationError, json.JSONDecodeError) as err:
            last_err = err
            messages += [response, HumanMessage(
                content=f"That was invalid ({err.__class__.__name__}). "
                        "Return ONLY the corrected JSON object.")]
    raise LlmJsonError(f"node {node}: response unparseable after one repair: {last_err}")
