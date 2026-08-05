"""Cliente DataJud — enriquecimento de capa/movimentos (não novidade)."""

from __future__ import annotations

from typing import Any

from monitor_jus.config import Settings, get_settings, load_yaml
from monitor_jus.exceptions import (
    FailedAuthentication,
    FailedSource,
    SkippedDisabled,
)
from monitor_jus.http_client import RateLimitedClient
from monitor_jus.instances import instance_rank_from_datajud_hit
from monitor_jus.sources.base import FonteJudicial
from monitor_jus.validators import TribunalResolver, normalize_cnj

_GRAU_RANK = {"G2": 2, "G1": 1, "JE": 0, "TR": 2, "TU": 2}


def grau_rank(grau: str | None) -> int:
    """Rank interno DataJud G1/G2 (0–2). Para hierarquia completa use instances."""
    if not grau:
        return 0
    g = str(grau).strip().upper()
    if g in _GRAU_RANK:
        return _GRAU_RANK[g]
    if "2" in g:
        return 2
    if "1" in g:
        return 1
    return 0


def prefer_datajud_hit(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefere a instância mais alta (2º grau > 1º; superiores via CNJ/tribunal)."""
    if not sources:
        return {}
    if len(sources) == 1:
        return sources[0]

    def sort_key(src: dict[str, Any]) -> tuple:
        return (
            instance_rank_from_datajud_hit(src),
            grau_rank(src.get("grau")),
            str(src.get("dataHoraUltimaAtualizacao") or ""),
            len(src.get("movimentos") or []),
        )

    return max(sources, key=sort_key)


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
        """Compat: retorna o hit preferido (em geral G2)."""
        hits = self.search_all_by_cnj(numero, alias=alias)
        return prefer_datajud_hit(hits)

    def search_all_by_cnj(self, numero: str, *, alias: str | None = None) -> list[dict[str, Any]]:
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
                return self._search_alias_all(a, parts.numero_digits)
            except FailedAuthentication:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        raise FailedSource(str(last_error) if last_error else "DataJud sem resultado")

    def _search_alias_all(self, alias: str, numero_digits: str) -> list[dict[str, Any]]:
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
        out: list[dict[str, Any]] = []
        for h in hits:
            src = h.get("_source") if isinstance(h, dict) else None
            if isinstance(src, dict) and src:
                out.append(src)
        return out
