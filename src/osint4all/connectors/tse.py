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
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj, validate_cpf


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


def parse_tse_assets(items: list[Any], *, origin_key: str, owner_name: str = "") -> ConnectorResult:
    result = ConnectorResult()
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("descricaoDeBem") or item.get("descricao") or item.get("dsTipoBem") or "").strip()
        tipo = str(item.get("descricaoTipoBem") or item.get("tipo") or item.get("dsTipoBem") or "bem declarado").strip()
        valor = item.get("valor") or item.get("valorBem") or item.get("vrBem")
        if not desc and not tipo:
            continue
        label = desc or tipo
        found = FoundEntity(
            entity_type="ASSET",
            kind="NAME",
            value=f"{tipo}:{label}"[:200],
            display_name=label[:180],
            attrs={
                "tipo": "bem_eleitoral",
                "tipo_imovel": tipo if "imó" in tipo.casefold() or "imovel" in tipo.casefold() else "",
                "valor": valor,
                "fonte": "tse",
                "status": "unconfirmed",
                "dono": owner_name,
            },
            confidence=0.55,
        )
        result.entities.append(found)
        from osint4all.graph.identity import found_canonical_key

        ref = found_canonical_key(found)
        result.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="TITULAR", confidence=0.55, attrs={"fonte": "tse"}))
        result.evidence.append(
            FoundEvidence(
                source_label="TSE · bens declarados",
                url="https://divulgacandcontas.tse.jus.br/",
                snippet=f"{tipo}: {label} {valor or ''}".strip()[:400],
                payload={"tipo": tipo, "descricao": desc, "valor": valor},
                entity_ref=ref,
            )
        )
    return result


def parse_tse_donations(items: list[Any], *, origin_key: str) -> ConnectorResult:
    result = ConnectorResult()
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nomeDoador") or item.get("nome") or item.get("nmDoador") or "").strip()
        if not nome:
            continue
        doc = only_digits(str(item.get("cpfCnpjDoador") or item.get("cpfCnpj") or item.get("nrCpfCnpjDoador") or ""))
        valor = item.get("valor") or item.get("vrReceita") or item.get("valorReceita")
        if validate_cnpj(doc):
            donor = FoundEntity(entity_type="ORG", kind="CNPJ", value=doc, display_name=nome, attrs={"papel": "doador"}, confidence=0.6)
            ref = canonical_key("CNPJ", doc)
        elif validate_cpf(doc):
            donor = FoundEntity(entity_type="PERSON", kind="CPF", value=doc, display_name=nome, attrs={"papel": "doador"}, confidence=0.6)
            ref = canonical_key("CPF", doc)
        else:
            donor = FoundEntity(
                entity_type="PERSON",
                kind="NAME",
                value=nome,
                display_name=nome,
                attrs={"papel": "doador", "status": "unconfirmed"},
                confidence=0.4,
            )
            ref = canonical_key("NAME", nome)
        result.entities.append(donor)
        if ref != origin_key:
            result.edges.append(
                FoundEdge(from_ref=ref, to_ref=origin_key, rel_type="DOACAO", confidence=0.5, attrs={"valor": valor, "fonte": "tse"})
            )
        result.evidence.append(
            FoundEvidence(
                source_label="TSE · doação de campanha",
                url="https://divulgacandcontas.tse.jus.br/",
                snippet=f"{nome} → {valor or 'valor não informado'}"[:400],
                payload={"doador": nome, "doc": doc, "valor": valor},
                entity_ref=ref,
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
        merged = parse_tse_candidates(matched, origin_key=entity.canonical_key)
        for cand in matched[:3]:
            merged.merge(self._enrich_candidate(cand, entity.canonical_key, entity.display_name))
        return merged

    def _enrich_candidate(self, cand: dict[str, Any], origin_key: str, owner_name: str) -> ConnectorResult:
        sq = str(cand.get("id") or cand.get("sqCandidato") or "").strip()
        unidade = cand.get("unidadeEleitoral") if isinstance(cand.get("unidadeEleitoral"), dict) else {}
        sg_ue = str(unidade.get("sigla") or cand.get("sgUe") or cand.get("ufSuperior") or "").strip()
        if not sq:
            bens = cand.get("bens") if isinstance(cand.get("bens"), list) else []
            receitas = cand.get("receitas") or cand.get("doacoes") or []
            extra = parse_tse_assets(bens if isinstance(bens, list) else [], origin_key=origin_key, owner_name=owner_name)
            extra.merge(parse_tse_donations(receitas if isinstance(receitas, list) else [], origin_key=origin_key))
            return extra
        url = (
            f"https://divulgacandcontas.tse.jus.br/divulga/rest/v1/candidatura/buscar/2024/{sg_ue or 'BR'}/20452024/candidato/{sq}"
        )
        try:
            resp = self.http.request("GET", url, allow_404=True, max_retries=1)
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        if not isinstance(data, dict):
            return ConnectorResult()
        bens = data.get("bens") or data.get("bensDeclarados") or []
        receitas = data.get("receitas") or data.get("doacoes") or []
        extra = parse_tse_assets(bens if isinstance(bens, list) else [], origin_key=origin_key, owner_name=owner_name)
        extra.merge(parse_tse_donations(receitas if isinstance(receitas, list) else [], origin_key=origin_key))
        return extra
