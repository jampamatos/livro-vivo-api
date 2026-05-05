# Dashboards Grafana

Dashboards versionados para o monitoramento beta do Livro Vivo.

## Importar no Grafana Cloud

1. Acesse Grafana Cloud.
2. Abra `Dashboards`.
3. Clique em `New` > `Import`.
4. Escolha `Upload dashboard JSON file`.
5. Selecione `livro-vivo-beta-overview.json`.
6. Na tela de importacao, mapear:
   - `DS_PROMETHEUS` para `grafanacloud-livrovivo-prom`;
   - `DS_LOKI` para `grafanacloud-livrovivo-logs`.
7. Clique em `Import`.

## Validacao depois do import

No dashboard `Livro Vivo Beta Overview`, confirmar:

- `API Up` com valor `1`;
- `Alloy Up` com valor `1`;
- secao `Synthetic Monitoring` com os checks externos em `UP`, depois que
  `deploy/monitoring/synthetics/` for configurado no Grafana Cloud;
- grafico `Android telemetry events by type` com eventos como `app_open`, `screen_view` e `chapter_open`;
- painel `Recent API logs` com logs da API.

Se a secao `Synthetic Monitoring` ficar vazia, isso significa que os checks
externos ainda nao foram criados ou ainda nao enviaram metricas. Validar com:

```promql
sm_check_info{label_project="livro-vivo", label_environment="beta"}
```

Se os paineis de telemetria Android ficarem vazios, abrir o APK beta no celular,
navegar por algumas telas e aguardar 1 a 2 minutos.

## Atalho no Admin da API

Depois de importar o dashboard, copie a URL final do Grafana e configure no
`.env` da API:

```env
GRAFANA_BETA_DASHBOARD_URL=https://<stack>.grafana.net/d/livro-vivo-beta-overview/livro-vivo-beta-overview
```

Depois recrie o container da API:

```bash
docker compose up -d --force-recreate api
```

Com isso, o Django Admin passa a exibir o atalho `Monitoramento beta` no grupo
`Painel operacional`. O link abre o dashboard do Grafana em nova aba.
