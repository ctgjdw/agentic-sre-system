import json
from pathlib import Path

import httpx
import pytest

import sre_gateway.testing.fake_holmes as fh
from sre_gateway.holmes.client import HolmesClient

FIXTURES = Path(__file__).parent / "fixtures/holmes/incident_error_storm"


@pytest.fixture
def client(monkeypatch) -> HolmesClient:
    monkeypatch.setenv("FAKE_HOLMES_DIR", str(FIXTURES))
    transport = httpx.ASGITransport(app=fh.app)
    return HolmesClient("http://fake", client=httpx.AsyncClient(transport=transport,
                                                                base_url="http://fake"))


async def test_non_streaming_chat_parses_tool_calls(client):
    answer = await client.chat("Domain: metrics\ninvestigate", model="fake/medium")
    assert "5xx ratio" in answer.text
    assert len(answer.tool_calls) == 2
    tc = answer.tool_calls[0]
    assert tc.toolset == "prometheus" and "kong_http_requests_total" in tc.invocation


async def test_streaming_relays_tool_events(client):
    events: list[dict] = []

    async def on_event(e: dict) -> None:
        events.append(e)

    answer = await client.chat("Domain: metrics\ninvestigate", model="fake/medium",
                               on_event=on_event)
    assert len(answer.tool_calls) == 2
    types = [e["type"] for e in events]
    assert types.count("tool_start") == 2 and types.count("tool_result") == 2


async def test_unknown_domain_is_a_clean_error(client):
    with pytest.raises(httpx.HTTPStatusError):
        await client.chat("Domain: nonsense\nx", model="fake/medium")


async def test_response_format_is_wrapped_in_json_schema_envelope():
    # The fake ignores response_format, so pin the outgoing payload shape directly: real
    # Holmes 0.36.0 requires {"type":"json_schema","json_schema":{"name",...,"schema"}},
    # not the raw model_json_schema() workers pass in. A regression here would only bite
    # against the real sidecar.
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"analysis": "{}", "tool_calls": []})

    hc = HolmesClient("http://fake", client=httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://fake"))
    await hc.chat("Domain: metrics\nx", model="m",
                  response_format={"type": "object", "properties": {"a": {"type": "string"}}})
    rf = captured["body"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "FindingsOut"
    assert rf["json_schema"]["schema"] == {"type": "object", "properties": {"a": {"type": "string"}}}
