# Monitoramento beta no VPS

Estes arquivos iniciam as Fases 1 a 3 do monitoramento beta com Grafana Cloud e Grafana Alloy.

O objetivo deste pacote e coletar:

- logs Docker da stack `livro-vivo-api`;
- logs emitidos pela API em JSON quando `DJANGO_LOG_STRUCTURED=true`;
- logs operacionais do Caddy disponiveis no stdout do container;
- metricas basicas da VPS via exporter Unix: CPU, memoria, disco, rede e filesystem.
- metricas HTTP da API quando `DJANGO_METRICS_ENABLED=true`;
- metricas de eventos criticos da API quando os fluxos instrumentados forem acionados.

Nao ha segredo versionado aqui. Credenciais reais do Grafana Cloud ficam somente no VPS.

## 1. Criar recursos no Grafana Cloud

Criar ou selecionar a stack `livro-vivo-beta`.

No Grafana Cloud, obter:

- Loki URL;
- Loki user/instance id;
- token com permissao de escrita em logs;
- Prometheus remote_write URL;
- Prometheus user/instance id;
- token com permissao de escrita em metricas.

Criar tambem os Synthetic Monitoring checks definidos em `docs/FONTE_DA_VERDADE_MONITORAMENTO_BETA_2026-04-30.md`:

- API health: `GET https://api-178-104-197-8.nip.io/health/`
- API readiness: `GET https://api-178-104-197-8.nip.io/readyz/`
- App web home: `GET https://livro-vivo-app.jampa-matos.workers.dev/`
- LP home: `GET https://livro-vivo-lp.jampa-matos.workers.dev/`
- Django admin: `GET https://api-178-104-197-8.nip.io/admin/`

## 2. Preparar arquivos no VPS

No servidor:

```bash
ssh livro-vivo
mkdir -p /opt/livro-vivo-monitoring
cd /opt/livro-vivo-api
cp deploy/monitoring/docker-compose.monitoring.example.yml /opt/livro-vivo-monitoring/docker-compose.yml
cp deploy/monitoring/config.alloy.example /opt/livro-vivo-monitoring/config.alloy
cp deploy/monitoring/monitoring.env.example /opt/livro-vivo-monitoring/.env
chmod 600 /opt/livro-vivo-monitoring/.env
```

Editar `/opt/livro-vivo-monitoring/.env` com os valores reais do Grafana Cloud.

Para habilitar metricas da API, definir tambem:

- `DJANGO_METRICS_ENABLED=true` no `.env` da API;
- `DJANGO_METRICS_BEARER_TOKEN=<token-forte>` no `.env` da API;
- `LIVRO_VIVO_API_METRICS_BEARER_TOKEN=<mesmo-token>` no `.env` do monitoramento.

Confirmar o nome do projeto Docker Compose da API:

```bash
cd /opt/livro-vivo-api
docker compose ls
```

Se o nome nao for `livro-vivo-api`, ajustar `MONITORED_DOCKER_COMPOSE_PROJECT` no `.env` do monitoramento.

## 3. Subir Alloy

```bash
cd /opt/livro-vivo-monitoring
docker compose up -d
docker compose ps
docker compose logs alloy --tail 100
```

O esperado:

- container `alloy` rodando;
- logs sem erro de autenticacao no Grafana Cloud;
- logs da API/Caddy aparecendo no Loki;
- metricas de host aparecendo no Grafana Cloud.
- metricas `livro_vivo_api_http_requests_total` e `livro_vivo_api_http_request_duration_seconds` aparecendo no Grafana Cloud quando `/metrics/` estiver habilitado.
- metrica `livro_vivo_api_domain_events_total` aparecendo no Grafana Cloud depois de login, aceite legal, reset de senha ou download de peca.

## 3.1. Validar Compose localmente

No repo, sem usar segredos reais:

```bash
MONITORING_ENV_FILE=monitoring.env.example docker compose -f deploy/monitoring/docker-compose.monitoring.example.yml --env-file deploy/monitoring/monitoring.env.example config
```

Em producao, o Compose usa `.env` por padrao.

## 4. Backup operacional dos segredos

Depois de validar o envio:

```bash
mkdir -p /root/bootstrap-secrets
cp /opt/livro-vivo-monitoring/.env /root/bootstrap-secrets/livro-vivo-monitoring.env.bootstrap
chmod 600 /root/bootstrap-secrets/livro-vivo-monitoring.env.bootstrap
```

## 5. Cuidados

- Nao habilitar access log bruto do Caddy antes de filtrar query strings, porque alguns fluxos usam tokens temporarios em URL.
- Manter `SENTRY_DSN` vazio salvo decisao explicita.
- Preferir `DJANGO_LOG_STRUCTURED=true` e `DJANGO_LOG_PROFILE=prod` no beta para facilitar queries no Loki.
- O deploy da API nao deve controlar o ciclo de vida do Alloy; a stack de monitoramento fica em `/opt/livro-vivo-monitoring`.
