from osint4all.identifiers import canonical_key, detect_kind, parse_seed, parse_seed_lines


def test_detect_kinds() -> None:
    assert detect_kind("33.000.167/0001-01") == "CNPJ"
    assert detect_kind("529.982.247-25") == "CPF"
    assert detect_kind("ana@exemplo.com") == "EMAIL"
    assert detect_kind("@jornalista") == "USERNAME"
    assert detect_kind("Maria Silva Souza") == "NAME"
    assert detect_kind("https://github.com/foo") == "URL"
    assert detect_kind("ABC1D23") == "PLATE"
    assert detect_kind("ABC-1234") == "PLATE"


def test_canonical_keys() -> None:
    assert canonical_key("CNPJ", "33.000.167/0001-01") == "cnpj:33000167000101"
    assert canonical_key("EMAIL", "Ana@Exemplo.com") == "email:ana@exemplo.com"
    assert canonical_key("USERNAME", "@Foo") == "username:foo"
    assert canonical_key("PLATE", "abc-1d23") == "plate:ABC1D23"
    seed = parse_seed("ABC1D23")
    assert seed is not None
    assert seed.entity_type == "VEHICLE"
    assert seed.display_name == "ABC-1D23"


def test_parse_seed_lines_dedup() -> None:
    seeds = parse_seed_lines("33.000.167/0001-01\n33000167000101\nMaria Silva\n")
    assert len(seeds) == 2
    assert parse_seed("").kind if parse_seed("") else True
