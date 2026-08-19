from osint4all.validators import normalize_cnj, validate_cnpj, validate_cpf


def test_cpf_valid_and_invalid() -> None:
    assert validate_cpf("529.982.247-25")
    assert not validate_cpf("111.111.111-11")
    assert not validate_cpf("123")


def test_cnpj_valid_and_invalid() -> None:
    assert validate_cnpj("33.000.167/0001-01")
    assert not validate_cnpj("00.000.000/0000-00")


def test_cnj_roundtrip() -> None:
    parts = normalize_cnj("0000001-23.2024.8.26.0100")
    assert parts is not None
    assert parts.segmento == "8"
    assert parts.tribunal == "26"
    assert normalize_cnj(parts.numero_digits) is not None
