"""Conector Wikidata — busca pública e cargos."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.graph.identity import name_overlap_score, name_tokens
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key


def commons_file_url(filename: str) -> str:
    clean = (filename or "").strip().replace(" ", "_")
    if clean.lower().startswith("file:"):
        clean = clean[5:]
    if not clean:
        return ""
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(clean)}"


def _claim_strings(claims: dict[str, Any], pid: str) -> list[str]:
    out: list[str] = []
    for row in claims.get(pid) or []:
        if not isinstance(row, dict):
            continue
        snak = row.get("mainsnak") if isinstance(row.get("mainsnak"), dict) else {}
        data = snak.get("datavalue") if isinstance(snak.get("datavalue"), dict) else {}
        value = data.get("value")
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
        elif isinstance(value, dict):
            time = str(value.get("time") or "")
            if time.startswith("+") and "T" in time:
                out.append(time[1:].split("T", 1)[0])
            elif value.get("id"):
                out.append(str(value["id"]))
            elif value.get("text"):
                out.append(str(value["text"]))
    return out


def parse_wikidata_entity(payload: dict[str, Any], *, origin_key: str, needle: str = "") -> ConnectorResult:
    out = ConnectorResult()
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, dict):
        return out
    for qid, item in list(entities.items())[:4]:
        if not isinstance(item, dict) or str(qid).startswith("-"):
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        label = ""
        for lang in ("pt", "pt-br", "en"):
            block = labels.get(lang)
            if isinstance(block, dict) and block.get("value"):
                label = str(block["value"])
                break
        label = label or str(qid)
        if needle and len(name_tokens(needle)) >= 2 and name_overlap_score(label, needle) < 0.4:
            continue
        claims = item.get("claims") if isinstance(item.get("claims"), dict) else {}
        photo = ""
        files = _claim_strings(claims, "P18")
        if files:
            photo = commons_file_url(files[0])
        birth = (_claim_strings(claims, "P569") or [""])[0]
        sitelinks = item.get("sitelinks") if isinstance(item.get("sitelinks"), dict) else {}
        wiki = sitelinks.get("ptwiki") if isinstance(sitelinks.get("ptwiki"), dict) else sitelinks.get("enwiki")
        wiki_title = str((wiki or {}).get("title") or "") if isinstance(wiki, dict) else ""
        wiki_host = "pt" if "ptwiki" in sitelinks else "en"
        wiki_url = f"https://{wiki_host}.wikipedia.org/wiki/{quote(wiki_title.replace(' ', '_'))}" if wiki_title else ""
        score = name_overlap_score(label, needle) if needle else 0.6
        attrs: dict[str, Any] = {
            "wikidata_id": qid,
            "nascimento": birth,
            "identity_match": int(round(score * 100)),
        }
        if photo and score >= 0.5:
            attrs["thumb"] = photo
            attrs["profile_photo"] = photo
            attrs["profile_photo_source"] = "wikidata"
        if photo or birth:
            out.entities.append(
                FoundEntity(
                    entity_type="PERSON",
                    kind="NAME",
                    value=label,
                    display_name=label,
                    attrs={"papel": "wikidata", "status": "unconfirmed", **attrs},
                    confidence=min(0.72, 0.45 + score * 0.3),
                )
            )
        if wiki_url:
            found = FoundEntity(
                entity_type="PUBLICATION",
                kind="URL",
                value=wiki_url,
                display_name=wiki_title or label,
                attrs={"fonte": "wikipedia", "wikidata_id": qid},
                confidence=0.55,
            )
            out.entities.append(found)
            ref = canonical_key("URL", wiki_url)
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5))
            out.evidence.append(
                FoundEvidence(
                    source_label="Wikipedia",
                    url=wiki_url,
                    snippet=label,
                    payload={"id": qid, "label": label, "nascimento": birth},
                    entity_ref=ref,
                )
            )
    return out


def parse_wikidata_search(results: list[dict[str, Any]], *, origin_key: str, needle: str = "") -> ConnectorResult:
    out = ConnectorResult()
    for item in results[:8]:
        qid = str(item.get("id") or "")
        label = str(item.get("label") or item.get("title") or qid)
        desc = str(item.get("description") or "")
        if needle and len(name_tokens(needle)) >= 2 and name_overlap_score(label, needle) < 0.4:
            continue
        url = f"https://www.wikidata.org/wiki/{qid}" if qid else "https://www.wikidata.org/"
        found = FoundEntity(
            entity_type="PUBLICATION" if item.get("concepturi") else "PERSON",
            kind="URL",
            value=url,
            display_name=f"{label} ({qid})" if qid else label,
            attrs={"wikidata_id": qid, "description": desc},
            confidence=0.5,
        )
        # Pessoa/organização descrita no Wikidata vira PUBLICATION (ficha) ligada à origem
        found.entity_type = "PUBLICATION"
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5))
        out.evidence.append(
            FoundEvidence(
                source_label="Wikidata",
                url=url,
                snippet=f"{label} — {desc}".strip(" —"),
                payload={"id": qid, "label": label, "description": desc},
                entity_ref=ref,
            )
        )
    return out


class WikidataConnector:
    name = "wikidata"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=25.0,
            default_headers={
                "Accept": "application/json",
                "User-Agent": "osint4all/0.3 (https://github.com/P2FU2/Ossint4all; public OSINT research)",
            },
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.wikidata_enable}

    def accepts(self, entity: Entity) -> bool:
        return entity.entity_type in {"PERSON", "ORG"} and bool(entity.display_name)

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.wikidata_enable:
            raise SkippedDisabled("Wikidata desabilitado")
        nome = entity.display_name
        resp, err = self.http.safe_request(
            "GET",
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": nome,
                "language": "pt",
                "uselang": "pt",
                "format": "json",
                "limit": 8,
            },
        )
        results: list[Any] = []
        if err:
            notes = [f"Wikidata: {err}"]
        else:
            notes = []
            try:
                data = resp.json() if resp is not None else {}
            except Exception:
                data = {}
            results = data.get("search") if isinstance(data, dict) else []
        if not results:
            fallback, ferr = self.http.safe_request(
                "GET",
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "search": nome,
                    "language": "en",
                    "uselang": "en",
                    "format": "json",
                    "limit": 8,
                },
            )
            if ferr:
                notes.append(f"Wikidata EN: {ferr}")
            elif fallback is not None:
                try:
                    extra = fallback.json()
                except Exception:
                    extra = {}
                results = extra.get("search") if isinstance(extra, dict) else []
        parsed = parse_wikidata_search(results or [], origin_key=entity.canonical_key, needle=nome)
        qids = [str(item.get("id") or "") for item in (results or [])[:3] if isinstance(item, dict) and item.get("id")]
        if qids:
            detail, derr = self.http.safe_request(
                "GET",
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(qids),
                    "props": "labels|descriptions|claims|sitelinks",
                    "languages": "pt|en",
                    "format": "json",
                },
            )
            if derr:
                notes.append(f"Wikidata ficha: {derr}")
            elif detail is not None:
                try:
                    payload = detail.json()
                except Exception:
                    payload = {}
                parsed.merge(parse_wikidata_entity(payload if isinstance(payload, dict) else {}, origin_key=entity.canonical_key, needle=nome))
        parsed.notes.extend(notes)
        if not parsed.entities:
            parsed.merge(self._wikipedia(nome, entity.canonical_key))
        if not parsed.entities:
            parsed.notes.append("Wikidata/Wikipedia sem ficha pública para este nome.")
        return parsed

    def _wikipedia(self, nome: str, origin_key: str) -> ConnectorResult:
        out = ConnectorResult()
        for lang in ("pt", "en"):
            resp, err = self.http.safe_request(
                "GET",
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": nome, "limit": 5, "namespace": 0, "format": "json"},
            )
            if err or resp is None:
                out.notes.append(f"Wikipedia {lang}: {err or 'sem resposta'}")
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            titles = data[1] if isinstance(data, list) and len(data) > 1 else []
            urls = data[3] if isinstance(data, list) and len(data) > 3 else []
            descs = data[2] if isinstance(data, list) and len(data) > 2 else []
            for idx, title in enumerate(titles[:5]):
                label = str(title or "").strip()
                if not label:
                    continue
                if len(name_tokens(nome)) >= 2 and name_overlap_score(label, nome) < 0.4:
                    continue
                url = str(urls[idx] if idx < len(urls) else f"https://{lang}.wikipedia.org/wiki/{quote(label.replace(' ', '_'))}")
                desc = str(descs[idx] if idx < len(descs) else "")
                out.entities.append(
                    FoundEntity(
                        entity_type="PUBLICATION",
                        kind="URL",
                        value=url,
                        display_name=label[:160],
                        attrs={"fonte": "wikipedia", "description": desc},
                        confidence=0.52,
                    )
                )
                ref = canonical_key("URL", url)
                out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5))
                out.evidence.append(
                    FoundEvidence(
                        source_label="Wikipedia",
                        url=url,
                        snippet=(desc or label)[:400],
                        payload={"title": label, "lang": lang},
                        entity_ref=ref,
                    )
                )
            if out.entities:
                photo = self._wikipedia_photo(str(titles[0]), lang, nome)
                if photo:
                    out.entities.append(
                        FoundEntity(
                            entity_type="PERSON",
                            kind="NAME",
                            value=nome,
                            display_name=str(titles[0]),
                            attrs={"papel": "wikidata", "status": "unconfirmed", **photo},
                            confidence=0.58,
                        )
                    )
                break
        return out

    def _wikipedia_photo(self, title: str, lang: str, needle: str) -> dict[str, Any]:
        resp, err = self.http.safe_request(
            "GET",
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "pageimages|pageprops",
                "titles": title,
                "pithumbsize": 400,
                "ppprop": "wikibase_item",
                "format": "json",
            },
        )
        if err or resp is None:
            return {}
        try:
            data = resp.json()
        except Exception:
            return {}
        pages = ((data.get("query") or {}).get("pages") or {}) if isinstance(data, dict) else {}
        if not isinstance(pages, dict):
            return {}
        attrs: dict[str, Any] = {}
        score = name_overlap_score(title, needle)
        attrs["identity_match"] = int(round(score * 100))
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            props = page.get("pageprops") if isinstance(page.get("pageprops"), dict) else {}
            if props.get("wikibase_item"):
                attrs["wikidata_id"] = str(props["wikibase_item"])
            thumb = ((page.get("thumbnail") or {}).get("source") if isinstance(page.get("thumbnail"), dict) else "")
            if thumb and score >= 0.5:
                attrs["thumb"] = thumb
                attrs["profile_photo"] = thumb
                attrs["profile_photo_source"] = "wikipedia"
        return attrs
