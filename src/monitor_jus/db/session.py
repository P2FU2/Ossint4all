"""Engine / session dual SQLite + PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from monitor_jus.config import get_settings

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


def _ensure_schema_compat(engine: Engine) -> None:
    """Ajusta colunas em bancos já existentes (create_all não altera tipos)."""
    dialect = engine.dialect.name
    statements: list[str] = []
    if dialect == "postgresql":
        statements.extend(
            [
                "ALTER TABLE processes ALTER COLUMN situacao TYPE TEXT",
                "ALTER TABLE processes ALTER COLUMN grau TYPE VARCHAR(64)",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_pct INTEGER DEFAULT 0",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_done DOUBLE PRECISION",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_total DOUBLE PRECISION",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_stage VARCHAR(64)",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_message VARCHAR(512)",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS eta_seconds DOUBLE PRECISION",
                "ALTER TABLE digests ADD COLUMN IF NOT EXISTS pdf_path VARCHAR(512)",
            ]
        )
    elif dialect == "sqlite":
        # SQLite: ADD COLUMN ignora se já existir (tratamos Exception)
        statements.extend(
            [
                "ALTER TABLE jobs ADD COLUMN progress_pct INTEGER DEFAULT 0",
                "ALTER TABLE jobs ADD COLUMN progress_done REAL",
                "ALTER TABLE jobs ADD COLUMN progress_total REAL",
                "ALTER TABLE jobs ADD COLUMN progress_stage VARCHAR(64)",
                "ALTER TABLE jobs ADD COLUMN progress_message VARCHAR(512)",
                "ALTER TABLE jobs ADD COLUMN eta_seconds REAL",
                "ALTER TABLE digests ADD COLUMN pdf_path VARCHAR(512)",
            ]
        )
    if not statements:
        return
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception:  # noqa: BLE001
                pass


def init_db(database_url: str | None = None) -> None:
    from monitor_jus.db import models  # noqa: F401
    from monitor_jus.db.models import Base

    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    _ensure_schema_compat(engine)
    # seed digest_cursor
    with session_scope(database_url) as session:
        exists = session.execute(text("SELECT 1 FROM digest_cursor WHERE id = 1")).first()
        if not exists:
            session.execute(
                text(
                    "INSERT INTO digest_cursor (id, last_successful_digest_at) VALUES (1, NULL)"
                )
            )
