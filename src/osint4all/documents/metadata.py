"""Metadados de PDF enviado pelo usuário — sem varrer a web."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from osint4all.connectors.base import FoundEntity
from osint4all.db.models import Entity, Investigation
from osint4all.graph.resolve import _add_evidence, _ensure_edge, upsert_found_entity
from osint4all.identifiers import canonical_key
from osint4all.paths import project_root

_INFO_KEYS = ("Title", "Author", "Subject", "Creator", "Producer", "CreationDate", "ModDate")
_LITERAL_RE = re.compile(rb"/([A-Za-z]+)\s*\(((?:\\.|[^\\)])*)\)")
_XMP_RE = re.compile(
    rb"<(?:dc:title|dc:creator|xmp:CreatorTool|pdf:Producer)[^>]*>\s*(?:<[^>]+>)?\s*([^<]{1,200})",
    re.I,
)


def extract_pdf_metadata(data: bytes) -> dict[str, str]:
    """Lê o dicionário Info e um pedaço de XMP do próprio arquivo."""
    head = data[: 256 * 1024]
    out: dict[str, str] = {}
    for match in _LITERAL_RE.finditer(head):
        key = match.group(1).decode("latin-1")
        if key not in _INFO_KEYS:
            continue
        raw = match.group(2).decode("latin-1", errors="replace")
        value = raw.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\").strip()
        if value:
            out[key.lower()] = value
    for match in _XMP_RE.finditer(head):
        tag = match.group(0).decode("latin-1", errors="replace")
        text = match.group(1).decode("utf-8", errors="replace").strip()
        if not text:
            continue
        if "dc:title" in tag and "title" not in out:
            out["title"] = text
        elif "dc:creator" in tag and "author" not in out:
            out["author"] = text
        elif "CreatorTool" in tag and "creator" not in out:
            out["creator"] = text
        elif "Producer" in tag and "producer" not in out:
            out["producer"] = text
    return out


def _upload_dir(investigation_id: str) -> Path:
    path = project_root() / "data" / "uploads" / investigation_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def ingest_local_pdf(
    session: Session,
    investigation: Investigation,
    *,
    filename: str,
    data: bytes,
) -> Entity:
    digest = hashlib.sha256(data).hexdigest()
    dest = _upload_dir(investigation.id) / f"{digest}.pdf"
    dest.write_bytes(data)
    meta = extract_pdf_metadata(data)
    display = meta.get("title") or filename
    found = FoundEntity(
        entity_type="PUBLICATION",
        kind="URL",
        value=f"local://documento/{digest}",
        display_name=display[:512],
        attrs={
            "filename": filename,
            "sha256": digest,
            "pdf_metadata": meta,
            "bytes": len(data),
        },
        confidence=0.95,
    )
    entity = upsert_found_entity(session, investigation, found, depth=0, is_seed=False)
    snippet_bits = [f"Arquivo {filename}"]
    for key in ("title", "author", "creator", "producer"):
        if meta.get(key):
            snippet_bits.append(f"{key}: {meta[key]}")
    _add_evidence(
        session,
        investigation,
        entity,
        "foca_local",
        "Metadados do PDF anexado",
        None,
        " · ".join(snippet_bits),
        {"sha256": digest, "metadata": meta, "path": str(dest)},
    )
    author = meta.get("author")
    if author and " " in author:
        person = upsert_found_entity(
            session,
            investigation,
            FoundEntity(
                entity_type="PERSON",
                kind="NAME",
                value=author,
                display_name=author,
                attrs={"from_pdf_author": True},
                confidence=0.4,
            ),
            depth=1,
        )
        _ensure_edge(
            session,
            investigation,
            entity.id,
            person.id,
            "MENCAO",
            0.4,
            {"field": "Author"},
            "foca_local",
        )
    return entity


def document_canonical_key(digest: str) -> str:
    return canonical_key("URL", f"local://documento/{digest}")


def metadata_summary(meta: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in meta.items() if v)
