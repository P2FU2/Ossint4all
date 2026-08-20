"""Open source ≠ base privada: o que o painel embute, equivale ou recusa."""

from __future__ import annotations

from typing import Any

OSS_TOOLS: tuple[dict[str, str], ...] = (
    {
        "name": "SpiderFoot",
        "github": "https://github.com/smicallef/spiderfoot",
        "role": "OSINT automatizado geral",
        "in_app": "Já é o modelo: conectores, busca em massa, crt.sh e fila. Não instalamos o daemon desktop.",
        "status": "embutido",
    },
    {
        "name": "LinkScope",
        "github": "https://github.com/AccentuSoft/LinkScope_Client",
        "role": "Grafo de entidades e relações (alternativa ao Maltego)",
        "in_app": "Rede / Árvore / Split / Mapa + quadro do caso já cobrem o grafo. Não empacotamos o cliente desktop.",
        "status": "equivalente",
    },
    {
        "name": "Recon-ng",
        "github": "https://github.com/lanmaster53/recon-ng",
        "role": "Framework modular de recon",
        "in_app": "Cada conector é um módulo. Explodir/Processar é o runner. Sem o CLI.",
        "status": "equivalente",
    },
    {
        "name": "theHarvester",
        "github": "https://github.com/laramies/theHarvester",
        "role": "E-mails, hosts, domínios",
        "in_app": "Conector Hosts (Wayback, HackerTarget, urlscan) + crt.sh + e-mail no Alvo. Sem o binário.",
        "status": "embutido",
    },
    {
        "name": "Amass",
        "github": "https://github.com/owasp-amass/amass",
        "role": "DNS e infraestrutura",
        "in_app": "Mesmos índices passivos do conector Hosts. Sem enum ativa nem brute de DNS.",
        "status": "parcial",
    },
    {
        "name": "Subfinder",
        "github": "https://github.com/projectdiscovery/subfinder",
        "role": "Subdomínios",
        "in_app": "Subdomínios pelos índices públicos (Wayback / urlscan / HackerTarget / crt.sh). Sem API paga do ProjectDiscovery.",
        "status": "parcial",
    },
    {
        "name": "Sherlock",
        "github": "https://github.com/sherlock-project/sherlock",
        "role": "Username em redes",
        "in_app": "Ferramenta Redes sociais: GET em URL canônica (também WhatsMyName / user-scanner).",
        "status": "embutido",
    },
    {
        "name": "Maigret",
        "github": "https://github.com/soxoj/maigret",
        "role": "Username / identidade digital",
        "in_app": "Mesmo conector de perfis, com templates extras (Bluesky, Threads, Mastodon, Patreon…). Sem o relatório HTML do Maigret.",
        "status": "embutido",
    },
    {
        "name": "Holehe",
        "github": "https://github.com/megadose/holehe",
        "role": "Serviços vinculados a e-mail",
        "in_app": "Keybase + Gravatar no conector de e-mail. Sem lista de 120 sites e sem qualquer base de leak.",
        "status": "parcial",
    },
    {
        "name": "PhoneInfoga",
        "github": "https://github.com/sundowndev/phoneinfoga",
        "role": "Telefone",
        "in_app": "DDD, cidade âncora, UF e tipo (fixo/celular). Sem operadora, sem IMEI, sem scraper de Truecaller.",
        "status": "parcial",
    },
    {
        "name": "GHunt",
        "github": "https://github.com/mxrch/GHunt",
        "role": "Ecossistema Google",
        "in_app": "Parcial: Scholar, News, Maps, YouTube e classificação de URL. Sem cookie, sem People API, sem sessão.",
        "status": "parcial",
    },
    {
        "name": "ExifTool",
        "github": "https://github.com/exiftool/exiftool",
        "role": "Metadados",
        "in_app": "PDF, JPEG e PNG que você anexa no caso. Sem varrer a web atrás de arquivos (FOCA/Photon).",
        "status": "embutido",
    },
    {
        "name": "Photon",
        "github": "https://github.com/s0md3v/Photon",
        "role": "Web crawler OSINT",
        "in_app": "Só a homepage de um domínio já no dossiê: até 8 links do mesmo host. Sem crawl profundo.",
        "status": "parcial",
    },
    {
        "name": "OpenCTI",
        "github": "https://github.com/OpenCTI-Platform/opencti",
        "role": "Threat intelligence + knowledge graph",
        "in_app": "O grafo do caso cobre entidades e relações. Não instalamos o stack STIX/OpenCTI.",
        "status": "equivalente",
    },
    {
        "name": "Aleph",
        "github": "https://github.com/alephdata/aleph",
        "role": "Pessoas, empresas, documentos, datasets",
        "in_app": "Conector na API pública do Aleph/OCCRP. Não self-host do Aleph nem envio de CPF.",
        "status": "embutido",
    },
    {
        "name": "IVRE",
        "github": "https://github.com/ivre/ivre",
        "role": "Indexação e correlação de inteligência de rede",
        "in_app": "Camada local: normaliza, guarda histórico e correlaciona hosts de fontes permitidas (crt.sh, índices, Shodan/Censys, ficha HTTP, JSON importado). Não dispara scan.",
        "status": "parcial",
    },
    {
        "name": "ZMap",
        "github": "https://github.com/zmap/zmap",
        "role": "Internet-wide scanning",
        "in_app": "Quase nada. Scan de internet não entra no dossiê.",
        "status": "fora",
    },
    {
        "name": "ZGrab2",
        "github": "https://github.com/zmap/zgrab2",
        "role": "Banner grabbing em larga escala",
        "in_app": "Só o parser/modelo se o JSON já veio de fonte lícita. Sem coleta ativa.",
        "status": "parcial",
    },
    {
        "name": "Masscan",
        "github": "https://github.com/robertdavidgraham/masscan",
        "role": "Port scanning de alta velocidade",
        "in_app": "Parser de JSON importado só se houver hostname público. Sem port scan e sem indexar IP solto.",
        "status": "parcial",
    },
    {
        "name": "Uncover",
        "github": "https://github.com/projectdiscovery/uncover",
        "role": "Unifica Shodan / Censys / FOFA",
        "in_app": "Shodan e Censys só com API oficial. Sem FOFA scrape e sem o binário Uncover.",
        "status": "parcial",
    },
    {
        "name": "Shodan (API)",
        "github": "https://developer.shodan.io/api",
        "role": "Serviços anunciados na internet",
        "in_app": "Conector Shodan só com SHODAN_API_KEY. Sem scrape, sem CVE.",
        "status": "parcial",
    },
    {
        "name": "httpx (ProjectDiscovery)",
        "github": "https://github.com/projectdiscovery/httpx",
        "role": "Status, título e tecnologia de um host conhecido",
        "in_app": "Um GET HTTPS no domínio já no dossiê: status, <title>, Server/X-Powered-By. Sem lista e sem porta.",
        "status": "parcial",
    },
    {
        "name": "Nuclei",
        "github": "https://github.com/projectdiscovery/nuclei",
        "role": "Fingerprinting informativo",
        "in_app": "Muito parcial: security.txt e robots/sitemap. Sem template de CVE, sem DAST.",
        "status": "parcial",
    },
)


def oss_cards() -> list[dict[str, Any]]:
    return [dict(row) for row in OSS_TOOLS]
