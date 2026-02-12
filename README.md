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

### Upload de PDF (BookVersion)

No admin, em uma `BookVersion`, você pode anexar um PDF.
Em dev, esse arquivo é salvo em:

- `media/books/<book_id>/versions/<version>/<filename>`

> Importante: a pasta `media/` **não deve** ser commitada (contém PDFs reais).

### Jurisprudência

No MVP, a base de jurisprudência é gerenciada via Django Admin (CRUD), e o app consome via API (listagem + busca).

---

## Ingestão de texto do PDF (PageText)

Para habilitar busca e leitura por página, o backend extrai o texto do PDF e salva no banco (uma linha por página).

### Command: extrair texto por página

Após anexar o PDF em uma `BookVersion` no admin:

```bash
python manage.py extract_pdf_text --book-version-id <version_id> --force
```

- `--force:` remove os `PageText` existentes daquela versão e reprocessa tudo.

> Nota: o texto pode conter quebras de linha `\n` (normal em JSON). A UI decide como renderizar.

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

### 5) Baixar PDF

```bash
ACCESS_TOKEN="<seu_access_token>"

URL="$(
  curl -s http://127.0.0.1:8000/books/1/versions/1/download-url/ \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
  | jq -r .url
)"

curl -L -o /tmp/livro.pdf "$URL"
file /tmp/livro.pdf
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
- `/search/` usa busca simples (`icontains`) no MVP; a implementação pode evoluir para FTS no Postgres sem mudar o contrato do endpoint.
- O comando `extract_pdf_text` é manual no MVP (sem jobs/filas).
- Jurisprudência v0: vínculo por âncora/trecho e alertas por tema entram depois (Gate JIT).
- CI mínimo de qualidade está em `.github/workflows/ci.yml` (testes + `check --deploy`).
