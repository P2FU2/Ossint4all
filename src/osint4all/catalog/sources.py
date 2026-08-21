"""Catálogo das fontes do grafo: o que cada uma busca e o que devolve."""

from __future__ import annotations

from typing import Any

from osint4all.config import ALL_CONNECTORS, Settings, get_settings

SOURCE_CATALOG: dict[str, dict[str, str]] = {
    "cnpj_receita": {
        "label": "Receita · CNPJ",
        "group": "Empresa",
        "accepts": "Nó com CNPJ",
        "returns": "Razão, QSA, CNAE, endereço, Simples/MEI, situação cadastral",
        "how": "Consulta Minha Receita ou BrasilAPI (dado público da RFB). Cada sócio vira pessoa e, no Explodir, as outras empresas dele.",
        "key": "",
        "url": "https://minhareceita.org/",
    },
    "socio_search": {
        "label": "Sócios · QSA aberto",
        "group": "Empresa",
        "accepts": "Nome (2+ palavras) ou CPF válido",
        "returns": "Empresas em que o nome/CPF aparece no quadro societário",
        "how": "Brasil.IO (com token) lista pelo CPF com máscara oficial. Sem token, só busca por nome em bases públicas — nunca inventa empresa para um CPF.",
        "key": "BRASIL_IO_API_TOKEN",
        "url": "https://brasil.io/",
    },
    "datajud": {
        "label": "DataJud · CNJ",
        "group": "Justiça",
        "accepts": "Processo (CNJ) ou nome em capa",
        "returns": "Capa, partes e movimentos públicos",
        "how": "API pública do CNJ. Sem DATAJUD_API_KEY a fonte fica offline — o painel não completa capa com chute.",
        "key": "DATAJUD_API_KEY",
        "url": "https://datajud-wiki.cnj.jus.br/api-publica/acesso/",
    },
    "djen": {
        "label": "DJEN · Comunica",
        "group": "Justiça",
        "accepts": "Nome, CNPJ ou número de comunicação",
        "returns": "Publicações do diário de justiça e intimações",
        "how": "API Comunica/PJe. Costuma falhar fora do Brasil (egress). Não abre PJe autenticado.",
        "key": "",
        "url": "https://comunica.pje.jus.br/",
    },
    "tse": {
        "label": "TSE · candidaturas",
        "group": "Público",
        "accepts": "Pessoa ou partido (nome)",
        "returns": "Candidatura, cargo, UF, partido",
        "how": "DivulgaCandContas. Homônimo fica candidato até você confirmar. Sem doação privada nem urna.",
        "key": "",
        "url": "https://divulgacandcontas.tse.jus.br/",
    },
    "transparencia": {
        "label": "Transparência · sanções",
        "group": "Público",
        "accepts": "Pessoa ou empresa (nome, CPF, CNPJ)",
        "returns": "CEIS, CNEP e órgãos sancionadores",
        "how": "Portal da Transparência (CGU). Com chave rende busca na API; sem chave a fonte avisa e não fabrica sanção.",
        "key": "TRANSPARENCIA_API_KEY",
        "url": "https://portaldatransparencia.gov.br/",
    },
    "opencorporates": {
        "label": "OpenCorporates",
        "group": "Empresa",
        "accepts": "Empresa ou nome",
        "returns": "Registros societários fora do Brasil",
        "how": "Complementa a Receita quando o alvo tem firma no exterior. Token opcional sobe o limite.",
        "key": "OPENCORPORATES_API_TOKEN",
        "url": "https://opencorporates.com/",
    },
    "wikidata": {
        "label": "Wikidata",
        "group": "Ficha",
        "accepts": "Pessoa ou empresa com nome",
        "returns": "Ficha pública (Q-id), cargo, descrição",
        "how": "Busca o rótulo em pt. Vira publicação ligada ao nó — não confirma identidade sozinha.",
        "key": "",
        "url": "https://www.wikidata.org/",
    },
    "web_search": {
        "label": "Busca web",
        "group": "Menção",
        "accepts": "Nome, CNPJ, placa, e-mail, @user, processo",
        "returns": "Menções e, no painel, notícias/fotos cruzadas",
        "how": "SearXNG público, Brave ou Google CSE. CPF não vai ao buscador. Combina pares (nome+empresa) em vez de repetir a mesma query.",
        "key": "SEARXNG_URL / BRAVE / CSE",
        "url": "https://docs.searxng.org/",
    },
    "username_public": {
        "label": "Perfis públicos",
        "group": "Digital",
        "accepts": "@user ou username",
        "returns": "URLs canônicas que respondem 200 (GitHub, X, YouTube…)",
        "how": "Só GET na URL pública, sem login. Fora: Instagram session, leak, Hudson Rock.",
        "key": "",
        "url": "https://github.com/",
    },
    "crtsh": {
        "label": "crt.sh · certificados",
        "group": "Digital",
        "accepts": "Domínio ou URL",
        "returns": "Nomes em certificados públicos (subdomínios, SANs)",
        "how": "Certificate Transparency. Complementa RDAP: aqui entram hosts emitidos, não o titular do domínio.",
        "key": "",
        "url": "https://crt.sh/",
    },
    "plate_public": {
        "label": "Placa · menção pública",
        "group": "Patrimônio",
        "accepts": "Veículo (placa)",
        "returns": "Série histórica de 1º emplacamento e dono só se o texto público citar",
        "how": "Portais e busca pública. Sem DETRAN, sem dono só com a placa.",
        "key": "",
        "url": "https://www.gov.br/infraestrutura/",
    },
    "diario_oficial": {
        "label": "Diários oficiais",
        "group": "Publicação",
        "accepts": "Nome completo, CNPJ ou razão social",
        "returns": "Edições municipais/estaduais com trecho e data",
        "how": "API do Querido Diário (OK.br). Não envia CPF. Complementa DJEN (justiça) e a busca web (jornal).",
        "key": "",
        "url": "https://queridodiario.ok.org.br/",
    },
    "geo_public": {
        "label": "Geo · endereço público",
        "group": "Mapa",
        "accepts": "Empresa com CEP, município ou endereço (QSA)",
        "returns": "lat/lng no nó para o Mapa deixar de usar só o centro da UF",
        "how": "ViaCEP (correios/CEP) + Nominatim/OSM. Sem cadastro predial, sem SIGEF privado.",
        "key": "",
        "url": "https://nominatim.openstreetmap.org/",
    },
    "rdap_public": {
        "label": "RDAP · domínio",
        "group": "Digital",
        "accepts": "E-mail (domínio próprio) ou URL",
        "returns": "Titular público, eventos e nameservers do domínio",
        "how": "RDAP do registro.br (.br) ou rdap.org. Ignora Gmail/Hotmail/Outlook. Complementa crt.sh (certificado ≠ titular).",
        "key": "",
        "url": "https://rdap.registro.br/",
    },
    "shodan_public": {
        "label": "Shodan · API oficial",
        "group": "Digital",
        "accepts": "Domínio da empresa (URL/e-mail) ou razão social",
        "returns": "Hostname, porta, produto e país de serviços anunciados na internet",
        "how": "Só a API oficial (SHODAN_API_KEY). Busca hostname:dominio ou org:\"razão\". Sem scrape do site, sem CVE, sem banner de exploit. Complementa crt.sh (certificado) e RDAP (titular).",
        "key": "SHODAN_API_KEY",
        "url": "https://developer.shodan.io/api",
    },
    "host_public": {
        "label": "Hosts · índices públicos",
        "group": "Digital",
        "accepts": "Domínio (URL ou e-mail próprio)",
        "returns": "Subdomínios e e-mails do mesmo domínio em índices abertos",
        "how": "Wayback CDX, HackerTarget e urlscan — coleta passiva estilo theHarvester/Amass/Subfinder. Sem brute de DNS, sem httpx, sem Nuclei. Complementa crt.sh (certificado) e Shodan (serviço ao vivo).",
        "key": "",
        "url": "https://web.archive.org/",
    },
    "email_public": {
        "label": "E-mail · serviços públicos",
        "group": "Digital",
        "accepts": "Nó com e-mail",
        "returns": "Keybase e Gravatar se o dono cadastrou o endereço",
        "how": "Lookup público (Holehe sem caixa e sem leak). Não consulta HIBP nem lista de contas vazadas. Complementa @user derivado do local-part.",
        "key": "",
        "url": "https://keybase.io/",
    },
    "phone_public": {
        "label": "Telefone · DDD público",
        "group": "Contato",
        "accepts": "Nó com telefone",
        "returns": "País, DDD, cidade âncora, UF e tipo (fixo/celular)",
        "how": "Tabela ANATEL estilo PhoneInfoga. Sem operadora, sem IMEI, sem Truecaller autenticado. Menção na web fica na busca pública.",
        "key": "",
        "url": "https://www.anatel.gov.br/",
    },
    "aleph_public": {
        "label": "Aleph · OCCRP",
        "group": "Investigação",
        "accepts": "Pessoa (nome e sobrenome) ou empresa/CNPJ",
        "returns": "Entidades e documentos em datasets investigativos públicos",
        "how": "API pública do Aleph (OCCRP). Não envia CPF. Homônimo fica menção até você confirmar.",
        "key": "",
        "url": "https://aleph.occrp.org/",
    },
    "censys_public": {
        "label": "Censys · API oficial",
        "group": "Digital",
        "accepts": "Domínio (URL ou e-mail próprio)",
        "returns": "Hosts e localização anunciados no índice Censys",
        "how": "Search API oficial (estilo Uncover, sem FOFA scrape). Precisa CENSYS_API_ID e CENSYS_API_SECRET. Sem banner grab, sem ZMap/Masscan.",
        "key": "CENSYS_API_ID / CENSYS_API_SECRET",
        "url": "https://search.censys.io/api",
    },
    "host_observe": {
        "label": "Ficha de host",
        "group": "Digital",
        "accepts": "Hostname já no dossiê (URL, perfil ou domínio da empresa)",
        "returns": "HTTP status, título, tecnologia anunciada, security.txt, sitemap e até 8 links do mesmo domínio",
        "how": "Um GET no host conhecido (httpx parcial + Photon raso + Nuclei só informativo). Indexa no histórico estilo IVRE. Sem lista, sem porta, sem IP, sem CVE.",
        "key": "",
        "url": "https://github.com/ivre/ivre",
    },
    "google_public": {
        "label": "Google · páginas públicas",
        "group": "Digital",
        "accepts": "Pessoa, @user ou e-mail",
        "returns": "Scholar, News, Maps e YouTube como busca/perfil público",
        "how": "Normaliza o ecossistema Google sem cookie (GHunt parcial). Sem People API e sem sessão.",
        "key": "",
        "url": "https://scholar.google.com/",
    },
    "pncp_public": {
        "label": "PNCP · contratos",
        "group": "Público",
        "accepts": "Empresa (CNPJ) ou nome",
        "returns": "Editais e contratos públicos, órgão contratante e valor se publicado",
        "how": "API de busca do Portal Nacional de Contratações Públicas. Sem chave. Não usa Portal da Transparência/CGU.",
        "key": "",
        "url": "https://pncp.gov.br/",
    },
    "congresso_public": {
        "label": "Congresso · dados abertos",
        "group": "Público",
        "accepts": "Pessoa (nome e sobrenome)",
        "returns": "Mandato de deputado ou senador em exercício, partido e UF",
        "how": "APIs públicas da Câmara e do Senado. Sem chave e sem login. Homônimo fica candidato até você confirmar.",
        "key": "",
        "url": "https://dadosabertos.camara.leg.br/",
    },
    "opensanctions_public": {
        "label": "OpenSanctions",
        "group": "Investigação",
        "accepts": "Pessoa ou empresa (nome/CNPJ)",
        "returns": "PEP e sanções internacionais em datasets públicos",
        "how": "Busca pública da API OpenSanctions. Sem chave. Se o endpoint pedir auth, a fonte fica vazia — sem chute.",
        "key": "",
        "url": "https://www.opensanctions.org/",
    },
    "gleif_public": {
        "label": "GLEIF · LEI",
        "group": "Empresa",
        "accepts": "Empresa (razão ou CNPJ)",
        "returns": "Legal Entity Identifier, jurisdição e registro local",
        "how": "API pública do GLEIF. Sem chave. Complementa OpenCorporates quando a firma tem LEI.",
        "key": "",
        "url": "https://search.gleif.org/",
    },
}


def _ready(name: str, health: dict[str, Any], settings: Settings) -> str:
    if not health.get("enabled", True):
        return "desligada"
    if name == "datajud" and not settings.datajud_api_key:
        return "precisa chave"
    if name == "transparencia" and not settings.transparencia_api_key:
        return "precisa chave"
    if name == "socio_search" and not settings.brasil_io_api_token:
        return "parcial"
    if name == "shodan_public" and not settings.shodan_api_key:
        return "precisa chave"
    if name == "censys_public" and not (settings.censys_api_id and settings.censys_api_secret):
        return "precisa chave"
    return "pronta"


def source_cards(settings: Settings | None = None, health_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    by_id = {row.get("source"): row for row in (health_rows or [])}
    cards: list[dict[str, Any]] = []
    for name in ALL_CONNECTORS:
        meta = SOURCE_CATALOG.get(name, {"label": name, "group": "", "accepts": "", "returns": "", "how": "", "key": "", "url": ""})
        health = dict(by_id.get(name) or {"source": name, "enabled": False})
        status = _ready(name, health, settings)
        cards.append(
            {
                "id": name,
                "label": meta.get("label") or name,
                "group": meta.get("group") or "",
                "accepts": meta.get("accepts") or "",
                "returns": meta.get("returns") or "",
                "how": meta.get("how") or "",
                "key": meta.get("key") or "",
                "url": meta.get("url") or "",
                "status": status,
                "status_slug": status.replace(" ", "-"),
                "enabled": bool(health.get("enabled")),
                "health": {k: v for k, v in health.items() if k != "source"},
            }
        )
    return cards
