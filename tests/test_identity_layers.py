from osint4all.connectors.base import ConnectorResult, FoundEntity
from osint4all.connectors.cnpj_receita import parse_cnpj_payload
from osint4all.db.models import Entity
from osint4all.db.models import Edge
from osint4all.db.repository import detach_entity, enqueue_qsa_network
from osint4all.graph.identity import (
    TargetProfile,
    bind_found_to_profile,
    found_canonical_key,
    has_expandable_anchor,
    is_unconfirmed,
    name_search_blocked,
    names_match,
    name_overlap_score,
    name_search_variants,
    names_same_person,
    profile_from_fields,
    seed_fits_profile,
    should_enqueue_child,
)
from osint4all.graph.layers import confirmed_seeds, run_alvo_layer
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed


def test_name_overlap_score_flags_same_politician() -> None:
    assert name_overlap_score("Luiz Inácio Lula da Silva", "Lula da Silva") >= 0.5
    assert name_overlap_score("Maria Silva Souza", "João Outro") < 0.5
    assert name_overlap_score("Lula da Fonte", "Luiz Inácio Lula da Silva") < 0.5
    variants = name_search_variants("Luiz Inácio Lula da Silva")
    assert variants[0] == "Luiz Inácio Lula da Silva"
    assert any("lula" in item.casefold() and "silva" in item.casefold() for item in variants)


def test_homonym_does_not_share_key() -> None:
    a = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="MARIA SILVA",
        display_name="MARIA SILVA",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:1"},
    )
    b = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="MARIA SILVA",
        display_name="MARIA SILVA",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:2"},
    )
    assert found_canonical_key(a) != found_canonical_key(b)
    assert is_unconfirmed(a)


def test_validated_seeds_do_not_auto_expand(db) -> None:
    from sqlalchemy import func, select

    from osint4all.db.models import ExpansionJob

    name = parse_seed("Maria Silva Souza", forced_kind="NAME")
    email = parse_seed("ana@exemplo.com", forced_kind="EMAIL")
    inv = create_investigation(
        db,
        title="Só validado",
        hypothesis="sem expand",
        seeds=[name, email],
        connectors=[],
        max_depth=1,
        monitor=False,
        created_by="t",
        enqueue=False,
    )
    queued = db.scalar(select(func.count()).select_from(ExpansionJob).where(ExpansionJob.investigation_id == inv.id))
    assert queued == 0


def test_name_only_does_not_seed_graph() -> None:
    seeds = confirmed_seeds({"NAME": "Maria Silva Souza"})
    assert seeds == []
    seeds = confirmed_seeds({"NAME": "Maria Silva Souza", "CNPJ": "33000167000101"}, qsa_match=True)
    assert {s.kind for s in seeds} >= {"NAME", "CNPJ"}
    cnpj_only = confirmed_seeds({"NAME": "Maria Silva Souza", "CNPJ": "33000167000101"}, qsa_match=False)
    assert {s.kind for s in cnpj_only} == {"CNPJ"}
    email_anchor = confirmed_seeds({"NAME": "Maria Silva Souza", "EMAIL": "ana@exemplo.com"})
    assert {s.kind for s in email_anchor} >= {"NAME", "EMAIL"}


def test_email_layer_derives_username() -> None:
    layer = run_alvo_layer({}, kind="EMAIL", value="pedromilani14@gmail.com", live=False)
    assert layer.ok
    assert layer.fields["EMAIL"] == "pedromilani14@gmail.com"
    assert layer.fields["USERNAME"] == "pedromilani14"
    assert any(hit.kind == "USERNAME" for hit in layer.confirmed)
    assert layer.consult and layer.consult.facts
    assert layer.consult.hits


def test_qsa_name_only_is_unconfirmed() -> None:
    result = parse_cnpj_payload(
        {
            "cnpj": "33000167000101",
            "razao_social": "EMPRESA X",
            "qsa": [{"nome_socio": "MARIA SILVA SOUZA", "qualificacao_socio": "Sócio"}],
        }
    )
    person = next(e for e in result.entities if e.kind == "NAME")
    assert is_unconfirmed(person)
    assert found_canonical_key(person).startswith("name:")


def test_names_match_is_exact() -> None:
    assert names_match("Maria Silva Souza", "MARIA  SILVA   SOUZA")
    assert names_match("João Antônio de Oliveira", "Joao Antonio de Oliveira")
    assert not names_match("Maria Silva", "Maria Silva Souza")
    assert names_same_person("Pedro Milani Neves", "PEDRO MILANI MARINHO QUEIROZ NEVES")
    assert not names_same_person("Pedro Neves", "Pedro Milani Marinho Queiroz Neves")
    assert not names_same_person("Joao Pereira", "Empresa Aleatoria LTDA")


def test_qsa_partner_with_full_name_is_enqueued() -> None:
    found = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="JOAO PEREIRA LIMA",
        display_name="JOAO PEREIRA LIMA",
        attrs={"status": "unconfirmed", "papel": "Sócio", "candidate_key": "qsa:1", "documento_ausente": True},
        confidence=0.45,
    )
    parent = Entity(
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    assert should_enqueue_child(found, parent) is True
    anchored = TargetProfile(name="Maria Silva Souza", cpf="52998224725")
    assert should_enqueue_child(found, parent, anchored) is False


def test_unconfirmed_company_is_not_enqueued() -> None:
    found = FoundEntity(
        entity_type="ORG",
        kind="CNPJ",
        value="33000167000101",
        display_name="Empresa solta",
        attrs={"status": "unconfirmed"},
        confidence=0.45,
    )
    parent = Entity(
        entity_type="PERSON",
        canonical_key="name:pedro milani",
        display_name="Pedro Milani",
        attrs={},
        depth=0,
    )
    assert should_enqueue_child(found, parent) is False


def test_profile_child_is_not_enqueued() -> None:
    found = FoundEntity(
        entity_type="PROFILE",
        kind="URL",
        value="https://vimeo.com/telegram",
        display_name="Vimeo",
        confidence=0.7,
    )
    parent = Entity(
        entity_type="PROFILE",
        canonical_key="url:https://t.me/telegram",
        display_name="Telegram",
        attrs={},
        depth=1,
    )
    assert should_enqueue_child(found, parent) is False


def test_publication_child_is_not_enqueued() -> None:
    found = FoundEntity(
        entity_type="PUBLICATION",
        kind="URL",
        value="https://scholar.google.com/citations?view_op=search_authors&mauthors=ana",
        display_name="Google Scholar",
        confidence=0.35,
    )
    parent = Entity(
        entity_type="PERSON",
        canonical_key="email:ana@exemplo.com",
        display_name="Ana",
        attrs={},
        depth=0,
    )
    assert should_enqueue_child(found, parent) is False


def test_alvo_layer_plate_offline() -> None:
    layer = run_alvo_layer({}, kind="PLATE", value="ABC1D23", live=False)
    assert layer.ok
    assert layer.confirmed


def test_unconfirmed_name_child_not_enqueued(settings, db) -> None:
    seed = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["socio_search"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    found = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="JOAO PEREIRA LIMA",
        display_name="JOAO PEREIRA LIMA",
        attrs={"status": "unconfirmed", "candidate_key": "homonym:1"},
        confidence=0.4,
    )
    from osint4all.connectors.base import ConnectorResult, FoundEdge

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=origin.canonical_key, to_ref=found_canonical_key(found), rel_type="CANDIDATO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=True,
        max_attempts=3,
    )
    jobs = [j for j in inv.jobs if j.entity_id != origin.id]
    assert jobs == []


def test_qsa_edge_records_degree_to_target(settings, db) -> None:
    seed = parse_seed("33000167000101", forced_kind="CNPJ")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita", "socio_search"],
        max_depth=3,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    found = FoundEntity(
        entity_type="PERSON",
        kind="CPF",
        value="52998224725",
        display_name="JOAO PEREIRA LIMA",
        attrs={"papel": "Sócio"},
        confidence=0.9,
    )
    from osint4all.connectors.base import ConnectorResult, FoundEdge
    from osint4all.db.models import Edge
    from sqlalchemy import select

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=found_canonical_key(found), to_ref=origin.canonical_key, rel_type="SOCIO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=True,
        max_attempts=3,
    )
    person = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")).first()
    assert person is not None
    assert person.depth == 1
    assert person.attrs.get("grau") == 1
    edge = db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.rel_type == "SOCIO")).first()
    assert edge is not None
    assert edge.attrs.get("grau") == 1
    assert any(j.entity_id == person.id for j in inv.jobs)


def test_unconfirmed_cnpj_child_is_enqueued(settings, db) -> None:
    seed = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    found = FoundEntity(
        entity_type="ORG",
        kind="CNPJ",
        value="33000167000101",
        display_name="Empresa",
        attrs={"status": "unconfirmed"},
        confidence=0.4,
    )
    from osint4all.connectors.base import ConnectorResult, FoundEdge

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=origin.canonical_key, to_ref="cnpj:33000167000101", rel_type="CANDIDATO")],
        ),
        connector="socio_search",
        depth=0,
        enqueue_children=True,
        max_attempts=3,
    )
    jobs = [j for j in inv.jobs if j.entity_id != origin.id]
    assert jobs == []
    assert has_expandable_anchor(found)


def test_detach_removes_edges(settings, db) -> None:
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=[],
        max_depth=1,
        monitor=False,
        created_by="tester",
    )
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
    from osint4all.db.models import Edge

    db.add(
        Edge(
            investigation_id=inv.id,
            from_entity_id=person.id,
            to_entity_id=other.id,
            rel_type="SOCIO",
        )
    )
    db.flush()
    assert detach_entity(db, inv.id, other.id)
    from sqlalchemy import select

    left = db.scalars(select(Edge).where(Edge.investigation_id == inv.id)).all()
    assert left == []
    assert db.get(Entity, other.id) is None


def test_enqueue_qsa_network_raises_depth_and_queues_cnpj(settings, db) -> None:
    seed = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    company = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={"status": "confirmed"},
        depth=1,
    )
    db.add(company)
    db.flush()
    origin = next(e for e in inv.entities if e.is_seed)
    db.add(Edge(investigation_id=inv.id, from_entity_id=origin.id, to_entity_id=company.id, rel_type="SOCIO"))
    db.flush()
    queued = enqueue_qsa_network(db, inv, max_attempts=3)
    db.flush()
    assert inv.max_depth == 6
    assert queued >= 1
    from osint4all.db.models import ExpansionJob
    from sqlalchemy import select

    jobs = db.scalars(select(ExpansionJob).where(ExpansionJob.entity_id == company.id)).all()
    assert jobs


def test_profile_blocks_homonym_cpf_and_name_seed() -> None:
    profile = profile_from_fields({"NAME": "Maria Silva Souza", "CPF": "529.982.247-25"})
    assert profile.has_person_anchor
    same = FoundEntity(
        entity_type="PERSON",
        kind="CPF",
        value="39053344705",
        display_name="Maria Silva Souza",
        confidence=0.8,
    )
    partner = FoundEntity(
        entity_type="PERSON",
        kind="CPF",
        value="39053344705",
        display_name="Joao Pereira Lima",
        confidence=0.8,
    )
    alias = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="Maria Silva Souza",
        display_name="Maria Silva Souza",
        attrs={"status": "unconfirmed"},
        confidence=0.4,
    )
    assert bind_found_to_profile(same, profile) == "skip"
    assert bind_found_to_profile(partner, profile) == "keep"
    assert bind_found_to_profile(alias, profile) == "remap"
    assert seed_fits_profile("CPF", "390.533.447-05", "Maria Silva Souza", profile) is False
    assert seed_fits_profile("NAME", "Maria Silva Souza", "Maria Silva Souza", profile) is False
    assert seed_fits_profile("EMAIL", "maria@exemplo.com", "", profile) is True
    assert name_search_blocked("Maria Silva Souza", profile) is True
    assert name_search_blocked("Joao Pereira Lima", profile) is False


def test_alvo_name_stays_quiet_when_cpf_present() -> None:
    layer = run_alvo_layer(
        {"NAME": "Maria Silva Souza", "CPF": "529.982.247-25"},
        kind="NAME",
        value="Maria Silva Souza",
        live=False,
    )
    assert any("homônimo" in note for note in layer.notes)
    assert layer.candidates == []


def test_qsa_same_name_links_target_instead_of_clone(settings, db) -> None:
    seed = parse_seed("Eduardo Hermelino Leite", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=3,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    from osint4all.connectors.base import ConnectorResult, FoundEdge
    from sqlalchemy import select

    first = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="EDUARDO HERMELINO LEITE",
        display_name="EDUARDO HERMELINO LEITE",
        attrs={"status": "unconfirmed", "papel": "Sócio", "candidate_key": "qsa:1:eduardo", "documento_ausente": True},
        confidence=0.45,
    )
    second = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="Eduardo Hermelino Leite",
        display_name="Eduardo Hermelino Leite",
        attrs={"status": "unconfirmed", "papel": "Sócio", "candidate_key": "qsa:2:eduardo", "documento_ausente": True},
        confidence=0.45,
    )
    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[
                FoundEntity(entity_type="ORG", kind="CNPJ", value="33000167000101", display_name="Empresa A", confidence=0.9),
                first,
                FoundEntity(entity_type="ORG", kind="CNPJ", value="00394460005887", display_name="Empresa B", confidence=0.9),
                second,
            ],
            edges=[
                FoundEdge(from_ref=found_canonical_key(first), to_ref="cnpj:33000167000101", rel_type="SOCIO"),
                FoundEdge(from_ref=found_canonical_key(second), to_ref="cnpj:00394460005887", rel_type="SOCIO"),
            ],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    people = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")).all()
    assert len(people) == 1
    assert people[0].id == origin.id
    links = db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.rel_type == "SOCIO")).all()
    assert len(links) == 2
    assert all(edge.from_entity_id == origin.id or edge.to_entity_id == origin.id for edge in links)


def test_consolidate_folds_existing_qsa_name_clones(settings, db) -> None:
    from osint4all.db.repository import consolidate_identities
    from sqlalchemy import select

    seed = parse_seed("Eduardo Hermelino Leite", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=3,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    company = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa A",
        attrs={"status": "confirmed"},
        depth=1,
    )
    clone = Entity(
        investigation_id=inv.id,
        entity_type="PERSON",
        canonical_key="name:eduardo hermelino leite#cand:qsa:1:eduardo",
        display_name="EDUARDO HERMELINO LEITE",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:1:eduardo"},
        depth=2,
    )
    db.add_all([company, clone])
    db.flush()
    db.add(Edge(investigation_id=inv.id, from_entity_id=clone.id, to_entity_id=company.id, rel_type="SOCIO"))
    db.flush()
    assert consolidate_identities(db, inv.id) >= 1
    people = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")).all()
    assert len(people) == 1
    assert people[0].id == origin.id
    links = db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.rel_type == "SOCIO")).all()
    assert len(links) == 1
    assert links[0].from_entity_id == origin.id or links[0].to_entity_id == origin.id


def test_qsa_name_remaps_even_without_cpf_anchor() -> None:
    profile = profile_from_fields({"NAME": "Eduardo Hermelino Leite"})
    assert not profile.has_person_anchor
    found = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="EDUARDO HERMELINO LEITE",
        display_name="EDUARDO HERMELINO LEITE",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:1:eduardo"},
        confidence=0.45,
    )
    assert bind_found_to_profile(found, profile) == "remap"
    stranger = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="Joao Pereira Lima",
        display_name="Joao Pereira Lima",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:1:joao"},
        confidence=0.45,
    )
    assert bind_found_to_profile(stranger, profile) == "keep"


def test_apply_result_drops_homonym_and_remaps_alias(settings, db) -> None:
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    name = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed, name],
        connectors=[],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.canonical_key.startswith("cpf:"))
    from osint4all.connectors.base import ConnectorResult, FoundEdge
    from sqlalchemy import select

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[
                FoundEntity(
                    entity_type="PERSON",
                    kind="CPF",
                    value="39053344705",
                    display_name="Maria Silva Souza",
                    confidence=0.8,
                ),
                FoundEntity(
                    entity_type="ORG",
                    kind="CNPJ",
                    value="33000167000101",
                    display_name="Empresa",
                    confidence=0.8,
                ),
            ],
            edges=[
                FoundEdge(from_ref="name:maria silva souza", to_ref="cnpj:33000167000101", rel_type="SOCIO"),
            ],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    people = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")).all()
    assert all(not (e.canonical_key or "").endswith("39053344705") for e in people)
    assert any(e.canonical_key.startswith("cnpj:") for e in db.scalars(select(Entity).where(Entity.investigation_id == inv.id)))


def test_apply_result_remap_keeps_cargo_and_photo(settings, db) -> None:
    name = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[name],
        connectors=[],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.entity_type == "PERSON")
    from sqlalchemy import select

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[
                FoundEntity(
                    entity_type="PERSON",
                    kind="NAME",
                    value="Maria Silva Souza",
                    display_name="Maria Silva Souza",
                    attrs={
                        "status": "unconfirmed",
                        "papel": "parlamentar",
                        "cargo": "deputado federal",
                        "partido": "PX",
                        "thumb": "https://www.camara.leg.br/foto.jpg",
                        "profile_photo": "https://www.camara.leg.br/foto.jpg",
                        "identity_match": 88,
                    },
                    confidence=0.7,
                )
            ]
        ),
        connector="congresso_public",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    db.flush()
    db.refresh(origin)
    assert (origin.attrs or {}).get("cargo") == "deputado federal"
    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(notes=["Câmara HTTP 403"]),
        connector="congresso_public",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    db.flush()
    from osint4all.db.models import Evidence

    notes = db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id, Evidence.source_label.contains("status"))).all()
    assert any("403" in (row.snippet or "") for row in notes)
    assert str((origin.attrs or {}).get("profile_photo") or "").startswith("https://")
    people = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")).all()
    assert len(people) == 1


def test_enqueue_skips_company_off_the_target(settings, db) -> None:
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    stray = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa solta",
        attrs={},
        depth=2,
    )
    db.add(stray)
    db.flush()
    queued = enqueue_qsa_network(db, inv, max_attempts=3)
    db.flush()
    from osint4all.db.models import ExpansionJob
    from sqlalchemy import select

    jobs = db.scalars(select(ExpansionJob).where(ExpansionJob.entity_id == stray.id)).all()
    assert jobs == []
    assert db.get(Entity, stray.id) is None
    assert queued >= 0


def test_assign_name_search_adds_companies_when_name_already_on_case(db) -> None:
    from sqlalchemy import select

    from osint4all.consult import ConsultResult
    from osint4all.web.router import _assign_seeds

    name = parse_seed("Maria Silva Souza", forced_kind="NAME")
    cpf = parse_seed("529.982.247-25", forced_kind="CPF")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="assign",
        seeds=[name, cpf],
        connectors=[],
        max_depth=1,
        monitor=False,
        created_by="t",
        enqueue=False,
    )
    parts = [
        ConsultResult(kind="NAME", query="Maria Silva Souza", title="Maria Silva Souza", summary="", ok=True),
        ConsultResult(kind="CNPJ", query="33.000.167/0001-01", title="Petrobras", summary="", ok=True),
    ]
    added = _assign_seeds(db, inv, parts)
    db.flush()
    assert added >= 1
    orgs = list(db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "ORG")))
    assert orgs
    person = db.scalar(
        select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON", Entity.is_seed.is_(True))
    )
    assert person is not None
    links = list(
        db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.from_entity_id == person.id, Edge.rel_type == "CANDIDATO"))
    )
    assert links
