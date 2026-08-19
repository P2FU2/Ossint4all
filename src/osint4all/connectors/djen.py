"""Conector DJEN / Comunica API — publicações e menções."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import FailedSource, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.validators import normalize_cnj


def parse_djen_items(items: list[dict[str, Any]], *, origin_key: str) -> ConnectorResult:
    result = ConnectorResult()
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        cnj_raw = str(item.get("numeroprocessocommascara") or item.get("numero_processo") or "")
        parts = normalize_cnj(cnj_raw)
        texto = str(item.get("texto") or "")[:400]
        tribunal = str(item.get("siglaTribunal") or item.get("sigla_tribunal") or "")
        link = item.get("link") or item.get("linkComunicacao")
        disp = str(item.get("data_disponibilizacao") or item.get("dataDisponibilizacao") or "")
        tipo = str(item.get("tipoComunicacao") or item.get("tipo_comunicacao") or "Comunicação")
        pub_name = f"{tipo} {tribunal} {disp}".strip()
        pub = FoundEntity(
            entity_type="PUBLICATION",
            kind="URL" if link else "NAME",
            value=str(link or pub_name),
            display_name=pub_name[:120] or "Publicação DJEN",
            attrs={"tribunal": tribunal, "tipo": tipo, "data": disp},
            confidence=0.75,
        )
        result.entities.append(pub)
        pub_key = canonical_key(pub.kind, pub.value)
        result.edges.append(
            FoundEdge(from_ref=origin_key, to_ref=pub_key, rel_type="MENCAO", confidence=0.6)
        )
        result.evidence.append(
            FoundEvidence(
                source_label="DJEN / Comunica API",
                url=str(link) if link else "https://comunica.pje.jus.br/",
                snippet=texto or pub_name,
                payload={"tribunal": tribunal, "tipo": tipo, "data": disp, "cnj": cnj_raw},
                entity_ref=pub_key,
            )
        )
        if parts:
            case = FoundEntity(
                entity_type="CASE",
                kind="CNJ",
                value=parts.numero_digits,
                display_name=parts.numero_formatado,
                attrs={"tribunal": tribunal},
                confidence=0.85,
            )
            result.entities.append(case)
            case_key = canonical_key("CNJ", parts.numero_digits)
            result.edges.append(
                FoundEdge(from_ref=pub_key, to_ref=case_key, rel_type="MENCAO", confidence=0.85)
            )
            result.edges.append(
                FoundEdge(from_ref=origin_key, to_ref=case_key, rel_type="PARTE", confidence=0.45)
            )
        for dest in item.get("destinatarioadvogados") or []:
            adv = dest.get("advogado") if isinstance(dest, dict) else None
            if not isinstance(adv, dict):
                continue
            nome = str(adv.get("nome") or "").strip()
            if not nome:
                continue
            result.entities.append(
                FoundEntity(entity_type="PERSON", kind="NAME", value=nome, display_name=nome, confidence=0.5)
            )
            result.edges.append(
                FoundEdge(
                    from_ref=canonical_key("NAME", nome),
                    to_ref=pub_key,
                    rel_type="ADVOGADO",
                    confidence=0.5,
                )
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
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1"},
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
            return ConnectorResult()
        until = date.today()
        start = until - timedelta(days=180)
        params.setdefault("dataDisponibilizacaoInicio", start.isoformat())
        params.setdefault("dataDisponibilizacaoFim", until.isoformat())
        params.setdefault("pagina", 1)
        params.setdefault("itensPorPagina", 20)
        resp = self.http.request("GET", self.settings.djen_base_url, params=params)
        ctype = (resp.headers.get("content-type") or "").lower()
        if "text/html" in ctype:
            raise FailedSource("DJEN bloqueado (CloudFront/geo). Configure DJEN_HTTP_PROXY no Brasil.")
        if resp.status_code >= 400:
            raise FailedSource(f"DJEN HTTP {resp.status_code}")
        data = resp.json()
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = []
        return parse_djen_items(items, origin_key=entity.canonical_key)

    def _params_for(self, entity: Entity) -> dict[str, Any]:
        if entity.entity_type == "CASE" and entity.canonical_key.startswith("cnj:"):
            return {"numeroProcesso": entity.canonical_key.split(":", 1)[1]}
        name = entity.display_name
        if entity.entity_type == "ORG":
            return {"texto": name}
        if entity.entity_type == "PERSON":
            return {"texto": name}
        return {}
