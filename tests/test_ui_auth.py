"""Smoke do painel web (login + sessão)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def ui_client(tmp_path, monkeypatch):
    db = tmp_path / "ui.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("UI_SESSION_SECRET", "test-ui-secret")
    monkeypatch.setenv("UI_ADMIN_USER", "admin")
    monkeypatch.setenv("UI_ADMIN_PASSWORD", "senha-forte-123")
    monkeypatch.setenv("JUDIT_WEBHOOK_AUTH_MODE", "static_token")
    monkeypatch.setenv("JUDIT_WEBHOOK_TOKEN", "tok")

    from monitor_jus.config import get_settings
    from monitor_jus.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()

    # reimport app after env
    import importlib
    import monitor_jus.api as api_mod

    importlib.reload(api_mod)
    with TestClient(api_mod.app) as client:
        yield client

    get_settings.cache_clear()
    reset_engine()


def test_login_page(ui_client: TestClient):
    r = ui_client.get("/login")
    assert r.status_code == 200
    assert "Authentic" in r.text
    assert "Monitor Judicial" in r.text


def test_login_and_dashboard(ui_client: TestClient):
    page = ui_client.get("/login")
    assert page.status_code == 200
    html = page.text
    marker = 'name="csrf_token" value="'
    assert marker in html
    csrf = html.split(marker, 1)[1].split('"', 1)[0]
    r = ui_client.post(
        "/login",
        data={"username": "admin", "password": "senha-forte-123", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/app"

    dash = ui_client.get("/app")
    assert dash.status_code == 200
    assert "Visão geral" in dash.text


def test_app_requires_login(ui_client: TestClient):
    r = ui_client.get("/app", follow_redirects=False)
    assert r.status_code in (303, 307)
    assert "/login" in r.headers.get("location", "")
