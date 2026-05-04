# Monitoramento beta no VPS

Estes arquivos iniciam as Fases 1 a 3 do monitoramento beta com Grafana Cloud e Grafana Alloy.

O objetivo deste pacote e coletar:

- logs Docker da stack `livro-vivo-api`;
- logs emitidos pela API em JSON quando `DJANGO_LOG_STRUCTURED=true`;
- logs operacionais do Caddy disponiveis no stdout do container;
- metricas basicas da VPS via exporter Unix: CPU, memoria, disco, rede e filesystem;
- metricas internas do proprio Alloy para saber se o agente esta vivo;
- metricas HTTP da API quando `DJANGO_METRICS_ENABLED=true`;
- metricas de eventos criticos da API quando os fluxos instrumentados forem acionados.

Nao ha segredo versionado aqui. Credenciais reais do Grafana Cloud ficam somente no VPS.

## Estado esperado antes desta fase

No VPS da API:

- `/opt/livro-vivo-api/.env` tem `DJANGO_METRICS_ENABLED=true`;
- `/opt/livro-vivo-api/.env` tem `DJANGO_METRICS_BEARER_TOKEN=<token-forte>`;
- `docker compose up -d --force-recreate api` ja foi executado depois de alterar o `.env`;
- `docker compose ps` mostra o servico `api` como `healthy`;
- `curl` autenticado para `/metrics/` retorna metricas `livro_vivo_api_*`.

Se o token de metricas foi exposto em chat, ticket ou terminal compartilhado, rotacionar antes de configurar o Alloy.

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
ssh root@<ip-ou-host-do-vps>
mkdir -p /opt/livro-vivo-monitoring
cd /opt/livro-vivo-api
cp deploy/monitoring/docker-compose.monitoring.example.yml /opt/livro-vivo-monitoring/docker-compose.yml
cp deploy/monitoring/config.alloy.example /opt/livro-vivo-monitoring/config.alloy
cp deploy/monitoring/monitoring.env.example /opt/livro-vivo-monitoring/.env
chmod 600 /opt/livro-vivo-monitoring/.env
```

Editar `/opt/livro-vivo-monitoring/.env` com os valores reais do Grafana Cloud.

Campos que precisam ser preenchidos:

- `GRAFANA_CLOUD_LOKI_URL`
- `GRAFANA_CLOUD_LOKI_USERNAME`
- `GRAFANA_CLOUD_LOKI_PASSWORD`
- `GRAFANA_CLOUD_PROMETHEUS_REMOTE_WRITE_URL`
- `GRAFANA_CLOUD_PROMETHEUS_USERNAME`
- `GRAFANA_CLOUD_PROMETHEUS_PASSWORD`
- `LIVRO_VIVO_API_METRICS_BEARER_TOKEN`

Para metricas da API, manter o mesmo token nos dois lugares:

- `DJANGO_METRICS_ENABLED=true` no `.env` da API;
- `DJANGO_METRICS_BEARER_TOKEN=<token-forte>` no `.env` da API;
- `LIVRO_VIVO_API_METRICS_BEARER_TOKEN=<mesmo-token>` no `.env` do monitoramento.

Confirmar o nome do projeto Docker Compose da API:

```bash
cd /opt/livro-vivo-api
docker compose ls
```

Se o nome nao for `livro-vivo-api`, ajustar `MONITORED_DOCKER_COMPOSE_PROJECT` no `.env` do monitoramento.

Confirmar tambem os nomes dos servicos:

```bash
docker compose ps
```

Por padrao, o Alloy envia logs apenas dos servicos `api` e `caddy`:

```env
MONITORED_DOCKER_COMPOSE_SERVICE_REGEX=api|caddy
```

Se for necessario investigar banco/cache em algum incidente, trocar temporariamente para:

```env
MONITORED_DOCKER_COMPOSE_SERVICE_REGEX=api|caddy|postgres|redis
```

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
- metricas de host aparecendo no Grafana Cloud;
- metricas internas do Alloy aparecendo no Grafana Cloud;
- metricas `livro_vivo_api_http_requests_total` e `livro_vivo_api_http_request_duration_seconds` aparecendo no Grafana Cloud quando `/metrics/` estiver habilitado.
- metrica `livro_vivo_api_domain_events_total` aparecendo no Grafana Cloud depois de login, aceite legal, reset de senha ou download de peca.

## 3.1. Importar dashboard beta

Depois de validar metricas e logs no Explore, importar o dashboard versionado:

```text
deploy/monitoring/dashboards/livro-vivo-beta-overview.json
```

No Grafana Cloud:

1. abrir `Dashboards`;
2. clicar em `New` > `Import`;
3. escolher `Upload dashboard JSON file`;
4. selecionar `livro-vivo-beta-overview.json`;
5. mapear `DS_PROMETHEUS` para `grafanacloud-livrovivo-prom`;
6. mapear `DS_LOKI` para `grafanacloud-livrovivo-logs`;
7. clicar em `Import`.

O dashboard esperado chama `Livro Vivo Beta Overview` e concentra:

- saude da API e do Alloy;
- volume HTTP, status e latencia da API;
- telemetria Android;
- eventos criticos de login, legal, e-mail e templates;
- logs recentes da API e Caddy.

## 3.2. Validar Alloy no VPS

O painel HTTP do Alloy fica exposto apenas no localhost do VPS:

```bash
curl -s http://127.0.0.1:12345/-/ready
curl -s http://127.0.0.1:12345/-/healthy
```

O esperado:

```text
Alloy is ready.
All Alloy components are healthy.
```

Ver tambem metricas internas do Alloy:

```bash
curl -s http://127.0.0.1:12345/metrics | grep -E "alloy_build_info|alloy_component_controller_running_components"
```

Se aparecer erro de autenticacao nos logs do Alloy, revisar usuarios/tokens de Loki e Prometheus no `.env` do monitoramento.

## 3.3. Validar API metrics antes do Grafana

Antes de procurar no Grafana, confirmar no proprio VPS que a API ainda responde metricas:

```bash
curl -s -H "Authorization: Bearer <DJANGO_METRICS_BEARER_TOKEN>" \
  https://api-178-104-197-8.nip.io/metrics/ \
  | grep -E "livro_vivo_api_http_requests_total|livro_vivo_api_domain_events_total"
```

Depois de usar o app Android beta:

```bash
curl -s -H "Authorization: Bearer <DJANGO_METRICS_BEARER_TOKEN>" \
  https://api-178-104-197-8.nip.io/metrics/ \
  | grep -E "client_telemetry_event|screen_view|chapter_open|login_success|template_download"
```

## 3.4. Validar Compose localmente

No repo, sem usar segredos reais:

```bash
MONITORING_ENV_FILE=monitoring.env.example docker compose -f deploy/monitoring/docker-compose.monitoring.example.yml --env-file deploy/monitoring/monitoring.env.example config
```

Em producao, o Compose usa `.env` por padrao.

Se a imagem `grafana/alloy` ja estiver disponivel localmente ou puder ser baixada, validar a sintaxe do Alloy com:

```bash
docker run --rm \
  --env GRAFANA_CLOUD_ENVIRONMENT=beta \
  --env GRAFANA_CLOUD_LOKI_URL=https://logs-prod-000.grafana.net/loki/api/v1/push \
  --env GRAFANA_CLOUD_LOKI_USERNAME=example \
  --env GRAFANA_CLOUD_LOKI_PASSWORD=example \
  --env GRAFANA_CLOUD_PROMETHEUS_REMOTE_WRITE_URL=https://prometheus-prod-000.grafana.net/api/prom/push \
  --env GRAFANA_CLOUD_PROMETHEUS_USERNAME=example \
  --env GRAFANA_CLOUD_PROMETHEUS_PASSWORD=example \
  --env MONITORED_DOCKER_COMPOSE_PROJECT=livro-vivo-api \
  --env MONITORED_DOCKER_COMPOSE_SERVICE_REGEX='api|caddy' \
  --env LIVRO_VIVO_API_METRICS_HOST=api-178-104-197-8.nip.io \
  --env LIVRO_VIVO_API_METRICS_SCHEME=https \
  --env LIVRO_VIVO_API_METRICS_PATH=/metrics/ \
  --env LIVRO_VIVO_API_METRICS_BEARER_TOKEN=example \
  -v "$PWD/deploy/monitoring/config.alloy.example:/etc/alloy/config.alloy:ro" \
  grafana/alloy:latest \
  validate /etc/alloy/config.alloy
```

## 3.5. Validar no Grafana

Usar as consultas iniciais de `deploy/monitoring/GRAFANA_QUERIES.md`.

Depois de importar `deploy/monitoring/dashboards/livro-vivo-beta-overview.json`,
configurar `GRAFANA_BETA_DASHBOARD_URL=<url-final-do-dashboard>` no `.env` da API
para exibir o atalho `Monitoramento beta` no Django Admin.

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
