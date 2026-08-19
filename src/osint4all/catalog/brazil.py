"""Ramo Brasil + conectores internos do OSINT4ALL."""

from __future__ import annotations

from typing import Any


def _url(
    name: str,
    url: str,
    *,
    description: str,
    input_type: str,
    output: str,
    internal: bool = False,
    edit_url: bool = False,
    registration: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": "url",
        "url": url,
        "description": description,
        "status": "live",
        "pricing": "free",
        "bestFor": description,
        "input": input_type,
        "output": output,
        "opsec": "passive",
        "localInstall": False,
        "googleDork": False,
        "registration": registration,
        "editUrl": edit_url,
        "api": False,
        "internal": internal,
        "source": "osint4all",
    }


def brazil_branch() -> dict[str, Any]:
    return {
        "name": "Brasil · oficiais",
        "type": "folder",
        "source": "osint4all",
        "children": [
            {
                "name": "Empresas e sócios",
                "type": "folder",
                "children": [
                    _url(
                        "Minha Receita (CNPJ)",
                        "https://minhareceita.org/{seed}",
                        description="Consulta pública de CNPJ com QSA (quadro de sócios).",
                        input_type="CNPJ",
                        output="Razão social, CNAE, sócios e situação cadastral",
                        edit_url=True,
                    ),
                    _url(
                        "BrasilAPI CNPJ",
                        "https://brasilapi.com.br/api/cnpj/v1/{seed}",
                        description="API pública de CNPJ.",
                        input_type="CNPJ",
                        output="JSON com dados cadastrais e QSA",
                        edit_url=True,
                    ),
                    _url(
                        "Receita Federal · CNPJ",
                        "https://solucoes.receita.fazenda.gov.br/servicos/cnpjreva/cnpjreva_solicitacao.asp",
                        description="Comprovante de inscrição e situação cadastral.",
                        input_type="CNPJ",
                        output="Comprovante oficial",
                    ),
                    _url(
                        "OSINT4ALL · conector CNPJ",
                        "/app/nova",
                        description="Expande QSA no grafo da investigação (Minha Receita / BrasilAPI).",
                        input_type="CNPJ",
                        output="Nós ORG/PERSON e arestas SOCIO/ADMIN",
                        internal=True,
                    ),
                ],
            },
            {
                "name": "Processos e diários",
                "type": "folder",
                "children": [
                    _url(
                        "DataJud (CNJ)",
                        "https://www.cnj.jus.br/sistemas/datajud/",
                        description="API pública de capa e movimentos processuais.",
                        input_type="CNJ",
                        output="Capa, classe, movimentos",
                    ),
                    _url(
                        "DJEN / Comunica",
                        "https://comunica.pje.jus.br/",
                        description="Diário de Justiça Eletrônico Nacional.",
                        input_type="Nome / CNJ / OAB",
                        output="Publicações e intimações",
                    ),
                    _url(
                        "OSINT4ALL · conectores judiciais",
                        "/app/nova",
                        description="DataJud e DJEN como expansão do grafo.",
                        input_type="CNJ / nome / empresa",
                        output="Nós CASE e PUBLICATION",
                        internal=True,
                    ),
                ],
            },
            {
                "name": "Eleições e transparência",
                "type": "folder",
                "children": [
                    _url(
                        "TSE DivulgaCandContas",
                        "https://divulgacandcontas.tse.jus.br/",
                        description="Candidaturas, partidos e prestações de contas.",
                        input_type="Nome",
                        output="Cargo, partido, UF, ano",
                    ),
                    _url(
                        "Portal da Transparência",
                        "https://portaldatransparencia.gov.br/",
                        description="CEIS, CNEP, contratos e servidores.",
                        input_type="CPF / CNPJ",
                        output="Sanções e despesas públicas",
                        registration=True,
                    ),
                    _url(
                        "Portal da Transparência API",
                        "https://api.portaldatransparencia.gov.br/",
                        description="API oficial (exige chave gratuita).",
                        input_type="CPF / CNPJ",
                        output="JSON CEIS/CNEP",
                        registration=True,
                    ),
                    _url(
                        "TSE FiliaWeb",
                        "https://filiaweb.tse.jus.br/filiaweb/",
                        description="Consulta pública de filiação partidária.",
                        input_type="Nome",
                        output="Partido e situação de filiação",
                    ),
                    _url(
                        "TSE Dados Abertos",
                        "https://dadosabertos.tse.jus.br/",
                        description="Repositório oficial de dados eleitorais.",
                        input_type="Nome / partido",
                        output="Candidaturas, contas, eleitorado",
                    ),
                    _url(
                        "Câmara · votações",
                        "https://www.camara.leg.br/busca-portal/proposicoes/votacoes",
                        description="Votações da Câmara dos Deputados.",
                        input_type="Nome / proposição",
                        output="Votos públicos",
                    ),
                ],
            },
            {
                "name": "Tribunais e consultas (Brazuca)",
                "type": "folder",
                "children": [
                    _url(
                        "Consulta processual CNJ",
                        "https://www.cnj.jus.br/pjecnj/ConsultaPublica/listView.seam",
                        description="Consulta pública unificada (PJe CNJ).",
                        input_type="CNJ / nome",
                        output="Capa pública do processo",
                    ),
                    _url(
                        "BNMP · mandados de prisão",
                        "https://portalbnmp.cnj.jus.br/#/pesquisa-peca",
                        description="Banco Nacional de Mandados de Prisão (consulta pública).",
                        input_type="Nome",
                        output="Peças públicas de mandado",
                    ),
                    _url(
                        "Jurisprudência STF",
                        "https://jurisprudencia.stf.jus.br/",
                        description="Acórdãos e decisões do STF.",
                        input_type="Nome / tema",
                        output="Julgados",
                    ),
                    _url(
                        "PJe TST",
                        "https://pje.tst.jus.br/consultaprocessual/",
                        description="Consulta pública da Justiça do Trabalho.",
                        input_type="CNJ / nome",
                        output="Processo trabalhista",
                    ),
                    _url(
                        "JusBrasil",
                        "https://www.jusbrasil.com.br/",
                        description="Índice público de peças e notícias jurídicas.",
                        input_type="Nome / CNJ",
                        output="Menções processuais",
                    ),
                    _url(
                        "Escavador",
                        "https://www.escavador.com/",
                        description="Busca pública de pessoas, instituições e processos.",
                        input_type="Nome",
                        output="Menções em fontes públicas",
                    ),
                ],
            },
            {
                "name": "Cadastros profissionais e empresa",
                "type": "folder",
                "children": [
                    _url(
                        "CPF · situação cadastral",
                        "https://servicos.receita.fazenda.gov.br/Servicos/CPF/ConsultaSituacao/ConsultaPublica.asp",
                        description="Consulta pública da situação do CPF (Receita).",
                        input_type="CPF",
                        output="Situação cadastral",
                    ),
                    _url(
                        "CNA · OAB",
                        "https://cna.oab.org.br/",
                        description="Cadastro Nacional dos Advogados.",
                        input_type="Nome / OAB",
                        output="Inscrição e seccional",
                    ),
                    _url(
                        "CFM · médicos",
                        "https://portal.cfm.org.br/busca-medicos/",
                        description="Busca pública no Conselho Federal de Medicina.",
                        input_type="Nome / CRM",
                        output="Registro profissional",
                    ),
                    _url(
                        "SINTEGRA",
                        "http://www.sintegra.gov.br/",
                        description="Inscrição estadual (consulta pública).",
                        input_type="CNPJ / IE",
                        output="Inscrição estadual",
                    ),
                    _url(
                        "CEIS",
                        "https://portaldatransparencia.gov.br/sancoes/consulta?cadastro=ceis",
                        description="Empresas inidôneas e suspensas.",
                        input_type="CNPJ / nome",
                        output="Sanção pública",
                    ),
                    _url(
                        "Jucesp",
                        "https://www.jucesponline.sp.gov.br/",
                        description="Junta Comercial de São Paulo (consulta pública).",
                        input_type="Nome / NIRE",
                        output="Ficha cadastral estadual",
                    ),
                ],
            },
            {
                "name": "Fonte do catálogo",
                "type": "folder",
                "children": [
                    _url(
                        "OSINT Brazuca",
                        "https://github.com/osintbrazuca/osint-brazuca",
                        description="Índice comunitário de portais públicos no contexto Brasil. Só fontes oficiais/públicas entram no mapa.",
                        input_type="—",
                        output="Lista de portais",
                    ),
                ],
            },
        ],
    }
