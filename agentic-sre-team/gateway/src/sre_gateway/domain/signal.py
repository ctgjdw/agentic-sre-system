import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from sre_gateway.domain.enums import CaseKind, SignalSource


class Signal(BaseModel):
    source: SignalSource
    reporter: str = ""
    kind: CaseKind = CaseKind.incident
    fingerprint: str
    summary: str
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def fingerprint_of(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
