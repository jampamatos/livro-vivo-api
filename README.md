# Livro Vivo API

Backend Django/DRF do app Livro Vivo.

## Estado atual

Implementado e ativo em `main`:

- Auth JWT (`register`, `login`, `refresh`, `logout`).
- Entitlements por assinatura (`essential` / `professional`) com suporte a founder.
- Biblioteca chapter-first (`Book`, `BookVersion`, `BookChapter`) sem dependencia de PDF.
- Busca por capitulo com FTS no Postgres e snippets por ocorrencia.
- Anotacoes por capitulo com `selector + offsets`.
- Jurisprudencia com `ementa_rich`, `ementa_plain`, `anchors` e tags.
- Comunidade (categorias, posts, comentarios, reports).
- Preferencias de notificacao por usuario e evento de publicacao de versao.
- Health/readiness, rate limiting, CI e checks de seguranca de configuracao.

## Stack

- Python 3.12+
- Django 5
- Django REST Framework
- PostgreSQL (dev/prod)
- `djangorestframework-simplejwt`
- `django-cors-headers`
- `django-tinymce`
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

Notificacoes (base pronta):

- `NOTIFICATIONS_ENABLED`
- `NOTIFICATIONS_PUSH_PROVIDER` (`noop` por padrao)
- `NOTIFICATIONS_FCM_PROJECT_ID`
- `NOTIFICATIONS_APNS_TOPIC`

### 4) Banco e migrations

```bash
python manage.py migrate
```

### 5) Rodar servidor

```bash
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
DJANGO_SECRET_KEY=change-me \
DJANGO_ALLOWED_HOSTS=api.example.com \
DJANGO_CORS_ALLOWED_ORIGINS=https://app.example.com \
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com \
DATABASE_URL=sqlite:///./tmp-prod-check.sqlite3 \
python manage.py check --deploy --fail-level WARNING
```

## Health e readiness

- `GET /health/` (e alias `/healthz/`)
- `GET /readyz/`

Exemplo:

```bash
curl -s http://127.0.0.1:8000/health/
curl -s http://127.0.0.1:8000/readyz/
```

## Endpoints principais

### Auth e conta

- `POST /auth/register/`
- `POST /auth/login/`
- `POST /auth/refresh/`
- `POST /auth/logout/`
- `GET /me/`
- `GET /me/entitlements/`
- `GET /me/notification-preferences/`
- `PATCH /me/notification-preferences/`

### Biblioteca (chapter-first)

- `GET /books/`
- `GET /books/<book_id>/versions/`
- `GET /books/<book_id>/current-version/`
- `GET /books/<book_id>/current-version/chapters/`
- `GET /books/<book_id>/current-version/chapters/<chapter_slug>/`

Busca:

- `GET /books/<book_id>/search/?q=...`
- `GET /search/?q=...&book_id=...`
- `GET /search/?q=...&book_version_id=...`

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
- `POST /caselaw/` (staff)
- `GET /caselaw/<id>/`
- `PATCH /caselaw/<id>/` (staff)
- `DELETE /caselaw/<id>/` (staff)

### Comunidade

- `GET/POST /community/categories/` (POST staff)
- `GET/POST /community/posts/`
- `GET/POST /community/comments/`
- `POST /community/reports/`
- `GET/PATCH /community/reports/<id>/` (staff)

## Admin

```bash
python manage.py createsuperuser
```

Acesso:

- `http://127.0.0.1:8000/admin/`

No admin ja existem fluxos para:

- assinatura/entitlement (incluindo founder)
- edicao de capitulos em rich text (TinyMCE)
- clonagem/publicacao de novas versoes com changelog
- jurisprudencia com ementa rich
- moderacao basica da comunidade

## CI

Workflow API (`.github/workflows/ci.yml`) executa:

- testes unitarios
- check de migrations
- smoke em Postgres real
- `check --deploy` com ambiente de producao simulado

## Proximos epics (pre-deploy)

O backlog de pendencias pre-deploy esta em:

- `docs/BACKLOG_EXECUTAVEL_2026-02-22.md`

Fora do estado atual: Curso (B9), Banco de Pecas (B10), moderacao operacional avancada,
notificacoes expandidas e busca unificada cross-modulo.
