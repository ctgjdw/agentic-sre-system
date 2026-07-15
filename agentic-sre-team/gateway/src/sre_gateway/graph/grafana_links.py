import json
from urllib.parse import quote

from sre_gateway.settings import Settings

# Holmes toolset_name -> which datasource an evidence query belongs to. Covers both the
# real 0.36.0 toolset ids (prometheus/metrics, grafana/loki) and the bare names the fake
# fixtures use (prometheus, loki).
_PROM = {"prometheus", "prometheus/metrics"}
_LOKI = {"loki", "grafana/loki"}


class LinkBuilder:
    """Builds Grafana Explore deep links so an operator can open an evidence query with
    one click (wireframe screen 2, note 11). URL shape matches what the stack's own
    deeplink generator emits (`?left=<url-encoded state>`), verified against Grafana 13."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def url_for(self, toolset: str, invocation: str) -> str | None:
        if not self.settings.grafana_url or not invocation:
            return None
        if toolset in _PROM:
            uid = self.settings.grafana_prom_ds_uid
        elif toolset in _LOKI:
            uid = self.settings.grafana_loki_ds_uid
        else:
            uid = None
        if not uid:
            return None
        left = {"datasource": uid,
                "queries": [{"refId": "A", "expr": invocation, "datasource": {"uid": uid}}],
                "range": {"from": "now-1h", "to": "now"}}
        return f"{self.settings.grafana_url}/explore?left={quote(json.dumps(left), safe='')}"
