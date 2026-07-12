from typing import Protocol

INCIDENT_WORDS = (
    "down", "error", "fail", "slow", "latency", "timeout", "5xx", "500", "crash",
    "outage", "unavailable", "broken", "degraded", "cannot", "can't", "spike",
)


class IncidentScorer(Protocol):
    async def score(self, text: str) -> float: ...


class HeuristicScorer:
    async def score(self, text: str) -> float:
        t = text.lower()
        hits = sum(1 for w in INCIDENT_WORDS if w in t)
        return min(1.0, 0.25 * hits)


INCIDENT_THRESHOLD = 0.3
