import httpx
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
