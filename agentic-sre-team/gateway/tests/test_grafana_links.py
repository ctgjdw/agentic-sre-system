import json
from urllib.parse import parse_qs, urlparse

from sre_gateway.graph.grafana_links import LinkBuilder
from sre_gateway.settings import Settings


def _links() -> LinkBuilder:
    return LinkBuilder(Settings(database_url="x", grafana_url="https://g.example.net",
                                grafana_prom_ds_uid="prom-uid",
                                grafana_loki_ds_uid="loki-uid"))


def _left(url: str) -> dict:
    # The Explore state rides in the `left` query param as url-encoded JSON (the shape the
    # stack's own deeplink generator emits). Decode it rather than substring-match, since
    # a query with quotes is json-escaped (\") before url-encoding.
    return json.loads(parse_qs(urlparse(url).query)["left"][0])


def test_prometheus_query_builds_explore_url():
    url = _links().url_for("prometheus", 'up{job="keycloak"}')
    assert url.startswith("https://g.example.net/explore?")
    left = _left(url)
    assert left["datasource"] == "prom-uid"
    assert left["queries"][0]["expr"] == 'up{job="keycloak"}'
    assert left["queries"][0]["datasource"]["uid"] == "prom-uid"


def test_real_holmes_toolset_names_are_mapped():
    # Real 0.36.0 toolset ids carry a suffix; the fake fixtures use the bare name.
    assert _left(_links().url_for("prometheus/metrics", "up"))["datasource"] == "prom-uid"
    assert _left(_links().url_for("grafana/loki", '{app="admin"}'))["datasource"] == "loki-uid"
    assert _left(_links().url_for("loki", '{app="admin"}'))["datasource"] == "loki-uid"


def test_unknown_toolset_returns_none():
    assert _links().url_for("docker", "docker ps") is None
    assert _links().url_for("github", "gh pr list") is None


def test_returns_none_without_config_or_query():
    assert LinkBuilder(Settings(database_url="x")).url_for("prometheus", "up") is None
    assert _links().url_for("prometheus", "") is None
