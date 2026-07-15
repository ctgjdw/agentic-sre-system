import asyncio

import httpx
import pytest
import respx

from sre_gateway.audit import AuditWriter
from sre_gateway.intake.grafana import labels_fingerprint
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.poller_grafana import GrafanaPoller
from sre_gateway.intake.service import IntakeService
from sre_gateway.settings import Settings

ALERTS = {"data": {"alerts": [{
    "labels": {"alertname": "KeycloakDown", "service": "keycloak", "severity": "sev1"},
    "annotations": {"summary": "Keycloak is not responding"},
    "state": "Alerting", "activeAt": "2026-07-11T14:00:00Z", "value": "0"}]}}

# Confirmed against the real Grafana Cloud stack: on a stack with no alert rules, the
# alerts key is present but null rather than an empty list or missing entirely.
ALERTS_NULL = {"data": {"alerts": None}}


def _poller(db, settings=None):
    audit = AuditWriter(db)
    intake = IntakeService(db, audit, NoiseControl(db, audit))
    s = settings or Settings(database_url="unused", grafana_url="https://stack.grafana.net",
                             grafana_sa_token="tok")
    return GrafanaPoller(s, intake, audit, health={})


@respx.mock
async def test_poll_opens_case_once_then_dedupes(db):
    route = respx.get(
        "https://stack.grafana.net/api/prometheus/grafana/api/v1/alerts"
    ).mock(return_value=httpx.Response(200, json=ALERTS))
    poller = _poller(db)
    r1 = await poller.poll_once()
    r2 = await poller.poll_once()
    assert route.called
    assert [x.action for x in r1] == ["open"]
    assert [x.action for x in r2] == ["suppress"]  # debounce window


@respx.mock
async def test_poll_handles_null_alerts_without_error(db):
    respx.get(
        "https://stack.grafana.net/api/prometheus/grafana/api/v1/alerts"
    ).mock(return_value=httpx.Response(200, json=ALERTS_NULL))
    poller = _poller(db)
    results = await poller.poll_once()
    assert results == []


def test_fingerprint_is_label_stable():
    a = labels_fingerprint({"alertname": "X", "service": "s"})
    b = labels_fingerprint({"service": "s", "alertname": "X"})
    assert a == b and a.startswith("grafana:")


async def test_run_backs_off_on_error_then_resets_and_reraises_cancel(db, monkeypatch):
    # The supervised loop is where a crash would take the poller down for the process
    # lifetime, so exercise it: errors double the backoff (capped), success resets it and
    # marks health ok, and CancelledError propagates cleanly.
    poller = _poller(db)  # grafana_poll_interval_s defaults to 30
    calls, sleeps = {"n": 0}, []

    async def fake_poll_once():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")
        return []

    async def fake_sleep(secs):
        sleeps.append(secs)
        if len(sleeps) >= 4:
            raise asyncio.CancelledError()

    monkeypatch.setattr(poller, "poll_once", fake_poll_once)
    monkeypatch.setattr("sre_gateway.intake.poller_grafana.asyncio.sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await poller.run()
    assert sleeps[:3] == [60, 120, 30]   # 30*2, 60*2, then reset to interval on success
    assert poller.health["grafana_poller"] == "ok"
