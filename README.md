# Livro Vivo API

Backend Django/DRF do app Livro Vivo.

## Estado atual

Implementado e ativo em `main`:

- Auth JWT (`register`, `login`, `refresh`, `logout`).
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
- Hardening de avatar com validacao de formato/MIME, limite de tamanho, limite de dimensoes e recorte seguro.

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
- `DJANGO_ALLOWED_HOSTS`: obrigatoria em stage/prod
- `DJANGO_CORS_ALLOWED_ORIGINS`: obrigatoria em stage/prod
- `DJANGO_CSRF_TRUSTED_ORIGINS`: obrigatoria em stage/prod
- `APP_VERSION`: versao exibida em health/readiness
- `REDIS_URL`: opcional (cache/throttle distribuido)
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

Banco de Pecas:

- `TEMPLATES_BANK_DOWNLOAD_TOKEN_MAX_AGE_SECONDS`
- `TEMPLATES_BANK_REMOTE_FILE_FETCH_TIMEOUT_SECONDS`
- `TEMPLATES_BANK_REMOTE_FILE_MAX_BYTES`

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
- `*_storage_alias`
- `*_storage_backend`
- `*_storage_key`
- `*_cache_control`

Politica minima recomendada:

- avatar: `public, max-age=86400, stale-while-revalidate=604800`
- uploads protegidos: `private, max-age=300, no-store`

Migracao recomendada para object storage:

1. configurar bucket e credenciais S3 compativeis;
2. subir com `DJANGO_STORAGE_PROVIDER=s3`;
3. manter URLs remotas historicas onde elas ja existirem;
4. migrar uploads locais existentes para o bucket e preservar `name/key`;
5. validar `health/`, `readyz/` e payloads com `storage_key` antes de abrir trafego.

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

## Qualidade local

### Testes

```bash
python manage.py test
```

### Sem migrations pendentes

```bash
python manage.py makemigrations --check --dry-run
```

### Check de deploy (simulacao)

```bash
DJANGO_ENV=production \
DEBUG=false \
DJANGO_SECRET_KEY=ci-production-secret-key-with-minimum-length-1234567890 \
DJANGO_ALLOWED_HOSTS=api.example.com \
DJANGO_CORS_ALLOWED_ORIGINS=https://app.example.com \
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com \
DATABASE_URL=sqlite:///./tmp-prod-check.sqlite3 \
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
- `GET/POST/DELETE /me/push-devices/`

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

- A busca global atual cobre biblioteca, jurisprudencia e comunidade; cursos e banco de pecas ainda nao entram nesse agregador.
- `NOTIFICATIONS_PUSH_PROVIDER` continua `noop` por padrao em dev; FCM/APNs seguem dependentes da configuracao de deploy.
- Para uploads protegidos do Banco de Pecas em producao, a configuracao recomendada continua sendo object storage S3-compativel.

## CI

Workflow API (`.github/workflows/ci.yml`) executa:

- testes unitarios
- check de migrations
- smoke em Postgres real
- `check --deploy` com ambiente de producao simulado

## Backlog atual

As pendencias do ciclo atual estao em:

- `../docs/BACKLOG_EXECUTAVEL_2026-03-09.md`
