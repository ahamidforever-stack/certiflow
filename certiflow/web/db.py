"""Database models (SQLAlchemy 2.0). PostgreSQL in production, SQLite for development and tests.
Schema changes go through Alembic (migrations/)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
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
