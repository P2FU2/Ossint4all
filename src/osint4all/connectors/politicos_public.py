"""Políticos e PEPs — TSE já cobre urna; aqui entram PEP, TCU, ranking.org.br e fotos oficiais."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.graph.identity import name_overlap_score, name_search_variants
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits


def _name_from_entity(entity: Entity) -> str | None:
    name = (entity.display_name or "").strip()
    if entity.entity_type != "PERSON" or len(name.split()) < 2:
        return None
    return name


def _photo_url(row: dict[str, Any]) -> str:
    for key in ("urlFoto", "url_foto", "fotoUrl", "foto_url", "UrlFotoParlamentar", "urlFotoParlamentar"):
        raw = str(row.get(key) or "").strip()
        if raw.startswith("http"):
            return raw
    return ""


def parse_pep_rows(rows: list[Any], *, origin_key: str, needle: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        nome = str(row.get("nome") or row.get("nomePep") or row.get("nomePEP") or "").strip()
        if not nome:
            continue
        score = name_overlap_score(nome, needle)
        if score < 0.5:
            continue
        cargo = str(row.get("descricaoFuncao") or row.get("funcao") or row.get("cargo") or "PEP")
        orgao = str(row.get("nomeOrgao") or row.get("orgao") or "")
        label = " · ".join(part for part in (nome, cargo, orgao) if part)
        person = FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value=nome,
            display_name=nome,
            attrs={
                "cargo": cargo,
                "orgao": orgao,
                "papel": "pep",
                "status": "unconfirmed",
                "identity_match": int(round(score * 100)),
            },
            confidence=min(0.88, 0.5 + score * 0.35),
        )
        out.entities.append(person)
        ref = canonical_key("NAME", nome)
        if ref != origin_key:
            out.edges.append(
                FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.55, attrs={"lista": "PEP"})
            )
        out.evidence.append(
            FoundEvidence(
                source_label="CGU · PEP",
                url="https://portaldatransparencia.gov.br/pessoa-exposta-politicamente",
                snippet=label,
                payload={"nome": nome, "cargo": cargo, "orgao": orgao, "match": int(round(score * 100))},
                entity_ref=ref,
            )
        )
    return out


def parse_ranking_html(html: str, *, nome: str) -> list[dict[str, Any]]:
    """Extrai fichas públicas do HTML (WordPress, Next ou busca)."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    blob = html or ""
    marker = "__NEXT_DATA__"
    if marker in blob:
        raw = blob.split(marker, 1)[1]
        raw = raw.split(">", 1)[-1]
        raw = raw.split("</script>", 1)[0]
        try:
            import json

            payload = json.loads(raw)
            text = json.dumps(payload, ensure_ascii=False)
        except Exception:
            text = raw
        blob = blob + " " + text
    low = nome.casefold()
    tokens = [t for t in low.split() if t not in {"da", "de", "do", "dos", "das", "e"} and len(t) > 2]
    for raw in blob.split("href="):
        href = raw.split('"', 2)
        if len(href) < 2:
            continue
        link = href[1].strip()
        if link.startswith("/"):
            link = "https://ranking.org.br" + link
        if not link.startswith("http") or "ranking.org.br" not in link:
            continue
        path = link.casefold()
        if not any(part in path for part in ("/politic", "/parlamentar", "/deputad", "/senador", "/candidato")):
            if "ranking.org.br/?" in path or path.rstrip("/") == "https://ranking.org.br":
                continue
        title = " ".join(raw[len(href[1]) : len(href[1]) + 220].split())[:140]
        hay = (title + " " + link).casefold()
        if tokens and not any(token in hay for token in tokens[:3]):
            continue
        if link in seen:
            continue
        seen.add(link)
        items.append({"nome": nome, "url": link, "snippet": title or "Ficha no Ranking dos Políticos"})
        if len(items) >= 6:
            break
    return items


def parse_ranking_hits(items: list[Any], *, origin_key: str, needle: str) -> ConnectorResult:
    out = ConnectorResult()
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or item.get("title") or "").strip()
        url = str(item.get("url") or item.get("href") or "").strip()
        if not url.startswith("http"):
            continue
        score = name_overlap_score(nome or needle, needle)
        if nome and score < 0.5:
            continue
        label = nome or "Ranking dos Políticos"
        found = FoundEntity(
            entity_type="PUBLICATION",
            kind="URL",
            value=url,
            display_name=label[:160],
            attrs={"fonte": "ranking.org.br", "identity_match": int(round(score * 100))},
            confidence=min(0.7, 0.45 + score * 0.3),
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.45, attrs={"fonte": "ranking"}))
        out.evidence.append(
            FoundEvidence(
                source_label="Ranking dos Políticos",
                url=url,
                snippet=str(item.get("snippet") or label)[:400],
                payload={"nome": nome, "match": int(round(score * 100))},
                entity_ref=ref,
            )
        )
    return out


def official_photo_attrs(row: dict[str, Any], *, needle: str, nome: str) -> dict[str, Any]:
    score = name_overlap_score(nome, needle)
    photo = _photo_url(row)
    attrs: dict[str, Any] = {"identity_match": int(round(score * 100))}
    if photo and score >= 0.5:
        attrs["thumb"] = photo
        attrs["profile_photo"] = photo
        attrs["profile_photo_source"] = "oficial"
    return attrs


class PoliticosPublicConnector:
    name = "politicos_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        headers = {"Accept": "application/json", "User-Agent": "osint4all/0.1 (politicos public)"}
        if settings.transparencia_api_key:
            headers["chave-api-dados"] = settings.transparencia_api_key
        self.http = RateLimitedClient(source=self.name, max_concurrency=2, timeout=25.0, default_headers=headers)

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": getattr(self.settings, "politicos_public_enable", True),
            "via": "PEP + TCU + ranking.org.br",
            "api_key_configured": bool(self.settings.transparencia_api_key),
            "free_fallback": True,
        }

    def accepts(self, entity: Entity) -> bool:
        return _name_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not getattr(self.settings, "politicos_public_enable", True):
            raise SkippedDisabled("Políticos/PEP desabilitado")
        nome = _name_from_entity(entity)
        if not nome:
            return ConnectorResult()
        origin = entity.canonical_key
        merged = ConnectorResult()
        cpf = ""
        if entity.canonical_key.startswith("cpf:"):
            cpf = only_digits(entity.canonical_key.split(":", 1)[1])
        else:
            for ident in getattr(entity, "identifiers", []) or []:
                if getattr(ident, "kind", "") == "CPF":
                    cpf = only_digits(ident.value)
                    break
        merged.merge(self._portals(nome, origin))
        merged.merge(self._pep(nome, origin, cpf=cpf))
        merged.merge(self._ranking(nome, origin))
        return merged

    def _portals(self, nome: str, origin_key: str) -> ConnectorResult:
        out = ConnectorResult()
        encoded = quote_plus(nome)
        portals = (
            ("TSE Dados Abertos", "Candidatos, bens, partido e situação da urna", "https://dadosabertos.tse.jus.br/"),
            ("DivulgaCandContas", "Ficha de candidatura e redes declaradas", "https://divulgacandcontas.tse.jus.br/"),
            ("CGU · PEP", "Cadastro oficial de pessoas expostas politicamente", "https://portaldatransparencia.gov.br/pessoa-exposta-politicamente"),
            ("Câmara · dados abertos", "Mandato, despesas, votações e foto oficial", "https://dadosabertos.camara.leg.br/"),
            ("Senado · dados abertos", "Senadores, filiação, mandatos e benefícios", "https://www.senado.leg.br/transparencia/LAI/secrh/"),
            ("CEIS / CNEP / CEAF / CEPIM", "Sanções, expulsões e impedimentos", "https://portaldatransparencia.gov.br/sancoes/consulta"),
            ("TCU · pesquisa", "Contas irregulares e responsáveis", f"https://pesquisa.apps.tcu.gov.br/#/pesquisa/all/{encoded}"),
            ("DOU · Imprensa Nacional", "Nomeações, exonerações e atos", "https://www.in.gov.br/consulta"),
            ("Ranking dos Políticos", "Notas e histórico parlamentar público", f"https://ranking.org.br/"),
        )
        for title, meta, url in portals:
            out.evidence.append(
                FoundEvidence(
                    source_label=title,
                    url=url,
                    snippet=f"{meta} · {nome}",
                    payload={"portal": title, "nome": nome},
                    entity_ref=origin_key,
                )
            )
        return out

    def _pep(self, nome: str, origin_key: str, *, cpf: str = "") -> ConnectorResult:
        merged = ConnectorResult()
        if not self.settings.transparencia_api_key:
            scraped = self._pep_portal(nome, origin_key, cpf=cpf)
            if scraped.entities or scraped.evidence:
                return scraped
            merged.notes.append("PEP: API paga/chave não é usada — consulta no portal público.")
            return scraped if scraped.notes else merged
        queries: list[dict[str, Any]] = []
        if cpf and len(cpf) == 11:
            queries.append({"cpf": cpf, "pagina": 1})
        for variant in name_search_variants(nome)[:2]:
            queries.append({"nome": variant, "pagina": 1})
        seen = 0
        for params in queries:
            try:
                resp = self.http.request(
                    "GET",
                    "https://api.portaldatransparencia.gov.br/api-de-dados/pep",
                    params=params,
                    allow_404=True,
                    max_retries=1,
                )
            except Exception as exc:  # noqa: BLE001
                merged.notes.append(f"PEP: {exc}"[:160])
                continue
            if resp.status_code >= 400:
                merged.notes.append(f"PEP HTTP {resp.status_code}")
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            rows = data if isinstance(data, list) else data.get("data") or data.get("dados") or []
            parsed = parse_pep_rows(rows if isinstance(rows, list) else [], origin_key=origin_key, needle=nome)
            merged.merge(parsed)
            seen += len(parsed.entities)
            if seen:
                break
        if not merged.entities:
            merged.merge(self._pep_portal(nome, origin_key, cpf=cpf))
        return merged

    def _pep_portal(self, nome: str, origin_key: str, *, cpf: str = "") -> ConnectorResult:
        from osint4all.connectors.html_public import parse_portal_html, parse_portal_payload

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://portaldatransparencia.gov.br/pessoa-exposta-politicamente",
        }
        params: dict[str, Any] = {
            "paginacaoSimples": "true",
            "tamanhoPagina": 15,
            "offset": 0,
            "nome": nome,
        }
        if cpf and len(cpf) == 11:
            params["cpf"] = cpf
        resp, err = self.http.safe_request(
            "GET",
            "https://portaldatransparencia.gov.br/pessoa-exposta-politicamente/consulta/resultado",
            params=params,
            headers=headers,
            max_retries=1,
        )
        if err or resp is None:
            return ConnectorResult(
                notes=[f"PEP portal: {err or 'sem resposta'}"],
                evidence=[
                    FoundEvidence(
                        source_label="CGU · PEP",
                        url="https://portaldatransparencia.gov.br/pessoa-exposta-politicamente",
                        snippet=f"Consulta pública gratuita · {nome}",
                        payload={"nome": nome, "via": "scraper"},
                        entity_ref=origin_key,
                    )
                ],
            )
        try:
            data = resp.json()
            rows = data if isinstance(data, list) else data.get("data") or data.get("dados") or []
            parsed = parse_pep_rows(rows if isinstance(rows, list) else [], origin_key=origin_key, needle=nome)
            if parsed.entities:
                return parsed
            extra = parse_portal_payload(data, origin_key=origin_key, lista="PEP")
            if extra.entities:
                return extra
        except Exception:
            pass
        html = parse_portal_html(resp.text or "", origin_key=origin_key, lista="PEP")
        if html.entities:
            return html
        return ConnectorResult(
            evidence=[
                FoundEvidence(
                    source_label="CGU · PEP",
                    url="https://portaldatransparencia.gov.br/pessoa-exposta-politicamente",
                    snippet=f"Consulta pública gratuita · {nome}",
                    payload={"nome": nome, "via": "scraper"},
                    entity_ref=origin_key,
                )
            ]
        )

    def _ranking(self, nome: str, origin_key: str) -> ConnectorResult:
        encoded = quote_plus(nome)
        urls = (
            f"https://ranking.org.br/?s={encoded}",
            f"https://ranking.org.br/politicos?q={encoded}",
            f"https://ranking.org.br/busca?q={encoded}",
        )
        items: list[dict[str, Any]] = []
        notes: list[str] = []
        for url in urls:
            try:
                resp = self.http.request("GET", url, allow_404=True, max_retries=1)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"ranking.org.br: {exc}"[:160])
                continue
            if resp.status_code >= 400:
                notes.append(f"ranking.org.br HTTP {resp.status_code}")
                continue
            items.extend(parse_ranking_html((resp.text or "")[:80000], nome=nome))
            if items:
                break
        if not items:
            items = [{"nome": nome, "url": "https://ranking.org.br/", "snippet": "Índice público de parlamentares"}]
        parsed = parse_ranking_hits(items, origin_key=origin_key, needle=nome)
        parsed.notes.extend(notes)
        return parsed
