from sre_gateway.domain.enums import CaseKind, SignalSource
from sre_gateway.domain.signal import Signal, fingerprint_of
from sre_gateway.intake.scorer import INCIDENT_THRESHOLD, IncidentScorer
from sre_gateway.intake.service import IntakeService

CANNED = ("Doesn't look like an incident; not opening a case. "
          "Reply with more detail if it is one.")


async def handle_report(intake: IntakeService, scorer: IncidentScorer,
                        text: str, reporter: str) -> str:
    if await scorer.score(text) < INCIDENT_THRESHOLD:
        return CANNED
    normalized = " ".join(text.lower().split())[:120]
    result = await intake.ingest(Signal(
        source=SignalSource.telegram, reporter=reporter, kind=CaseKind.incident,
        fingerprint=fingerprint_of("telegram", normalized),
        summary=f"Report from {reporter}: {text[:180]}",
        payload={"text": text, "reporter": reporter}))
    if result.action == "open":
        return (f"Report received. Opened {result.display_id}, triaging now - "
                f"you will get updates here.")
    if result.action == "attach":
        return ("Your report was merged into an existing case as a supporting signal "
                "(matching symptoms, same window).")
    return "Already tracked; suppressed as a duplicate of an open case."
