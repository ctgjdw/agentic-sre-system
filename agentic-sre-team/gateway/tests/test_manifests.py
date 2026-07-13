from pathlib import Path

import pytest
from pydantic import ValidationError

from sre_gateway.manifests import assert_tool_allowed, load_manifests

AGENTS_DIR = Path(__file__).parents[2] / "config/agents"


def test_loads_all_agents_and_validates_tools():
    m = load_manifests(AGENTS_DIR)
    assert set(m) >= {"triage", "workers", "synthesize", "rca", "verify",
                      "remediate", "learnings", "chat"}
    assert m["triage"].tier == "small"
    assert "runbook_search" in m["triage"].tools


def test_default_deny(tmp_path):
    m = load_manifests(AGENTS_DIR)
    assert_tool_allowed(m, "triage", "runbook_search")  # declared: no raise
    with pytest.raises(PermissionError):
        assert_tool_allowed(m, "rca", "runbook_search")  # not declared for rca
    with pytest.raises(PermissionError):
        assert_tool_allowed(m, "ghost-agent", "runbook_search")  # unknown agent


def test_unknown_tool_fails_at_load(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "agent: bad\ntier: small\ntools: [delete_everything]\nbudgets: {usd_per_day: 1}\n")
    with pytest.raises(ValueError, match="delete_everything"):
        load_manifests(tmp_path)


def test_invalid_tier_fails_at_load(tmp_path):
    # A typo'd tier must explode at manifest-load time, not as a mid-case KeyError
    # inside factory.chat() when the case reaches that agent.
    (tmp_path / "typo.yaml").write_text(
        "agent: typo\ntier: smol\ntools: []\nbudgets: {usd_per_day: 1}\n")
    with pytest.raises(ValidationError, match="tier"):
        load_manifests(tmp_path)
