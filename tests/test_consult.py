from osint4all.consult import KIND_LABELS, _graph_from_cnpj, resolve_kind, run_consult
from osint4all.connectors.cnpj_receita import parse_cnpj_payload


def test_resolve_and_plate_consult() -> None:
    assert resolve_kind("auto", "ABC1D23") == "PLATE"
    result = run_consult("ABC1D23", mode="PLATE")
    assert result.ok
    assert result.kind == "PLATE"
    assert result.kind_label == KIND_LABELS["PLATE"]
    assert result.facts
    assert any(label == "Série (1º emplacamento)" for label, _ in result.facts)
    assert result.timeline
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
    assert email.timeline
    assert any("ana" in ev.meta or "ana" in ev.title for ev in email.timeline)
    assert email.graph_payload
    assert run_consult("111.111.111-11", mode="CPF").ok is False
    cpf = run_consult("529.982.247-25", mode="CPF")
    assert cpf.ok
    assert cpf.timeline
    assert any("Receita" in (h.title or "") for h in cpf.hits)
    assert any("Transparência" in (h.title or "") for h in cpf.hits)


def test_cnpj_graph_from_partners() -> None:
    parsed = parse_cnpj_payload(
        {
            "cnpj": "33000167000101",
            "razao_social": "PETROLEO BRASILEIRO SA PETROBRAS",
            "qsa": [
                {
                    "nome_socio": "BANCO DO BRASIL SA",
                    "cnpj_cpf_do_socio": "00000000000191",
                    "qualificacao_socio": "Sócio",
                },
                {
                    "nome_socio": "JOAO DA SILVA",
                    "cnpj_cpf_do_socio": "52998224725",
                    "qualificacao_socio": "Diretor",
                },
            ],
        }
    )
    partners = [e for e in parsed.entities if not (e.kind == "CNPJ" and e.value == "33000167000101")]
    graph = _graph_from_cnpj("33000167000101", "PETROBRAS", partners)
    payload = graph.to_payload()
    assert len(payload["nodes"]) >= 3
    assert payload["edges"]
    assert any(n["kind"] == "org" for n in payload["nodes"])
    assert any(n["kind"] == "person" for n in payload["nodes"])
