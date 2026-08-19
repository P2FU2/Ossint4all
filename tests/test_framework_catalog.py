from osint4all.catalog.brazil import brazil_branch
from osint4all.catalog.framework import (
    apply_seed_to_url,
    filter_tree,
    load_framework_tree,
    matching_branches,
    merge_brazil,
    tree_stats,
)
from osint4all.catalog.local_suite import local_suite_branch


def test_filter_drops_breach_and_keeps_username() -> None:
    raw = {
        "name": "OSINT Framework",
        "type": "folder",
        "children": [
            {
                "name": "Username",
                "type": "folder",
                "children": [{"name": "WhatsMyName Web", "type": "url", "url": "https://whatsmyname.app/"}],
            },
            {
                "name": "Breach Data",
                "type": "folder",
                "children": [{"name": "DeHashed", "type": "url", "url": "https://dehashed.com/"}],
            },
        ],
    }
    filtered = filter_tree(raw)
    assert filtered is not None
    names = [c["name"] for c in filtered["children"]]
    assert "Username" in names
    assert "Breach Data" not in names


def test_merge_brazil_and_stats() -> None:
    root = {"name": "OSINT Framework", "type": "folder", "children": []}
    merged = merge_brazil(root)
    names = [c["name"] for c in merged["children"]]
    assert brazil_branch()["name"] in names
    assert local_suite_branch()["name"] in names
    assert "Toutatis" not in str(merged)
    stats = tree_stats(merged)
    assert stats["tools"] >= 16
    assert stats["folders"] >= 5


def test_apply_seed_placeholders() -> None:
    assert apply_seed_to_url("https://minhareceita.org/{seed}", "33000167000101").endswith("33000167000101")
    assert "q=alice" in apply_seed_to_url("https://example.com/search", "alice", edit_url=True)


def test_kind_branches_and_load_offline() -> None:
    assert "Brasil · oficiais" in matching_branches("CNPJ")
    assert "Brasil · oficiais" in matching_branches("PLATE")
    assert "Tribunais e consultas (Brazuca)" in matching_branches("CNJ")
    tree = load_framework_tree(raw={"name": "OSINT Framework", "type": "folder", "children": []})
    assert tree["name"] == "OSINT4ALL"
    assert any(c["name"] == "Brasil · oficiais" for c in tree["children"])
    assert any(c["name"] == "Suíte local (T)" for c in tree["children"])


def test_filter_drops_intelx_and_toutatis() -> None:
    raw = {
        "name": "OSINT Framework",
        "type": "folder",
        "children": [
            {"name": "Intelligence X", "type": "url", "url": "https://intelx.io/"},
            {"name": "Toutatis", "type": "url", "url": "https://github.com/megadose/toutatis"},
            {"name": "WhatsMyName Web", "type": "url", "url": "https://whatsmyname.app/"},
        ],
    }
    filtered = filter_tree(raw)
    assert filtered is not None
    names = [c["name"] for c in filtered["children"]]
    assert names == ["WhatsMyName Web"]


def test_brazil_official_portals() -> None:
    blob = str(brazil_branch())
    assert "CNA · OAB" in blob
    assert "BNMP" in blob
    assert "Jucesp" in blob
    assert "filiaweb" in blob.lower()
    assert "SENATRAN" in blob
    assert "Veículos" in blob
    assert "rede societária" in blob.lower()
    assert "Brasil.IO" in blob
