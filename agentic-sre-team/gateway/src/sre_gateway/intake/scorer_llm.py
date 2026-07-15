import logging

from pydantic import BaseModel, Field

from sre_gateway.audit import AuditWriter
from sre_gateway.intake.scorer import HeuristicScorer
from sre_gateway.llm.factory import ModelFactory
from sre_gateway.llm.json_call import call_llm_json

logger = logging.getLogger("sre.scorer")


class ScoreOut(BaseModel):
    score: float = Field(ge=0, le=1)


class LlmScorer:
    def __init__(self, models: ModelFactory, audit: AuditWriter) -> None:
        self.models = models
        self.audit = audit
        self._fallback = HeuristicScorer()

    async def score(self, text: str) -> float:
        try:
            model_id, pricing = self.models.describe("small")
            out = await call_llm_json(
                self.models.chat("small", "intake-scorer"),
                system=("Score how likely this chat message reports a real production "
                        "incident or outage, 0..1. Greetings, questions and chatter "
                        "score below 0.2."),
                user=text[:1000], schema=ScoreOut, audit=self.audit,
                node="intake-scorer", case_id=None, model_id=model_id, pricing=pricing)
            return out.score
        except Exception as err:
            logger.warning("llm scorer failed, using heuristic: %s", err)
            return await self._fallback.score(text)
