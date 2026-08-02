# Monitor Judicial

Serviço automatizado de monitoramento judicial em nuvem, com painel web autenticado.

- **Judit** — fonte operacional principal (descoberta, tracking, DJEN, webhooks, STF)
- **DataJud** — confirmação oficial seletiva / fallback (API pública CNJ)
- **OpenRouter** — resumos (com fallback determinístico)
- **Resend** — e-mail digest diário
- **Painel** — login usuário/senha, status do pipeline, acervo, eventos e histórico de digests

## Arquitetura

```
Railway / Docker
├── web        → FastAPI (painel /app + /health /ready /run /webhooks/judit /metrics)
├── worker     → consome jobs (fila no banco)
├── scheduler  → enfileira DAILY_DIGEST via cron
└── PostgreSQL → produção  |  SQLite → desenvolvimento local
```

Webhooks ingerem eventos o dia todo (`WEBHOOK_INGEST`). O e-mail é um **digest diário** (`DAILY_DIGEST`), não um e-mail por webhook.

## Painel web

Acesse `https://<seu-dominio>/login` (local: `http://localhost:8000/login`).

Variáveis:

```
UI_SESSION_SECRET=...          # obrigatório em produção (diferente do default)
UI_ADMIN_USER=admin            # cria o 1º usuário se a tabela users estiver vazia
UI_ADMIN_PASSWORD=...          # obrigatório em produção no primeiro boot
UI_SESSION_HOURS=72
```

Papéis: `admin` (dispara jobs, gerencia usuários) e `viewer` (somente leitura).  
`API_TRIGGER_TOKEN` continua só para automação (`POST /run`); não é o login do painel.

**Acompanhamento** (`/app/acompanhamento`): barra de progresso, % e ETA dos jobs (bootstrap, discovery, tracking, digest). Os logs do worker emitem o mesmo (`progress [####----] 42% ETA 3m …`). `GET /runs/{id}` também devolve os campos de progresso.

## Requisitos

- Python 3.12+
- Conta Judit (módulos contratados) + chave `api-key`
- Chave pública DataJud (CNJ) — [wiki de acesso](https://datajud-wiki.cnj.jus.br/api-publica/acesso/)
- OpenRouter (opcional) e Resend

## Instalação local

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

copy .env.example .env
copy config\monitoramentos.example.yaml config\monitoramentos.yaml
# edite .env e monitoramentos.yaml

python -m monitor_jus.main init-db
```

## Configuração

### Monitoramentos

Edite `config/monitoramentos.yaml` (OABs, CPFs, nomes, processos, empresas).

### Flags Judit (default `false`)

Habilite **somente** o que estiver no contrato:

```
JUDIT_ENABLE_HISTORICAL_SEARCH=true
JUDIT_ENABLE_OAB=true
JUDIT_ENABLE_CPF_CNPJ=true
JUDIT_ENABLE_PROCESS_TRACKING=true
JUDIT_ENABLE_DJEN=true
```

### DataJud

`DATAJUD_API_KEY` é a **chave pública** do CNJ (não é credencial individual). Pode mudar; veja `DATAJUD_API_KEY_URL`. Em 401/403 o sistema retorna erro claro pedindo atualização da chave.

Política seletiva: `config/datajud_policy.yaml`.

### Webhook Judit

```
JUDIT_WEBHOOK_AUTH_MODE=static_token   # none|static_token|hmac|ip_allowlist
JUDIT_WEBHOOK_TOKEN=...
```

Em `ENV=production`, `none` é **proibido**.

### Resend (e-mail)

```
RESEND_API_KEY=re_...
RESEND_MAX_CONCURRENCY=1
EMAIL_FROM=Monitor Judicial <onboarding@resend.dev>
EMAIL_TO=seu@email.com
```

Use um remetente de domínio verificado no Resend (ou o domínio de testes `resend.dev` em desenvolvimento).

## Execução

Três processos (ou Docker Compose):

```bash
python -m monitor_jus.main serve
python -m monitor_jus.main worker
python -m monitor_jus.main schedule
```

Bootstrap histórico (baseline **sem** flood de novidades no digest):

```bash
python -m monitor_jus.main bootstrap
# com worker rodando para processar o job
```

Enfileirar digest manualmente:

```bash
python -m monitor_jus.main run DAILY_DIGEST
```

API:

```bash
curl -X POST http://localhost:8000/run ^
  -H "Authorization: Bearer change-me" ^
  -H "Idempotency-Key: digest-manual-1" ^
  -H "Content-Type: application/json" ^
  -d "{\"run_type\":\"DAILY_DIGEST\"}"
```

Webhook:

`POST /webhooks/judit` — valida auth, persiste payload, responde 200 e enfileira `WEBHOOK_INGEST`.

## Docker Compose (local / SQLite)

```bash
docker compose up --build
```

## Produção (Railway)

1. Provisionar **PostgreSQL**
2. Definir `DATABASE_URL=postgresql+psycopg://...`
3. `ENV=production`
4. Definir `UI_SESSION_SECRET`, `UI_ADMIN_USER` e `UI_ADMIN_PASSWORD`
5. Três serviços: `web`, `worker`, `scheduler` (1 réplica cada no início)
6. Volume **não** é necessário para o banco (Postgres gerenciado)
7. Apontar a URL pública do webhook Judit para `https://<app>/webhooks/judit`
8. Painel em `https://<app>/login`

Ver também `docker-compose.prod.yml`.

## Agendamento

```
SCHEDULE_CRON=0 7 * * 1-5
TZ=America/Sao_Paulo
```

`SCHEDULE_HOUR` é fallback se o cron estiver vazio.

## Exclusão LGPD

```bash
python -m monitor_jus.main purge 00000000000
```

## Checklist comercial Judit

Antes de produção, confirme na proposta:

- consulta histórica por múltiplas OABs
- CPF / CNPJ / nome
- monitoramento de novos processos e movimentações
- DJEN (e o que **não** cobre fora do DJEN)
- STF / TJs / TRFs desejados
- webhooks + autenticação + histórico
- limites, preços, retenção, anexos, sandbox/Postman, SLA

## Disclaimer

O sistema consolida os eventos encontrados nas fontes habilitadas. A disponibilidade e o horário dos dados dependem da publicação e do processamento de cada tribunal e fornecedor. Publicações via DJEN e o início do monitoramento podem ter latência. Não há garantia de cobertura instantânea ou absoluta.

## Testes

```bash
pytest -q
```
