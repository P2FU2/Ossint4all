"""Converte o HTML do digest em PDF (anexo)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from xhtml2pdf import pisa

from monitor_jus.logging_setup import get_logger

logger = get_logger(__name__)


def html_to_pdf_bytes(html: str) -> bytes:
    """Gera bytes PDF a partir do HTML do relatório."""
    # xhtml2pdf lida melhor com HTML relativamente simples (inline CSS)
    src = html or "<html><body><p>Relatório vazio</p></body></html>"
    out = BytesIO()
    result = pisa.CreatePDF(src, dest=out, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"Falha ao gerar PDF ({result.err} erro(s) no xhtml2pdf)")
    data = out.getvalue()
    if not data or len(data) < 64:
        raise RuntimeError("PDF gerado está vazio ou inválido")
    return data


def write_pdf(html: str, path: Path) -> Path:
    """Persiste PDF no disco e retorna o path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = html_to_pdf_bytes(html)
    path.write_bytes(data)
    logger.info(
        "digest_pdf_written",
        extra={"extra": {"path": str(path), "bytes": len(data)}},
    )
    return path
