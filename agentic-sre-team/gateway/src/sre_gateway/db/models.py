import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBED_DIM = 768


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_id: Mapped[str] = mapped_column(String(16), unique=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    phase: Mapped[str] = mapped_column(String(32), default="queued")
    title: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[int] = mapped_column(Integer, default=3)
    effort: Mapped[str] = mapped_column(String(8), default="medium")
    round: Mapped[int] = mapped_column(Integer, default=0)
    failure_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(36))
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    spend_usd: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_counter: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    source: Mapped[str] = mapped_column(String(16))
    reporter: Mapped[str] = mapped_column(String(128), default="")
    kind: Mapped[str] = mapped_column(String(24))
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    labels: Mapped[dict] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    attach_reason: Mapped[str] = mapped_column(String(32), default="opened")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    hid: Mapped[str] = mapped_column(String(8))
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|supported|refuted
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_for: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_against: Mapped[list] = mapped_column(JSONB, default=list)
    round: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_hypotheses_case_hid", "case_id", "hid", unique=True),)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    eid: Mapped[str] = mapped_column(String(8))
    worker: Mapped[str] = mapped_column(String(24))
    toolset: Mapped[str] = mapped_column(String(48))
    invocation: Mapped[str] = mapped_column(Text, default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    hypothesis_links: Mapped[list] = mapped_column(JSONB, default=list)  # [{hid, direction}]
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_evidence_case_eid", "case_id", "eid", unique=True),)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    version: Mapped[int] = mapped_column(Integer, default=1)
    structured: Mapped[dict] = mapped_column(JSONB, default=dict)
    body_md: Mapped[str] = mapped_column(Text, default="")
    body_edited_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str] = mapped_column(String(96), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    gate: Mapped[str] = mapped_column(String(12))  # rca | runbook
    decision: Mapped[str] = mapped_column(String(24))
    decided_by: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(String(12))  # ui | telegram
    annotation: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64))       # node/agent name, "system", or human id
    event_type: Mapped[str] = mapped_column(String(24), index=True)
    # llm_call | tool_call | approval | suppression | intake | publish | pause | budget | chat
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class Runbook(Base):
    __tablename__ = "runbooks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    source_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Repo(Base):
    __tablename__ = "repos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(12))  # github | gitlab
    slug: Mapped[str] = mapped_column(String(256))     # owner/name or gitlab project path
    default_branch: Mapped[str] = mapped_column(String(64), default="main")
    # env var name holding this repo's token; empty = the provider-level default token
    credential_env: Mapped[str] = mapped_column(String(64), default="")
    watch: Mapped[bool] = mapped_column(Boolean, default=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    poll_cursor: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_repos_provider_slug", "provider", "slug", unique=True),)


class CaseLearning(Base):
    __tablename__ = "case_learnings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    signal_signature: Mapped[str] = mapped_column(Text)
    confirmed_root_cause: Mapped[str] = mapped_column(Text)
    decisive_queries: Mapped[list] = mapped_column(JSONB, default=list)
    false_leads: Mapped[list] = mapped_column(JSONB, default=list)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatThread(Base):
    __tablename__ = "chat_threads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(Text, default="")
    context_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    promoted_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    budget_date: Mapped[str] = mapped_column(String(10), default="")
    spend_usd_today: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(ForeignKey("chat_threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    tool_ledger: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseEvent(Base):
    __tablename__ = "case_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_case_events_case_seq", "case_id", "seq", unique=True),)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
