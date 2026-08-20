"""Engine / session SQLite + PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from osint4all.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_engine_url: str | None = None


def reset_engine() -> None:
    global _engine, _SessionLocal, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _engine_url = None


def get_engine(database_url: str | None = None) -> Engine:
    global _engine, _SessionLocal, _engine_url
    url = database_url or get_settings().database_url
    if _engine is not None and _engine_url == url:
        return _engine

    reset_engine()
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:" and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    _engine_url = url

    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragma(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    get_engine(database_url)
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    factory = get_session_factory(database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_legacy_columns(engine: Engine) -> None:
    """O Postgres do Railway ainda tem o schema do Script_Jus — só completa o que falta."""
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import OperationalError

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    statements: list[str] = []

    def add_col(table: str, name: str, ddl: str) -> None:
        if table not in tables:
            return
        cols = {c["name"] for c in inspector.get_columns(table)}
        if name not in cols:
            statements.append(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    if "audit_log" in tables:
        add_col("audit_log", "username", "VARCHAR(80)")
        add_col("audit_log", "investigation_id", "VARCHAR(36)")
    if "investigations" in tables:
        add_col("investigations", "purpose", "TEXT")
        add_col("investigations", "assignee", "VARCHAR(80)")
        add_col("investigations", "classification", "VARCHAR(32) DEFAULT 'interno'")
        add_col("investigations", "retain_until", "TIMESTAMP")
        add_col("investigations", "playbook_key", "VARCHAR(32)")
        add_col("investigations", "workflow", "VARCHAR(32) DEFAULT 'INVESTIGATING'")
        add_col("investigations", "retention_days", "INTEGER")
        add_col("investigations", "graph_layout", "JSON")
    if "evidence" in tables:
        add_col("evidence", "method", "VARCHAR(16)")
        add_col("evidence", "http_status", "INTEGER")
        add_col("evidence", "content_sha256", "VARCHAR(64)")
        add_col("evidence", "raw_path", "VARCHAR(512)")
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            try:
                if dialect == "postgresql":
                    conn.execute(text(sql.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS")))
                else:
                    conn.execute(text(sql))
            except OperationalError:
                continue


def init_db(database_url: str | None = None) -> None:
    from osint4all.db.models import Base

    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    _ensure_legacy_columns(engine)
