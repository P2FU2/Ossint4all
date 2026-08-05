"""Sincroniza source_capabilities a partir das flags de env/YAML."""

from __future__ import annotations

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_fontes
from monitor_jus.db.repository import Repository


def sync_capabilities(session: Session, settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    repo = Repository(session)
    fontes = load_fontes(settings)
    djen_on = settings.djen_enable and (fontes.get("djen") or {}).get("enabled", True) is not False
    datajud_on = settings.datajud_enable and (fontes.get("datajud") or {}).get("enabled", True) is not False
    cna_on = settings.cna_enabled and bool((fontes.get("cna") or {}).get("enabled"))

    mapping = [
        ("djen", "national_criteria_search", djen_on),
        ("djen", "tribunal_sweep", djen_on),
        ("datajud", "process_refresh", datajud_on),
        ("cna", "lawyer_validation", cna_on),
        ("openrouter", "summaries", bool(settings.openrouter_api_key)),
        ("resend", "email", bool(settings.resend_api_key)),
    ]
    rows = []
    for source, cap, enabled in mapping:
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
