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


def init_db(database_url: str | None = None) -> None:
    from monitor_jus.db import models  # noqa: F401
    from monitor_jus.db.models import Base

    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    # seed digest_cursor
    with session_scope(database_url) as session:
        exists = session.execute(text("SELECT 1 FROM digest_cursor WHERE id = 1")).first()
        if not exists:
            session.execute(
                text(
                    "INSERT INTO digest_cursor (id, last_successful_digest_at) VALUES (1, NULL)"
                )
            )
