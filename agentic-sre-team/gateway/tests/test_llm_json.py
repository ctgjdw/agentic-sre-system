import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sqlalchemy import select

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import AuditEvent
from sre_gateway.llm.json_call import LlmJsonError, call_llm_json, extract_json
from sre_gateway.llm.scripted import ScriptedChatModel, reset_scripts


class Out(BaseModel):
    answer: str
    score: float


def _script(tmp_path, node, items):
    (tmp_path / f"{node}.json").write_text(json.dumps(items))
    reset_scripts()
    return ScriptedChatModel(node=node, script_dir=tmp_path)


class _FlakyModel:
    """Minimal ainvoke-only stub: raises a generic (transient-like) exception
    `fail_times` times, then returns a valid AIMessage. Used to verify the
    provider-retry loop still retries-with-backoff for non-deterministic errors."""

    def __init__(self, fail_times: int, content: str) -> None:
        self.fail_times = fail_times
        self.content = content
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient provider hiccup")
        return AIMessage(content=self.content, usage_metadata={
            "input_tokens": 5, "output_tokens": 5, "total_tokens": 10})


def _patch_sleep(monkeypatch) -> list[float]:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleep_calls


def test_extract_json_strips_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    # A wrapping fence is discarded by the brace slice, but fences embedded INSIDE a
    # JSON string value must survive untouched (Phase 3's remediate node emits this
    # shape for runbook_md) -- regression guard for stripping fences globally.
    assert extract_json('{"runbook_md": "```bash\\nrestart\\n```"}') == {
        "runbook_md": "```bash\nrestart\n```"
    }


async def test_happy_path_parses_and_audits(db, tmp_path):
    model = _script(tmp_path, "triage", [{"answer": "ok", "score": 0.9}])
    out = await call_llm_json(model, system="s", user="u", schema=Out,
                              audit=AuditWriter(db), node="triage", case_id=None,
                              model_id="fake", pricing=(1.0, 2.0))
    assert out.answer == "ok"
    async with db() as s:
        events = (await s.execute(select(AuditEvent))).scalars().all()
    assert len(events) == 1 and events[0].event_type == "llm_call"
    assert events[0].payload["tokens_in"] == 50


async def test_repair_retry_recovers(db, tmp_path):
    model = _script(tmp_path, "triage", ["not json at all", {"answer": "fixed", "score": 1.0}])
    out = await call_llm_json(model, system="s", user="u", schema=Out,
                              audit=AuditWriter(db), node="triage", case_id=None)
    assert out.answer == "fixed"
    async with db() as s:
        events = (await s.execute(select(AuditEvent))).scalars().all()
    # Every attempt is audited, including the one that failed to parse -- pins the
    # every-attempt-audited contract so moving audit.log_llm after the parse (which
    # would silently drop the failed attempt's audit row) fails loudly here.
    assert len(events) == 2


async def test_double_failure_raises(db, tmp_path):
    model = _script(tmp_path, "triage", ["junk", "more junk"])
    with pytest.raises(LlmJsonError):
        await call_llm_json(model, system="s", user="u", schema=Out,
                            audit=AuditWriter(db), node="triage", case_id=None)


def test_script_exhaustion_is_loud(tmp_path):
    model = _script(tmp_path, "triage", [])
    with pytest.raises(IndexError, match="triage"):
        model.invoke("hi")


async def test_transient_error_retries_with_backoff_then_recovers(db, monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    model = _FlakyModel(fail_times=2, content=json.dumps({"answer": "ok", "score": 1.0}))
    out = await call_llm_json(model, system="s", user="u", schema=Out,
                              audit=AuditWriter(db), node="triage", case_id=None)
    assert out.answer == "ok"
    assert model.calls == 3
    assert sleep_calls == [1, 2]  # backoff attempted for both transient failures


async def test_deterministic_error_skips_retry_and_backoff(db, tmp_path, monkeypatch):
    sleep_calls = _patch_sleep(monkeypatch)
    model = _script(tmp_path, "triage", [])  # empty script -> ainvoke raises IndexError
    with pytest.raises(IndexError, match="triage"):
        await call_llm_json(model, system="s", user="u", schema=Out,
                            audit=AuditWriter(db), node="triage", case_id=None)
    # Without the fix this would have retried twice with real asyncio.sleep backoff
    # before surfacing; a deterministic script-exhaustion error must surface immediately.
    assert sleep_calls == []
