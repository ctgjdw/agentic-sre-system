import json
from pathlib import Path

from sre_gateway.audit import AuditWriter
from sre_gateway.intake.scorer import INCIDENT_THRESHOLD, HeuristicScorer
from sre_gateway.intake.scorer_llm import LlmScorer
from sre_gateway.llm.factory import ModelFactory, load_models_config
from sre_gateway.llm.scripted import reset_scripts

CONFIG_DIR = Path(__file__).parents[2] / "config"


def _factory(tmp_path, score: float) -> ModelFactory:
    (tmp_path / "intake-scorer.json").write_text(json.dumps([{"score": score}]))
    reset_scripts()
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    return ModelFactory(cfg, script_dir=tmp_path)


async def test_llm_scorer_returns_llm_score_on_happy_path(db, tmp_path):
    factory = _factory(tmp_path, 0.83)
    scorer = LlmScorer(factory, AuditWriter(db))
    score = await scorer.score("payments API is throwing 500s for everyone")
    assert score == 0.83


async def test_llm_scorer_falls_back_to_heuristic_on_error(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr("sre_gateway.intake.scorer_llm.call_llm_json", _raise)
    cfg = load_models_config(CONFIG_DIR / "models.fake.yaml")
    scorer = LlmScorer(ModelFactory(cfg), audit=None)

    incident_text = "checkout is down, 500 errors everywhere"
    chatter_text = "lunch anyone?"
    heuristic = HeuristicScorer()

    assert await scorer.score(incident_text) == await heuristic.score(incident_text)
    assert await scorer.score(chatter_text) == await heuristic.score(chatter_text)


async def test_heuristic_scorer_flags_incident_words_above_threshold():
    heuristic = HeuristicScorer()
    assert await heuristic.score("prod is down, 500 errors and timeouts") >= INCIDENT_THRESHOLD


async def test_heuristic_scorer_scores_chatter_below_threshold():
    heuristic = HeuristicScorer()
    assert await heuristic.score("lunch anyone?") < INCIDENT_THRESHOLD
