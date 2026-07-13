from pathlib import Path

import pytest

from sre_gateway.llm.factory import ModelFactory, load_models_config

CONFIG_DIR = Path(__file__).parents[2] / "config"


def test_local_profile_parses(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-x")
    cfg = load_models_config(CONFIG_DIR / "models.yaml")
    assert cfg.tiers["frontier"].provider == "vertex-anthropic"
    assert cfg.vertex["project"] == "proj-x"
    f = ModelFactory(cfg)
    assert f.holmes_model("medium") == "vertex_ai/gemini-2.5-flash"
    model_id, (pin, pout) = f.describe("small")
    assert model_id == "gemini-2.5-flash" and pin == 0.30 and pout == 2.50


def test_unknown_tier_raises():
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    with pytest.raises(KeyError):
        ModelFactory(cfg).describe("gigantic")


async def test_fake_embeddings_deterministic_unit_vectors():
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    f = ModelFactory(cfg)
    a1 = (await f.embed(["keycloak down"]))[0]
    a2 = (await f.embed(["keycloak down"]))[0]
    b = (await f.embed(["something else"]))[0]
    assert a1 == a2 and a1 != b and len(a1) == 768
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-6
