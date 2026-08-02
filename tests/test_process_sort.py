from datetime import datetime, timezone

from monitor_jus.web.services.processes import sort_process_rows


def _row(cnj: str, when: datetime | None) -> dict:
    return {
        "numero_cnj": cnj,
        "tribunal": "TJSP",
        "classe": "A",
        "assunto": "",
        "situacao": "Ativo",
        "outcome": "ativo",
        "criteria": "OAB SP 1",
        "_sort_last_movement": when,
        "last_movement_at": when.isoformat() if when else "—",
    }


def test_sort_last_movement_desc_global():
    d2026 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    d2025 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    d2024 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [_row("c24", d2024), _row("c26", d2026), _row("c25", d2025), _row("c0", None)]
    sorted_rows = sort_process_rows(rows, sort_by="last_movement_at", sort_dir="desc")
    assert [r["numero_cnj"] for r in sorted_rows] == ["c26", "c25", "c24", "c0"]


def test_sort_last_movement_asc_toggle():
    d2026 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    d2025 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = [_row("c26", d2026), _row("c25", d2025)]
    sorted_rows = sort_process_rows(rows, sort_by="last_movement_at", sort_dir="asc")
    assert [r["numero_cnj"] for r in sorted_rows] == ["c25", "c26"]


def test_sort_preserves_order_before_pagination_slice():
    """Simula: ordena tudo e só então pagina — página 2 não 'pula' anos."""
    rows = [
        _row(f"p{i}", datetime(2020 + i, 1, 1, tzinfo=timezone.utc)) for i in range(6)
    ]
    # 2020..2025
    ordered = sort_process_rows(rows, sort_by="last_movement_at", sort_dir="desc")
    page1 = ordered[0:3]
    page2 = ordered[3:6]
    assert [r["numero_cnj"] for r in page1] == ["p5", "p4", "p3"]  # 2025,2024,2023
    assert [r["numero_cnj"] for r in page2] == ["p2", "p1", "p0"]  # 2022,2021,2020
