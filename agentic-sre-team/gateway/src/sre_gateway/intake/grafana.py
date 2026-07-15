import hashlib
import hmac

from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal, fingerprint_of

# Grafana 11.x signs webhook bodies with HMAC-SHA256 in this header when an
# HMAC secret is configured on the contact point. Docs-check happens in Task 48
# when the contact point is provisioned; header name is config below.
SIGNATURE_HEADER = "X-Grafana-Alerting-Signature"


def verify_grafana_hmac(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    # header may arrive as "t=...,v1=<hex>" or bare hex; accept the trailing token
    candidate = signature_header.split("=")[-1].strip()
    return hmac.compare_digest(expected, candidate)


def labels_fingerprint(labels: dict) -> str:
    # Shared by the webhook and poller intake paths (instead of Grafana's own per-alert
    # "fingerprint" field) so both dedupe against each other on the same label set.
    return "grafana:" + fingerprint_of(*sorted(f"{k}={v}" for k, v in labels.items()))


def normalize_grafana(payload: dict) -> list[Signal]:
    signals: list[Signal] = []
    for alert in payload.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        labels = dict(alert.get("labels", {}))
        annotations = alert.get("annotations", {})
        signals.append(Signal(
            source=SignalSource.grafana,
            reporter="grafana-alerting",
            kind=CaseKind.incident,
            fingerprint=labels_fingerprint(labels),
            summary=annotations.get("summary") or labels.get("alertname", "Grafana alert"),
            labels=labels,
            payload={
                "labels": labels,
                "annotations": annotations,
                "startsAt": alert.get("startsAt"),
                "generatorURL": alert.get("generatorURL"),
                "groupKey": payload.get("groupKey"),
            },
        ))
    return signals
