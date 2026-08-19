from osint4all.consult import ConsultResult, run_consult
from osint4all.graph.seed import add_seed_entities, create_investigation
from osint4all.tools_suite import get_tool, list_tools, run_mass, seeds_from_results


def test_suite_search_and_internal_urls() -> None:
    assert get_tool("username") is not None
    assert get_tool("pdf").upload
    names = [t.id for t in list_tools("sherlock")]
    assert "username" in names
    plates = list_tools("placa")
    assert any(t.id == "plate" for t in plates)
    assert all("/app/ferramentas?tool=" in f"/app/ferramentas?tool={t.id}" for t in list_tools())


def test_mass_plate_offline() -> None:
    mass = run_mass("ABC1D23", live=False)
    assert mass.ok
    assert mass.parts[0].kind == "PLATE"
    assert mass.derived
    seeds = seeds_from_results(mass.parts)
    assert any(s.kind == "PLATE" for s in seeds)


def test_mass_email_derives_user_and_domain() -> None:
    mass = run_mass("ana@exemplo.com", live=False)
    assert mass.ok
    kinds = {k for k, _ in mass.derived}
    assert "USERNAME" in kinds
    assert "URL" in kinds


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
