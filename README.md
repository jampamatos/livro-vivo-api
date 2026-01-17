# Livro Vivo API

Backend do app **Livro Vivo**.

- **Framework:** Django + Django REST Framework  
- **Banco:** PostgreSQL  
- **Config:** `.env` + `DATABASE_URL`

> **RDS (Request-Driven Scaffolding):** só adicionamos estrutura quando um Byte exigir.  
> Este repositório está em fase MVP inicial (auth + entitlements + health/admin).

---

## Stack

- Django
- Django REST Framework (DRF)
- PostgreSQL
- `python-dotenv` (carrega `.env`)
- `dj-database-url` (lê `DATABASE_URL`)
- `TokenAuthentication` (DRF) para o MVP

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
```

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

- `DJANGO_SECRET_KEY` (obrigatório no deploy; no dev pode ser simples)
- `DEBUG` (`true`/`false`)
- `DATABASE_URL` (Postgres)
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

## Troubleshooting (Postgres)

### Verificar se o Postgres está rodando

```bash
pg_isready
```

### Ver cluster ativo e porta

```bash
pg_lsclusters
```

### Onde fica o `pg_hba.conf`

Geralmente:
`/etc/postgresql/<versao>/main/pg_hba.conf`

Se você precisar que o usuário Linux `postgres` consiga entrar no DB sem senha (dev local), as regras úteis são:

```conf
local   all   postgres   peer
local   all   all       scram-sha-256
```

Depois de alterar o arquivo:

```bash
sudo systemctl restart postgresql@<versao>-main
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

---

## Endpoints (MVP)

### Health

- `GET /health/`: `{ "status": "ok", "version": "dev" }`

### Auth (Token)

- `POST /auth/register/`: cria usuário e retorna token
- `POST /auth/login/`: retorna token

Header para endpoints autenticados:

- `Authorization: Token <seu_token>`

### Me

- `GET /me/`: dados do usuário autenticado
- `GET /me/entitlements/`: lista de entitlements do usuário autenticado

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

### 3) /me (com token)

```basg
TOKEN="COLE_O_TOKEN_AQUI"
curl -s http://127.0.0.1:8000/me/ \
  -H "Authorization: Token $TOKEN" && echo
```

### 4) /me/entitlements (com token)

```bash
TOKEN="COLE_O_TOKEN_AQUI"
curl -s http://127.0.0.1:8000/me/entitlements/ \
  -H "Authorization: Token $TOKEN" && echo
```

---

## Notas de desenvolvimento

- Por padrão, endpoints DRF exigem autenticação (Token).
- `register` e `login` são públicos.
- A autorização (o “que você pode acessar”) será baseada em entitlements.
