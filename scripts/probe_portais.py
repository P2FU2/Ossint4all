"""Probe HTTP dos portais oficiais gerados por resolve_official_link_result.

Uso:
  .\\.venv\\Scripts\\python.exe scripts/probe_portais.py
  → data/outbox/portais_probe.json
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from monitor_jus.official_portal import resolve_official_link_result
from monitor_jus.validators import normalize_cnj

# CNJ sintético válido em formato por tribunal (J.TR)
_SAMPLES: dict[str, str] = {
    "stf": "0000001-00.2024.1.00.0000",
    "stj": "0000001-00.2020.3.00.0000",
    "tst": "0000001-00.2020.5.00.0000",
    "tse": "0000001-00.2020.6.00.0000",
    "tjsp": "1000123-45.2023.8.26.0100",
    "tjrj": "0000123-45.2023.8.19.0001",
    "tjmg": "0000123-45.2023.8.13.0024",
    "tjrs": "0000123-45.2023.8.21.0001",
    "tjpr": "0000123-45.2023.8.18.0001",  # 8.18 = PR
    "tjsc": "0000123-45.2023.8.24.0001",
    "tjba": "0000123-45.2023.8.05.0001",
    "tjce": "0000123-45.2023.8.06.0001",
    "tjgo": "0000123-45.2023.8.09.0001",
    "tjdft": "0000123-45.2023.8.07.0001",
    "tjes": "0000123-45.2023.8.08.0001",
    "tjpe": "0000123-45.2023.8.16.0001",  # 8.16 = PE
    "tjpb": "0000123-45.2023.8.15.0001",
    "tjrn": "0000123-45.2023.8.20.0001",
    "tjma": "0000123-45.2023.8.10.0001",
    "tjmt": "0000123-45.2023.8.11.0001",
    "tjms": "0000123-45.2023.8.12.0001",
    "tjpa": "0000123-45.2023.8.14.0001",
    "tjpi": "0000123-45.2023.8.17.0001",  # 8.17 = PI
    "tjal": "0000123-45.2023.8.02.0001",
    "tjam": "0000123-45.2023.8.04.0001",
    "tjac": "0000123-45.2023.8.01.0001",
    "tjap": "0000123-45.2023.8.03.0001",
    "tjro": "0000123-45.2023.8.22.0001",
    "tjrr": "0000123-45.2023.8.23.0001",
    "tjse": "0000123-45.2023.8.25.0001",
    "tjto": "0000123-45.2023.8.27.0001",
    "trf1": "1000123-45.2023.4.01.3400",
    "trf2": "0000123-45.2023.4.02.5101",
    "trf3": "0000123-45.2023.4.03.6100",
    "trf4": "5000123-45.2023.4.04.7100",
    "trf5": "0000123-45.2023.4.05.8100",
    "trf6": "0000123-45.2023.4.06.3800",
}

CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (compatible; monitor-jus-portal-probe/1.0)"}


def http_probe(url: str) -> dict:
    # Hash SPA: probe base path
    probe_url = url.split("#")[0] or url
    if not probe_url.endswith("/") and "?" not in probe_url and probe_url.count("/") <= 3:
        pass
    req = urllib.request.Request(probe_url, headers=UA, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            body = r.read(2500).decode("utf-8", "replace")
            return {
                "http": r.status,
                "final_url": r.geturl()[:180],
                "ctype": (r.headers.get("content-type") or "")[:80],
                "body_hint": body[:120].replace("\n", " "),
            }
    except urllib.error.HTTPError as e:
        return {"http": e.code, "error": e.reason, "final_url": getattr(e, "url", "")[:180]}
    except Exception as e:  # noqa: BLE001
        return {"http": None, "error": f"{type(e).__name__}: {e}"}


def classify(link) -> str:
    url = (link.url or "").lower()
    if not url:
        return "unavailable"
    if link.requires_manual_search or link.link_type in {"COURT_SEARCH_PAGE", "COURT_HOMEPAGE"}:
        if "listview.seam" in url:
            return "pje_empty_listview"
        if "open.do" in url and "search.do" not in url:
            return "esaj_homepage"
        if "?" not in url and "#" not in url:
            return "homepage_no_query"
        return "manual_search"
    if link.link_type in {"PROCESS_SEARCH_PREFILLED", "PROCESS_DEEP_LINK"}:
        return "prefilled_ok"
    return link.link_type


def main() -> None:
    rows = []
    for court, cnj in _SAMPLES.items():
        parts = normalize_cnj(cnj)
        assert parts, cnj
        link = resolve_official_link_result(cnj, tribunal=court.upper())
        kind = classify(link)
        probe = http_probe(link.url) if link.url else {}
        rows.append(
            {
                "court": court,
                "cnj": cnj,
                "url": link.url,
                "link_type": link.link_type,
                "confidence": link.confidence,
                "requires_manual_search": link.requires_manual_search,
                "kind": kind,
                "http": probe,
            }
        )
        print(f"{court:8} {kind:22} HTTP={probe.get('http')} {link.url[:90]}")
        time.sleep(0.15)

    out = Path("data/outbox/portais_probe.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "total": len(rows),
        "by_kind": {},
        "rows": rows,
    }
    for r in rows:
        summary["by_kind"][r["kind"]] = summary["by_kind"].get(r["kind"], 0) + 1
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSUMMARY", json.dumps(summary["by_kind"], ensure_ascii=False))
    print("wrote", out)


if __name__ == "__main__":
    main()
