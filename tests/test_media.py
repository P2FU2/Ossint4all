from osint4all.graph.media import (
    collect_target_media,
    fields_from_identifiers,
    media_picks_to_result,
    media_queries_from_fields,
    media_queries_from_identifiers,
    parse_image_rows,
    parse_media_picks,
    parse_news_rows,
    plan_search_combos,
)


def test_plan_skips_cpf_and_short_name() -> None:
    combos = plan_search_combos(
        {
            "NAME": "Ana",
            "CPF": "529.982.247-25",
            "CNPJ": "33.000.167/0001-01",
            "USERNAME": "ana",
            "PLATE": "ABC1D23",
        }
    )
    blob = " ".join(combo.query for combo in combos)
    labels = [combo.label for combo in combos]
    assert "33.000.167/0001-01" in blob
    assert "@ana" in blob
    assert "ABC-1D23" in blob
    assert "529" not in blob
    assert all("Ana" not in combo.parts for combo in combos)
    assert "CNPJ + @user (notícia)" in labels
    assert "CNPJ + placa (notícia)" in labels
    assert "nome (notícia)" not in labels


def test_plan_pairs_name_and_company_without_overlap() -> None:
    combos = plan_search_combos(
        {
            "NAME": "Maria Silva Souza",
            "CNPJ": "33.000.167/0001-01",
            "USERNAME": "maria.silva",
        }
    )
    labels = [combo.label for combo in combos]
    assert "nome + empresa (notícia)" in labels
    assert "nome + @user (notícia)" in labels
    assert "nome (notícia)" not in labels
    assert "CNPJ (notícia)" not in labels
    assert "@user (notícia)" not in labels
    queries = [combo.query for combo in combos]
    assert any("Maria Silva Souza" in query and "33.000.167" in query for query in queries)
    assert any("Maria Silva Souza" in query and "@maria.silva" in query for query in queries)


def test_plan_complements_unpaired_image_after_email_news() -> None:
    combos = plan_search_combos(
        {"NAME": "Maria Silva Souza", "EMAIL": "maria@exemplo.com"},
    )
    labels = [combo.label for combo in combos]
    assert "nome + e-mail (notícia)" in labels
    assert "nome + domínio (notícia)" in labels
    assert "e-mail (notícia)" not in labels
    assert "nome (foto)" in labels
    assert "nome (notícia)" not in labels
    assert not any("gmail" in combo.query.lower() for combo in combos)


def test_plan_skips_generic_mail_domain() -> None:
    combos = plan_search_combos(
        {"NAME": "Maria Silva Souza", "EMAIL": "maria@gmail.com"},
    )
    assert not any("domínio" in combo.label for combo in combos)
    assert any("gmail.com" in combo.query for combo in combos)


def test_media_queries_are_combo_labels() -> None:
    queries = media_queries_from_fields(
        {
            "NAME": "Ana",
            "CPF": "529.982.247-25",
            "CNPJ": "33.000.167/0001-01",
            "USERNAME": "ana",
            "PLATE": "ABC1D23",
        }
    )
    assert any("CNPJ" in item for item in queries)
    assert any("@user" in item or "placa" in item for item in queries)
    assert all("529" not in item for item in queries)


def test_media_queries_use_full_name() -> None:
    queries = media_queries_from_identifiers(
        [{"kind": "NAME", "value": "Maria Silva Souza"}, {"kind": "EMAIL", "value": "maria@exemplo.com"}],
        title="Alvo · Maria Silva Souza",
    )
    assert "nome + e-mail (notícia)" in queries
    assert "nome + domínio (notícia)" in queries


def test_fields_prefer_seed_name_and_skip_filiation() -> None:
    fields = fields_from_identifiers(
        [
            {"kind": "NAME", "value": "Homônimo Qualquer", "seed": False},
            {"kind": "NAME", "value": "Maria Silva Souza", "seed": True},
            {"kind": "FATHER", "value": "Joao da Silva"},
            {"kind": "CPF", "value": "529.982.247-25"},
        ],
        name="Eduardo Hermelino Leite",
    )
    assert fields["NAME"] == "Maria Silva Souza"
    assert "FATHER" not in fields
    assert "CPF" not in fields
    only_title = fields_from_identifiers([], name="Eduardo Hermelino Leite")
    assert only_title["NAME"] == "Eduardo Hermelino Leite"


def test_fields_from_identifiers_add_company_not_cnpj() -> None:
    fields = fields_from_identifiers(
        [{"kind": "NAME", "value": "Maria Silva Souza"}, {"kind": "CPF", "value": "529.982.247-25"}],
        company="Petrobras Distribuidora",
    )
    assert fields["COMPANY"] == "Petrobras Distribuidora"
    assert "CPF" not in fields
    skip = fields_from_identifiers([], company="33.000.167/0001-01")
    assert "COMPANY" not in skip


def test_parse_news_and_images() -> None:
    news = parse_news_rows(
        [
            {"title": "Empresa no jornal", "url": "https://g1.exemplo/a", "content": "menção", "engine": "g1"},
            {"title": "sem url", "url": ""},
        ],
        source="nome + empresa (notícia)",
    )
    assert len(news) == 1
    assert news[0].title.startswith("Empresa")
    assert news[0].via == "nome + empresa (notícia)"
    images = parse_image_rows(
        [
            {
                "title": "Sede",
                "url": "https://exemplo.com/materia",
                "thumbnail_src": "https://img.exemplo/t.jpg",
            },
            {"title": "local", "thumbnail_src": "data:image/gif;base64,xx"},
        ],
        source="nome + empresa (foto)",
    )
    assert len(images) == 1
    assert images[0].thumb.startswith("https://")
    assert images[0].via == "nome + empresa (foto)"


def test_collect_explains_dead_instances(monkeypatch, settings) -> None:
    from osint4all.graph import media as media_mod

    monkeypatch.setattr(media_mod, "web_search_ready", lambda _settings: True)
    monkeypatch.setattr(media_mod, "_fetch_category", lambda *_a, **_k: [])
    dead = collect_target_media(["Maria Silva Souza"], settings=settings, live=True)
    assert dead.news == []
    assert dead.images == []
    assert any("instância" in note.lower() for note in dead.notes)

    monkeypatch.setattr(
        media_mod,
        "_fetch_category",
        lambda *_a, **_k: [{"title": "Menção", "url": "https://g1.exemplo/a", "content": "texto"}],
    )
    hit = collect_target_media(["Maria Silva Souza"], settings=settings, live=True)
    assert hit.news
    assert any("não provam identidade" in note for note in hit.notes)


def test_parse_media_picks_builds_publications() -> None:
    news, images = parse_media_picks(
        news_pick=["0", "2", "x"],
        news_url=["https://g1.exemplo/a", "https://ignorada.exemplo/b", "https://folha.exemplo/c"],
        news_title=["Matéria A", "Ignorada", "Matéria C"],
        news_snippet=["trecho a", "trecho b", "trecho c"],
        news_source=["g1", "x", "folha"],
        news_when=["hoje", "", "ontem"],
        news_via=["nome + empresa (notícia)", "", "nome (notícia)"],
        image_pick=["0"],
        image_url=["https://exemplo.com/materia"],
        image_title=["Sede"],
        image_thumb=["https://img.exemplo/t.jpg"],
        image_via=["nome + empresa (foto)"],
    )
    assert [item.url for item in news] == ["https://g1.exemplo/a", "https://folha.exemplo/c"]
    assert images[0].thumb.startswith("https://")
    result = media_picks_to_result("name:maria silva", news, images)
    assert len(result.entities) == 3
    assert all(item.entity_type == "PUBLICATION" and item.kind == "URL" for item in result.entities)
    assert any(item.attrs.get("tipo") == "noticia" for item in result.entities)
    assert any(item.attrs.get("thumb") == "https://img.exemplo/t.jpg" for item in result.entities)
    assert all(edge.rel_type == "MENCAO" for edge in result.edges)
    assert all(edge.from_ref == "name:maria silva" for edge in result.edges)


def test_collect_media_stays_offline_in_pytest(settings) -> None:
    bundle = collect_target_media(["Maria Silva Souza"], settings=settings)
    assert bundle.news == []
    assert bundle.images == []
    assert any("ao vivo" in note for note in bundle.notes)
    assert any("nome" in item for item in bundle.queries)
    empty = collect_target_media([], settings=settings)
    assert empty.ok is False
    assert any("CPF" in note for note in empty.notes)


def test_add_selected_media_creates_publication_nodes(monkeypatch, settings) -> None:
    import re

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from osint4all.api import create_app
    from osint4all.db.models import Edge, Entity
    from osint4all.db.session import session_scope
    from osint4all.graph.media import ImageItem, MediaBundle, NewsItem
    from osint4all.web.auth import seed_admin_user

    def fake_collect(*_a, **_k):
        return MediaBundle(
            queries=["nome (notícia)"],
            news=[
                NewsItem(
                    title="Empresa no jornal",
                    url="https://g1.exemplo/a",
                    snippet="menção pública",
                    source="g1",
                    when="hoje",
                    via="nome + empresa (notícia)",
                )
            ],
            images=[
                ImageItem(
                    title="Sede",
                    page_url="https://exemplo.com/materia",
                    thumb="https://img.exemplo/t.jpg",
                    via="nome + empresa (foto)",
                )
            ],
            notes=["Marque e adicione."],
        )

    monkeypatch.setattr("osint4all.web.router.collect_target_media", fake_collect)
    with session_scope() as session:
        seed_admin_user(session, settings)

    client = TestClient(create_app())
    login_html = client.get("/login").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', login_html).group(1)
    client.post("/login", data={"username": "admin", "password": "secret", "csrf_token": token}, follow_redirects=True)
    tools = client.get("/app/ferramentas")
    token = re.search(r'name="csrf_token" value="([^"]+)"', tools.text).group(1)
    created = client.post(
        "/app/nova",
        data={
            "csrf_token": token,
            "title": "Caso mídia",
            "hypothesis": "Picker",
            "seed_name": "Maria Silva Souza",
            "max_depth": "1",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    case_id = created.url.path.split("/")[3]
    panel = client.get(f"/app/casos/{case_id}/midia")
    assert panel.status_code == 200
    assert 'name="news_pick"' in panel.text
    assert 'name="image_pick"' in panel.text
    assert "Adicionar selecionadas" in panel.text
    assert "menção pública" in panel.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', panel.text).group(1)
    added = client.post(
        f"/app/casos/{case_id}/midia/adicionar",
        data={
            "csrf_token": token,
            "dest_case_id": case_id,
            "news_pick": "0",
            "news_url": "https://g1.exemplo/a",
            "news_title": "Empresa no jornal",
            "news_snippet": "menção pública",
            "news_source": "g1",
            "news_when": "hoje",
            "news_via": "nome + empresa (notícia)",
            "image_pick": "0",
            "image_url": "https://exemplo.com/materia",
            "image_title": "Sede",
            "image_thumb": "https://img.exemplo/t.jpg",
            "image_via": "nome + empresa (foto)",
        },
        headers={"HX-Request": "true"},
    )
    assert added.status_code == 200
    assert "adicionada" in added.text.lower()
    with session_scope() as session:
        pubs = list(
            session.scalars(
                select(Entity).where(Entity.investigation_id == case_id, Entity.entity_type == "PUBLICATION")
            )
        )
        assert len(pubs) == 2
        assert {item.display_name for item in pubs} == {"Empresa no jornal", "Sede"}
        target = session.scalar(select(Entity).where(Entity.investigation_id == case_id, Entity.is_seed.is_(True)))
        assert target is not None
        links = list(
            session.scalars(
                select(Edge).where(
                    Edge.investigation_id == case_id,
                    Edge.rel_type == "MENCAO",
                    Edge.from_entity_id == target.id,
                )
            )
        )
        assert len(links) == 2
