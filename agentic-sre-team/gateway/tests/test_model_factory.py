from pathlib import Path

import pytest

from sre_gateway.llm.factory import ModelFactory, ModelsConfig, load_models_config

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


def test_non_fake_tier_missing_pricing_raises():
    # A tier's model id drifting out of sync with the pricing table (e.g. Task 25
    # bumping a model id without updating pricing) must fail fast at construction
    # instead of silently zeroing cost_usd and disarming the daily spend cap.
    cfg = ModelsConfig.model_validate({
        "tiers": {"small": {"provider": "vertex-gemini", "model": "gemini-9000", "params": {}}},
        "embeddings": {"provider": "fake", "model": "hash", "dim": 8},
        "pricing": {},
    })
    with pytest.raises(ValueError, match="gemini-9000"):
        ModelFactory(cfg)


def test_fake_profile_tiers_are_exempt_from_pricing():
    # The fake profile ships pricing: {} for every tier (all provider: fake) -- must
    # stay legal, since it is the no-network test/dev profile.
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    assert cfg.pricing == {}
    ModelFactory(cfg)  # must not raise


async def test_fake_embeddings_deterministic_unit_vectors():
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    f = ModelFactory(cfg)
    a1 = (await f.embed(["keycloak down"]))[0]
    a2 = (await f.embed(["keycloak down"]))[0]
    b = (await f.embed(["something else"]))[0]
    assert a1 == a2 and a1 != b and len(a1) == 768
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-6


def test_fake_chat_returns_scripted_model(tmp_path):
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    model = ModelFactory(cfg, script_dir=tmp_path).chat("small", "triage")
    assert type(model).__name__ == "ScriptedChatModel"
