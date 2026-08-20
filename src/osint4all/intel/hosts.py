"""Camada estilo IVRE: normaliza, indexa e correlaciona hosts já conhecidos.

Não inicia scan. Porta/IP só entram se vieram de API oficial ou de um JSON
que o jornalista já tinha (import). httpx/Photon/Nuclei aqui são parsers
informativos sobre um único hostname público.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import HostIntel, Investigation
from osint4all.db.repository import utcnow

_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{1,200})", re.I)
_GEN_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\']generator["\'][^>]+content=["\']([^"\']{1,120})',
    re.I,
)
_HREF_RE = re.compile(r"""(?:href|src)=["']([^"']+)["']""", re.I)
_MAILTO_RE = re.compile(r"mailto:([^\s,;>]+)", re.I)
_PRIVATE = frozenset({"localhost", "localhost.localdomain"})


@dataclass
class HostObservation:
    host: str
    ip: str = ""
    port: int | None = None
    status: int | None = None
    title: str = ""
    tech: list[str] = field(default_factory=list)
    cert: str = ""
    source: str = ""
    origin: str = "passive"
    snippet: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class HostCard:
    host: str
    sources: list[str]
    origins: list[str]
    title: str
    tech: list[str]
    ips: list[str]
    history: list[tuple[str, str]]
    rows: list[HostObservation]


def is_public_hostname(host: str) -> bool:
    text = (host or "").strip().lower().lstrip("www.").rstrip(".")
    if not text or text in _PRIVATE:
        return False
    if text.endswith((".local", ".internal", ".localhost", ".lan")):
        return False
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", text):
        return False
    return bool(_HOST_RE.match(text))


def normalize_host(raw: str) -> str | None:
    text = (raw or "").strip().lower()
    if "://" in text:
        text = (urlparse(text).hostname or "")
    text = text.split("/")[0].split(":")[0].lstrip("www.").rstrip(".")
    return text if is_public_hostname(text) else None


def _tech_list(*parts: str) -> list[str]:
    seen: list[str] = []
    for part in parts:
        label = re.sub(r"\s+", " ", (part or "").strip())
        if not label or label.lower() in {t.lower() for t in seen}:
            continue
        seen.append(label[:80])
        if len(seen) >= 8:
            break
    return seen


def parse_http_snapshot(
    url: str,
    *,
    status: int,
    headers: dict[str, str] | None = None,
    html: str = "",
) -> HostObservation | None:
    host = normalize_host(url)
    if not host:
        return None
    hdrs = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    title_m = _TITLE_RE.search(html or "")
    gen_m = _GEN_RE.search(html or "")
    title = (title_m.group(1) if title_m else "").strip()
    tech = _tech_list(hdrs.get("server") or "", hdrs.get("x-powered-by") or "", gen_m.group(1) if gen_m else "")
    snippet = " · ".join(part for part in (f"HTTP {status}", title, ", ".join(tech)) if part)
    return HostObservation(
        host=host,
        status=status,
        title=title[:180],
        tech=tech,
        source="observe_http",
        origin="observe",
        snippet=snippet[:400],
        extra={"url": f"https://{host}/"},
    )


def extract_same_domain_links(html: str, domain: str, *, limit: int = 8) -> list[str]:
    """Photon controlado: só links do mesmo domínio, homepage, sem seguir."""
    apex = normalize_host(domain)
    if not apex:
        return []
    found: list[str] = []
    seen: set[str] = set()
    base = f"https://{apex}/"
    for match in _HREF_RE.finditer(html or ""):
        raw = match.group(1).strip()
        if raw.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
            continue
        absolute = urljoin(base, raw)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = normalize_host(parsed.hostname or "")
        if not host or not (host == apex or host.endswith("." + apex)):
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"
        if clean in seen:
            continue
        seen.add(clean)
        found.append(clean)
        if len(found) >= limit:
            break
    return found


def parse_security_txt(text: str) -> list[tuple[str, str]]:
    """Arquivo público RFC 9116 — contato e política. Sem CVE."""
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "contact" and value:
            mail = _MAILTO_RE.search(value)
            out.append(("contact", mail.group(1).lower() if mail else value[:200]))
        elif key == "policy" and value.startswith("http"):
            out.append(("policy", value[:300]))
        if len(out) >= 6:
            break
    return out


def parse_robots(text: str) -> list[str]:
    """Só sitemaps anunciados — não interpretamos Disallow como mapa do site."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if line.lower().startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            if url.startswith("http") and url not in out:
                out.append(url[:300])
        if len(out) >= 4:
            break
    return out


def parse_banner_record(row: dict[str, Any]) -> HostObservation | None:
    """ZGrab2 / Shodan já coletado: status, produto, host. Sem corpo de banner."""
    if not isinstance(row, dict):
        return None
    host = normalize_host(str(row.get("host") or row.get("domain") or row.get("name") or ""))
    names = row.get("name") or row.get("names") or row.get("hostnames") or []
    if not host and isinstance(names, list) and names:
        host = normalize_host(str(names[0]))
    if not host:
        return None
    status = _as_int(row.get("status") or row.get("status_code"))
    title = str(row.get("title") or "").strip()
    product = str(row.get("product") or row.get("service") or "").strip()
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    http = data.get("http") if isinstance(data.get("http"), dict) else {}
    result = http.get("result") if isinstance(http.get("result"), dict) else http
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    if status is None:
        status = _as_int(response.get("status_code") or response.get("status"))
    headers = response.get("headers") if isinstance(response.get("headers"), dict) else {}
    server = ""
    if isinstance(headers.get("server"), list) and headers["server"]:
        server = str(headers["server"][0])
    elif headers.get("server"):
        server = str(headers.get("server"))
    tech = _tech_list(product, server, str(row.get("server") or ""))
    ip = str(row.get("ip") or row.get("ip_str") or "").strip()
    port = _as_int(row.get("port"))
    snippet = " · ".join(part for part in (host, f"HTTP {status}" if status else "", ", ".join(tech), title) if part)
    return HostObservation(
        host=host,
        ip=ip if _public_ip(ip) else "",
        port=port,
        status=status,
        title=title[:180],
        tech=tech,
        source=str(row.get("source") or "banner_import"),
        origin="import" if row.get("source") in {None, "", "banner_import", "zgrab2", "masscan"} else str(row.get("origin") or "import"),
        snippet=snippet[:400],
    )


def parse_imported_host_rows(raw: Any) -> list[HostObservation]:
    """JSON que o jornalista já tem. Linha sem hostname público é ignorada (não indexa varredura de IP)."""
    rows: list[Any]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        rows = next(
            (raw[key] for key in ("hosts", "matches", "results") if isinstance(raw.get(key), list)),
            [raw],
        )
    elif isinstance(raw, list):
        rows = raw
    else:
        return []
    out: list[HostObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        obs = parse_banner_record(row)
        if not obs:
            continue
        obs.origin = "import"
        if not obs.source or obs.source == "banner_import":
            obs.source = "import"
        out.append(obs)
        if len(out) >= 40:
            break
    return out


def observation_from_payload(payload: dict[str, Any] | None, *, source: str) -> HostObservation | None:
    if not isinstance(payload, dict):
        return None
    host = normalize_host(str(payload.get("host") or payload.get("domain") or ""))
    if not host:
        return None
    tech = payload.get("tech") if isinstance(payload.get("tech"), list) else []
    product = str(payload.get("produto") or payload.get("product") or payload.get("server") or "")
    labels = _tech_list(*[str(t) for t in tech], product)
    status = _as_int(payload.get("status"))
    title = str(payload.get("title") or "").strip()
    origin = str(payload.get("origin") or "passive")
    if origin not in {"passive", "observe", "import"}:
        origin = "passive"
    return HostObservation(
        host=host,
        ip=str(payload.get("ip") or "") if _public_ip(str(payload.get("ip") or "")) else "",
        port=_as_int(payload.get("port") or payload.get("porta")),
        status=status,
        title=title[:180],
        tech=labels,
        cert=str(payload.get("cert") or payload.get("issuer") or "")[:180],
        source=source or str(payload.get("fonte") or "unknown"),
        origin=origin,
        snippet=str(payload.get("snippet") or title or host)[:400],
        extra={k: payload[k] for k in ("local", "org", "fonte") if payload.get(k)},
    )


def correlate_hosts(rows: list[HostObservation]) -> list[HostCard]:
    grouped: dict[str, list[HostObservation]] = defaultdict(list)
    for row in rows:
        if row.host:
            grouped[row.host].append(row)
    cards: list[HostCard] = []
    for host, items in sorted(grouped.items()):
        sources = list(dict.fromkeys(i.source for i in items if i.source))
        origins = list(dict.fromkeys(i.origin for i in items if i.origin))
        tech = _tech_list(*(t for i in items for t in i.tech))
        ips = list(dict.fromkeys(i.ip for i in items if i.ip))
        title = next((i.title for i in items if i.title), "")
        history = [(i.source, i.snippet or i.title or i.origin) for i in items if i.source]
        cards.append(
            HostCard(
                host=host,
                sources=sources,
                origins=origins,
                title=title,
                tech=tech,
                ips=ips,
                history=history[:12],
                rows=items,
            )
        )
    return cards


def upsert_host_intel(
    session: Session,
    investigation: Investigation,
    entity_id: str | None,
    obs: HostObservation,
) -> HostIntel | None:
    if not obs.host or not is_public_hostname(obs.host):
        return None
    existing = session.scalar(
        select(HostIntel).where(
            HostIntel.investigation_id == investigation.id,
            HostIntel.host == obs.host,
            HostIntel.source == (obs.source or "unknown")[:64],
        )
    )
    now = utcnow()
    if existing:
        existing.last_seen_at = now
        if entity_id and not existing.entity_id:
            existing.entity_id = entity_id
        if obs.ip:
            existing.ip = obs.ip[:64]
        if obs.port is not None:
            existing.port = obs.port
        if obs.status is not None:
            existing.status = obs.status
        if obs.title:
            existing.title = obs.title[:255]
        tech = list(existing.tech or [])
        for item in obs.tech:
            if item not in tech:
                tech.append(item)
        existing.tech = tech[:12]
        if obs.cert:
            existing.cert = obs.cert[:255]
        if obs.snippet:
            existing.snippet = obs.snippet[:400]
        payload = dict(existing.payload or {})
        payload.update(obs.extra)
        existing.payload = payload
        return existing
    row = HostIntel(
        investigation_id=investigation.id,
        entity_id=entity_id,
        host=obs.host[:255],
        ip=(obs.ip or "")[:64],
        port=obs.port,
        status=obs.status,
        title=(obs.title or "")[:255],
        tech=list(obs.tech)[:12],
        cert=(obs.cert or "")[:255],
        source=(obs.source or "unknown")[:64],
        origin=(obs.origin or "passive")[:16],
        snippet=(obs.snippet or "")[:400],
        payload=obs.extra,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(row)
    return row


def cards_for_host(session: Session, investigation_id: str, host: str) -> list[HostCard]:
    needle = normalize_host(host)
    if not needle:
        return []
    rows = session.scalars(
        select(HostIntel).where(HostIntel.investigation_id == investigation_id, HostIntel.host == needle)
    ).all()
    return correlate_hosts([_row_to_obs(r) for r in rows])


def cards_for_entity(session: Session, investigation_id: str, entity: Any) -> list[HostCard]:
    hosts: set[str] = set()
    for raw in (
        getattr(entity, "display_name", None),
        (getattr(entity, "attrs", None) or {}).get("host"),
        str(getattr(entity, "canonical_key", "")).split(":", 1)[-1],
    ):
        host = normalize_host(str(raw or ""))
        if host:
            hosts.add(host)
    rows: list[HostObservation] = []
    for host in hosts:
        for card in cards_for_host(session, investigation_id, host):
            rows.extend(card.rows)
    return correlate_hosts(rows)


def cards_for_investigation(session: Session, investigation_id: str, *, limit: int = 40) -> list[HostCard]:
    rows = session.scalars(
        select(HostIntel).where(HostIntel.investigation_id == investigation_id).limit(limit)
    ).all()
    return correlate_hosts([_row_to_obs(r) for r in rows])


def _row_to_obs(row: HostIntel) -> HostObservation:
    return HostObservation(
        host=row.host,
        ip=row.ip or "",
        port=row.port,
        status=row.status,
        title=row.title or "",
        tech=list(row.tech or []),
        cert=row.cert or "",
        source=row.source,
        origin=row.origin,
        snippet=row.snippet or "",
        extra=dict(row.payload or {}),
    )


def _as_int(value: Any) -> int | None:
    try:
        number = int(str(value).split()[0])
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 65535 else None


def _public_ip(ip: str) -> bool:
    text = (ip or "").strip()
    if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", text):
        return False
    parts = [int(p) for p in text.split(".")]
    if parts[0] in {0, 10, 127} or parts == [169, 254, 169, 254]:
        return False
    if parts[0] == 192 and parts[1] == 168:
        return False
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return False
    return True
