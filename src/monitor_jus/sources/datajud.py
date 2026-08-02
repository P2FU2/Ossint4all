"""Cliente DataJud — confirmação seletiva / fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from monitor_jus.config import Settings, get_settings, load_yaml
from monitor_jus.exceptions import (
    FailedAuthentication,
    FailedSource,
    SkippedDisabled,
)
from monitor_jus.http_client import RateLimitedClient
from monitor_jus.sources.base import FonteJudicial
from monitor_jus.validators import TribunalResolver, normalize_cnj


class DataJudClient(FonteJudicial):
    name = "datajud"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.http = RateLimitedClient(
            source="datajud",
            max_concurrency=self.settings.datajud_max_concurrency,
            timeout=30.0,
            default_headers={
                "Authorization": f"APIKey {self.settings.datajud_api_key}",
                "Content-Type": "application/json",
            },
        )
        tribunais_path = self.settings.config_path("tribunais.yaml")
        self.resolver = TribunalResolver(tribunais_path)
        self.policy = load_yaml(self.settings.config_path("datajud_policy.yaml"))

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.datajud_enable,
            "mode": self.settings.datajud_mode,
            "api_key_configured": bool(self.settings.datajud_api_key),
            "api_key_url": self.settings.datajud_api_key_url,
        }

    def should_confirm(self, reason: str) -> bool:
        if not self.settings.datajud_enable or self.settings.datajud_mode == "off":
            return False
        rules = (self.policy or {}).get("confirmar_datajud") or {}
        return bool(rules.get(reason, False))

    def search_by_cnj(self, numero: str, *, alias: str | None = None) -> dict[str, Any]:
        if not self.settings.datajud_enable or self.settings.datajud_mode == "off":
            raise SkippedDisabled("DataJud desabilitado")
        if not self.settings.datajud_api_key:
            raise FailedAuthentication(
                f"DATAJUD_API_KEY ausente. Obtenha a chave pública em {self.settings.datajud_api_key_url}"
            )

        parts = normalize_cnj(numero)
        if not parts:
            raise FailedSource(f"CNJ inválido: {numero}")

        resolved = self.resolver.resolve_from_cnj(numero)
        if resolved and not resolved.get("datajud_supported"):
            raise SkippedDisabled(
                f"Tribunal sem endpoint DataJud (ex.: STF). segmento={resolved.get('segmento')}"
            )

        aliases: list[str] = []
        if alias:
            aliases.append(alias)
        elif resolved and resolved.get("alias"):
            aliases.append(str(resolved["alias"]))

        if not aliases:
            raise FailedSource("Não foi possível inferir endpoint DataJud para o CNJ")

        last_error: Exception | None = None
        for a in aliases:
            try:
                return self._search_alias(a, parts.numero_digits)
            except FailedAuthentication:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise FailedSource(str(last_error) if last_error else "DataJud sem resultado")

    def _search_alias(self, alias: str, numero_digits: str) -> dict[str, Any]:
        url = f"{self.settings.datajud_base_url.rstrip('/')}/{alias}/_search"
        body = {
            "size": 10,
            "query": {"match": {"numeroProcesso": numero_digits}},
        }
        resp = self.http.request("POST", url, json=body, operation=f"search:{alias}")
        if resp.status_code in (401, 403):
            raise FailedAuthentication(
                f"DataJud 401/403 — atualize DATAJUD_API_KEY em {self.settings.datajud_api_key_url}"
            )
        resp.raise_for_status()
        data = resp.json()
        hits = (((data or {}).get("hits") or {}).get("hits")) or []
        if not hits:
            return {}
        return hits[0].get("_source") or {}
