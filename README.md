# Livro Vivo API

Backend Django/DRF do app Livro Vivo.

## Estado atual

Implementado e ativo em `main`:

- Auth JWT (`register`, `login`, `refresh`, `logout`).
- Reset de senha por e-mail transacional.
- Auth social Google para web e Android beta, com vinculo/desvinculo de contas em Minha Conta.
- Fluxo de documentos legais vigentes com aceite obrigatorio antes do uso da plataforma.
- Perfil/roles e resumo de moderacao na resposta de entitlements.
- Acoes LGPD self-service com exportacao de dados e solicitacao de anonimização/exclusao logica da conta.
- Entitlements por assinatura (`essential` / `professional`) com suporte a founder.
- Biblioteca chapter-first (`Book`, `BookVersion`, `BookChapter`) com publicacao de versoes e changelog.
- Busca de capitulos com FTS no Postgres e fallback para SQLite.
- Busca global cross-modulo para biblioteca, jurisprudencia e comunidade.
- Anotacoes por capitulo com `selector + offsets`.
- Jurisprudencia com ementa rich/plain, anchors, tags, busca e consumo no app.
- Curso com `CoursePost`, `CourseAsset` e `LiveEvent`, gating Profissional, admin e notificacoes de publicacao.
- Banco de Pecas versionado com metadados de arquivo, upload/URL remota, token temporario de download e gating Profissional.
- Comunidade com categorias, posts, comentarios, reports, follow/unfollow de posts, fila de moderacao, trilha de acoes e banimento por escopo.
- Notificacoes com preferencias por usuario, `NotificationEvent`, `NotificationDispatch`, inbox in-app, registro de devices e dispatcher de push.
- Health/readiness, `check --deploy`, logs estruturados com sanitizacao de segredos em query string e Sentry opcional.
- Monitoramento beta com Grafana Cloud como painel unico, Alloy no VPS, dashboard operacional, atalho no Admin e alertas iniciais.
- Hardening de avatar com validacao de formato/MIME, limite de tamanho, limite de dimensoes e recorte seguro.
- Cadastro endurecido contra enumeracao de e-mail, registro estavel de dispositivo push por `installation_id` e limpeza de backlog antigo no registro do device atual.

## Status operacional beta

Ultima revisao documental validada em `2026-05-04`:

- API beta publica: `https://api-178-104-197-8.nip.io`.
- Django admin beta: `https://api-178-104-197-8.nip.io/admin/`.
- Deploy da `main` para VPS via GitHub Actions.
- `readyz/` deve retornar `database: ok` e `cache: ok`.
- Google social auth exige `SOCIAL_AUTH_ALLOWED_REDIRECT_URIS` com app web e `livrovivo://auth/callback`.
- SMTP transacional esta configurado no VPS via Brevo para reset de senha.
- Grafana Cloud recebe metricas da API, metricas do VPS, logs da API/Caddy e telemetria Android.
- Dashboard `Livro Vivo Beta Overview` esta importado no Grafana e linkado no Admin por `GRAFANA_BETA_DASHBOARD_URL`.
- Primeira leva de 8 alertas Grafana esta ativa e em estado `Normal`.
- Inventario consolidado do beta: `docs/FONTE_DA_VERDADE_ESTADO_BETA_2026-05-04.md`.
- Monitoramento oficial do beta deve seguir `docs/FONTE_DA_VERDADE_MONITORAMENTO_BETA_2026-04-30.md`.

Checks de referencia antes de PR/deploy:

- `python manage.py test`
- `python manage.py check --deploy --fail-level WARNING` com ambiente de producao simulado
- `pip-audit -r requirements.txt`

## Stack

- Python 3.12+
- Django 5
- Django REST Framework
- PostgreSQL (dev/prod)
- Filesystem storage em dev / object storage S3-compativel em stage-producao
- `djangorestframework-simplejwt`
- `django-cors-headers`
- `django-tinymce`
- `django-storages` + `boto3`
- `sentry-sdk` (opcional)
- `gunicorn` + `whitenoise` para runtime HTTP de producao

## Setup local

### 1) Ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2) Dependencias

```bash
pip install -r requirements.txt
```

Para desenvolvimento com cobertura e checks locais completos:

```bash
pip install -r requirements-dev.txt
```

### 3) Variaveis de ambiente

Crie `.env` a partir de `.env.example`:

```bash
cp .env.example .env
```

Variaveis principais:

- `DJANGO_ENV`: `development` | `stage` | `production`
- `DEBUG`: `true` | `false`
- `DJANGO_SECRET_KEY`: obrigatoria em stage/prod
- `DATABASE_URL`: obrigatoria em stage/prod
- `DJANGO_OFFLINE_MIGRATION_CHECK`: em dev, usa SQLite local para `makemigrations --check --dry-run` e evita warnings quando o banco externo nao esta de pe
- `DJANGO_ALLOWED_HOSTS`: obrigatoria em stage/prod
- `DJANGO_CORS_ALLOWED_ORIGINS`: obrigatoria em stage/prod
- `DJANGO_CSRF_TRUSTED_ORIGINS`: obrigatoria em stage/prod
- `APP_VERSION`: versao exibida em health/readiness
- `PASSWORD_RESET_CONFIRM_URL`: URL do app para concluir reset de senha
- `DJANGO_EMAIL_BACKEND`
- `DJANGO_EMAIL_HOST`
- `DJANGO_EMAIL_PORT`
- `DJANGO_EMAIL_HOST_USER`
- `DJANGO_EMAIL_HOST_PASSWORD`
- `DJANGO_EMAIL_USE_TLS`
- `DJANGO_EMAIL_USE_SSL`
- `DJANGO_DEFAULT_FROM_EMAIL`
- `REDIS_URL`: obrigatoria em stage/prod; recomendada em desenvolvimento para reproduzir throttle/cache distribuido
- `DJANGO_LOG_PROFILE`: `dev` | `prod`
- `DJANGO_LOG_INCLUDE_REQUESTS`: habilita logs request-by-request do `django.server`
- `DJANGO_LOG_STRUCTURED`: `true` para JSON estruturado
- `DJANGO_LOG_LEVEL`: override opcional do nivel raiz
- `DJANGO_LOG_DJANGO_LEVEL`: override opcional do nivel do logger `django`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_SESSION_COOKIE_SECURE`
- `DJANGO_CSRF_COOKIE_SECURE`
- `DJANGO_SECURE_PROXY_SSL_HEADER_ENABLED`
- `DJANGO_SECURE_HSTS_SECONDS`
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `DJANGO_SECURE_HSTS_PRELOAD`
- `SENTRY_DSN`
- `SENTRY_ENVIRONMENT`
- `SENTRY_TRACES_SAMPLE_RATE`
- `GRAFANA_BETA_DASHBOARD_URL`: atalho opcional exibido no Admin para abrir o dashboard beta do Grafana
- `DJANGO_STORAGE_PROVIDER`: `filesystem` | `s3`
- `DJANGO_MEDIA_URL`
- `DJANGO_MEDIA_ROOT`
- `DJANGO_MEDIA_PUBLIC_CACHE_CONTROL`
- `DJANGO_MEDIA_PRIVATE_CACHE_CONTROL`
- `DJANGO_STORAGE_S3_BUCKET_NAME`
- `DJANGO_STORAGE_S3_ENDPOINT_URL`
- `DJANGO_STORAGE_S3_REGION_NAME`
- `DJANGO_STORAGE_S3_ACCESS_KEY_ID`
- `DJANGO_STORAGE_S3_SECRET_ACCESS_KEY`
- `DJANGO_STORAGE_S3_CUSTOM_DOMAIN`
- `DJANGO_STORAGE_S3_QUERYSTRING_EXPIRE`
- `DJANGO_AVATAR_MAX_UPLOAD_BYTES`
- `DJANGO_AVATAR_MAX_DIMENSION`
- `DJANGO_AVATAR_ALLOWED_MIME_TYPES`

Notificacoes:

- `NOTIFICATIONS_ENABLED`
- `NOTIFICATIONS_PUSH_PROVIDER` (`noop` por padrao)
- `NOTIFICATIONS_FCM_PROJECT_ID`
- `NOTIFICATIONS_APNS_TOPIC`
- `PUSH_AUTODISPATCH_ENABLED` (`true` por padrão; defina `false` se preferir despachar push por job/command)
- `EXPO_PUSH_API_URL`
- `EXPO_PUSH_ACCESS_TOKEN`
- `GUNICORN_BIND`
- `GUNICORN_WORKERS`
- `GUNICORN_TIMEOUT`

Banco de Pecas:

- `TEMPLATES_BANK_DOWNLOAD_TOKEN_MAX_AGE_SECONDS`
  Padrao recomendado para beta: `60` segundos.
- `TEMPLATES_BANK_REMOTE_FILE_FETCH_TIMEOUT_SECONDS`
- `TEMPLATES_BANK_REMOTE_FILE_MAX_BYTES`

Auth social:

- `SOCIAL_AUTH_ALLOWED_REDIRECT_URIS`
- `SOCIAL_AUTH_STATE_MAX_AGE_SECONDS`
- `SOCIAL_AUTH_RESULT_TOKEN_MAX_AGE_SECONDS`
- `SOCIAL_AUTH_HTTP_TIMEOUT_SECONDS`
- `SOCIAL_AUTH_GOOGLE_ENABLED`
- `SOCIAL_AUTH_GOOGLE_CLIENT_ID`
- `SOCIAL_AUTH_GOOGLE_CLIENT_SECRET`
- `SOCIAL_AUTH_GOOGLE_AUTHORIZATION_URL`
- `SOCIAL_AUTH_GOOGLE_TOKEN_URL`
- `SOCIAL_AUTH_GOOGLE_USERINFO_URL`
- `SOCIAL_AUTH_GOOGLE_SCOPES`
- `SOCIAL_AUTH_LINKEDIN_ENABLED`
- `SOCIAL_AUTH_LINKEDIN_CLIENT_ID`
- `SOCIAL_AUTH_LINKEDIN_CLIENT_SECRET`
- `SOCIAL_AUTH_LINKEDIN_AUTHORIZATION_URL`
- `SOCIAL_AUTH_LINKEDIN_TOKEN_URL`
- `SOCIAL_AUTH_LINKEDIN_USERINFO_URL`
- `SOCIAL_AUTH_LINKEDIN_SCOPES`
- `DJANGO_METRICS_ENABLED`
- `DJANGO_METRICS_BEARER_TOKEN`
- `GRAFANA_BETA_DASHBOARD_URL`
- `CLIENT_TELEMETRY_ENABLED`
- `CLIENT_TELEMETRY_SHARED_SECRET`
- `CLIENT_TELEMETRY_MAX_BYTES`
- `CLIENT_TELEMETRY_RATE_LIMIT`

Notas:

- nesta fase, `Google` é o unico provider operacional
- `LinkedIn` ja esta modelado, mas segue desabilitado por padrao
- `SOCIAL_AUTH_ALLOWED_REDIRECT_URIS` deve incluir o callback web e o scheme mobile
- o fluxo usa:
  - `POST /auth/social/<provider>/start/`
  - `GET /auth/social/<provider>/callback/`
  - `POST /auth/social/complete/`
  - `GET /me/linked-accounts/`
  - `DELETE /me/linked-accounts/<provider>/`
  - `POST /me/set-password/`

## Storage de midia e anexos

O backend agora suporta storage configuravel por alias:

- `avatars`: midia publica do usuario
- `template_uploads`: uploads do Banco de Pecas

Modo padrao em desenvolvimento:

- `DJANGO_STORAGE_PROVIDER=filesystem`
- arquivos servidos por `MEDIA_ROOT` / `MEDIA_URL`

Modo recomendado para stage/producao:

- `DJANGO_STORAGE_PROVIDER=s3`
- bucket/object storage compativel com S3
- `avatars` com entrega publica e cacheavel
- `template_uploads` preparados para entrega com URL assinada

Diretriz tecnica:

- manter texto e metadados no Postgres
- manter arquivos binarios em object storage
- usar CDN/dominio publico para avatar
- preferir entrega assinada para uploads protegidos do Banco de Pecas

Metadados expostos pela API para assets/arquivos:

- `*_url`
- `*_source`

Politica minima recomendada:

- avatar: `public, max-age=86400, stale-while-revalidate=604800`
- uploads protegidos: `private, max-age=300, no-store`

No beta barato com storage local em VPS:

- `avatars` continuam publicos em `/media/avatars/...`;
- uploads do Banco de Pecas nao sao expostos como URL publica de filesystem;
- o download autenticado passa por endpoint assinado do backend.

Migracao recomendada para object storage:

1. configurar bucket e credenciais S3 compativeis;
2. subir com `DJANGO_STORAGE_PROVIDER=s3`;
3. manter URLs remotas historicas onde elas ja existirem;
4. migrar uploads locais existentes para o bucket e preservar `name/key`;
5. validar `health/`, `readyz/` e a resolucao publica de `*_url` antes de abrir trafego.

### 4) Banco e migrations

```bash
python manage.py migrate
```

### 5) Rodar servidor

```bash
python manage.py runserver
```

Exemplo para reduzir ruido de terminal em desenvolvimento:

```bash
DJANGO_LOG_PROFILE=dev
DJANGO_LOG_INCLUDE_REQUESTS=false
python manage.py runserver
```

## Deploy beta barato no VPS

Esta API esta preparada para o beta `web-first` com:

- `Dockerfile`
- `docker-compose.yml`
- `deploy/Caddyfile`
- `gunicorn` como servidor WSGI
- `whitenoise` para estaticos/admin

Topologia oficial do beta:

- `caddy`: TLS/reverse proxy
- `api`: Django + gunicorn
- `postgres`: banco principal
- `redis`: cache/throttle/filas leves
- volume local para `media/`

### 1) Preparar ambiente no VPS

No servidor:

```bash
git clone <repo-da-api> /opt/livro-vivo-api
cd /opt/livro-vivo-api
cp .env.beta.example .env
```

Edite `.env` com os valores reais, em especial:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CORS_ALLOWED_ORIGINS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `CADDY_SITE_ADDRESS`
- `EXPO_PUSH_ACCESS_TOKEN` se usar token de acesso da Expo

### 2) Subir a stack

```bash
docker compose up -d --build
```

### 3) Criar superuser

```bash
docker compose exec api python manage.py createsuperuser
```

### 4) Checklist de smoke no VPS

```bash
curl -I http://127.0.0.1/health/
curl -I http://127.0.0.1/readyz/
docker compose ps
docker compose logs api --tail 100
```

Esperado:

- `health/` responde `200`
- `readyz/` responde `200`
- `caddy`, `api`, `postgres` e `redis` estao `running` ou `healthy`

### 5) Deploy continuo da `main`

O repositório inclui `.github/workflows/deploy.yml`.

Fluxo oficial:

1. PR aprovado
2. merge na `main`
3. `API CI` fecha verde
4. workflow `API Deploy` conecta por SSH no VPS
5. servidor executa `docker compose up -d --build`

Secrets necessarios no GitHub:

- `VPS_HOST`
- `VPS_PORT`
- `VPS_USER`
- `VPS_SSH_KEY`
- `DEPLOY_PATH`

## Qualidade local

### Testes

```bash
python manage.py test
```

### Cobertura

```bash
coverage run --rcfile=.coveragerc manage.py test
coverage report --rcfile=.coveragerc
```

Threshold global atual: `>= 78%`.

### Sem migrations pendentes

```bash
python manage.py makemigrations --check --dry-run
```

Em desenvolvimento, esse comando usa fallback local de SQLite por padrao. Para validar contra o banco configurado em `DATABASE_URL`, rode com:

```bash
DJANGO_OFFLINE_MIGRATION_CHECK=false python manage.py makemigrations --check --dry-run
```

### Check de deploy (simulacao)

```bash
DJANGO_ENV=production \
DEBUG=false \
DJANGO_SECRET_KEY="$(openssl rand -hex 32)" \
DJANGO_ALLOWED_HOSTS=api.example.com \
DJANGO_CORS_ALLOWED_ORIGINS=https://app.example.com \
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com \
DATABASE_URL=sqlite:///./tmp-prod-check.sqlite3 \
REDIS_URL=redis://127.0.0.1:6379/1 \
python manage.py check --deploy --fail-level WARNING
```

## Health e readiness

- `GET /health/` (e alias `/healthz/`)
- `GET /readyz/`
- Header de rastreio em todas as respostas: `X-Request-ID`
- Header simples de latencia: `X-Response-Time-ms`

Exemplo:

```bash
curl -s http://127.0.0.1:8000/health/
curl -s http://127.0.0.1:8000/readyz/
```

## Monitoramento beta

Fonte da verdade:

- `docs/FONTE_DA_VERDADE_MONITORAMENTO_BETA_2026-04-30.md`

Decisao atual:

- Grafana Cloud sera o painel unico do beta.
- Grafana Alloy sera o agente oficial no VPS.
- Sentry nao sera painel principal no beta; `SENTRY_DSN` deve continuar vazio salvo decisao explicita.
- A operacao inicial cobre logs da API/Caddy, metricas basicas da VPS, metricas HTTP/eventos criticos da API em `/metrics/` e telemetria Android enviada pela API.

Estado atual validado em `2026-05-04`:

- Alloy roda no VPS em `/opt/livro-vivo-monitoring`, separado da stack da API.
- Logs da API/Caddy chegam no datasource Loki `grafanacloud-livrovivo-logs`.
- Metricas da API, do Alloy e do VPS chegam no datasource Prometheus `grafanacloud-livrovivo-prom`.
- O dashboard `Livro Vivo Beta Overview` esta importado no Grafana.
- O Admin exibe o atalho `Monitoramento beta` quando `GRAFANA_BETA_DASHBOARD_URL` esta configurado.
- O contact point `Livro Vivo Ops` recebe os alertas do beta.
- 8 alertas iniciais estao ativos e em estado `Normal`: API down, Alloy down, disco baixo, 5xx, logs de erro, p95 alto, memoria baixa e erros Android.
- O alerta `Android telemetry silent` permanece apenas catalogado, sem ativacao padrao, para evitar falso positivo fora de janelas de teste.

Ainda pendente:

- criar Synthetic Monitoring para API, app web, LP e admin;
- instrumentar app web e LP com Grafana Faro/Frontend Observability;
- consolidar dashboard/alertas de custos e cotas;
- definir rotina operacional diaria, escalation e registro de incidentes.

Bootstrap versionado:

- `deploy/monitoring/README.md`
- `deploy/monitoring/GRAFANA_QUERIES.md`
- `deploy/monitoring/dashboards/livro-vivo-beta-overview.json`
- `deploy/monitoring/alerts/livro-vivo-beta-alerts.json`
- `deploy/monitoring/docker-compose.monitoring.example.yml`
- `deploy/monitoring/config.alloy.example`
- `deploy/monitoring/monitoring.env.example`

Bootstrap/reproducao em novo ambiente:

1. criar stack `livro-vivo-beta` no Grafana Cloud;
2. criar Synthetic Monitoring para API, app web, LP e admin;
3. copiar os exemplos de `deploy/monitoring/` para `/opt/livro-vivo-monitoring` no VPS;
4. preencher `/opt/livro-vivo-monitoring/.env` com credenciais reais do Grafana Cloud;
5. subir Alloy com `docker compose up -d`;
6. confirmar logs no Loki, metricas de host e metricas `livro_vivo_api_*` no Grafana.
7. criar alertas beta a partir de `deploy/monitoring/alerts/`.

Cuidados:

- nao versionar credenciais do Grafana Cloud;
- nao habilitar access log bruto do Caddy antes de filtrar query strings;
- nao habilitar `/metrics/` em stage/producao sem `DJANGO_METRICS_BEARER_TOKEN`;
- manter `DJANGO_LOG_STRUCTURED=true` no beta para facilitar queries por `request_id`;
- manter a stack de monitoramento separada da stack da API para que deploys da API nao derrubem o Alloy.

## Operacao minima de homologacao

### Subida minima

```bash
python manage.py migrate
python manage.py check --deploy --fail-level WARNING
python manage.py runserver
```

Checklist minima apos subir:

```bash
curl -i http://127.0.0.1:8000/health/
curl -i http://127.0.0.1:8000/readyz/
```

O esperado e:

- `health/` -> `200`
- `readyz/` -> `200`
- presenca de `X-Request-ID` nas respostas

### Logging util na primeira homologacao

Os fluxos abaixo agora geram logs dedicados:

- `auth_register_success`
- `auth_register_failed`
- `auth_login_failed`
- `auth_login_blocked`
- `auth_login_success`
- `auth_logout_success`
- `me_profile_updated`
- `me_password_changed`
- `me_data_export_generated`
- `me_data_erasure_requested`
- `api_readiness_degraded`
- `api_request_client_error`
- `api_request_failed`
- `api_request_unhandled_exception`

### Dispatch operacional de push

O enqueue de notificacoes tenta autodispatch no request por padrao. Em stage/producao, mantenha tambem um dispatcher recorrente como redundancia operacional:

```bash
python manage.py dispatch_push_notifications --limit 100
```

### Rollback minimo

Procedimento recomendado:

1. voltar a release do app/servico para o artefato anterior;
2. manter o banco no estado atual por padrao;
3. so reverter migration se a migration nova for comprovadamente a causa e tiver rollback seguro;
4. usar `readyz/` e logs por `X-Request-ID` para confirmar recuperacao.

Regra pratica:

- preferir `roll-forward` quando o schema ja tiver sido aplicado;
- usar rollback de banco apenas quando a migration for reversivel e o impacto estiver claro.

## Endpoints principais

### Auth e conta

- `POST /auth/register/`
- `POST /auth/login/`
- `POST /auth/refresh/`
- `POST /auth/logout/`
- `GET /me/`
- `GET /me/entitlements/`
- `GET /me/data-export/`
- `POST /me/data-erasure/`
- `GET /me/notifications/`
- `POST /me/notifications/<dispatch_id>/ack/`
- `POST /me/notifications/in-app/consume-latest/`
- `GET/PATCH /me/notification-preferences/`
- `GET/POST/DELETE /me/push-devices/` com `installation_id` estavel por instalacao para atualizar token push sem criar device duplicado a cada rotacao e expirar backlog push antigo no registro do device atual

### Biblioteca

- `GET /books/`
- `GET /books/<book_id>/versions/`
- `GET /books/<book_id>/current-version/`
- `GET /books/<book_id>/current-version/chapters/`
- `GET /books/<book_id>/current-version/chapters/<chapter_slug>/`
- `GET /books/<book_id>/search/?q=...`
- `GET /search/?q=...&book_id=...`
- `GET /search/?q=...&book_version_id=...`
- `GET /search/global/?q=...`

### Anotacoes

- `GET /annotations/`
- `POST /annotations/`
- `GET /annotations/<id>/`
- `PATCH /annotations/<id>/`
- `DELETE /annotations/<id>/`

Filtros comuns:

- `book_version`
- `chapter_id`
- `chapter_slug`

### Jurisprudencia

- `GET /caselaw/`
- `GET /caselaw/<id>/`

Observacao:

- o CRUD operacional de jurisprudencia hoje fica no Django Admin.

### Curso

- `GET /courses/posts/`
- `GET /courses/posts/<id>/`
- `GET /courses/assets/`
- `GET /courses/assets/<id>/`
- `GET /courses/lives/`
- `GET /courses/lives/<id>/`
- `POST/PATCH/DELETE` dessas rotas para staff

### Banco de Pecas

- `GET /templates-bank/templates/`
- `GET /templates-bank/templates/<id>/`
- `GET /templates-bank/templates/<id>/download-token/`
- `GET /templates-bank/templates/<id>/download/?token=...`
- `POST/PATCH/DELETE /templates-bank/templates/` para staff

### Comunidade

- `GET/POST /community/categories/` (POST staff)
- `GET/POST/PATCH/DELETE /community/posts/`
- `POST /community/posts/<id>/follow/`
- `POST /community/posts/<id>/unfollow/`
- `POST /community/posts/<id>/like/`
- `POST /community/posts/<id>/unlike/`
- `GET /community/posts/<id>/mention-candidates/` (sugestoes para `@mencoes`)
- `GET/POST/PATCH/DELETE /community/comments/`
- `POST /community/comments/<id>/like/`
- `POST /community/comments/<id>/unlike/`
- `POST /community/comments/` aceita `mention_user_ids: number[]` opcional para notificar mencionados
- `POST /community/reports/`
- `GET/PATCH /community/reports/<id>/` (staff)
- `POST /community/reports/<id>/approve/` (staff)
- `POST /community/reports/<id>/remove/` (staff)
- `POST /community/reports/<id>/escalate/` (staff)
- `POST /community/reports/<id>/ban-author/` (staff)

## Admin

```bash
python manage.py createsuperuser
```

Acesso:

- `http://127.0.0.1:8000/admin/`

No admin ja existem fluxos para:

- assinatura/entitlement (incluindo founder)
- edicao de capitulos em rich text e publicacao de versoes/changelog
- jurisprudencia com ementa rich
- curso (`CoursePost`, `CourseAsset`, `LiveEvent`)
- banco de pecas com upload/URL remota e metadados
- moderacao da comunidade com fila, acoes e trilha
- status/eventos de moderacao de usuario
- preferencias, eventos, dispatches e devices de notificacao

Auditoria funcional (A1-01 / UX-A1.1):

- documento: `docs/ADMIN_AUDITORIA_FUNCIONAL_A1-01_2026-03-09.md`
- conteudo: inventario de telas/fluxos, friccoes por severidade e backlog priorizado para A1-02/A1-03

Norteador UX do Admin para operacao juridica (nao-tech):

- principios: `docs/ADMIN_PRINCIPIOS_UX_OPERACAO_JURIDICA_2026-03-09.md`
- proposta inicial A1-02: `docs/ADMIN_PROPOSTA_ARQUITETURA_A1-02_2026-03-09.md`
- implementacao A1-02: menu do admin agrupado por jornada operacional + atalhos de fila critica (`config/admin_navigation.py`)

## Limites conhecidos

- A busca global cobre biblioteca, curso, banco de pecas, jurisprudencia e comunidade, respeitando gating por tier.
- `NOTIFICATIONS_PUSH_PROVIDER` continua `noop` por padrao em dev; FCM/APNs seguem dependentes da configuracao de deploy.
- Para uploads protegidos do Banco de Pecas em producao, a configuracao recomendada continua sendo object storage S3-compativel.
- O gate da LP para APK Android e operacional, nao seguranca forte; o link do APK deve ser rotacionado antes de expirar.

## CI

Workflow API (`.github/workflows/ci.yml`) executa:

- testes unitarios
- coverage com threshold minimo
- check de migrations
- smoke em Postgres real
- `check --deploy` com ambiente de producao simulado

## Backlog atual

As pendencias do ciclo atual estao em:

- `../docs/BACKLOG_EXECUTAVEL_2026-03-09.md`
