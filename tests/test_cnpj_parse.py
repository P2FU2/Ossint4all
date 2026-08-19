from osint4all.connectors.cnpj_receita import parse_cnpj_payload
from osint4all.identifiers import canonical_key


def test_parse_qsa_creates_partners_and_admin() -> None:
    payload = {
        "cnpj": "33000167000101",
        "razao_social": "PETROLEO BRASILEIRO SA PETROBRAS",
        "nome_fantasia": "PETROBRAS",
        "qsa": [
            {
                "nome_socio": "HOLDING EXEMPLO LTDA",
                "cnpj_cpf_do_socio": "00000000000191",
                "qualificacao_socio": "Sócio",
            },
            {
                "nome_socio": "JOAO DA SILVA",
                "cnpj_cpf_do_socio": "52998224725",
                "qualificacao_socio": "Diretor",
            },
            {
                "nome_socio": "SEM DOCUMENTO",
                "qualificacao_socio": "Sócio",
            },
        ],
    }
    # 00000000000191 is invalid CNPJ (repeated) — use a valid one
    payload["qsa"][0]["cnpj_cpf_do_socio"] = "00000000000191"
    result = parse_cnpj_payload(
        {
            **payload,
            "qsa": [
                {
                    "nome_socio": "BANCO DO BRASIL SA",
                    "cnpj_cpf_do_socio": "00000000000191",
                    "qualificacao_socio": "Sócio",
                },
                payload["qsa"][1],
                payload["qsa"][2],
            ],
        }
    )
    types = {e.entity_type for e in result.entities}
    assert "ORG" in types
    assert "PERSON" in types
    rels = {e.rel_type for e in result.edges}
    assert "ADMIN" in rels
    assert "SOCIO" in rels
    assert result.evidence
    org_key = canonical_key("CNPJ", "33000167000101")
    assert any(e.to_ref == org_key for e in result.edges)
    org = next(e for e in result.entities if e.kind == "CNPJ" and e.value == "33000167000101")
    assert "razao_social" in org.attrs
