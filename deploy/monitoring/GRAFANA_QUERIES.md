# Consultas iniciais no Grafana

Use este arquivo depois que o Alloy estiver rodando no VPS.

## Metrics / PromQL

Confirmar que o scrape da API esta ativo:

```promql
up{job="livro-vivo-api", environment="beta"}
```

Confirmar requests HTTP da API:

```promql
sum by (route, status) (livro_vivo_api_http_requests_total)
```

Confirmar eventos de dominio e telemetria Android:

```promql
sum by (result, source) (livro_vivo_api_domain_events_total{event="client_telemetry_event"})
```

Confirmar metricas internas do Alloy:

```promql
alloy_build_info{job="grafana-alloy", environment="beta"}
```

Confirmar que o Alloy esta com componentes saudaveis:

```promql
alloy_component_controller_running_components{job="grafana-alloy"}
```

Confirmar CPU/memoria/disco da VPS:

```promql
node_load1
```

```promql
node_memory_MemAvailable_bytes
```

```promql
node_filesystem_avail_bytes{mountpoint="/"}
```

## Logs / LogQL

Logs da API:

```logql
{project="livro-vivo", environment="beta", compose_service="api"}
```

Erros da API quando os logs estruturados estiverem ativos:

```logql
{project="livro-vivo", environment="beta", compose_service="api", level="ERROR"}
```

Logs do Caddy:

```logql
{project="livro-vivo", environment="beta", compose_service="caddy"}
```

Eventos de telemetria client-side registrados pela API:

```logql
{project="livro-vivo", environment="beta", compose_service="api"} |= "client_telemetry_event"
```

Fluxos de login registrados pela API:

```logql
{project="livro-vivo", environment="beta", compose_service="api"} |= "auth_login"
```
