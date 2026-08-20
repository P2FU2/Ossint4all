from osint4all.consult import ConsultGraph, ConsultHit, ConsultResult, GraphEdge, GraphNode, run_consult
from osint4all.graph.seed import add_seed_entities, create_investigation
from osint4all.tools_suite import (
    get_tool,
    graph_tools_plan,
    list_tools,
    outcome_to_connector,
    run_mass,
    seeds_from_results,
    tool_id_for_kind,
)


def test_suite_search_and_internal_urls() -> None:
    assert get_tool("username") is not None
    assert get_tool("pdf").upload
    names = [t.id for t in list_tools("sherlock")]
    assert "username" in names
    assert any(t.id == "hosts" for t in list_tools("amass"))
    assert any(t.id == "hosts" for t in list_tools("theharvester"))
    assert any(t.id == "username" for t in list_tools("maigret"))
    assert any(t.id == "email" for t in list_tools("holehe"))
    assert any(t.id == "phone" for t in list_tools("phoneinfoga"))
    assert any(t.id == "pdf" for t in list_tools("exiftool"))
    assert any(t.id == "name" for t in list_tools("aleph"))
    assert any(t.id == "hostficha" for t in list_tools("httpx"))
    assert any(t.id == "hostficha" for t in list_tools("ivre"))
    assert any(t.id == "hostficha" for t in list_tools("photon"))
    plates = list_tools("placa")
    assert any(t.id == "plate" for t in plates)
    assert any(t.id == "cnj" for t in list_tools("processos"))
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


def test_graph_tools_plan_matches_dossier() -> None:
    plan = {item["id"]: item for item in graph_tools_plan([
        {"kind": "PLATE", "value": "ABC1D23"},
        {"kind": "EMAIL", "value": "ana@exemplo.com"},
    ])}
    assert plan["plate"]["ready"] is True
    assert plan["plate"]["checked"] is True
    assert "ABC1D23" in plan["plate"]["values"]
    assert plan["email"]["ready"] is True
    assert plan["name"]["checked"] is False
    assert plan["cnpj"]["ready"] is False
    assert plan["cnj"]["ready"] is False
    assert plan["username"]["ready"] is False
    assert "pdf" not in plan


def test_graph_tools_plan_processos_ready_on_name() -> None:
    named = {item["id"]: item for item in graph_tools_plan([
        {"kind": "NAME", "value": "Eduardo Hermelino Leite"},
        {"kind": "CPF", "value": "52998224725"},
    ])}
    assert named["cnj"]["ready"] is True
    assert named["cnj"]["checked"] is False
    assert "Eduardo Hermelino Leite" in named["cnj"]["values"]
    numbered = {item["id"]: item for item in graph_tools_plan([
        {"kind": "CNJ", "value": "00001234520248260100"},
    ])}
    assert numbered["cnj"]["ready"] is True
    assert numbered["cnj"]["checked"] is True


def test_outcome_to_connector_adds_without_name_dump() -> None:
    result = outcome_to_connector(
        ConsultResult(
            kind="EMAIL",
            query="ana@exemplo.com",
            title="ana@exemplo.com",
            summary="ok",
            hits=[
                ConsultHit("Perfil público", "github", "https://github.com/ana", "host"),
                ConsultHit("Empresa solta", "menção", None, "mencao"),
            ],
            graph=ConsultGraph(
                nodes=[
                    GraphNode("cnpj-33000167000101", "Alvo Ltda", "org", "33.000.167/0001-01"),
                    GraphNode("p-0-ana", "Ana Silva", "person", "sócia"),
                ],
                edges=[GraphEdge("p-0-ana", "cnpj-33000167000101", "sócia")],
            ),
        ),
        "email:ana@exemplo.com",
    )
    kinds = {found.kind for found in result.entities}
    assert "EMAIL" in kinds
    assert "URL" in kinds
    assert "CNPJ" in kinds
    assert "NAME" in kinds
    assert not any(found.display_name == "Empresa solta" for found in result.entities)
    assert any(edge.rel_type == "SOCIO" for edge in result.edges)


def test_outcome_skips_catalog_portals() -> None:
    result = outcome_to_connector(
        ConsultResult(
            kind="NEGATIVA",
            query="Ana Silva Souza",
            title="Ana Silva Souza",
            summary="ok",
            hits=[
                ConsultHit(
                    "CNEP — punições a pessoas jurídicas",
                    "cadastro",
                    "https://portaldatransparencia.gov.br/sancoes/consulta?cadastro=2",
                    "fonte",
                ),
                ConsultHit(
                    "Sanção na lista",
                    "CGU",
                    "https://portaldatransparencia.gov.br/sancoes/123456",
                    "sancao",
                ),
            ],
        ),
        "name:ana silva souza",
    )
    urls = [found.value for found in result.entities if found.kind == "URL"]
    assert not any("consulta?cadastro=2" in item for item in urls)
    assert any("sancoes/123456" in item for item in urls)
    assert all(found.attrs.get("fonte") for found in result.entities if found.kind == "URL")


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
