from pathlib import Path

from monitor_jus.report.pdf_report import html_to_pdf_bytes, write_pdf


def test_html_to_pdf_bytes_minimal():
    html = """
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"/><title>T</title></head>
    <body><h1>Monitor Judicial</h1><p>Relatório de teste</p></body></html>
    """
    data = html_to_pdf_bytes(html)
    assert data[:4] == b"%PDF"
    assert len(data) > 200


def test_write_pdf(tmp_path: Path):
    out = tmp_path / "r.pdf"
    write_pdf("<html><body><p>ok</p></body></html>", out)
    assert out.is_file()
    assert out.read_bytes()[:4] == b"%PDF"
