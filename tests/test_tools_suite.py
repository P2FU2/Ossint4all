from osint4all.consult import ConsultResult, run_consult
from osint4all.graph.seed import add_seed_entities, create_investigation
from osint4all.tools_suite import get_tool, list_tools, run_mass, seeds_from_results, tool_id_for_kind


def test_suite_search_and_internal_urls() -> None:
    assert get_tool("username") is not None
    assert get_tool("pdf").upload
    names = [t.id for t in list_tools("sherlock")]
    assert "username" in names
    plates = list_tools("placa")
    assert any(t.id == "plate" for t in plates)
    assert all("/app/ferramentas?tool=" in f"/app/ferramentas?tool={t.id}" for t in list_tools())
    assert tool_id_for_kind("NAME") == "name"
    assert tool_id_for_kind("CNJ") == "cnj"
    assert tool_id_for_kind("PROCESSOS") == "cnj"
    assert tool_id_for_kind("NEGATIVA") == "negativa"
    assert tool_id_for_kind("URL") == "crtsh"


def test_processos_result_becomes_cnj_seed() -> None:
    parts = [ConsultResult(kind="PROCESSOS", query="0000123-45.2024.8.26.0100", title="CNJ", summary="", ok=True)]
    seeds = seeds_from_results(parts)
    assert len(seeds) == 1
    assert seeds[0].kind == "CNJ"
    assert seeds[0].entity_type == "CASE"


def test_mass_plate_offline() -> None:
    mass = run_mass("ABC1D23", live=False)
    assert mass.ok
    assert mass.parts[0].kind == "PLATE"
    seeds = seeds_from_results(mass.parts)
    assert any(s.kind == "PLATE" for s in seeds)


def test_mass_email_derives_user_and_domain() -> None:
    mass = run_mass("ana@exemplo.com", live=False)
    assert mass.ok
    kinds = {k for k, _ in mass.derived}
    assert "URL" in kinds
    assert mass.parts[0].kind == "EMAIL"
    assert any("ana" in (ev.title + ev.meta) for ev in mass.parts[0].timeline)


def test_assign_seeds_to_existing_case(settings, db) -> None:
    inv = create_investigation(
        db,
        title="Caso corrente",
        hypothesis="Teste",
        seeds=[],
        connectors=["plate_public"],
        max_depth=1,
        monitor=False,
        created_by="tester",
    )
    parts = [
        ConsultResult(kind="PLATE", query="ABC1D23", title="ABC1D23", summary="", ok=True),
        ConsultResult(kind="PHONE", query="11987654321", title="11987654321", summary="", ok=True),
    ]
    added = add_seed_entities(db, inv, seeds_from_results(parts))
    assert len(added) == 2
    inv.title = "Caso editado"
    inv.hypothesis = "Nova hipótese"
    db.flush()
    db.refresh(inv)
    assert inv.title == "Caso editado"
    assert {e.entity_type for e in inv.entities} == {"VEHICLE", "PERSON"}


def test_consult_rejects_empty_mass() -> None:
    assert run_consult("", mode="massa").ok is False


def test_mass_derived_domain_stays_offline(monkeypatch) -> None:
    from osint4all import tools_suite

    seen: dict[str, bool] = {}

    def wrap(raw, settings, *, live):
        seen["live"] = live
        return ConsultResult(kind="URL", query=raw, title=raw, summary="offline", ok=True)

    monkeypatch.setattr(tools_suite, "_consult_domain", wrap)
    mass = run_mass("ana@exemplo.com", live=True)
    assert mass.ok
    assert seen.get("live") is False


def test_mass_keeps_going_if_derived_breaks(monkeypatch) -> None:
    from osint4all import tools_suite

    def boom(*_args, **_kwargs):
        raise RuntimeError("fonte caiu")

    monkeypatch.setattr(tools_suite, "_consult_domain", boom)
    mass = run_mass("ana@exemplo.com", live=True)
    assert mass.ok
    assert mass.parts[0].ok
    assert any(not p.ok and "fonte caiu" in (p.error or "") for p in mass.parts[1:])
