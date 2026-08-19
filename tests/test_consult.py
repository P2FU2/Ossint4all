from osint4all.consult import KIND_LABELS, resolve_kind, run_consult


def test_resolve_and_plate_consult() -> None:
    assert resolve_kind("auto", "ABC1D23") == "PLATE"
    result = run_consult("ABC1D23", mode="PLATE")
    assert result.ok
    assert result.kind == "PLATE"
    assert result.kind_label == KIND_LABELS["PLATE"]
    assert result.facts
    assert run_consult("XX", mode="PLATE").ok is False
    assert run_consult("", mode="auto").ok is False
    cnj = run_consult("0000123-45.2024.8.26.0100", mode="CNJ")
    assert cnj.ok
    assert cnj.kind == "CNJ"


def test_phone_email_cpf() -> None:
    phone = run_consult("11987654321", mode="PHONE")
    assert phone.ok
    assert any("wa.me" in (h.url or "") for h in phone.hits)
    email = run_consult("ana@exemplo.com", mode="EMAIL")
    assert email.ok
    assert email.kind == "EMAIL"
    assert run_consult("111.111.111-11", mode="CPF").ok is False
    assert run_consult("529.982.247-25", mode="CPF").ok
