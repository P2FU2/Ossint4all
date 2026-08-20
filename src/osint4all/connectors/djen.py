"""Conector DJEN / Comunica API — publicações e menções."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import FailedAuthentication, FailedSource, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.validators import normalize_cnj

_HTML_RE = re.compile(r"<[^>]+>")
_LOOKBACK_DAYS = 2920
_PAGE_SIZE = 20
_MAX_ITEMS = 24


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", _HTML_RE.sub(" ", text or "")).strip()


def _cnj_raw(item: dict[str, Any]) -> str:
    return str(
        item.get("numeroprocessocommascara")
        or item.get("numeroProcessoComMascara")
        or item.get("numero_processo")
        or item.get("numeroProcesso")
        or ""
    ).strip()


def _item_link(item: dict[str, Any]) -> str:
    link = str(item.get("link") or item.get("linkComunicacao") or "").strip()
    if link.startswith("http"):
        return link
    digest = str(item.get("hash") or "").strip()
    if digest:
        return f"https://comunicaapi.pje.jus.br/api/v1/comunicacao/{digest}/certidao"
    return ""


def parse_djen_items(items: list[dict[str, Any]], *, origin_key: str) -> ConnectorResult:
    result = ConnectorResult()
    seen_cnj: set[str] = set()
    seen_pub: set[str] = set()
    for item in items[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        cnj_raw = _cnj_raw(item)
        parts = normalize_cnj(cnj_raw)
        texto = _plain(str(item.get("texto") or ""))[:400]
        tribunal = str(item.get("siglaTribunal") or item.get("sigla_tribunal") or "")
        link = _item_link(item)
        disp = str(item.get("data_disponibilizacao") or item.get("dataDisponibilizacao") or "")
        tipo = str(item.get("tipoComunicacao") or item.get("tipo_comunicacao") or "Comunicação")
        cnj_label = parts.numero_formatado if parts else cnj_raw
        pub_name = " · ".join(part for part in (tipo, tribunal, cnj_label, disp) if part)
        pub_value = link or pub_name
        pub_key = canonical_key("URL" if link else "NAME", pub_value)
        if pub_key not in seen_pub:
            seen_pub.add(pub_key)
            result.entities.append(
                FoundEntity(
                    entity_type="PUBLICATION",
                    kind="URL" if link else "NAME",
                    value=pub_value,
                    display_name=(pub_name or "Publicação DJEN")[:160],
                    attrs={"tribunal": tribunal, "tipo": tipo, "data": disp, "fonte": link, "cnj": cnj_label},
                    confidence=0.75,
                )
            )
            result.edges.append(FoundEdge(from_ref=origin_key, to_ref=pub_key, rel_type="MENCAO", confidence=0.6))
            result.evidence.append(
                FoundEvidence(
                    source_label=pub_name or "DJEN",
                    url=link,
                    snippet=texto or pub_name,
                    payload={"tribunal": tribunal, "tipo": tipo, "data": disp, "cnj": cnj_raw},
                    entity_ref=pub_key,
                )
            )
        if parts and parts.numero_digits not in seen_cnj:
            seen_cnj.add(parts.numero_digits)
            case_key = canonical_key("CNJ", parts.numero_digits)
            result.entities.append(
                FoundEntity(
                    entity_type="CASE",
                    kind="CNJ",
                    value=parts.numero_digits,
                    display_name=parts.numero_formatado,
                    attrs={"tribunal": tribunal, "fonte": link, "tipo": tipo, "data": disp},
                    confidence=0.85,
                )
            )
            result.edges.append(FoundEdge(from_ref=pub_key, to_ref=case_key, rel_type="MENCAO", confidence=0.85))
            result.edges.append(FoundEdge(from_ref=origin_key, to_ref=case_key, rel_type="PARTE", confidence=0.45))
        for dest in list(item.get("destinatarios") or []) + list(item.get("destinatarioadvogados") or []):
            if not isinstance(dest, dict):
                continue
            adv = dest.get("advogado") if isinstance(dest.get("advogado"), dict) else None
            nome = str((adv or dest).get("nome") or "").strip()
            if not nome:
                continue
            rel = "ADVOGADO" if adv else "PARTE"
            result.entities.append(
                FoundEntity(entity_type="PERSON", kind="NAME", value=nome, display_name=nome, confidence=0.5)
            )
            result.edges.append(
                FoundEdge(from_ref=canonical_key("NAME", nome), to_ref=pub_key, rel_type=rel, confidence=0.5)
            )
    return result


class DjenConnector:
    name = "djen"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        proxy = (settings.djen_http_proxy or "").strip() or None
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=settings.djen_max_concurrency,
            timeout=45.0,
            default_headers={
                "Accept": "application/json",
                "User-Agent": "osint4all/0.1 (+https://github.com/P2FU2/Ossint4all; public-source research)",
            },
            proxy=proxy,
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.djen_enable,
            "base_url": self.settings.djen_base_url,
            "proxy": bool(self.settings.djen_http_proxy),
        }

    def accepts(self, entity: Entity) -> bool:
        if entity.entity_type in {"PERSON", "ORG"}:
            return True
        if entity.entity_type == "CASE" and entity.canonical_key.startswith("cnj:"):
            return True
        return False

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.djen_enable:
            raise SkippedDisabled("DJEN desabilitado")
        params = self._params_for(entity)
        if not params:
            return ConnectorResult(notes=["Sem nome ou número CNJ para perguntar ao DJEN."])
        items: list[dict[str, Any]] = []
        notes: list[str] = []
        try:
            items = self._fetch_items(params)
        except (FailedAuthentication, FailedSource) as exc:
            notes.append(str(exc))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"DJEN: {exc}")
        out = parse_djen_items(items, origin_key=entity.canonical_key)
        if items and not out.entities:
            notes.append("O DJEN respondeu, mas nenhum processo veio com número ou link utilizável.")
        if not out.entities:
            extra = self._web_processos(entity)
            out.merge(extra)
            if extra.entities:
                notes.append("DJEN vazio ou bloqueado — menções processuais públicas em jus.br.")
            elif not notes:
                notes.append("Nenhuma comunicação DJEN neste período. Se o servidor estiver fora do Brasil, use DJEN_HTTP_PROXY.")
        out.notes.extend(notes)
        return out

    def _fetch_items(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        until = date.today()
        start = until - timedelta(days=_LOOKBACK_DAYS)
        query = dict(params)
        query.setdefault("dataDisponibilizacaoInicio", start.isoformat())
        query.setdefault("dataDisponibilizacaoFim", until.isoformat())
        query.setdefault("pagina", 1)
        query.setdefault("itensPorPagina", _PAGE_SIZE)
        resp = self.http.request("GET", self.settings.djen_base_url, params=query, allow_404=True, max_retries=1)
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code in (401, 403) or "text/html" in ctype:
            raise FailedSource("DJEN bloqueado (CloudFront/geo). Configure DJEN_HTTP_PROXY no Brasil.")
        if resp.status_code >= 400:
            raise FailedSource(f"DJEN HTTP {resp.status_code}")
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise FailedSource(f"DJEN JSON inválido: {exc}") from exc
        rows = data.get("items") if isinstance(data, dict) else data
        if rows is None and isinstance(data, dict):
            rows = data.get("itens") or data.get("content")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _params_for(self, entity: Entity) -> dict[str, Any]:
        if entity.entity_type == "CASE" and entity.canonical_key.startswith("cnj:"):
            return {"numeroProcesso": entity.canonical_key.split(":", 1)[1]}
        name = (entity.display_name or "").strip()
        if entity.entity_type in {"PERSON", "ORG"} and name:
            return {"nomeParte": name}
        return {}

    def _web_processos(self, entity: Entity) -> ConnectorResult:
        from osint4all.connectors.web_search import WebSearchConnector, web_search_ready

        if not web_search_ready(self.settings):
            return ConnectorResult()
        name = (entity.display_name or "").strip()
        if not name:
            return ConnectorResult()
        query = f'"{name}" (processo OR "número CNJ" OR sentença OR tribunal OR reclamatória) (site:jus.br OR site:pje.jus.br OR site:cnj.jus.br)'
        try:
            return WebSearchConnector(self.settings).search(query, entity.canonical_key)
        except Exception:
            return ConnectorResult()
