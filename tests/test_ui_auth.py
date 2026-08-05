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
    monkeypatch.setenv("DJEN_ENABLE", "true")
    monkeypatch.setenv("DATAJUD_ENABLE", "true")

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


def _login(client: TestClient) -> str:
    page = client.get("/login")
    marker = 'name="csrf_token" value="'
    csrf = page.text.split(marker, 1)[1].split('"', 1)[0]
    client.post(
        "/login",
        data={"username": "admin", "password": "senha-forte-123", "csrf_token": csrf},
        follow_redirects=False,
    )
    # CSRF da sessão após login (página autenticada)
    dash = client.get("/app/acompanhamento")
    assert dash.status_code == 200
    assert marker in dash.text
    return dash.text.split(marker, 1)[1].split('"', 1)[0]


def test_cancel_job_accepts_valid_csrf(ui_client: TestClient, tmp_path, monkeypatch):
    csrf = _login(ui_client)
    from monitor_jus.db.repository import Repository
    from monitor_jus.db.session import session_scope
    from monitor_jus.models import JobStatus

    with session_scope() as session:
        repo = Repository(session)
        run = repo.create_run("BOOTSTRAP", "ui")
        job = repo.enqueue_job(run.id, "BOOTSTRAP", max_attempts=3)
        job_id = job.id

    r = ui_client.post(
        "/app/actions/cancel-job",
        data={
            "csrf_token": csrf,
            "job_id": job_id,
            "next_path": "/app/acompanhamento",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/app/acompanhamento" in r.headers.get("location", "")

    with session_scope() as session:
        from monitor_jus.db.models import Job

        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.CANCELLED.value


def test_cancel_job_empty_csrf_redirects_with_flash(ui_client: TestClient):
    _login(ui_client)
    r = ui_client.post(
        "/app/actions/cancel-job",
        data={"csrf_token": "", "job_id": "does-not-matter", "next_path": "/app/acompanhamento"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/app/acompanhamento" in r.headers.get("location", "")
