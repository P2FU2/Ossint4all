"""Ferramentas locais (T) que complementam o grafo — só as públicas e sem login."""

from __future__ import annotations

from typing import Any


def _tool(name: str, url: str, description: str, input_type: str, output: str) -> dict[str, Any]:
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
        "opsec": "active",
        "localInstall": True,
        "googleDork": False,
        "registration": False,
        "editUrl": False,
        "api": False,
        "internal": False,
        "source": "osint4all",
    }


def local_suite_branch() -> dict[str, Any]:
    return {
        "name": "Suíte local (T)",
        "type": "folder",
        "source": "osint4all",
        "children": [
            _tool(
                "Sherlock",
                "https://github.com/sherlock-project/sherlock",
                "Busca de username em páginas públicas (400+ sites). Rode localmente; no OSINT4ALL use o conector username_public.",
                "Username",
                "URLs de perfis públicos encontrados",
            ),
            _tool(
                "WhatsMyName",
                "https://whatsmyname.app/",
                "Enumeração web de username em sites públicos.",
                "Username",
                "Lista de perfis com HTTP 200",
            ),
            _tool(
                "SpiderFoot",
                "https://github.com/smicallef/spiderfoot",
                "Automação OSINT por módulos (e-mail, domínio, IP). Inspirou os conectores do OSINT4ALL.",
                "Domínio / e-mail / IP / username",
                "Grafo de footprint público",
            ),
            _tool(
                "FOCA",
                "https://github.com/ElevenPaths/FOCA",
                "Metadados em documentos oficiais (PDF/Office). No OSINT4ALL: anexe o PDF na investigação.",
                "Documento / domínio",
                "Autor, software, caminhos internos do arquivo",
            ),
            _tool(
                "Mr.Holmes",
                "https://github.com/Lucksi/Mr.Holmes",
                "Coleta pública de domínio, username e telefone (whois, dorks). Instale localmente; não roda dentro do painel.",
                "Domínio / username / telefone",
                "Relatório local",
            ),
            _tool(
                "user-scanner (T)",
                "https://github.com/kaifcodec/user-scanner",
                "Checagem de username/e-mail em sites públicos. Só o modo de presença de perfil; sem módulos de breach.",
                "Username / e-mail",
                "Onde o identificador aparece em página pública",
            ),
        ],
    }
