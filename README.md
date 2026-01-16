# Livro Vivo API

## Requisitos

- Python
- Postgres

## Rodar local

> Nota (RDS): este repositório ainda está no “casco” do Epic 0.  
> Assim que inicializarmos o Django (B1.1/B1.2), os comandos abaixo viram “oficiais”.

### 1) Criar ambiente virtual

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2) Configurar variáveis de ambiente

```bash
cp .env.example .env
# edite o .env e preencha DJANGO_SECRET_KEY e DATABASE_URL
```

### 3) Instalar dependências (quando existirem)

```bash
# (Depois do B1.1) teremos requirements.txt ou equivalente
pip install -r requirements.txt
```

### 4) Rodar a API (depois do B1.1)

```bash
python manage.py migrate
python manage.py runserver
```
