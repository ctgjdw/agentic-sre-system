from datetime import UTC, datetime, timedelta
from pathlib import Path

from sre_gateway.audit import AuditWriter
from sre_gateway.db.models import Case, SignalRow
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.grouping import CorrelationGrouping, load_grouping
from sre_gateway.intake.noise import NoiseControl

CONFIG = Path(__file__).parents[2] / "config/grouping.yaml"


def _grouping() -> CorrelationGrouping:
    return CorrelationGrouping(load_grouping(CONFIG))


async def _case_with_signal(db, labels, age_s=30, fp="grafana:kc-down",
                            kind="incident", source="grafana") -> str:
    async with db() as s:
        c = Case(display_id="CASE-0001", kind=kind, fingerprint=fp, thread_id="t")
        s.add(c)
        await s.flush()
        s.add(SignalRow(case_id=c.id, source=source, kind=kind, fingerprint=fp,
                        labels=labels,
                        received_at=datetime.now(UTC) - timedelta(seconds=age_s)))
        await s.commit()
        return c.id


async def test_cross_signature_same_service_groups(db):
    case_id = await _case_with_signal(db, {"service": "keycloak"})
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:5xx-admin",
                               summary="admin-server 5xx", labels={"service": "keycloak"}))
    assert d.action == "attach" and d.case_id == case_id and d.reason == "grouped"


async def test_outside_window_opens_new_case(db):
    await _case_with_signal(db, {"service": "keycloak"}, age_s=600)
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:5xx-admin",
                               summary="x", labels={"service": "keycloak"}))
    assert d.action == "open"


async def test_missing_label_never_groups(db):
    await _case_with_signal(db, {"service": "keycloak"})
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:other",
                               summary="x", labels={}))
    assert d.action == "open"


async def test_never_groups_across_case_kinds(db):
    # Open pipeline-failure case whose signal shares service=keycloak within the window.
    await _case_with_signal(db, {"service": "keycloak"}, fp="github:ci-fail",
                            kind="pipeline_failure", source="github")
    nc = NoiseControl(db, AuditWriter(db), grouping=_grouping())
    # Incident signal: same label + window, different fingerprint - only the kind differs.
    d = await nc.decide(Signal(source="grafana", fingerprint="grafana:5xx-admin",
                               summary="admin-server 5xx", labels={"service": "keycloak"}))
    assert d.action == "open"  # must NOT attach onto the pipeline-failure case
