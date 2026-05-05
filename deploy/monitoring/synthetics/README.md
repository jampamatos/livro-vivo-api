# Synthetic Monitoring beta

Catalogo e runbook para criar checks HTTP externos no Grafana Cloud.

O objetivo aqui e testar os endpoints publicos do beta de fora do VPS. Isso
complementa o Alloy: o Alloy mostra se a API responde para o agente no servidor;
o Synthetic Monitoring mostra se um usuario externo consegue chegar na API, app,
LP e admin.

## Arquivos

- `livro-vivo-beta-synthetic-checks.json`: catalogo dos checks HTTP do beta.

## Premissas

Antes de criar os checks:

- stack Grafana Cloud `livro-vivo-beta` criada;
- datasource Prometheus `grafanacloud-livrovivo-prom` funcionando;
- dashboard `Livro Vivo Beta Overview` importado;
- contact point `Livro Vivo Ops` criado;
- API, app web e LP publicados nas URLs atuais do beta.

## Checks a criar

Criar checks do tipo `HTTP/HTTPS` ou `API Endpoint`, conforme a nomenclatura da
UI atual do Grafana Cloud.

| Job name | Target | Frequencia | Status valido | Service |
| --- | --- | ---: | --- | --- |
| `livro-vivo-beta-api-health` | `https://api-178-104-197-8.nip.io/health/` | 60s | `200` | `api` |
| `livro-vivo-beta-api-readyz` | `https://api-178-104-197-8.nip.io/readyz/` | 60s | `200` | `api` |
| `livro-vivo-beta-app-web-home` | `https://livro-vivo-app.jampa-matos.workers.dev/` | 300s | `200` | `app-web` |
| `livro-vivo-beta-lp-home` | `https://livro-vivo-lp.jampa-matos.workers.dev/` | 300s | `200` | `lp` |
| `livro-vivo-beta-django-admin` | `https://api-178-104-197-8.nip.io/admin/` | 300s | `200` | `admin` |

Labels customizadas em todos os checks:

```text
project=livro-vivo
environment=beta
component=synthetic
service=<valor da tabela>
```

No Grafana Synthetic Monitoring, essas labels aparecem em `sm_check_info` com
prefixo `label_`, por exemplo `label_project` e `label_environment`. Para as
metricas de execucao (`probe_success`, `probe_duration_seconds`, etc.), usar os
`job_name` do catalogo como filtro principal.

## Passo a passo no Grafana Cloud

1. Abrir `Testing & synthetics` > `Synthetics`.
2. Clicar em `Create new check` ou `Add new check`.
3. Selecionar `API Endpoint` / `HTTP/HTTPS`.
4. Preencher `Job name` exatamente como no catalogo.
5. Preencher `Target`.
6. Selecionar metodo `GET`.
7. Definir `Frequency` conforme o catalogo.
8. Definir `Timeout` como `10s`.
9. Manter `Follow redirects` habilitado.
10. Definir status valido `200`.
11. Desabilitar `Publish full set of metrics` inicialmente para conter series.
12. Adicionar labels customizadas.
13. Escolher uma ou mais public probes.
14. Usar `Test` para executar uma validacao pontual.
15. Salvar o check.

Para `health/`, adicionar validacao de body contendo `"status"` se a UI permitir.
Para `readyz/`, adicionar validacao de body contendo `"database"` ou `"cache"` se
a UI permitir. Se a UI dificultar essa validacao, manter apenas status `200` no
primeiro momento.

## Validar no Explore

No datasource Prometheus:

```promql
sm_check_info{label_project="livro-vivo", label_environment="beta"}
```

```promql
min by (job, instance) (probe_success{job=~"livro-vivo-beta-.*"})
```

```promql
max by (job, instance) (probe_http_status_code{job=~"livro-vivo-beta-.*"})
```

```promql
avg by (job) (probe_duration_seconds{job=~"livro-vivo-beta-.*"})
```

Esperado:

- os 5 checks aparecem em `sm_check_info`;
- `probe_success` retorna `1` para cada check;
- `probe_http_status_code` retorna `200`;
- latencia aparece em `probe_duration_seconds`.

## Validar no dashboard

Depois de importar novamente `deploy/monitoring/dashboards/livro-vivo-beta-overview.json`,
abrir a secao `Synthetic Monitoring`.

Esperado:

- `Synthetic status by endpoint` mostra os checks com valor `UP`;
- `Synthetic success by check` permanece em `1`;
- `Synthetic latency by check` mostra latencia externa;
- `Synthetic HTTP status by endpoint` mostra `200`.

## Alertas associados

Depois que os checks aparecerem no Explore, criar as regras sinteticas do
catalogo:

```text
deploy/monitoring/alerts/livro-vivo-beta-alerts.json
```

Regras adicionadas para esta fase:

- `Livro Vivo beta public API health down`
- `Livro Vivo beta public API readiness down`

Essas regras cobrem o minimo da issue #86: API health/readiness com alerta
baseado no resultado externo do Synthetic Monitoring.

## Quando um check falhar

1. Abrir `Livro Vivo Beta Overview`.
2. Confirmar se os paineis internos da API/Alloy tambem falharam.
3. Se Synthetic falhou mas Alloy/API seguem `UP`, suspeitar de DNS, TLS, Caddy,
   Cloudflare, rede publica ou caminho externo.
4. Se Synthetic e Alloy/API falharam, investigar a stack no VPS.
5. Registrar incidente se a falha durar mais que a janela do alerta.
