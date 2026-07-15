import asyncio
import logging

import httpx

from sre_gateway.audit import AuditWriter
from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal
from sre_gateway.intake.grafana import labels_fingerprint
from sre_gateway.intake.service import IngestResult, IntakeService
from sre_gateway.settings import Settings

logger = logging.getLogger("sre.poller.grafana")
ALERTS_PATH = "/api/prometheus/grafana/api/v1/alerts"


class GrafanaPoller:
    def __init__(self, settings: Settings, intake: IntakeService, audit: AuditWriter,
                 health: dict) -> None:
        self.settings = settings
        self.intake = intake
        self.audit = audit
        self.health = health

    async def poll_once(self) -> list[IngestResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(
                f"{self.settings.grafana_url}{ALERTS_PATH}",
                headers={"Authorization": f"Bearer {self.settings.grafana_sa_token}"})
            res.raise_for_status()
        results: list[IngestResult] = []
        # On stacks with no alert rules, Grafana Cloud returns {"data": {"alerts": null}} -
        # the key is present but null, not missing - so `.get("alerts", [])` would return
        # None and blow up the `for` below. Coerce both `data` and `alerts` null-safely.
        data = res.json().get("data") or {}
        for alert in (data.get("alerts") or []):
            if alert.get("state") not in ("Alerting", "firing"):
                continue
            labels = dict(alert.get("labels", {}))
            annotations = alert.get("annotations", {})
            results.append(await self.intake.ingest(Signal(
                source=SignalSource.grafana, reporter="grafana-poller",
                kind=CaseKind.incident, fingerprint=labels_fingerprint(labels),
                summary=annotations.get("summary") or labels.get("alertname", "alert"),
                labels=labels,
                payload={"labels": labels, "annotations": annotations,
                         "activeAt": alert.get("activeAt"), "via": "poller"})))
        return results

    async def run(self) -> None:
        backoff = self.settings.grafana_poll_interval_s
        while True:
            try:
                await self.poll_once()
                self.health["grafana_poller"] = "ok"
                backoff = self.settings.grafana_poll_interval_s
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.health["grafana_poller"] = f"error: {err}"[:120]
                logger.warning("grafana poll failed: %s", err)
                backoff = min(backoff * 2, 300)
            await asyncio.sleep(backoff)
