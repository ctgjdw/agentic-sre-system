import json

import pytest
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


async def test_double_failure_raises(db, tmp_path):
    model = _script(tmp_path, "triage", ["junk", "more junk"])
    with pytest.raises(LlmJsonError):
        await call_llm_json(model, system="s", user="u", schema=Out,
                            audit=AuditWriter(db), node="triage", case_id=None)


def test_script_exhaustion_is_loud(tmp_path):
    model = _script(tmp_path, "triage", [])
    with pytest.raises(IndexError, match="triage"):
        model.invoke("hi")
