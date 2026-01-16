# Livro Vivo API

Backend do app “Livro Vivo” (Django + PostgreSQL).

> Nota (RDS): seguimos Request-Driven Scaffolding — só adicionamos estrutura quando um Byte exigir.

## Stack

- Django
- PostgreSQL
- Config por `DATABASE_URL` (via `.env`)

## Requisitos

- Python (venv)
- PostgreSQL rodando local

## Setup local

### 1) Ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
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

- `DJANGO_SECRET_KEY`
- `DEBUG`
- `DATABASE_URL`
- `APP_VERSION` (usada no `/health`)

### 4) Banco de dados (Postgres)

Exemplo de setup local (cria user e database livro_vivo):

```bash
# cria role (se não existir)
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='livro_vivo'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE livro_vivo LOGIN PASSWORD 'livro_vivo';"

# cria db (se não existir)
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='livro_vivo'" | grep -q 1 || \
  sudo -u postgres createdb -O livro_vivo livro_vivo
```

E no `.env`:

```env
DATABASE_URL=postgresql://livro_vivo:livro_vivo@localhost:5432/livro_vivo
```

### 5) Migrations

```bash
python manage.py migrate
```

### 6) Rodar servidor

```bash
python manage.py runserver
```

## Healthcheck

Com o servidor rodando, teste:

```bash
curl -s http://127.0.0.1:8000/health/ && echo
```

Resposta esperada (exemplo):

```json
{"status":"ok","version":"dev"}
```

## Admin (Django)

Criar superuser:

```bash
python manage.py createsuperuser
```

Acessar:

`http://127.0.0.1:8000/admin/`

> Importante: **não coloque usuário/senha de superuser no README** (só o procedimento).
