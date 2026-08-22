from osint4all.connectors.base import FoundEntity
from osint4all.connectors.username_public import parse_public_hits
from osint4all.connectors.web_search import parse_web_hits
from osint4all.graph.preview import (
    attach_preview,
    build_entity_thumb,
    decorate_graph_attrs,
    enrich_found_entities,
    is_public_http_url,
    looks_like_pdf,
    normalize_official_url,
    opensanctions_entity_url,
    parse_open_graph,
    preview_from_html,
    preview_kind_for_url,
    render_card_svg,
    social_avatar_url,
    verify_source_url,
    youtube_embed,
)


OG_HTML = """
<html><head>
<title>Fallback</title>
<meta property="og:title" content="Ministro anuncia medida" />
<meta property="og:description" content="Texto da matéria em duas linhas." />
<meta property="og:image" content="https://img.exemplo/foto.jpg" />
</head></html>
"""

SOCIAL_HTML = """
<html><head>
<meta property="og:title" content="Alice / GitHub" />
<meta property="og:description" content="Repos e atividade pública." />
<meta property="og:image" content="/alice.png" />
</head></html>
"""


def test_open_graph_and_kinds() -> None:
    bag = parse_open_graph(OG_HTML, base_url="https://g1.exemplo/a")
    assert bag["og_title"] == "Ministro anuncia medida"
    assert "Texto da matéria" in bag["description"]
    assert bag["thumb"] == "https://img.exemplo/foto.jpg"
    assert preview_kind_for_url("https://in.gov.br/materia.pdf") == "pdf"
    assert preview_kind_for_url("https://cdn.exemplo/foto.png") == "image"
    assert preview_kind_for_url("https://x.com/alice") == "social"
    assert preview_kind_for_url("https://g1.globo.com/politica/a") == "article"
    assert looks_like_pdf("https://in.gov.br/arquivo.pdf?download=1")
    assert youtube_embed("https://www.youtube.com/watch?v=dQw4w9wgGcQ") == "https://www.youtube.com/embed/dQw4w9wgGcQ"


def test_social_avatar_and_public_url() -> None:
    assert social_avatar_url("https://github.com/alice", "alice", "GitHub") == "https://github.com/alice.png?size=240"
    assert "unavatar.io/twitter/lulaoficial" in social_avatar_url("https://x.com/lulaoficial", "lulaoficial", "X")
    assert is_public_http_url("https://in.gov.br/ato.pdf")
    assert not is_public_http_url("http://127.0.0.1/x")
    assert not is_public_http_url("http://192.168.0.8/x")
    bag = decorate_graph_attrs(
        {"network": "YouTube", "username": "lulaoficial", "preview_kind": "social"},
        url="https://www.youtube.com/@lulaoficial",
        entity_type="PROFILE",
        entity_id="e1",
        investigation_id="c1",
    )
    assert bag["thumb"] == "/app/casos/c1/entidades/e1/thumb"
    assert bag["tipo"] == "social"
    person = decorate_graph_attrs(
        {
            "thumb": "https://www.opensanctions.org/static/opensanctions-logo.png",
            "page_url": "https://www.opensanctions.org/entities/Q37181",
            "tipo": "pep",
        },
        url="https://www.opensanctions.org/entities/Q37181",
        entity_type="PERSON",
        entity_id="p1",
        investigation_id="c1",
    )
    assert not person.get("thumb")
    assert not person.get("profile_photo")
    portrait = decorate_graph_attrs(
        {
            "profile_photo": "https://upload.wikimedia.org/wikipedia/commons/lula.jpg",
            "profile_photo_source": "wikidata",
        },
        entity_type="PERSON",
        entity_id="p2",
        investigation_id="c1",
    )
    assert portrait["thumb"].endswith("lula.jpg")


def test_preview_from_html_social_resolves_relative_image() -> None:
    attrs = preview_from_html(SOCIAL_HTML, "https://github.com/alice")
    assert attrs["preview_kind"] == "social"
    assert attrs["thumb"] == "https://github.com/alice.png"
    assert attrs["og_title"] == "Alice / GitHub"


def test_official_url_is_normalized_and_verified_offline() -> None:
    assert opensanctions_entity_url("q10325423") == "https://www.opensanctions.org/entities/Q10325423"
    assert (
        normalize_official_url("https://www.opensanctions.org/entities/q10325423")
        == "https://www.opensanctions.org/entities/Q10325423"
    )
    check = verify_source_url("https://www.opensanctions.org/entities/q10325423")
    assert check["ok"] is True
    assert check["final_url"].endswith("/Q10325423")
    dead = FoundEntity(
        entity_type="PERSON",
        kind="URL",
        value="https://www.opensanctions.org/entities/q10325423",
        display_name="Q10325423",
        attrs={"_drop": True, "fonte_ok": False},
    )
    enrich_found_entities([dead])
    assert dead.attrs.get("_drop") is True


def test_card_svg_and_offline_thumb() -> None:
    svg = render_card_svg(kicker="PDF", title="Portaria", body="Dispõe sobre o ato.", kind="pdf")
    assert svg.startswith(b"<svg")
    assert b"Portaria" in svg
    assert b"Disp" in svg
    entity = type(
        "E",
        (),
        {
            "id": "n1",
            "investigation_id": "",
            "display_name": "Flickr · @lulaoficial",
            "entity_type": "PROFILE",
            "canonical_key": "url:https://www.flickr.com/people/lulaoficial/",
            "attrs": {
                "network": "Flickr",
                "username": "lulaoficial",
                "preview_kind": "social",
                "page_url": "https://www.flickr.com/people/lulaoficial/",
            },
        },
    )()
    data, ctype = build_entity_thumb(entity)
    assert ctype == "image/svg+xml"
    assert b"Flickr" in data or b"lulaoficial" in data
    news = type(
        "E",
        (),
        {
            "id": "n2",
            "investigation_id": "",
            "display_name": "Biografia",
            "entity_type": "PUBLICATION",
            "canonical_key": "url:https://g1.exemplo/a",
            "attrs": {"preview_kind": "article", "og_title": "Biografia do presidente", "description": "Texto da matéria."},
        },
    )()
    card, kind = build_entity_thumb(news)
    assert kind == "image/svg+xml"
    assert b"Biografia" in card
    assert b"Texto da" in card
    assert b"MAT" in card.upper()
    news_photo = type(
        "E",
        (),
        {
            "id": "n3",
            "investigation_id": "",
            "display_name": "Matéria",
            "entity_type": "PUBLICATION",
            "canonical_key": "url:https://g1.exemplo/b",
            "attrs": {
                "preview_kind": "article",
                "og_title": "Título da reportagem",
                "description": "Lead da matéria impressa.",
                "remote_thumb": "https://img.exemplo/foto.jpg",
            },
        },
    )()
    printed, printed_type = build_entity_thumb(news_photo)
    assert printed_type == "image/svg+xml"
    assert b"T" in printed and b"reportagem" in printed
    assert printed.startswith(b"<svg")
    person = type(
        "E",
        (),
        {
            "id": "n4",
            "investigation_id": "",
            "display_name": "Paulo Tarciso Okamotto",
            "entity_type": "PERSON",
            "canonical_key": "url:https://www.opensanctions.org/entities/Q1",
            "attrs": {
                "thumb": "https://www.opensanctions.org/static/logo.png",
                "page_url": "https://www.opensanctions.org/entities/Q1",
            },
        },
    )()
    name_card, name_type = build_entity_thumb(person)
    assert name_type == "image/svg+xml"
    assert b"Paulo" in name_card or b"Okamotto" in name_card


def test_attach_preview_pdf_skips_http() -> None:
    found = FoundEntity(
        entity_type="PUBLICATION",
        kind="URL",
        value="https://in.gov.br/dou/ato.pdf",
        display_name="DOU",
        attrs={},
    )
    attach_preview(found)
    assert found.attrs["preview_kind"] == "pdf"
    assert found.attrs["tipo"] == "pdf"
    assert found.attrs["page_url"].endswith(".pdf")


def test_enrich_found_stays_offline_in_pytest() -> None:
    found = FoundEntity(
        entity_type="PUBLICATION",
        kind="URL",
        value="https://g1.exemplo/materia",
        display_name="https://g1.exemplo/materia",
        attrs={},
    )
    enrich_found_entities([found])
    assert found.attrs["preview_kind"] == "article"
    assert "thumb" not in found.attrs


def test_web_and_username_carry_preview_fields() -> None:
    web = parse_web_hits(
        [{"url": "https://folha.exemplo/a", "title": "Título da matéria", "snippet": "Lead da reportagem."}],
        origin_key="name:maria",
    )
    pub = web.entities[0]
    assert pub.attrs["preview_kind"] == "article"
    assert pub.attrs["og_title"] == "Título da matéria"
    assert pub.attrs["description"] == "Lead da reportagem."
    pdf = parse_web_hits(
        [{"url": "https://in.gov.br/x.pdf", "title": "Portaria", "snippet": "DOU"}],
        origin_key="name:maria",
    )
    assert pdf.entities[0].attrs["preview_kind"] == "pdf"
    social = parse_public_hits(
        [("GitHub", "https://github.com/alice", SOCIAL_HTML)],
        origin_key="username:alice",
        user="alice",
    )
    profile = social.entities[0]
    assert profile.entity_type == "PROFILE"
    assert profile.attrs["preview_kind"] == "social"
    assert profile.attrs["thumb"] == "https://github.com/alice.png"
    assert profile.attrs["og_title"] == "Alice / GitHub"
