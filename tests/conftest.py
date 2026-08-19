from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from osint4all.config import Settings, reset_settings
from osint4all.db.session import init_db, reset_engine, session_scope


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.resolve().as_posix()}")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("UI_ADMIN_USER", "admin")
    monkeypatch.setenv("UI_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("EXPAND_SYNC", "false")
    reset_settings()
    reset_engine()
    init_db()
    yield Settings()
    reset_engine()
    reset_settings()


@pytest.fixture
def db(settings: Settings) -> Session:
    with session_scope() as session:
        yield session
