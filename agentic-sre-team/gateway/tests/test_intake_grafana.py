import hashlib
import hmac
import json
from pathlib import Path

from sre_gateway.intake.grafana import normalize_grafana, verify_grafana_hmac

FIXTURE = json.loads((Path(__file__).parent / "fixtures/grafana_webhook.json").read_text())


def test_normalize_produces_one_signal_per_firing_alert():
    signals = normalize_grafana(FIXTURE)
    assert len(signals) == 1
    s = signals[0]
    assert s.source == "grafana"
    assert s.kind == "incident"
    assert s.fingerprint == "grafana:c4a2f1d9e8b7a3f0"
    assert s.summary == "Error rate spike on admin-server /api/v1/users"
    assert s.labels["service"] == "admin-server"
    assert s.payload["generatorURL"].startswith("https://")


def test_resolved_alerts_are_skipped():
    payload = dict(FIXTURE)
    payload["alerts"] = [dict(FIXTURE["alerts"][0], status="resolved")]
    assert normalize_grafana(payload) == []


def test_hmac_verify_roundtrip():
    body = b'{"x":1}'
    sig = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert verify_grafana_hmac("topsecret", body, sig) is True
    assert verify_grafana_hmac("topsecret", body, "deadbeef") is False
    assert verify_grafana_hmac("topsecret", body, None) is False
