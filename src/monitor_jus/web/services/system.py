"""Página de sistema / saúde / usuários."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings
from monitor_jus.db.models import SourceCapability, SourceCheckpoint, User
from monitor_jus.metrics import snapshot
from monitor_jus.web.auth import hash_password, write_audit


def build_system_view(session: Session, settings: Settings) -> dict[str, Any]:
    caps = list(session.scalars(select(SourceCapability).order_by(SourceCapability.source)).all())
    checkpoints = list(
        session.scalars(select(SourceCheckpoint).order_by(SourceCheckpoint.source)).all()
    )
    users = list(session.scalars(select(User).order_by(User.username)).all())
    return {
        "flags": settings.judit_flags(),
        "email_from": settings.email_from or "—",
        "email_to": settings.email_to or "—",
        "tz": settings.tz,
        "schedule_cron": settings.schedule_cron,
        "datajud_mode": settings.datajud_mode,
        "datajud_enable": settings.datajud_enable,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "openrouter_model": settings.openrouter_model,
        "env": settings.env,
        "capabilities": [
            {
                "source": c.source,
                "capability": c.capability,
                "enabled": c.enabled,
                "contracted": c.contracted,
                "notes": c.notes or "",
            }
            for c in caps
        ],
        "checkpoints": [
            {
                "source": c.source,
                "checkpoint_key": c.checkpoint_key,
                "cursor": c.cursor,
                "updated_at": c.updated_at.astimezone().strftime("%d/%m/%Y %H:%M")
                if c.updated_at
                else "—",
            }
            for c in checkpoints
        ],
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "active": u.active,
                "last_login_at": u.last_login_at.astimezone().strftime("%d/%m/%Y %H:%M")
                if u.last_login_at
                else "—",
            }
            for u in users
        ],
        "metrics": snapshot(),
    }


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    role: str,
    actor: str,
) -> User:
    username = username.strip()
    if role not in ("admin", "viewer"):
        role = "viewer"
    existing = session.scalar(select(User).where(User.username == username))
    if existing:
        raise ValueError("Usuário já existe")
    if len(password) < 8:
        raise ValueError("Senha deve ter ao menos 8 caracteres")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        active=True,
    )
    session.add(user)
    write_audit(session, "user.create", username=actor, details={"new_user": username, "role": role})
    session.flush()
    return user


def set_user_active(session: Session, user_id: str, active: bool, actor: str) -> None:
    user = session.get(User, user_id)
    if not user:
        raise ValueError("Usuário não encontrado")
    user.active = active
    write_audit(
        session,
        "user.deactivate" if not active else "user.activate",
        username=actor,
        details={"target": user.username, "active": active},
    )
