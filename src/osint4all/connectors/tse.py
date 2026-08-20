"""Conector TSE — candidaturas públicas (DivulgaCand)."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import FailedSource, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.graph.identity import found_canonical_key
from osint4all.identifiers import canonical_key


def parse_tse_candidates(items: list[dict[str, Any]], *, origin_key: str) -> ConnectorResult:
    result = ConnectorResult()
    for item in items[:15]:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nomeUrna") or item.get("nome") or item.get("nomeCompleto") or "").strip()
        cargo = str(item.get("cargo") or item.get("ds_cargo") or "")
        partido = str(item.get("partido") or item.get("sg_partido") or item.get("siglaPartido") or "")
        uf = str(item.get("sg_ue") or item.get("ufSuperior") or item.get("uf") or "")
        ano = str(item.get("ano") or item.get("anoEleicao") or "")
        if isinstance(item.get("cargo"), dict):
            cargo = str(item["cargo"].get("nome") or cargo)
        if isinstance(item.get("partido"), dict):
            partido = str(item["partido"].get("sigla") or partido)
        if not nome:
            continue
        label = f"{nome} · {cargo} {partido} {uf} {ano}".strip()
        cand = FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value=nome,
            display_name=nome,
            attrs={
                "cargo": cargo,
                "partido": partido,
                "uf": uf,
                "ano": ano,
                "papel": "candidato",
                "status": "unconfirmed",
                "candidate_key": f"tse:{nome}:{uf}:{ano}",
            },
            confidence=0.4,
        )
        result.entities.append(cand)
        cand_key = found_canonical_key(cand)
        if cand_key != origin_key:
            result.edges.append(
                FoundEdge(from_ref=origin_key, to_ref=cand_key, rel_type="CANDIDATO", confidence=0.55)
            )
        result.evidence.append(
            FoundEvidence(
                source_label="TSE DivulgaCandContas",
                url="https://divulgacandcontas.tse.jus.br/",
                snippet=label,
                payload={"nome": nome, "cargo": cargo, "partido": partido, "uf": uf},
                entity_ref=cand_key,
            )
        )
        if partido:
            party = FoundEntity(
                entity_type="ORG",
                kind="NAME",
                value=partido,
                display_name=partido,
                attrs={"tipo": "partido"},
                confidence=0.5,
            )
            result.entities.append(party)
            result.edges.append(
                FoundEdge(
                    from_ref=cand_key,
                    to_ref=canonical_key("NAME", partido),
                    rel_type="CANDIDATO",
                    confidence=0.5,
                    attrs={"relacao": "filiacao_publica"},
                )
            )
    return result


class TseConnector:
    name = "tse"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.tse_enable}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type == "PERSON" and bool(entity.display_name)

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.tse_enable:
            raise SkippedDisabled("TSE desabilitado")
        nome = entity.display_name.strip()
        if len(nome.split()) < 2:
            return ConnectorResult(notes=["TSE exige nome e sobrenome"])
        # Endpoint público de pesquisa textual do DivulgaCand (eleição municipal 2024).
        url = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/listar/2024/BR/20452024/prefeito/candidatos"
        try:
            resp = self.http.request("GET", url, max_retries=2)
        except Exception as exc:  # noqa: BLE001
            raise FailedSource(f"TSE indisponível: {exc}") from exc
        if resp.status_code >= 400:
            return ConnectorResult(notes=[f"TSE HTTP {resp.status_code}"])
        data = resp.json()
        candidatos = []
        if isinstance(data, dict):
            candidatos = data.get("candidatos") or data.get("candidatures") or []
        elif isinstance(data, list):
            candidatos = data
        needle = nome.casefold()
        matched = [
            c
            for c in candidatos
            if isinstance(c, dict)
            and needle in str(c.get("nomeUrna") or c.get("nomeCompleto") or c.get("nome") or "").casefold()
        ]
        if not matched:
            return ConnectorResult(notes=["Nenhuma candidatura 2024 (prefeito/BR) com esse nome"])
        return parse_tse_candidates(matched, origin_key=entity.canonical_key)
