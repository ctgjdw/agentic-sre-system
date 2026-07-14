from sqlalchemy import select

from sre_gateway.db.models import Artifact, Case, EvidenceRow
from sre_gateway.graph.nodes.rca import make_rca, render_rca_md
from sre_gateway.graph.nodes.verify import make_verify


async def _seed(db, eids=("E1", "E2")):
    async with db() as s:
        c = Case(display_id="CASE-0001", kind="incident", fingerprint="f", thread_id="t",
                 title="Error spike", severity=2)
        s.add(c)
        await s.flush()
        for eid in eids:
            s.add(EvidenceRow(case_id=c.id, eid=eid, worker="metrics",
                              toolset="prometheus", invocation="q", excerpt="18% at 14:02"))
        await s.commit()
        return c


async def test_rca_persists_versioned_artifact(deps, db):
    case = await _seed(db)
    update = await make_rca(deps)({"case_id": case.id, "title": case.title,
                                   "severity": 2, "hypotheses": [], "verification": None})
    assert update["rca"]["version"] == 1 and update["repair_used"] is False
    async with db() as s:
        art = (await s.execute(select(Artifact))).scalars().one()
    assert art.kind == "rca" and "Immediate mitigation" in art.body_md
    assert art.structured["confidence"] == 0.81


async def test_verify_passes_when_citations_exist(deps, db):
    case = await _seed(db)
    rca_update = await make_rca(deps)({"case_id": case.id, "title": "t", "severity": 2,
                                       "hypotheses": [], "verification": None})
    update = await make_verify(deps)({"case_id": case.id, **rca_update})
    assert update["verification"]["verified"] is True
    assert update["verification"]["checked"] == 2
    async with db() as s:
        art = await s.get(Artifact, rca_update["rca"]["artifact_id"])
    assert art.verification["verified"] is True


async def test_verify_fails_on_missing_eid_without_llm(deps, db):
    case = await _seed(db, eids=("E1",))  # E2 cited by the script but absent
    rca_update = await make_rca(deps)({"case_id": case.id, "title": "t", "severity": 2,
                                       "hypotheses": [], "verification": None})
    update = await make_verify(deps)({"case_id": case.id, **rca_update})
    v = update["verification"]
    assert v["verified"] is False
    assert any("E2" in f["reason"] for f in v["failures"])
    assert update["context_notes"]


def test_render_puts_mitigation_first():
    from sre_gateway.graph.nodes.rca import RcaOut

    out = RcaOut(mitigation_md="do X", causal_chain=[], blast_radius_md="",
                 claims=[], confidence=0.5)
    md = render_rca_md(out)
    assert md.index("Immediate mitigation") < md.index("Root cause")
