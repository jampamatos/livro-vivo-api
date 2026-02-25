# Livro Vivo API

Backend do app **Livro Vivo**.

- **Framework:** Django + Django REST Framework  
- **Banco:** PostgreSQL  
- **Config:** `.env` + `DATABASE_URL`

> Este repositório está em fase MVP inicial (auth + entitlements + biblioteca + leitor/busca + anotações + jurisprudência v0 + comunidade).

---

## Stack

- Django
- Django REST Framework (DRF)
- PostgreSQL
- `python-dotenv` (carrega `.env`)
- `dj-database-url` (lê `DATABASE_URL`)
- `JWTAuthentication` (SimpleJWT, access/refresh)
- cache configurável (LocMem em dev/test, Redis via `REDIS_URL` em stage/prod)
- `PyMuPDF` (extração de texto por página do PDF)

---

## Requisitos

- Python 3.x (venv)
- PostgreSQL rodando localmente

---

## Setup local

### 1) Ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
````

### 2) Instalar dependências

```bash
pip install -r requirements.txt
```

### 3) Variáveis de ambiente

Crie um `.env` (não commitar):

```bash
cp .env.example .env
```

Variáveis esperadas:

- `DJANGO_ENV` (`development`, `stage`, `production`)
- `DJANGO_SECRET_KEY` (obrigatório em `stage/production`)
- `DEBUG` (`true`/`false`)
- `DATABASE_URL` (Postgres)
- `REDIS_URL` (opcional; recomendado para stage/prod e rate limit distribuído)
- `DJANGO_CACHE_TIMEOUT_SECONDS` (TTL padrão de cache/throttle)
- `DJANGO_ALLOWED_HOSTS` (obrigatório em `stage/production`)
- `DJANGO_CORS_ALLOWED_ORIGINS` (CSV de origins permitidos)
- `APP_VERSION` (aparece no `/health`)

Exemplo `DATABASE_URL` local:

```env
DATABASE_URL=postgresql://livro_vivo:livro_vivo@localhost:5432/livro_vivo
```

### 4) Banco de dados (Postgres)

Cria role e database `livro_vivo` (idempotente):

```bash
# cria role (se não existir)
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='livro_vivo'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE livro_vivo LOGIN PASSWORD 'livro_vivo';"

# cria db (se não existir)
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='livro_vivo'" | grep -q 1 || \
  sudo -u postgres createdb -O livro_vivo livro_vivo
```

Teste de conexão:

```bash
psql "postgresql://livro_vivo:livro_vivo@localhost:5432/livro_vivo" -c "SELECT 1;"
```

### 5) Migrations

```bash
python manage.py migrate
```

### 6) Rodar servidor

```bash
python manage.py runserver
```

---

## Healthcheck

Com o servidor rodando:

```bash
curl -s http://127.0.0.1:8000/health/ && echo
```

Resposta esperada (exemplo):

```bash
{"status":"ok","version":"dev"}
```

---

## Admin (Django)

Criar superuser:

```bash
python manage.py createsuperuser
```

Acessar: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

### Capítulos nativos (BookVersion/BookChapter)

No admin, cada `BookVersion` possui capítulos (`BookChapter`) com:

- `order` (ordem de leitura)
- `slug` (rota estável)
- `content_rich` (HTML sanitizado)
- `content_plain` (texto para busca)

### Jurisprudência

No MVP, a base de jurisprudência é gerenciada via Django Admin (CRUD), e o app consome via API (listagem + busca).

---

## Plano de migração PDF -> texto nativo (E3-02)

Objetivo: migrar de leitura por PDF/página para leitura por capítulos sem downtime e sem quebrar o app atual.

### Estratégia de rollout por feature flag

- `BOOK_CONTENT_MODE` (backend): `pdf` | `hybrid` | `chapters` (default recomendado: `pdf`).
- `EXPO_PUBLIC_BOOK_CONTENT_MODE` (app): `pdf` | `hybrid` | `chapters` (default recomendado: `pdf`).

Contrato de compatibilidade:

- `pdf`: mantém comportamento atual (somente endpoints legados de PDF/página).
- `hybrid`: mantém endpoints legados + habilita fluxo chapter-first.
- `chapters`: chapter-first como padrão; legado fica desativado por flag para usuário final.

### Sequência reproduzível em staging

1. Aplicar schema novo sem ativar flags:

```bash
python manage.py migrate
```

2. Popular capítulos em versões-alvo via admin (`BookVersion` + `BookChapter`) e validar:
   - `slug` único por versão
   - `order` único por versão
   - `content_plain` gerado automaticamente

3. Ativar backend em `hybrid` e executar smoke test:
   - endpoints legados continuam funcionais (`/books/:id/versions`, `/books/:id/search`, download PDF etc.)
   - endpoints chapter-first passam a responder (quando disponíveis na fase de API chapter-first)

4. Ativar app em `hybrid` e validar fallback:
   - livro com capítulos: abre reader chapter-first
   - livro sem capítulos: fallback para reader PDF legado

5. Após validação do lote beta founder, promover para `chapters`.

### Rollback operacional

- Rollback rápido (sem downtime): voltar flags backend/app para `pdf`.
- Rollback de deploy: reverter release da API/app sem reverter migrations do banco.
- Dados de capítulos permanecem intactos; novo cutover depende apenas de reativar `hybrid`/`chapters`.

---

## Endpoints (MVP)

### Health

- `GET /health/`: `{ "status": "ok", "version": "dev" }`

### Auth (JWT)

- `POST /auth/register/`: cria usuário e retorna sessão (`access` + `refresh`)
- `POST /auth/login/`: retorna sessão (`access` + `refresh`)
- `POST /auth/refresh/`: renova o `access` (e pode rotacionar `refresh`)
- `POST /auth/logout/`: invalida `refresh` (blacklist)

Header para endpoints autenticados:

- `Authorization: Bearer <seu_access_token>`

### Me

- `GET /me/`: dados do usuário autenticado
- `GET /me/entitlements/`: lista de entitlements do usuário autenticado

### Biblioteca (requer Entitlement ativo)

- `GET /books/`: lista livros (para usuários não-staff, normalmente apenas `published`)
- `GET /books/<book_id>/versions/`: lista versões do livro (também para usuários não-staff apenas `published`)
- `GET /search/?q=<termo>&book_version_id=<id>`: busca simples por termo nas páginas (retorna page_number + snippet)
  - também disponível por livro: `GET /books/<book_id>/search/?q=<termo>`

  - params: `q` (mín. 2 chars), `book_version_id` **ou** `book_id`, `limit` (1–100), `offset` (>=0)
- `GET /books/<book_id>/versions/<version_id>/pages/<page_number>/`: retorna o texto completo da página

> Importante (visibilidade): usuários não-staff normalmente só acessam conteúdo `published` (Book e BookVersion).
> Para testar drafts, use um token de usuário `is_staff=true` ou publique o Book/BookVersion.

### Download protegido do PDF (requer Entitlement ativo)

- `GET /books/<book_id>/versions/<version_id>/download-url/`: retorna `{"url": "<...>}`
- `GET /books/<book_id>/versions/<version_id>/download/`: baixa o PDF (Content-Disposition: attachment)

### Anotações (Destaques/Notas)

- `GET /annotations/?book_version=<id>&page_number=<n>`: lista (do usuário)
- `POST /annotations/`: cria anotação (do usuário)

### Jurisprudência (CaseLaw)

- `GET /caselaw/`: lista/pesquisa jurisprudências

  - querystring:

    - `q` (opcional): termo de busca (ex.: "bagagem")
    - `limit` / `offset` (paginação, quando aplicável)

Resposta típica:

```json
{
  "q": "bagagem",
  "count": 0,
  "limit": 20,
  "offset": 0,
  "results": []
}
```

### Comunidade (requer auth)

Categorias:

- `GET /community/categories/`: lista categorias (auth)
- `POST /community/categories/`: cria categoria (staff)

Posts:

- `GET /community/posts/`: lista posts (auth)
  - filtro: `?category=<id>`
- `POST /community/posts/`: cria post (auth)
- `PATCH /community/posts/<id>/`: autor ou staff
- `DELETE /community/posts/<id>/`: autor ou staff

Comentários:

- `GET /community/comments/?post=<id>`: lista comentários de um post (auth)
- `POST /community/comments/`: cria comentário (auth)
- `PATCH /community/comments/<id>/`: autor ou staff
- `DELETE /community/comments/<id>/`: autor ou staff

Denúncias (reports):

- `POST /community/reports/`: cria denúncia (auth)
  - body: `post_id` **ou** `comment_id` (exatamente um)
- `GET /community/reports/`: lista denúncias (staff)
- `PATCH /community/reports/<id>/`: atualiza status (staff)

---

## Exemplos (curl)

### 1) Register

```bash
curl -s -X POST http://127.0.0.1:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"teste@exemplo.com","password":"12345678","name":"Teste","profession":"Advogado"}' && echo
```

### 2) Login

```bash
curl -s -X POST http://127.0.0.1:8000/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"teste@exemplo.com","password":"12345678"}' && echo
```

### 3) /me (com access token)

```bash
ACCESS_TOKEN="COLE_O_ACCESS_TOKEN_AQUI"
curl -s http://127.0.0.1:8000/me/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" && echo
```

### 4) /me/entitlements (com access token)

```bash
ACCESS_TOKEN="COLE_O_ACCESS_TOKEN_AQUI"
curl -s http://127.0.0.1:8000/me/entitlements/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" && echo
```

### 5) Ler versão atual + capítulos (chapter-first)

```bash
ACCESS_TOKEN="<seu_access_token>"

curl -s http://127.0.0.1:8000/books/1/current-version/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq

curl -s http://127.0.0.1:8000/books/1/current-version/chapters/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq

curl -s http://127.0.0.1:8000/books/1/current-version/chapters/<chapter-slug>/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq
```

### 6) Buscar termo em páginas (Search)

```bash
ACCESS_TOKEN="<seu_access_token>"

curl -s "http://127.0.0.1:8000/search/?q=duergar&book_version_id=1" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq
```

### 7) Jurisprudência (CaseLaw)

```bash
ACCESS_TOKEN="<seu_access_token>"

curl -s "http://127.0.0.1:8000/caselaw/?q=bagagem" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq
```

---

## Acesso ao livro (Entitlements)

Alguns endpoints do livro exigem que o usuário possua um entitlement ativo:

- `product=book` (ou `subscription`, quando aplicável)
- `status=active`
- `expires_at` nulo ou no futuro

Caso contrário, o endpoint responde:

- `403 Forbidden` com mensagem de acesso negado.

## Notas de desenvolvimento

- Por padrão, endpoints DRF exigem autenticação JWT (`Bearer`).
- `register`, `login` e `refresh` são públicos; `logout` exige usuário autenticado.
- A autorização (o “que você pode acessar”) será baseada em entitlements.
- `/search/` usa FTS (Postgres) com fallback controlado para SQLite.
- Jurisprudência v0: vínculo por âncora/trecho e alertas por tema entram depois (Gate JIT).
- CI mínimo de qualidade está em `.github/workflows/ci.yml` (testes + `check --deploy`).
