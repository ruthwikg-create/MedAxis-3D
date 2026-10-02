from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from ..config import BASE_DIR, env_bool
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CaseRow(Base):
    __tablename__ = "cases"
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AuditRow(Base):
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(128), default="local-user")
    action: Mapped[str] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AnalysisRow(Base):
    __tablename__ = "analyses"
    analysis_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    analysis_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class JobRow(Base):
    __tablename__ = "jobs"
    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    job_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone=True))


class AnalyticsRow(Base):
    __tablename__ = "analytics_records"
    record_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    record_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def database_url() -> str:
    default_path = (BASE_DIR / "data" / "medaxis-dev.db").resolve().as_posix()
    return os.getenv("DATABASE_URL", f"sqlite:///{default_path}")


def _engine():
    url = database_url()
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update({
            "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        })
    return create_engine(url, **kwargs)


ENGINE = _engine()
SessionLocal = sessionmaker(bind=ENGINE, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(ENGINE)


def db_kind() -> str:
    return ENGINE.url.get_backend_name()


def persistence_enabled() -> bool:
    # Local development uses SQLite persistence by default. Production can point
    # DATABASE_URL at PostgreSQL; PERSISTENCE_ENABLED=false is available only for
    # explicitly stateless demonstration environments.
    return not os.getenv("PERSISTENCE_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}


def upsert_case(meta: dict[str, Any]) -> None:
    init_db()
    with SessionLocal.begin() as session:
        row = session.get(CaseRow, meta["case_id"])
        if row is None:
            row = CaseRow(case_id=meta["case_id"], status=str(meta.get("status", "UNKNOWN")), meta_json=meta)
            session.add(row)
        else:
            row.status = str(meta.get("status", row.status))
            row.meta_json = meta
            row.updated_at = datetime.now(timezone.utc)


def delete_case(case_id: str) -> None:
    init_db()
    with SessionLocal.begin() as session:
        row = session.get(CaseRow, case_id)
        if row is not None:
            session.delete(row)
        session.query(AuditRow).filter(AuditRow.case_id == case_id).delete()
        session.query(AnalysisRow).filter(AnalysisRow.case_id == case_id).delete()
        session.query(JobRow).filter(JobRow.case_id == case_id).delete()
        session.query(AnalyticsRow).filter(AnalyticsRow.case_id == case_id).delete()


def list_cases() -> list[dict[str, Any]]:
    init_db()
    with SessionLocal() as session:
        rows = session.scalars(select(CaseRow).order_by(CaseRow.created_at.desc())).all()
        return [row.meta_json for row in rows]


def get_case(case_id: str) -> dict[str, Any] | None:
    init_db()
    with SessionLocal() as session:
        row = session.get(CaseRow, case_id)
        return row.meta_json if row else None


def audit(case_id: str, action: str, details: dict[str, Any] | None = None, username: str = "local-user") -> None:
    init_db()
    with SessionLocal.begin() as session:
        session.add(AuditRow(case_id=case_id, action=action, username=username, details=details or {}))


def read_audit(case_id: str) -> list[dict[str, Any]]:
    init_db()
    with SessionLocal() as session:
        rows = session.scalars(select(AuditRow).where(AuditRow.case_id == case_id).order_by(AuditRow.created_at.asc())).all()
        return [{"timestamp": r.created_at.isoformat(), "user": r.username, "action": r.action, "details": r.details} for r in rows]


def save_analysis(analysis_id: str, case_id: str, analysis_type: str, status: str, result: dict[str, Any]) -> None:
    init_db()
    with SessionLocal.begin() as session:
        session.merge(AnalysisRow(analysis_id=analysis_id, case_id=case_id, analysis_type=analysis_type, status=status, result=result))


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    init_db()
    with SessionLocal() as session:
        row = session.get(AnalysisRow, analysis_id)
        return row.result if row else None


def create_job(job_id: str, case_id: str, job_type: str) -> None:
    init_db()
    with SessionLocal.begin() as session:
        session.add(JobRow(job_id=job_id, case_id=case_id, job_type=job_type, status="QUEUED", progress=0.0))


def update_job(job_id: str, *, status: str | None = None, progress: float | None = None, message: str | None = None, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    init_db()
    with SessionLocal.begin() as session:
        row = session.get(JobRow, job_id)
        if row is None:
            return
        if status is not None:
            row.status = status
        if progress is not None:
            row.progress = max(0.0, min(100.0, float(progress)))
        if message is not None:
            row.message = message
        if result is not None:
            row.result = result
        if error is not None:
            row.error = error
        row.updated_at = datetime.now(timezone.utc)


def get_job(job_id: str) -> dict[str, Any] | None:
    init_db()
    with SessionLocal() as session:
        row = session.get(JobRow, job_id)
        if row is None:
            return None
        return {
            "job_id": row.job_id,
            "case_id": row.case_id,
            "job_type": row.job_type,
            "status": row.status,
            "progress": row.progress,
            "message": row.message,
            "result": row.result,
            "error": row.error,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }


def list_analyses(case_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with SessionLocal() as session:
        stmt = select(AnalysisRow).where(AnalysisRow.case_id == case_id).order_by(AnalysisRow.created_at.desc()).limit(max(1, min(int(limit), 500)))
        rows = session.scalars(stmt).all()
        return [
            {
                "analysis_id": r.analysis_id,
                "case_id": r.case_id,
                "analysis_type": r.analysis_type,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                **(r.result if isinstance(r.result, dict) else {}),
            }
            for r in rows
        ]


def save_analytics(case_id: str, record_type: str, payload: dict[str, Any]) -> int:
    init_db()
    with SessionLocal.begin() as session:
        row = AnalyticsRow(case_id=case_id, record_type=record_type, payload=payload)
        session.add(row)
        session.flush()
        return int(row.record_id)


def list_analytics(case_id: str, record_type: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with SessionLocal() as session:
        stmt = select(AnalyticsRow).where(AnalyticsRow.case_id == case_id).order_by(AnalyticsRow.created_at.desc())
        if record_type:
            stmt = stmt.where(AnalyticsRow.record_type == record_type)
        rows = session.scalars(stmt).all()
        return [{"record_id": r.record_id, "record_type": r.record_type, "created_at": r.created_at.isoformat(), **r.payload} for r in rows]


def ensure_bootstrap_admin(password_hash: str, username: str = "admin") -> None:
    init_db()
    with SessionLocal.begin() as session:
        if session.scalars(select(User).where(User.username == username)).first() is None:
            session.add(User(username=username, password_hash=password_hash, role="administrator", active=True))
