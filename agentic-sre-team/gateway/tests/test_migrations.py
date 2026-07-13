import pytest
from sqlalchemy import text

from sre_gateway.db.models import AuditEvent


async def test_all_tables_exist(db):
    async with db() as session:
        res = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        )
        names = {r[0] for r in res}
    expected = {
        "cases", "signals", "hypotheses", "evidence", "artifacts", "approvals",
        "audit_events", "runbooks", "repos", "case_learnings", "chat_threads",
        "chat_messages", "case_events", "settings",
    }
    assert expected <= names


async def test_audit_is_append_only(db):
    async with db() as session:
        session.add(AuditEvent(actor="system", event_type="intake", payload={}))
        await session.commit()
        with pytest.raises(Exception, match="append-only"):
            await session.execute(text("UPDATE audit_events SET actor='x'"))
            await session.commit()

    # fresh session: the prior transaction is aborted after the raised exception
    async with db() as session:
        session.add(AuditEvent(actor="system", event_type="intake", payload={}))
        await session.commit()
        with pytest.raises(Exception, match="append-only"):
            await session.execute(text("DELETE FROM audit_events"))
            await session.commit()
