"""Sincroniza source_capabilities a partir das flags de env."""

from __future__ import annotations

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.repository import Repository


def sync_capabilities(session: Session, settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    repo = Repository(session)
    flags = settings.judit_flags()
    mapping = [
        ("judit", "historical_search", flags["historical_search"]),
        ("judit", "oab", flags["oab"]),
        ("judit", "cpf_cnpj", flags["cpf_cnpj"]),
        ("judit", "name", flags["name"]),
        ("judit", "process_tracking", flags["process_tracking"]),
        ("judit", "document_tracking", flags["document_tracking"]),
        ("judit", "djen", flags["djen"]),
        ("judit", "attachments", flags["attachments"]),
        (
            "datajud",
            "confirm_selective",
            settings.datajud_enable and settings.datajud_mode != "off",
        ),
        ("openrouter", "summaries", bool(settings.openrouter_api_key)),
        ("resend", "email", bool(settings.resend_api_key)),
    ]
    rows = []
    for source, cap, enabled in mapping:
        # contracted espelha enabled na v1 (admin liga só o contratado)
        obj = repo.upsert_capability(source, cap, enabled=enabled, contracted=enabled)
        rows.append(
            {
                "source": obj.source,
                "capability": obj.capability,
                "enabled": obj.enabled,
                "contracted": obj.contracted,
            }
        )
    return rows
