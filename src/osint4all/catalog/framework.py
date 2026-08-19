"""Árvore do OSINT Framework + ramo Brasil, com filtro de categorias restritas."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from osint4all.catalog.brazil import brazil_branch
from osint4all.catalog.local_suite import local_suite_branch
from osint4all.http_client import RateLimitedClient
from osint4all.logging_setup import get_logger
from osint4all.paths import project_root

logger = get_logger(__name__)

ARF_URL = "https://raw.githubusercontent.com/lockfale/osint-framework/master/public/arf.json"
SOURCE_PAGE = "https://osintframework.com/"

# Pastas/ferramentas de dados vazados, exploits ou mercados — fora do produto.
EXCLUDED_NAMES = frozenset(
    {
        "breach data",
        "dark web",
        "darknet",
        "leaked",
        "stolen",
        "exploit",
        "exploits",
        "malware",
        "password",
        "passwords",
        "credit card",
        "dumps",
        "dehashed",
        "vigilante.pw",
        "snusbase",
        "leakcheck",
        "intelx",
        "darksearch",
        "onionsearch",
        "ahmia",
        "toutatis",
        "yesitsme",
        "hudson rock",
        "stealer",
    }
)

KIND_TO_BRANCHES = {
    "USERNAME": {"Username", "Social Networks", "Instant Messaging", "Suíte local (T)"},
    "EMAIL": {"Email Address", "Suíte local (T)"},
    "PHONE": {"Telephone Numbers", "Suíte local (T)"},
    "NAME": {"People Search Engines", "Social Networks", "Username", "Brasil · oficiais"},
    "CPF": {"Brasil · oficiais", "People Search Engines", "Cadastros profissionais e empresa"},
    "CNPJ": {"Brasil · oficiais", "Business Records", "Cadastros profissionais e empresa"},
    "CNJ": {"Brasil · oficiais", "Tribunais e consultas (Brazuca)"},
    "URL": {"Domain Name", "IP Address", "Suíte local (T)"},
    "OAB": {"Brasil · oficiais", "Cadastros profissionais e empresa"},
    "PLATE": {"Transportation", "Brasil · oficiais"},
}


def cache_path() -> Path:
    path = project_root() / "data" / "osint_framework.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _is_excluded(name: str, url: str = "") -> bool:
    blob = f"{name} {url}".casefold()
    return any(token in blob for token in EXCLUDED_NAMES)


def filter_tree(node: dict[str, Any]) -> dict[str, Any] | None:
    name = str(node.get("name") or "")
    url = str(node.get("url") or "")
    if _is_excluded(name, url):
        return None
    if node.get("deprecated"):
        return None
    children = node.get("children") or []
    if children:
        kept = [c for c in (filter_tree(c) for c in children) if c]
        if not kept and node.get("type") == "folder":
            return None
        out = {**node, "children": kept}
        return out
    return dict(node)


def apply_seed_to_url(url: str, seed: str, *, edit_url: bool = False) -> str:
    """Preenche placeholders de ferramentas M (URL editável) com a semente."""
    if not url or not seed:
        return url
    token = quote_plus(seed.strip())
    raw = seed.strip()
    for placeholder in ("{seed}", "{q}", "{query}", "{username}", "{email}", "{domain}"):
        if placeholder in url:
            return url.replace(placeholder, token if placeholder != "{seed}" else raw)
    if edit_url and "{seed}" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}q={token}"
    return url


def matching_branches(kind: str | None) -> set[str]:
    if not kind:
        return set()
    return set(KIND_TO_BRANCHES.get(kind.upper(), set()))


def _annotate(node: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    flags = []
    if node.get("localInstall"):
        flags.append("T")
    if node.get("googleDork"):
        flags.append("D")
    if node.get("registration"):
        flags.append("R")
    if node.get("editUrl"):
        flags.append("M")
    if node.get("internal"):
        flags.append("INT")
    out = {
        **node,
        "parent": parent,
        "flags": flags,
        "source": node.get("source") or "osint-framework",
    }
    kids = node.get("children") or []
    if kids:
        out["children"] = [_annotate(child, node.get("name")) for child in kids]
    return out


def extra_branches() -> list[dict[str, Any]]:
    return [brazil_branch(), local_suite_branch()]


def merge_brazil(root: dict[str, Any]) -> dict[str, Any]:
    tree = deepcopy(root)
    children = list(tree.get("children") or [])
    names = {str(c.get("name")) for c in children}
    extras = extra_branches()
    for branch in reversed(extras):
        if branch["name"] not in names:
            children.insert(0, branch)
    tree["children"] = children
    tree["name"] = "OSINT4ALL"
    return tree


def brazil_only_root() -> dict[str, Any]:
    return {"name": "OSINT Framework", "type": "folder", "children": []}


def load_raw_framework(*, refresh: bool = False, http: RateLimitedClient | None = None) -> dict[str, Any]:
    cached = cache_path()
    if cached.exists() and not refresh:
        return json.loads(cached.read_text(encoding="utf-8"))
    try:
        client = http or RateLimitedClient(
            source="osint-framework",
            timeout=30.0,
            default_headers={"User-Agent": "osint4all/0.1 (catalog)", "Accept": "application/json"},
        )
        resp = client.request("GET", ARF_URL)
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("ARF JSON inválido")
        cached.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        logger.info("osint_framework_cached path=%s", cached)
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("osint_framework_fetch_failed %s", exc)
        if cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))
        return brazil_only_root()


def load_framework_tree(
    *,
    refresh: bool = False,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = raw if raw is not None else load_raw_framework(refresh=refresh)
    filtered = filter_tree(source) or {"name": "OSINT Framework", "type": "folder", "children": []}
    merged = merge_brazil(filtered)
    merged["source_page"] = SOURCE_PAGE
    return _annotate(merged)


def tree_stats(node: dict[str, Any]) -> dict[str, int]:
    folders = 0
    tools = 0

    def walk(item: dict[str, Any]) -> None:
        nonlocal folders, tools
        if item.get("type") == "folder":
            folders += 1
            for child in item.get("children") or []:
                walk(child)
        else:
            tools += 1

    walk(node)
    return {"folders": folders, "tools": tools}
