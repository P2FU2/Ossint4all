from osint4all.consult import KIND_LABELS, _graph_from_cnpj, ficha_from_cnpj_result, public_ficha, resolve_kind, run_consult
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
    assert any("DJEN" in (h.title or "") for h in cnj.hits)
    assert any(label == "Número CNJ" for label, _ in cnj.facts)


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


def test_cnpj_and_name_stay_offline_in_pytest() -> None:
    cnpj = run_consult("33000167000101", mode="CNPJ")
    assert cnpj.ok
    assert cnpj.kind == "CNPJ"
    assert "ao vivo" in cnpj.summary
    name = run_consult("Ana Silva", mode="NAME")
    assert name.ok
    assert name.kind == "NAME"
    assert name.hits == []


def test_public_records_modes_stay_offline() -> None:
    processos = run_consult("Ana Silva", mode="PROCESSOS")
    assert processos.ok
    assert processos.kind == "PROCESSOS"
    assert any("DJEN" in (h.title or "") for h in processos.hits)
    assert any("PJe" in (h.meta or "") or "PJe" in (h.title or "") for h in processos.hits)
    assert processos.timeline

    negativa = run_consult("529.982.247-25", mode="NEGATIVA")
    assert negativa.ok
    assert negativa.kind == "NEGATIVA"
    assert any("CEIS" in (h.title or "") for h in negativa.hits)
    assert any("CNEP" in (h.title or "") for h in negativa.hits)
    assert any("TCU" in (h.title or "") for h in negativa.hits)

    imovel = run_consult("Ana Silva", mode="IMOVEL")
    assert imovel.ok
    assert imovel.kind == "IMOVEL"
    assert any("Caixa" in (h.title or "") for h in imovel.hits)
    assert any("SNCR" in (h.title or "") or "Incra" in (h.title or "") for h in imovel.hits)
    assert any("cartório" in n.lower() for n in imovel.notes)

    diario = run_consult("Ana Silva", mode="DIARIO")
    assert diario.ok
    assert diario.kind == "DIARIO"
    assert any("in.gov.br" in (h.url or "") for h in diario.hits)
    assert any("Querido" in (h.title or "") for h in diario.hits)


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
    assert payload["consulted_at"]
    assert any(n["kind"] == "org" for n in payload["nodes"])
    assert any(n["kind"] == "person" for n in payload["nodes"])
    root = next(n for n in payload["nodes"] if n["id"].startswith("cnpj-"))
    assert root["socios"]


def test_ficha_from_cnpj_lists_opening_email_and_partners() -> None:
    parsed = parse_cnpj_payload(
        {
            "cnpj": "19215658000149",
            "razao_social": "EHL GESTAO EMPRESARIAL E NEGOCIOS LTDA",
            "data_inicio_atividade": "2013-11-08",
            "capital_social": "100000.00",
            "correio_eletronico": "contato@ehl.example",
            "qsa": [
                {"nome_socio": "EDUARDO HERMELINO LEITE", "qualificacao_socio": "Sócio-Administrador"},
                {
                    "nome_socio": "OUTRA EMPRESA LTDA",
                    "cnpj_cpf_do_socio": "33000167000101",
                    "qualificacao_socio": "Sócio",
                },
            ],
        }
    )
    card = ficha_from_cnpj_result(parsed, consulted_at="20/08/2026 11:00")
    labels = [label for label, _ in card["facts"]]
    assert "data da consulta" in labels
    assert "ano de abertura" in labels
    assert "capital social" in labels
    assert "e-mail de contato" in labels
    assert any("EDUARDO" in item for item in card["socios"])
    assert card["participacoes"]
    offline = public_ficha("19215658000149", mode="CNPJ")
    assert offline["ok"]
    assert any(label == "CNPJ" for label, _ in offline["facts"])
