"""Câmara e Senado — dados abertos, sem chave."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key


def _name_from_entity(entity: Entity) -> str | None:
    name = (entity.display_name or "").strip()
    if entity.entity_type != "PERSON" or len(name.split()) < 2:
        return None
    return name


def parse_deputados(rows: list[Any], *, origin_key: str, needle: str) -> ConnectorResult:
    out = ConnectorResult()
    low = needle.casefold()
    for row in rows:
        if not isinstance(row, dict):
            continue
        nome = str(row.get("nome") or row.get("nomeCivil") or "").strip()
        if not nome or low not in nome.casefold():
            continue
        partido = str(row.get("siglaPartido") or "")
        uf = str(row.get("siglaUf") or "")
        uri = str(row.get("uri") or row.get("uriPartido") or "")
        dep_id = str(row.get("id") or "")
        url = uri if uri.startswith("http") else f"https://www.camara.leg.br/deputados/{dep_id}" if dep_id else "https://dadosabertos.camara.leg.br/"
        person = FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value=nome,
            display_name=nome,
            attrs={
                "cargo": "deputado federal",
                "partido": partido,
                "uf": uf,
                "papel": "parlamentar",
                "status": "unconfirmed",
                "camara_id": dep_id,
            },
            confidence=0.48,
        )
        out.entities.append(person)
        ref = canonical_key("NAME", nome)
        if ref != origin_key:
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="CANDIDATO", confidence=0.5, attrs={"casa": "camara"}))
        if partido:
            party = FoundEntity(entity_type="ORG", kind="NAME", value=partido, display_name=partido, attrs={"tipo": "partido"}, confidence=0.5)
            out.entities.append(party)
            out.edges.append(
                FoundEdge(from_ref=ref, to_ref=canonical_key("NAME", partido), rel_type="CANDIDATO", confidence=0.45, attrs={"relacao": "bancada"})
            )
        out.evidence.append(
            FoundEvidence(
                source_label="Câmara · dados abertos",
                url=url,
                snippet=f"{nome} · {partido} {uf}".strip(),
                payload={"id": dep_id, "partido": partido, "uf": uf},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 10:
            break
    return out


def parse_senadores(payload: Any, *, origin_key: str, needle: str) -> ConnectorResult:
    out = ConnectorResult()
    low = needle.casefold()
    rows: list[Any] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        lista = payload.get("ListaParlamentarEmExercicio") or payload
        if isinstance(lista, dict):
            bloco = lista.get("Parlamentares") or lista
            if isinstance(bloco, dict):
                raw = bloco.get("Parlamentar") or []
                rows = raw if isinstance(raw, list) else [raw]
            elif isinstance(bloco, list):
                rows = bloco
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = row.get("IdentificacaoParlamentar") if isinstance(row.get("IdentificacaoParlamentar"), dict) else row
        nome = str(ident.get("NomeParlamentar") or ident.get("NomeCompletoParlamentar") or ident.get("nome") or "").strip()
        if not nome or low not in nome.casefold():
            continue
        partido = str(ident.get("SiglaPartidoParlamentar") or ident.get("partido") or "")
        uf = str(ident.get("UfParlamentar") or ident.get("uf") or "")
        codigo = str(ident.get("CodigoParlamentar") or ident.get("id") or "")
        url = f"https://www25.senado.leg.br/web/senadores/senador/-/perfil/{codigo}" if codigo else "https://www.senado.leg.br/"
        person = FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value=nome,
            display_name=nome,
            attrs={
                "cargo": "senador",
                "partido": partido,
                "uf": uf,
                "papel": "parlamentar",
                "status": "unconfirmed",
                "senado_id": codigo,
            },
            confidence=0.48,
        )
        out.entities.append(person)
        ref = canonical_key("NAME", nome)
        if ref != origin_key:
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="CANDIDATO", confidence=0.5, attrs={"casa": "senado"}))
        if partido:
            out.entities.append(FoundEntity(entity_type="ORG", kind="NAME", value=partido, display_name=partido, attrs={"tipo": "partido"}, confidence=0.5))
            out.edges.append(
                FoundEdge(from_ref=ref, to_ref=canonical_key("NAME", partido), rel_type="CANDIDATO", confidence=0.45, attrs={"relacao": "bancada"})
            )
        out.evidence.append(
            FoundEvidence(
                source_label="Senado · dados abertos",
                url=url,
                snippet=f"{nome} · {partido} {uf}".strip(),
                payload={"id": codigo, "partido": partido, "uf": uf},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 10:
            break
    return out


class CongressoPublicConnector:
    name = "congresso_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1 (congresso public)"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.congresso_public_enable, "via": "camara + senado", "key": ""}

    def accepts(self, entity: Entity) -> bool:
        return _name_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.congresso_public_enable:
            raise SkippedDisabled("Congresso desabilitado")
        nome = _name_from_entity(entity)
        if not nome:
            return ConnectorResult()
        merged = ConnectorResult()
        merged.merge(self._camara(nome, entity.canonical_key))
        merged.merge(self._senado(nome, entity.canonical_key))
        if not merged.entities:
            merged.notes.append("Nenhum parlamentar em exercício com esse nome nas listas abertas.")
        return merged

    def _camara(self, nome: str, origin_key: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://dadosabertos.camara.leg.br/api/v2/deputados",
                params={"nome": nome, "ordem": "ASC", "ordenarPor": "nome"},
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        rows = data.get("dados") if isinstance(data, dict) else data
        return parse_deputados(rows if isinstance(rows, list) else [], origin_key=origin_key, needle=nome)

    def _senado(self, nome: str, origin_key: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json",
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        return parse_senadores(data, origin_key=origin_key, needle=nome)
