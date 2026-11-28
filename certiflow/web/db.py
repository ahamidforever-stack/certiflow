"""Database models (SQLAlchemy 2.0). PostgreSQL in production, SQLite for development and tests.
Schema changes go through Alembic (migrations/)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)   # = asset library user id
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))          # admin | certified_translator | reviewer
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    ui_language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    title: Mapped[str] = mapped_column(String(300))
    source_language: Mapped[str] = mapped_column(String(10))
    target_language: Mapped[str] = mapped_column(String(10))
    stamp: Mapped[str] = mapped_column(String(20))         # certified | office (required, no default)
    page_order: Mapped[str] = mapped_column(String(40), default="translation_then_source")
    document_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    # queued | running | waiting_glossary | waiting_review | releasing | released | failed | blocked
    stage: Mapped[str] = mapped_column(String(40), default="created")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # source pages (from Intake)
    client: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)  # for glossary memory
    keep: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # legal hold: never auto-deleted
    purged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # files deleted
    documents: Mapped[list["JobDocument"]] = relationship(back_populates="job", order_by="JobDocument.idx",
                                                          cascade="all, delete-orphan")


class JobDocument(Base):
    __tablename__ = "job_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    doc_key: Mapped[str] = mapped_column(String(10))       # d01, d02 ... (pipeline id)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    source_language: Mapped[str] = mapped_column(String(10))
    target_language: Mapped[str] = mapped_column(String(10))
    job: Mapped[Job] = relationship(back_populates="documents")


class JobEvent(Base):
    """Progress events for the live pipeline view (SSE). No document text in here."""
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class LlmUsage(Base):
    """One model call, copied from the job's audit log for the cost dashboard (numbers only, no text)."""
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    document: Mapped[str] = mapped_column(String(10), default="")
    agent: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class ClientTerm(Base):
    """Glossary memory: a term confirmed for a client and language pair, offered again in that client's next jobs."""
    __tablename__ = "client_terms"
    __table_args__ = (UniqueConstraint("client_key", "source_language", "target_language", "source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    client_key: Mapped[str] = mapped_column(String(200), index=True)     # normalised client name
    client: Mapped[str] = mapped_column(String(200))                     # as last typed
    source_language: Mapped[str] = mapped_column(String(10))
    target_language: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(500))
    target: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="term")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(80), default="")
    job_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)   # last job that confirmed it
    uses: Mapped[int] = mapped_column(Integer, default=1)


def client_key(name: Optional[str]) -> str:
    return " ".join((name or "").split()).casefold()[:200]


class LoginAttempt(Base):
    """One sign-in try (for lockout and rate limiting). Kept 30 days; no password, only the typed username."""
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)


class UserSession(Base):
    """A signed-in browser. The cookie names this row; deleting or revoking it signs the browser out."""
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(200), default="")


class AdminEvent(Base):
    """Who changed which user account and how (never passwords)."""
    __tablename__ = "admin_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))       # user_created | user_updated | password_reset | ...
    target: Mapped[str] = mapped_column(String(80), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


ROLES = ("admin", "certified_translator", "reviewer")


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; treat them as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def revoke_sessions(s, user_id: int, keep: Optional[str] = None) -> int:
    """Revoke every open session of a user (except ``keep``). Caller commits."""
    n = 0
    for row in s.scalars(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))):
        if row.id != keep:
            row.revoked_at = utcnow()
            n += 1
    return n


_engines: dict[str, object] = {}


def engine_for(url: str):
    if url not in _engines:
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engines[url] = create_engine(url, **kw)
    return _engines[url]


def session_factory(url: str):
    return sessionmaker(bind=engine_for(url), expire_on_commit=False)


def user_by_username(s, username: str) -> Optional[User]:
    return s.scalar(select(User).where(User.username == username))
