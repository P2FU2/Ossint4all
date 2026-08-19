"""Conector CNPJ via Minha Receita ou BrasilAPI (QSA público)."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import FailedSource, SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj, validate_cpf


def _cnpj_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = entity.canonical_key.split(":", 1)[1]
        return digits if validate_cnpj(digits) else None
    for ident in entity.identifiers:
        if ident.kind == "CNPJ" and validate_cnpj(ident.value):
            return only_digits(ident.value)
    return None


def _company_attrs(data: dict[str, Any], razao: str, fantasia: str) -> dict[str, Any]:
    secundarios = data.get("cnaes_secundarios") or data.get("cnae_secundario") or []
    if isinstance(secundarios, list):
        extra_cnae = []
        for item in secundarios:
            if isinstance(item, dict):
                label = str(item.get("descricao") or item.get("codigo") or "")
            else:
                label = str(item)
            if label:
                extra_cnae.append(label)
        extra_cnae = extra_cnae[:8]
    else:
        extra_cnae = []
    logradouro = " ".join(
        str(part).strip()
        for part in (
            data.get("descricao_tipo_de_logradouro") or data.get("tipo_logradouro"),
            data.get("logradouro"),
            data.get("numero"),
            data.get("complemento"),
        )
        if part
    )
    return {
        "razao_social": razao,
        "nome_fantasia": fantasia,
        "situacao": data.get("descricao_situacao_cadastral") or data.get("situacao"),
        "data_situacao": data.get("data_situacao_cadastral"),
        "cnae": data.get("cnae_fiscal_descricao") or data.get("cnae"),
        "cnae_codigo": data.get("cnae_fiscal"),
        "cnaes_secundarios": extra_cnae,
        "municipio": data.get("municipio"),
        "uf": data.get("uf"),
        "cep": data.get("cep"),
        "bairro": data.get("bairro"),
        "endereco": logradouro or None,
        "data_inicio": data.get("data_inicio_atividade"),
        "porte": data.get("porte") or data.get("descricao_porte"),
        "capital_social": data.get("capital_social"),
        "natureza_juridica": data.get("natureza_juridica") or data.get("descricao_natureza_juridica"),
        "simples": data.get("opcao_pelo_simples"),
        "mei": data.get("opcao_pelo_mei"),
        "telefone": data.get("ddd_telefone_1") or data.get("telefone"),
        "email": data.get("correio_eletronico") or data.get("email"),
    }


def _qualificacao_rel(qualificacao: str) -> str:
    q = (qualificacao or "").casefold()
    if any(token in q for token in ("administrador", "diretor", "presidente", "gerente")):
        return "ADMIN"
    return "SOCIO"


def parse_cnpj_payload(data: dict[str, Any]) -> ConnectorResult:
    """Transforma JSON público de CNPJ em nós/arestas (testável sem HTTP)."""
    cnpj = only_digits(str(data.get("cnpj") or data.get("taxId") or ""))
    if not validate_cnpj(cnpj):
        return ConnectorResult(notes=["CNPJ inválido no payload"])

    razao = str(data.get("razao_social") or data.get("company") or data.get("nome") or cnpj)
    fantasia = str(data.get("nome_fantasia") or data.get("alias") or "")
    org_key = canonical_key("CNPJ", cnpj)
    result = ConnectorResult()
    result.entities.append(
        FoundEntity(
            entity_type="ORG",
            kind="CNPJ",
            value=cnpj,
            display_name=fantasia or razao,
            attrs=_company_attrs(data, razao, fantasia),
            confidence=0.95,
        )
    )
    qsa = data.get("qsa") or data.get("socios") or []
    if isinstance(qsa, dict):
        qsa = qsa.get("socios") or []
    for socio in qsa:
        if not isinstance(socio, dict):
            continue
        nome = str(socio.get("nome_socio") or socio.get("nome") or "").strip()
        doc = only_digits(str(socio.get("cnpj_cpf_do_socio") or socio.get("cpf_cnpj_socio") or socio.get("cnpj_cpf") or ""))
        qual = str(socio.get("qualificacao_socio") or socio.get("qualificacao") or "")
        rel = _qualificacao_rel(qual)
        if validate_cnpj(doc):
            other = FoundEntity(
                entity_type="ORG",
                kind="CNPJ",
                value=doc,
                display_name=nome or doc,
                attrs={
                    "papel": qual,
                    "entrada": socio.get("data_entrada_sociedade"),
                    "faixa_etaria": socio.get("faixa_etaria"),
                },
                confidence=0.9,
            )
            other_key = canonical_key("CNPJ", doc)
        elif validate_cpf(doc):
            other = FoundEntity(
                entity_type="PERSON",
                kind="CPF",
                value=doc,
                display_name=nome or doc,
                attrs={
                    "papel": qual,
                    "entrada": socio.get("data_entrada_sociedade"),
                    "faixa_etaria": socio.get("faixa_etaria"),
                },
                confidence=0.9,
            )
            other_key = canonical_key("CPF", doc)
        elif nome:
            other = FoundEntity(
                entity_type="PERSON",
                kind="NAME",
                value=nome,
                display_name=nome,
                attrs={
                    "papel": qual,
                    "documento_ausente": True,
                    "entrada": socio.get("data_entrada_sociedade"),
                    "faixa_etaria": socio.get("faixa_etaria"),
                },
                confidence=0.45,
            )
            other_key = canonical_key("NAME", nome)
        else:
            continue
        result.entities.append(other)
        result.edges.append(
            FoundEdge(
                from_ref=other_key,
                to_ref=org_key,
                rel_type=rel,
                confidence=0.9 if other.kind in {"CPF", "CNPJ"} else 0.45,
                attrs={"qualificacao": qual},
            )
        )
    result.evidence.append(
        FoundEvidence(
            source_label="Receita Federal (consulta pública de CNPJ)",
            url=f"https://minhareceita.org/{cnpj}",
            snippet=f"{razao} — QSA com {len(qsa)} sócio(s)",
            payload={"cnpj": cnpj, "razao_social": razao, "qsa_count": len(qsa)},
            entity_ref=org_key,
        )
    )
    return result


class CnpjReceitaConnector:
    name = "cnpj_receita"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=settings.cnpj_max_concurrency,
            timeout=25.0,
            default_headers={"Accept": "application/json", "User-Agent": "osint4all/0.1"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.cnpj_enable,
            "provider": self.settings.cnpj_provider,
        }

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type == "ORG" and _cnpj_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.cnpj_enable:
            raise SkippedDisabled("conector CNPJ desabilitado")
        cnpj = _cnpj_from_entity(entity)
        if not cnpj:
            return ConnectorResult()
        data = self._fetch(cnpj)
        result = parse_cnpj_payload(data)
        geo = self._geocode_cep(str(data.get("cep") or ""))
        if geo:
            for found in result.entities:
                if found.kind == "CNPJ" and only_digits(found.value) == cnpj:
                    found.attrs.update(geo)
        return result

    def _fetch(self, cnpj: str) -> dict[str, Any]:
        providers = []
        if self.settings.cnpj_provider == "brasilapi":
            providers = [_brasilapi_url(cnpj), _minhareceita_url(cnpj)]
        else:
            providers = [_minhareceita_url(cnpj), _brasilapi_url(cnpj)]
        last: Exception | None = None
        for url in providers:
            try:
                resp = self.http.request("GET", url, allow_404=True)
                if resp.status_code == 404:
                    last = FailedSource(f"CNPJ não encontrado: {cnpj}")
                    continue
                if resp.status_code >= 400:
                    last = FailedSource(f"HTTP {resp.status_code} em {url}")
                    continue
                data = resp.json()
                if isinstance(data, dict):
                    data.setdefault("cnpj", cnpj)
                    return data
            except Exception as exc:  # noqa: BLE001
                last = exc
                continue
        raise FailedSource(str(last) if last else "falha na consulta de CNPJ")

    def _geocode_cep(self, cep: str) -> dict[str, Any]:
        digits = only_digits(cep)
        if len(digits) != 8:
            return {}
        try:
            resp = self.http.request("GET", f"https://brasilapi.com.br/api/cep/v2/{digits}", allow_404=True)
            if resp.status_code >= 400:
                return {}
            data = resp.json()
        except Exception:
            return {}
        loc = (data.get("location") or {}).get("coordinates") or {}
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat in (None, "") or lng in (None, ""):
            return {}
        return {"lat": float(lat), "lng": float(lng), "cep": digits}


def _minhareceita_url(cnpj: str) -> str:
    return f"https://minhareceita.org/{cnpj}"


def _brasilapi_url(cnpj: str) -> str:
    return f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
