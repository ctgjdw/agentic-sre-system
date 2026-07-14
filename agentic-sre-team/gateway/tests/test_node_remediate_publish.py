import pytest
from sqlalchemy import select

from sre_gateway.db.models import Artifact, Case, CaseLearning, Runbook
from sre_gateway.graph.nodes.remediate import make_remediate
from sre_gateway.graph.nodes.publish import make_publish


async def _seed_with_rca(db, deps):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error spike", severity=2)
        s.add(c)
        await s.flush()
        art = Artifact(case_id=c.id, kind="rca", version=1, body_md="## rca",
                       structured={"claims": [], "confidence": 0.8})
        s.add(art)
        await s.commit()
        return c, art


async def test_remediate_persists_runbook(deps, db):
    case, rca_art = await _seed_with_rca(db, deps)
    update = await make_remediate(deps)({
        "case_id": case.id, "kind": "incident", "title": case.title,
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured}})
    assert update["runbook"]["version"] == 1
    async with db() as s:
        art = await s.get(Artifact, update["runbook"]["artifact_id"])
    assert art.kind == "runbook" and "Feature-flag role badges off" in art.body_md


async def test_publish_closes_indexes_and_learns(deps, db):
    case, rca_art = await _seed_with_rca(db, deps)
    rb_update = await make_remediate(deps)({
        "case_id": case.id, "kind": "incident", "title": case.title,
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured}})
    await make_publish(deps)({
        "case_id": case.id, "display_id": "CASE-0001", "title": case.title,
        "hypotheses": [{"hid": "H2", "statement": "n+1", "status": "supported",
                        "confidence": 0.8},
                       {"hid": "H3", "statement": "cpu", "status": "refuted",
                        "confidence": 0.05}],
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured},
        "runbook": rb_update["runbook"]})
    async with db() as s:
        refreshed = await s.get(Case, case.id)
        runbooks = (await s.execute(select(Runbook))).scalars().all()
        learnings = (await s.execute(select(CaseLearning))).scalars().all()
    assert refreshed.status == "closed" and refreshed.closed_at is not None
    assert len(runbooks) == 1 and runbooks[0].source_case_id == case.id
    assert len(learnings) == 1 and "N+1" in learnings[0].confirmed_root_cause
    assert any("published" in m["text"].lower() for m in deps.channel.sent)


async def test_publish_indexes_and_learns_before_announcing_and_closing(deps, db, monkeypatch):
    # Indexing/learning must happen BEFORE the channel announce and the close: if the
    # learnings LLM call fails after Telegram already saw "published", the channel is
    # lying about the case being done, and a retry re-indexes a duplicate runbook.
    case, rca_art = await _seed_with_rca(db, deps)
    rb_update = await make_remediate(deps)({
        "case_id": case.id, "kind": "incident", "title": case.title,
        "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured}})

    async def _boom(*args, **kwargs):
        raise RuntimeError("learnings llm down")

    monkeypatch.setattr("sre_gateway.graph.nodes.publish.call_llm_json", _boom)

    with pytest.raises(RuntimeError):
        await make_publish(deps)({
            "case_id": case.id, "display_id": "CASE-0001", "title": case.title,
            "hypotheses": [{"hid": "H2", "statement": "n+1", "status": "supported",
                            "confidence": 0.8}],
            "rca": {"artifact_id": rca_art.id, "version": 1, "structured": rca_art.structured},
            "runbook": rb_update["runbook"]})

    assert deps.channel.sent == []  # nothing announced before the failure
    async with db() as s:
        refreshed = await s.get(Case, case.id)
    assert refreshed.status != "closed" and refreshed.closed_at is None
