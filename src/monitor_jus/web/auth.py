"""Autenticação do painel: senha, sessão, CSRF, seed admin, rate-limit."""

from __future__ import annotations

import secrets
import time
from typing import Any

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import AuditLog, User
from monitor_jus.db.repository import utcnow
from monitor_jus.exceptions import ConfigurationError
from monitor_jus.logging_setup import get_logger

logger = get_logger(__name__)

SESSION_USER_KEY = "uid"
SESSION_CSRF_KEY = "csrf"
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 12

_login_attempts: dict[str, list[float]] = {}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def ensure_csrf(session_data: dict[str, Any]) -> str:
    token = session_data.get(SESSION_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session_data[SESSION_CSRF_KEY] = token
    return str(token)


def validate_csrf(session_data: dict[str, Any], token: str | None) -> bool:
    expected = session_data.get(SESSION_CSRF_KEY)
    if not expected or not token:
        return False
    return secrets.compare_digest(str(expected), str(token))


def _client_key(ip: str) -> str:
    return ip or "unknown"


def check_login_rate_limit(ip: str) -> bool:
    """Retorna True se ainda pode tentar login."""
    now = time.time()
    key = _client_key(ip)
    window = [t for t in _login_attempts.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[key] = window
    return len(window) < LOGIN_MAX_ATTEMPTS


def record_login_failure(ip: str) -> None:
    key = _client_key(ip)
    _login_attempts.setdefault(key, []).append(time.time())


def clear_login_failures(ip: str) -> None:
    _login_attempts.pop(_client_key(ip), None)


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username.strip()))
    if not user or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user


def write_audit(
    session: Session,
    action: str,
    *,
    username: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    payload = dict(details or {})
    if username:
        payload["username"] = username
    session.add(AuditLog(action=action, details=payload or None))


def seed_admin_user(session: Session, settings: Settings | None = None) -> None:
    """Cria admin inicial se a tabela users estiver vazia."""
    settings = settings or get_settings()
    count = int(session.scalar(select(func.count()).select_from(User)) or 0)
    if count > 0:
        return

    username = (settings.ui_admin_user or "").strip()
    password = settings.ui_admin_password or ""
    if not username or not password:
        if settings.is_production:
            raise ConfigurationError(
                "UI_ADMIN_USER e UI_ADMIN_PASSWORD são obrigatórios em produção "
                "(nenhum usuário no banco)"
            )
        logger.warning(
            "ui_admin_not_seeded",
            extra={"extra": {"reason": "missing UI_ADMIN_USER/UI_ADMIN_PASSWORD"}},
        )
        return

    user = User(
        username=username,
        password_hash=hash_password(password),
        role="admin",
        active=True,
    )
    session.add(user)
    write_audit(session, "user.seed_admin", username=username)
    logger.info("ui_admin_seeded", extra={"extra": {"username": username}})


def get_user_by_id(session: Session, user_id: str) -> User | None:
    user = session.get(User, user_id)
    if not user or not user.active:
        return None
    return user
