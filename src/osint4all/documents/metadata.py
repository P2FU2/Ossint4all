"""Metadados de arquivo enviado pelo usuário (PDF/JPEG/PNG) — sem varrer a web."""

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


def extract_png_text(data: bytes) -> dict[str, str]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {}
    out: dict[str, str] = {}
    i = 8
    aliases = {"author": "author", "title": "title", "software": "software", "comment": "comment", "description": "title"}
    while i + 12 <= len(data):
        length = int.from_bytes(data[i : i + 4], "big")
        kind = data[i + 4 : i + 8]
        chunk = data[i + 8 : i + 8 + length]
        i += 12 + length
        if kind == b"IEND":
            break
        if kind not in {b"tEXt", b"iTXt"} or b"\x00" not in chunk:
            continue
        key, _, raw = chunk.partition(b"\x00")
        label = aliases.get(key.decode("latin-1", errors="ignore").lower())
        text = raw.decode("utf-8", errors="replace").strip("\x00 ").strip()
        if label and text and label not in out:
            out[label] = text[:200]
    return out


def extract_jpeg_exif(data: bytes) -> dict[str, str]:
    if not data.startswith(b"\xff\xd8"):
        return {}
    i = 2
    while i + 4 < len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        seglen = int.from_bytes(data[i + 2 : i + 4], "big")
        if marker == 0xDA or seglen < 2:
            break
        payload = data[i + 4 : i + 2 + seglen]
        i += 2 + seglen
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            return _parse_tiff_ascii(payload[6:])
    return {}


def _parse_tiff_ascii(blob: bytes) -> dict[str, str]:
    if len(blob) < 8:
        return {}
    endian = "<" if blob[:2] == b"II" else ">"
    import struct

    try:
        offset = struct.unpack(endian + "I", blob[4:8])[0]
        count = struct.unpack(endian + "H", blob[offset : offset + 2])[0]
    except struct.error:
        return {}
    wanted = {0x010F: "make", 0x0110: "model", 0x0131: "software", 0x0132: "datetime", 0x013B: "author"}
    out: dict[str, str] = {}
    pos = offset + 2
    for _ in range(min(count, 64)):
        if pos + 12 > len(blob):
            break
        tag, typ, n = struct.unpack(endian + "HHI", blob[pos : pos + 8])
        val = blob[pos + 8 : pos + 12]
        pos += 12
        if tag not in wanted or typ != 2 or n < 2:
            continue
        start = struct.unpack(endian + "I", val)[0] if n > 4 else pos - 4
        raw = blob[start : start + n]
        text = raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()
        if text:
            out[wanted[tag]] = text[:200]
    return out


def extract_file_metadata(filename: str, data: bytes) -> dict[str, str]:
    name = (filename or "").lower()
    if name.endswith(".pdf") or data.startswith(b"%PDF"):
        return extract_pdf_metadata(data)
    if name.endswith(".png") or data.startswith(b"\x89PNG"):
        return extract_png_text(data)
    if name.endswith((".jpg", ".jpeg")) or data.startswith(b"\xff\xd8"):
        return extract_jpeg_exif(data)
    return {}


def ingest_local_pdf(
    session: Session,
    investigation: Investigation,
    *,
    filename: str,
    data: bytes,
) -> Entity:
    return ingest_local_file(session, investigation, filename=filename, data=data)


def ingest_local_file(
    session: Session,
    investigation: Investigation,
    *,
    filename: str,
    data: bytes,
) -> Entity:
    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower() or ".bin"
    dest = _upload_dir(investigation.id) / f"{digest}{suffix}"
    dest.write_bytes(data)
    meta = extract_file_metadata(filename, data)
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
    for key in ("title", "author", "creator", "producer", "software", "make", "model", "datetime"):
        if meta.get(key):
            snippet_bits.append(f"{key}: {meta[key]}")
    _add_evidence(
        session,
        investigation,
        entity,
        "exif_local",
        "Metadados do arquivo anexado",
        None,
        " · ".join(snippet_bits),
        {"sha256": digest, "metadata": meta, "path": str(dest)},
    )
    from osint4all.engines.discovery import extract_document_facts, extract_pdf_text

    facts = extract_document_facts(extract_pdf_text(data))
    if any(facts.values()):
        entity.attrs = {**(entity.attrs or {}), "extracted": facts}
        _add_evidence(
            session,
            investigation,
            entity,
            "doc_extract",
            "Extração do documento anexado",
            None,
            " · ".join(f"{k}: {', '.join(v[:4])}" for k, v in facts.items() if v) or "estrutura lida",
            {"extracted": facts, "sha256": digest},
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
                attrs={"from_file_author": True},
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
            "exif_local",
        )
    return entity


def document_canonical_key(digest: str) -> str:
    return canonical_key("URL", f"local://documento/{digest}")


def store_case_image(investigation_id: str, filename: str, data: bytes) -> dict[str, str] | None:
    """Guarda JPEG/PNG enviado pelo usuário. Não baixa da web."""
    name = (filename or "foto.jpg").lower()
    suffix = Path(name).suffix
    if data.startswith(b"\x89PNG"):
        kind, ext = "png", ".png"
    elif data.startswith(b"\xff\xd8") or suffix in {".jpg", ".jpeg"}:
        kind, ext = "jpeg", ".jpg"
    else:
        return None
    if kind == "jpeg" and not data.startswith(b"\xff\xd8"):
        return None
    digest = hashlib.sha256(data).hexdigest()
    dest = _upload_dir(investigation_id) / f"{digest}{ext}"
    if not dest.exists():
        dest.write_bytes(data)
    return {"digest": digest, "suffix": ext, "name": Path(filename).name[:160] or f"foto{ext}"}


def case_image_path(investigation_id: str, digest: str) -> Path | None:
    token = (digest or "").strip().lower()
    if not token.isalnum() or len(token) != 64:
        return None
    folder = _upload_dir(investigation_id)
    for ext in (".jpg", ".jpeg", ".png"):
        path = folder / f"{token}{ext}"
        if path.is_file():
            return path
    return None


def metadata_summary(meta: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in meta.items() if v)
