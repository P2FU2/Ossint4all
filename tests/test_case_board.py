from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity
from osint4all.db.models import BlockedKey, CaseNote, Edge, Entity, Evidence, ExpansionJob, Identifier, Investigation
from osint4all.db.repository import (
    add_case_note,
    case_identifiers,
    case_target_fields,
    collapse_graph_view,
    consolidate_identities,
    blocked_key_set,
    create_manual_edge,
    delete_case_note,
    delete_edge,
    delete_edges,
    detach_entities,
    detach_entity,
    enrich_entity,
    entity_id_fields,
    graph_counts,
    graph_payload,
    live_investigations,
    purge_investigation,
    retire_investigation,
    requeue_stale_running_jobs,
    save_graph_layout,
    update_edge,
    utcnow,
)
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import attach_person_profile, create_investigation
from osint4all.identifiers import parse_seed
from sqlalchemy import select


def _case(db):
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    return create_investigation(
        db,
        title="Quadro",
        hypothesis="teste",
        seeds=[seed],
        connectors=[],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )


def test_detach_blocks_reexpansion(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    found = FoundEntity(entity_type="ORG", kind="CNPJ", value="33000167000101", display_name="Empresa", confidence=0.8)
    created = apply_result(
        db,
        inv,
        person,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=person.canonical_key, to_ref="cnpj:33000167000101", rel_type="SOCIO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    db.flush()
    company = next((e for e in created if e.entity_type == "ORG"), None) or db.scalar(
        select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "ORG")
    )
    assert company is not None
    assert detach_entity(db, inv.id, company.id)
    assert "cnpj:33000167000101" in blocked_key_set(db, inv.id)
    apply_result(
        db,
        inv,
        person,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=person.canonical_key, to_ref="cnpj:33000167000101", rel_type="SOCIO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    left = [e for e in db.scalars(select(Entity).where(Entity.investigation_id == inv.id)) if e.entity_type == "ORG"]
    assert left == []


def test_edge_edit_and_delete_keep_nodes(settings, db) -> None:
    inv = _case(db)
    other = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    db.add(other)
    db.flush()
    person = db.scalar(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON"))
    assert person is not None
    edge = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="SOCIO", note="QSA")
    assert edge
    updated = update_edge(db, inv.id, edge.id, rel_type="ADMIN", note="admin no QSA")
    assert updated and updated.rel_type == "ADMIN"
    assert updated.attrs.get("nota") == "admin no QSA"
    assert delete_edge(db, inv.id, edge.id)
    assert db.get(Entity, other.id) is not None
    assert db.scalars(select(Edge).where(Edge.investigation_id == inv.id)).all() == []


def test_update_edge_rejects_type_clash(settings, db) -> None:
    inv = _case(db)
    other = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    db.add(other)
    db.flush()
    person = db.scalar(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON"))
    assert person is not None
    first = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="SOCIO")
    second = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="ADMIN")
    assert first and second
    assert update_edge(db, inv.id, second.id, rel_type="SOCIO") is None
    db.refresh(second)
    assert second.rel_type == "ADMIN"


def test_case_note_tree_and_graph_node(settings, db) -> None:
    inv = _case(db)
    root = add_case_note(db, inv, title="Hipótese", body="mesmo grupo", created_by="tester")
    child = add_case_note(db, inv, title="Fonte", body="DOU", parent_id=root.id, created_by="tester")
    pinned = add_case_note(
        db,
        inv,
        title="Alerta",
        body="checar QSA",
        entity_id=inv.entities[0].id,
        on_graph=True,
        created_by="tester",
    )
    assert child.parent_id == root.id
    notes = db.scalars(select(CaseNote).where(CaseNote.investigation_id == inv.id)).all()
    assert len(notes) == 3
    note_nodes = [e for e in db.scalars(select(Entity).where(Entity.investigation_id == inv.id)) if e.entity_type == "NOTE"]
    assert len(note_nodes) == 1
    assert pinned.entity_id == note_nodes[0].id
    assert any(e.rel_type == "ANOTACAO" for e in db.scalars(select(Edge).where(Edge.investigation_id == inv.id)))
    note_id = pinned.id
    node_id = pinned.entity_id
    assert delete_case_note(db, inv.id, note_id)
    assert db.get(CaseNote, note_id) is None
    assert db.get(Entity, node_id) is None
    assert db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.rel_type == "ANOTACAO")).all() == []


def test_case_identifiers_lists_seeds(settings, db) -> None:
    inv = _case(db)
    rows = case_identifiers(db, inv.id)
    kinds = {item["kind"] for item in rows}
    assert "CPF" in kinds
    fields = case_target_fields(db, inv.id)
    assert fields.get("CPF")


def test_detach_removes_derived_people_and_companies(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    company = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    partner = Entity(
        investigation_id=inv.id,
        entity_type="PERSON",
        canonical_key="name:joao pereira lima",
        display_name="Joao Pereira Lima",
        attrs={"status": "unconfirmed"},
        depth=2,
    )
    extra = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:00000000000191",
        display_name="Outra",
        attrs={},
        depth=0,
        is_seed=True,
    )
    db.add_all([company, partner, extra])
    db.flush()
    db.add_all(
        [
            Edge(investigation_id=inv.id, from_entity_id=person.id, to_entity_id=company.id, rel_type="SOCIO"),
            Edge(investigation_id=inv.id, from_entity_id=company.id, to_entity_id=partner.id, rel_type="SOCIO"),
        ]
    )
    db.flush()
    assert detach_entity(db, inv.id, company.id)
    assert db.get(Entity, company.id) is None
    assert db.get(Entity, partner.id) is None
    assert db.get(Entity, person.id) is not None
    assert db.get(Entity, extra.id) is not None


def test_detach_entities_keeps_seed(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    extra = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:00000000000191",
        display_name="Solta",
        attrs={"status": "unconfirmed"},
        depth=1,
    )
    db.add(extra)
    db.flush()
    removed = detach_entities(db, inv.id, [person.id, extra.id], keep_seeds=True)
    assert removed == 1
    assert db.get(Entity, person.id) is not None
    assert db.get(Entity, extra.id) is None


def test_detach_entities_deletes_only_selected(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    company = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={"status": "unconfirmed"},
        depth=1,
    )
    partner = Entity(
        investigation_id=inv.id,
        entity_type="PERSON",
        canonical_key="name:joao pereira lima",
        display_name="Joao Pereira Lima",
        attrs={"status": "unconfirmed"},
        depth=2,
    )
    db.add_all([company, partner])
    db.flush()
    db.add_all(
        [
            Edge(investigation_id=inv.id, from_entity_id=person.id, to_entity_id=company.id, rel_type="SOCIO"),
            Edge(investigation_id=inv.id, from_entity_id=company.id, to_entity_id=partner.id, rel_type="SOCIO"),
        ]
    )
    db.flush()
    assert detach_entities(db, inv.id, [company.id], keep_seeds=True) == 1
    assert db.get(Entity, company.id) is None
    assert db.get(Entity, partner.id) is not None
    assert db.get(Entity, person.id) is not None


def test_enrich_entity_adds_cpf_for_precise_search(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    extra = parse_seed("ana@example.com", forced_kind="EMAIL")
    kinds = enrich_entity(person, [seed, extra])
    db.flush()
    assert "CPF" in kinds
    assert "EMAIL" in kinds
    fields = entity_id_fields(person)
    assert fields.get("EMAIL")
    assert any(item.kind == "EMAIL" for item in person.identifiers)


def test_delete_edges_batch(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    company = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    db.add(company)
    db.flush()
    edge = Edge(investigation_id=inv.id, from_entity_id=person.id, to_entity_id=company.id, rel_type="CANDIDATO")
    db.add(edge)
    db.flush()
    assert delete_edges(db, inv.id, [edge.id]) == 1
    assert db.get(Edge, edge.id) is None
    assert db.get(Entity, company.id) is not None


def test_add_company_links_to_target_without_becoming_seed(settings, db) -> None:
    from osint4all.graph.resolve import upsert_found_entity

    inv = _case(db)
    person = inv.entities[0]
    seed = parse_seed("33.000.167/0001-01", forced_kind="CNPJ")
    assert seed
    org = upsert_found_entity(
        db,
        inv,
        FoundEntity(
            entity_type="ORG",
            kind="CNPJ",
            value=seed.value,
            display_name=seed.display_name,
            confidence=0.99,
        ),
        depth=1,
        is_seed=False,
    )
    attrs = dict(org.attrs or {})
    attrs["probe_kinds"] = ["QSA"]
    org.attrs = attrs
    edge = create_manual_edge(db, inv, from_id=person.id, to_id=org.id, rel_type="EMPRESA", note="CNPJ")
    db.flush()
    assert org.is_seed is False
    assert org.attrs["probe_kinds"] == ["QSA"]
    assert edge is not None
    assert edge.rel_type == "EMPRESA"


def test_search_all_and_graph_photo(settings, db) -> None:
    from osint4all.graph.assets import add_graph_photo
    from osint4all.graph.expand import queue_search_all

    inv = _case(db)
    person = inv.entities[0]
    queued = queue_search_all(db, inv, max_attempts=2)
    db.flush()
    assert queued >= 1
    assert "POLITICOS" in (person.attrs or {}).get("probe_kinds", [])
    jobs = db.scalars(select(ExpansionJob).where(ExpansionJob.investigation_id == inv.id)).all()
    assert any(job.status == "PENDING" for job in jobs)
    shot = add_graph_photo(
        db,
        inv,
        person,
        title="Retrato",
        source="manual",
        photos=[{"url": "https://www.camara.leg.br/foto.jpg", "title": "oficial"}],
        as_profile=True,
    )
    db.flush()
    assert shot is not None
    assert shot.attrs["tipo"] == "imagem"
    assert person.attrs.get("profile_photo") == "https://www.camara.leg.br/foto.jpg"


def test_add_bank_and_wealth_link_to_target(settings, db) -> None:
    from osint4all.graph.assets import add_bank_account, add_wealth_estimate

    inv = _case(db)
    person = inv.entities[0]
    bank = add_bank_account(
        db,
        inv,
        person,
        bank="Itaú",
        agency="0001",
        account="12345-6",
        account_type="corrente",
        pix="ehleite@uol.com.br",
        source="notícia pública",
    )
    wealth = add_wealth_estimate(
        db,
        inv,
        person,
        amount="R$ 2.400.000",
        year="2024",
        source="declaração em processo",
    )
    db.flush()
    assert bank is not None
    assert bank.entity_type == "ASSET"
    assert bank.attrs["banco"] == "Itaú"
    assert wealth is not None
    assert wealth.display_name.startswith("Patrimônio")
    assert person.attrs["patrimonio_estimado"] == "R$ 2.400.000"
    assert person.attrs["patrimonio_ano"] == "2024"
    rels = {e.rel_type for e in db.scalars(select(Edge).where(Edge.investigation_id == inv.id))}
    assert "TITULAR" in rels
    assert "PATRIMONIO" in rels
    assert add_bank_account(db, inv, person) is None
    assert add_wealth_estimate(db, inv, person, amount="") is None


def test_add_property_with_photo_links_to_target(settings, db) -> None:
    from osint4all.graph.assets import add_property

    inv = _case(db)
    person = inv.entities[0]
    house = add_property(
        db,
        inv,
        person,
        address="Rua das Flores 100",
        city="Santos",
        uf="SP",
        property_type="casa",
        amount="R$ 890.000",
        source="leilão Caixa",
        photos=[{"url": "https://venda-imoveis.caixa.gov.br/foto.jpg", "title": "fachada"}],
    )
    db.flush()
    assert house is not None
    assert house.entity_type == "ASSET"
    assert house.attrs["tipo"] == "imagem"
    assert house.attrs["thumb"].startswith("https://")
    assert house.attrs["municipio"] == "Santos"
    places = (person.attrs or {}).get("places") or []
    assert any(p.get("role") == "imovel" and p.get("uf") == "SP" for p in places)
    rels = {e.rel_type for e in db.scalars(select(Edge).where(Edge.investigation_id == inv.id))}
    assert "PROPRIETARIO" in rels
    assert add_property(db, inv, person) is None


def test_satellite_card_for_company_hq(settings, db) -> None:
    from osint4all.graph.satellite import ensure_satellite_cards, satellite_urls

    urls = satellite_urls(-23.5505, -46.6333)
    assert "World_Imagery" in urls["thumb"]
    assert "google.com/maps" in urls["page_url"]
    assert "3m1!1e3" in urls["page_url"]

    inv = _case(db)
    firm = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa Sede",
        attrs={"lat": -23.5505, "lng": -46.6333, "municipio": "São Paulo", "uf": "SP", "endereco": "Praça da Sé"},
        depth=1,
    )
    db.add(firm)
    db.flush()
    assert ensure_satellite_cards(db, inv) == 1
    assert ensure_satellite_cards(db, inv) == 0
    sat = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.canonical_key.startswith("geo:"))).first()
    assert sat is not None
    assert sat.entity_type == "PUBLICATION"
    assert sat.attrs["tipo"] == "imagem"
    assert sat.attrs["thumb"].startswith("https://")
    rels = {e.rel_type for e in db.scalars(select(Edge).where(Edge.investigation_id == inv.id))}
    assert "SEDE" in rels


def test_same_person_stays_in_one_block(settings, db) -> None:
    seed = parse_seed("Eduardo Hermelino Leite", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=[],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    person = next(e for e in inv.entities if e.is_seed)
    twin = Entity(
        investigation_id=inv.id,
        entity_type="PERSON",
        canonical_key="name:eduardo hermelino leite#cand:qsa:1",
        display_name="Eduardo Hermelino Leite",
        attrs={"status": "unconfirmed"},
        depth=2,
    )
    user = Entity(
        investigation_id=inv.id,
        entity_type="PROFILE",
        canonical_key="username:ehleite",
        display_name="ehleite",
        attrs={"seed": True},
        depth=0,
        is_seed=True,
    )
    db.add_all([twin, user])
    db.flush()
    db.add(Edge(investigation_id=inv.id, from_entity_id=twin.id, to_entity_id=person.id, rel_type="ADMIN"))
    db.flush()
    assert consolidate_identities(db, inv.id) >= 1
    db.expire_all()
    people = [e for e in db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON"))]
    assert len(people) == 1
    seed = people[0]
    assert seed.is_seed
    kinds = {i.kind for i in seed.identifiers}
    assert "USERNAME" in kinds or (seed.canonical_key or "").startswith("username:") or any(
        (seed.attrs or {}).get("username")
    )
    payload = graph_payload(db, inv.id)
    labels = [n["label"] for n in payload["nodes"] if n["type"] == "PERSON"]
    assert labels.count("Eduardo Hermelino Leite") == 1
    edu = next(n for n in payload["nodes"] if n["type"] == "PERSON" and n.get("seed"))
    assert any(i["kind"] == "USERNAME" for i in edu["ids"])


def test_collapse_graph_view_merges_duplicate_name() -> None:
    nodes = [
        {"id": "a", "label": "Eduardo Hermelino Leite", "type": "PERSON", "seed": True, "key": "name:edu", "ids": [{"kind": "CPF", "value": "52998224725"}]},
        {"id": "b", "label": "Eduardo Hermelino Leite", "type": "PERSON", "seed": False, "key": "name:edu#cand:2", "ids": []},
        {"id": "c", "label": "EHL Gestao", "type": "ORG", "seed": False, "key": "cnpj:1", "ids": []},
    ]
    links = [
        {"id": "1", "source": "a", "target": "c", "type": "ADMIN"},
        {"id": "2", "source": "b", "target": "c", "type": "ADMIN"},
    ]
    kept, edges = collapse_graph_view(nodes, links)
    people = [n for n in kept if n["type"] == "PERSON"]
    assert len(people) == 2
    assert len(edges) == 2
    same_cpf = [
        {"id": "a", "label": "Eduardo Hermelino Leite", "type": "PERSON", "seed": True, "key": "name:edu", "ids": [{"kind": "CPF", "value": "52998224725"}], "status": "confirmed"},
        {"id": "b", "label": "Eduardo Hermelino Leite", "type": "PERSON", "seed": False, "key": "cpf:52998224725", "ids": [{"kind": "CPF", "value": "52998224725"}], "status": "probable"},
    ]
    folded, folded_edges = collapse_graph_view(same_cpf, [{"id": "1", "source": "a", "target": "c", "type": "ADMIN"}, {"id": "2", "source": "b", "target": "c", "type": "ADMIN"}])
    assert len([n for n in folded if n["type"] == "PERSON"]) == 1
    assert folded_edges[0]["source"] == "a"


def test_diagram_note_lands_on_graph(settings, db) -> None:
    inv = _case(db)
    note = add_case_note(
        db,
        inv,
        title="Fluxo QSA",
        body="alvo --> empresa",
        on_graph=True,
        kind="diagram",
        created_by="tester",
    )
    node = db.get(Entity, note.entity_id)
    assert node is not None
    assert node.entity_type == "NOTE"
    assert node.attrs.get("kind") == "diagram"
    assert node.display_name.startswith("Diagrama")


def test_purge_investigation_removes_children(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    other = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    db.add(other)
    db.flush()
    edge = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="SOCIO", note="QSA")
    db.add(
        Identifier(
            entity_id=person.id,
            kind="EMAIL",
            value="eduardo@exemplo.com",
            canonical_key="email:eduardo@exemplo.com",
            strong=True,
        )
    )
    db.add(
        Evidence(
            investigation_id=inv.id,
            entity_id=person.id,
            edge_id=edge.id,
            connector="cnpj_receita",
            source_label="Receita",
            snippet="sócio",
            dedup_hash="purge-test-hash",
        )
    )
    db.add(ExpansionJob(investigation_id=inv.id, entity_id=person.id, depth=0))
    add_case_note(db, inv, title="nota", body="apagar junto", created_by="tester")
    db.flush()
    case_id = inv.id
    assert purge_investigation(db, case_id)
    db.commit()
    assert db.get(Investigation, case_id) is None
    assert db.scalars(select(Entity).where(Entity.investigation_id == case_id)).all() == []
    assert db.scalars(select(Edge).where(Edge.investigation_id == case_id)).all() == []
    assert db.scalars(select(Evidence).where(Evidence.investigation_id == case_id)).all() == []
    assert db.scalars(select(ExpansionJob).where(ExpansionJob.investigation_id == case_id)).all() == []
    assert db.scalars(select(CaseNote).where(CaseNote.investigation_id == case_id)).all() == []
    assert db.scalars(select(BlockedKey).where(BlockedKey.investigation_id == case_id)).all() == []
    assert db.scalars(select(Identifier).where(Identifier.entity_id == person.id)).all() == []


def test_retire_hides_case_before_purge(settings, db) -> None:
    inv = _case(db)
    db.add(ExpansionJob(investigation_id=inv.id, entity_id=inv.entities[0].id, depth=0, status="PENDING"))
    db.flush()
    assert retire_investigation(db, inv.id)
    db.flush()
    assert inv.status == "DELETED"
    assert [row.id for row in live_investigations(db)] == []
    jobs = db.scalars(select(ExpansionJob).where(ExpansionJob.investigation_id == inv.id)).all()
    assert jobs and all(job.status == "FAILED" for job in jobs)
    assert db.get(Investigation, inv.id) is not None


def test_graph_layout_persists_on_case(settings, db) -> None:
    inv = _case(db)
    entity = inv.entities[0]
    saved = save_graph_layout(
        db,
        inv.id,
        {
            "view": "rede",
            "zoom": 1.35,
            "pan": {"x": 40, "y": -12},
            "nodes": {entity.id: {"x": 111.4, "y": 222.8}, "ghost": {"x": 1, "y": 2}},
        },
    )
    assert saved is not None
    assert saved["zoom"] == 1.35
    assert saved["nodes"][entity.id] == {"x": 111.4, "y": 222.8}
    assert "ghost" not in saved["nodes"]
    payload = graph_payload(db, inv.id)
    assert payload["layout"]["pan"]["x"] == 40
    assert payload["layout"]["nodes"][entity.id]["y"] == 222.8
    ordered = save_graph_layout(
        db,
        inv.id,
        {"view": "ordenar", "zoom": 0.9, "pan": {"x": 0, "y": 0}, "nodes": {entity.id: {"x": 10, "y": 20}}},
    )
    assert ordered is not None
    assert ordered["view"] == "ordenar"
    assert ordered["nodes"][entity.id] == {"x": 10.0, "y": 20.0}


def test_person_profile_birth_and_parents(settings, db) -> None:
    from osint4all.graph.seed import add_seed_entities
    from osint4all.identifiers import collect_form_seeds

    inv = _case(db)
    add_seed_entities(db, inv, collect_form_seeds(seed_father="Joao da Silva Souza", seed_mother="Maria da Silva Souza"))
    person = attach_person_profile(
        db,
        inv,
        birth="14061980",
        father="Joao da Silva Souza",
        mother="Maria da Silva Souza",
        cpf="529.982.247-25",
    )
    assert person is not None
    assert person.attrs.get("nascimento") == "14/06/1980"
    assert person.attrs.get("nome_pai") == "Joao da Silva Souza"
    rels = {edge.rel_type for edge in db.scalars(select(Edge).where(Edge.investigation_id == inv.id))}
    assert {"PAI", "MAE"} <= rels


def test_graph_counts_are_cheap(db) -> None:
    inv = _case(db)
    size = graph_counts(db, inv.id)
    assert size["entities"] >= 1
    assert size["edges"] >= 0


def test_stale_running_job_returns_to_queue(db) -> None:
    from datetime import timedelta

    inv = _case(db)
    person = db.scalar(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON"))
    assert person is not None
    job = ExpansionJob(
        investigation_id=inv.id,
        entity_id=person.id,
        status="RUNNING",
        started_at=utcnow() - timedelta(minutes=5),
        attempt_count=1,
        max_attempts=3,
    )
    db.add(job)
    db.flush()
    assert requeue_stale_running_jobs(db, inv.id, older_than=90) == 1
    db.refresh(job)
    assert job.status == "PENDING"
