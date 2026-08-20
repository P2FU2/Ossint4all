from sqlalchemy import select

from osint4all.db.models import Entity
from osint4all.documents.metadata import extract_file_metadata, extract_pdf_metadata, extract_png_text, ingest_local_pdf
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed


def _sample_pdf() -> bytes:
    return (
        b"%PDF-1.1\n"
        b"1 0 obj\n"
        b"<< /Title (Relatorio Publico) /Author (Maria Silva) "
        b"/Creator (LibreOffice) /Producer (Writer) >>\n"
        b"endobj\n%%EOF\n"
    )


def test_extract_pdf_info_dict() -> None:
    meta = extract_pdf_metadata(_sample_pdf())
    assert meta["title"] == "Relatorio Publico"
    assert meta["author"] == "Maria Silva"
    assert meta["creator"] == "LibreOffice"


def test_ingest_creates_publication_and_author(db) -> None:
    seed = parse_seed("exemplo.gov.br", forced_kind="URL")
    assert seed
    inv = create_investigation(
        db,
        title="PDF",
        hypothesis=None,
        seeds=[seed],
        connectors=[],
        max_depth=1,
        monitor=False,
        created_by="test",
    )
    entity = ingest_local_pdf(db, inv, filename="nota.pdf", data=_sample_pdf())
    db.flush()
    assert entity.entity_type == "PUBLICATION"
    assert entity.attrs["pdf_metadata"]["title"] == "Relatorio Publico"
    names = list(
        db.scalars(select(Entity.display_name).where(Entity.investigation_id == inv.id))
    )
    assert "Maria Silva" in names


def _png_with_author(author: str) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    text = b"Author\x00" + author.encode("latin-1")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"tEXt", text) + chunk(b"IEND", b"")


def test_extract_png_and_file_router() -> None:
    data = _png_with_author("Maria Silva")
    assert extract_png_text(data)["author"] == "Maria Silva"
    assert extract_file_metadata("foto.png", data)["author"] == "Maria Silva"
    assert extract_file_metadata("nota.pdf", _sample_pdf())["title"] == "Relatorio Publico"
