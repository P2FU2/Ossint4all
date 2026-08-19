from sqlalchemy import select

from osint4all.db.models import Entity
from osint4all.documents.metadata import extract_pdf_metadata, ingest_local_pdf
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
