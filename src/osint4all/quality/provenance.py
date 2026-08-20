"""Provenance: hash de conteúdo e captura local da evidência."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from osint4all.paths import project_root


def content_hash(payload: dict[str, Any] | None, snippet: str | None, url: str | None = None) -> str:
    raw = json.dumps(
        {"p": payload or {}, "s": (snippet or "")[:2000], "u": url or ""},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_snapshot(investigation_id: str, digest: str, body: bytes, *, suffix: str = ".html") -> str:
    folder = project_root() / "data" / "captures" / investigation_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{digest}{suffix}"
    dest.write_bytes(body[: 512 * 1024])
    return str(dest.relative_to(project_root())).replace("\\", "/")


def snapshot_abs(rel: str) -> Path | None:
    if not rel or ".." in rel:
        return None
    path = project_root() / rel
    captures = (project_root() / "data" / "captures").resolve()
    uploads = (project_root() / "data" / "uploads").resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not (resolved.is_relative_to(captures) or resolved.is_relative_to(uploads)):
        return None
    return resolved if resolved.is_file() else None
