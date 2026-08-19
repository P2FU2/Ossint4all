
<p align="center">
  <img src="static\readme_banner.png" alt="Ossint4all" width="100%">
</p>

# OSINT4ALL


Plataforma de investigação OSINT em grafo. Você entra com CPF, CNPJ, nome, e-mail, telefone ou usuário; conectores consultam **fontes públicas e APIs oficiais** e montam a rede de vínculos com citação de origem.

Uso previsto: jornalismo investigativo. Não consulta DETRAN, cartório, operadora, bases vazadas nem perfis privados.

## O que faz

- Grafo de pessoas, empresas, processos, perfis públicos, ativos mencionados e publicações
- Expansão por profundidade (sócios → outras empresas → menções)
- DJEN e DataJud como conectores de processo/publicação
- TSE, Transparência, OpenCorporates, Wikidata, busca web (Brave/Google CSE) e checagem de URL pública
- Relatório HTML/PDF e monitoramento das sementes no cron
- Mapa de ferramentas no modelo do [OSINT Framework](https://osintframework.com/) (árvore expansível + ramo Brasil / [OSINT Brazuca](https://github.com/osintbrazuca/osint-brazuca))
- Anexo de PDF na investigação para ler metadados (estilo FOCA, só o arquivo que você envia)
- Auditoria de quem buscou o quê

## Instalação

```powershell
cd OSINT4ALL
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
copy .env.example .env
# edite .env — UI_ADMIN_PASSWORD, DATAJUD_API_KEY, etc.
python -m osint4all.main init-db
python -m osint4all.main serve
```

Painel: http://localhost:8000/login (padrão `admin` / senha do `.env`).

Worker e agenda (opcional, se `EXPAND_SYNC=false`):

```powershell
python -m osint4all.main worker
python -m osint4all.main schedule
```

## Testes

```powershell
pytest -q
```

## Fontes

| Conector | Precisa de chave | Observação |
|---|---|---|
| `cnpj_receita` | não | Minha Receita / BrasilAPI |
| `datajud` | chave pública CNJ | capa e movimentos |
| `djen` | não | Comunica API; egress Brasil |
| `tse` | não | candidaturas públicas |
| `transparencia` | `TRANSPARENCIA_API_KEY` | CEIS / CNEP |
| `opencorporates` | token opcional | empresas globais |
| `wikidata` | não | ficha pública |
| `web_search` | Brave ou Google CSE | só API oficial |
| `username_public` | não | GET em URL canônica pública (GitHub, X, YouTube…) |
| `crtsh` | não | nomes em certificados públicos ([crt.sh](https://crt.sh/)) |

## Mapa de ferramentas

`/app/ferramentas` carrega a árvore pública do [OSINT Framework](https://osintframework.com/) (cache em `data/osint_framework.json`), acrescenta **Brasil · oficiais** (portais do [OSINT Brazuca](https://github.com/osintbrazuca/osint-brazuca)), a **Suíte local (T)** (Sherlock, WhatsMyName, [Mr.Holmes](https://github.com/Lucksi/Mr.Holmes), [FOCA](https://github.com/ElevenPaths/FOCA), [SpiderFoot](https://github.com/smicallef/spiderfoot), user-scanner) e omite pastas de dados vazados, dark web e exploits.

## O que entrou e o que ficou de fora

| Fonte | No OSINT4ALL |
|---|---|
| [OSINT Brazuca](https://github.com/osintbrazuca/osint-brazuca) | Portais oficiais/públicos no mapa (CNJ, TSE, CNA, CEIS, Jucesp…). Sem CPF por força bruta nem captcha. |
| [user-scanner](https://github.com/kaifcodec/user-scanner) | Mais templates de URL pública no conector `username_public`. Sem módulos de breach / Hudson Rock. |
| [SpiderFoot](https://github.com/smicallef/spiderfoot) | Modelo de conectores + `crtsh`. Link T no mapa. |
| [FOCA](https://github.com/ElevenPaths/FOCA) | Metadados do PDF **anexado** no caso. Sem varrer Google atrás de documentos. |
| [Mr.Holmes](https://github.com/Lucksi/Mr.Holmes) | Só link T (instale localmente). |
| [awesome-osint-arsenal](https://github.com/rawfilejson/awesome-osint-arsenal) | Mesma ideia de catálogo; não instalamos o script de red team. |
| [Babel Street](https://www.babelstreet.com/solutions/strategic-threat-intelligence) | Só referência de UX (grafo + monitoramento). Sem telemetria móvel. |
| [Toutatis](https://github.com/megadose/toutatis), [yesitsme](https://github.com/0x0be/yesitsme) | **Não.** Exigem `sessionid` do Instagram. |
| [DarkSearch](https://github.com/DarkSearchApp/DarkSearch), [dark-web-osint-tools](https://github.com/apurvsinghgautam/dark-web-osint-tools), [IntelX](https://intelx.io/) | **Não.** Dark web / leaks. |

## Docker

```powershell
docker compose up --build
```
