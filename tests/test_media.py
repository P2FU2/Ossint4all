from osint4all.graph.media import (
    collect_target_media,
    fields_from_identifiers,
    media_queries_from_fields,
    media_queries_from_identifiers,
    parse_image_rows,
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


def test_collect_media_stays_offline_in_pytest(settings) -> None:
    bundle = collect_target_media(["Maria Silva Souza"], settings=settings)
    assert bundle.news == []
    assert bundle.images == []
    assert any("ao vivo" in note for note in bundle.notes)
    assert any("nome" in item for item in bundle.queries)
    empty = collect_target_media([], settings=settings)
    assert empty.ok is False
    assert any("CPF" in note for note in empty.notes)
