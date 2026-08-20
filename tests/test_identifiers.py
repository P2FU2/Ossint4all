from osint4all.identifiers import (
    canonical_key,
    collect_form_seeds,
    detect_kind,
    normalize_birth,
    parse_seed,
    parse_seed_lines,
    seeds_from_kind_values,
)


def test_detect_kinds() -> None:
    assert detect_kind("33.000.167/0001-01") == "CNPJ"
    assert detect_kind("529.982.247-25") == "CPF"
    assert detect_kind("52998224725") == "CPF"
    assert detect_kind("11987654321") == "PHONE"
    assert detect_kind("ana@exemplo.com") == "EMAIL"
    assert detect_kind("@jornalista") == "USERNAME"
    assert detect_kind("Maria Silva Souza") == "NAME"
    assert detect_kind("https://github.com/foo") == "URL"
    assert detect_kind("ABC1D23") == "PLATE"
    assert detect_kind("ABC-1234") == "PLATE"
    assert parse_seed("111.111.111-11", forced_kind="CPF") is None
    assert parse_seed("12345678901", forced_kind="CPF") is None


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


def test_consult_modes_do_not_fake_entity_kind() -> None:
    cnj = parse_seed("0000123-45.2024.8.26.0100", forced_kind="PROCESSOS")
    assert cnj is not None
    assert cnj.kind == "CNJ"
    assert cnj.entity_type == "CASE"
    assert cnj.canonical_key.startswith("cnj:")
    name = parse_seed("Ana Silva Souza", forced_kind="PROCESSOS")
    assert name is not None
    assert name.kind == "NAME"
    assert collect_form_seeds(seed_cnj="0000123-45.2024.8.26.0100", seed_cnpj="33.000.167/0001-01")
    kinds = {s.kind for s in collect_form_seeds(seed_cnj="0000123-45.2024.8.26.0100", seed_cnpj="33.000.167/0001-01")}
    assert kinds == {"CNJ", "CNPJ"}
    assigned = seeds_from_kind_values([("PROCESSOS", "0000123-45.2024.8.26.0100"), ("PROCESSOS", "0000123-45.2024.8.26.0100")])
    assert len(assigned) == 1
    assert assigned[0].kind == "CNJ"


def test_birth_and_filiation_seeds() -> None:
    assert normalize_birth("14061980") == "14/06/1980"
    assert normalize_birth("14/06/1980") == "14/06/1980"
    assert normalize_birth("99/99/9999") is None
    assert parse_seed("14061980", forced_kind="BIRTHDATE").value == "14/06/1980"
    seeds = collect_form_seeds(
        seed_name="Eduardo Hermelino Leite",
        seed_birth="14/06/1980",
        seed_father="Joao da Silva",
        seed_mother="Maria da Silva",
    )
    kinds = {s.kind for s in seeds}
    assert kinds == {"NAME", "BIRTHDATE", "FATHER", "MOTHER"}
