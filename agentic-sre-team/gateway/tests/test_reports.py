from sre_gateway.audit import AuditWriter
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.reports import handle_report
from sre_gateway.intake.scorer import HeuristicScorer
from sre_gateway.intake.service import IntakeService


def _intake(db):
    audit = AuditWriter(db)
    return IntakeService(db, audit, NoiseControl(db, audit))


async def test_incident_like_report_opens_case(db):
    reply = await handle_report(_intake(db), HeuristicScorer(),
                                "admin console is down, 500 errors everywhere", "@minli")
    assert "Opened CASE-0001" in reply


async def test_chatter_gets_canned_reply_and_no_case(db):
    intake = _intake(db)
    reply = await handle_report(intake, HeuristicScorer(), "lunch anyone?", "@minli")
    assert "not opening a case" in reply.lower()
    from sqlalchemy import func, select

    from sre_gateway.db.models import Case

    async with db() as s:
        count = (await s.execute(select(func.count(Case.id)))).scalar_one()
    assert count == 0
