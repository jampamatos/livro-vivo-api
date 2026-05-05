# Alertas Grafana

Catalogo versionado de alertas recomendados para o beta do Livro Vivo.

Este diretorio nao contem segredos e nao altera o VPS sozinho. A primeira
ativacao dos alertas deve ser feita no Grafana Cloud, copiando as consultas do
catalogo para regras gerenciadas do Grafana.

## Arquivos

- `livro-vivo-beta-alerts.json`: catalogo operacional dos alertas beta.

## Estado atual em 2026-05-04

Foram criados no Grafana Cloud, com contact point `Livro Vivo Ops`, e validados
em estado `Normal`:

- `Livro Vivo beta API down`;
- `Livro Vivo beta Alloy down`;
- `Livro Vivo beta VPS root disk low`;
- `Livro Vivo beta API 5xx detected`;
- `Livro Vivo beta API error logs`;
- `Livro Vivo beta API p95 latency high`;
- `Livro Vivo beta VPS memory low`;
- `Livro Vivo beta Android client errors`.

O alerta `Livro Vivo beta Android telemetry silent` continua catalogado, mas nao
deve ficar ativo por padrao enquanto nao houver uma janela de teste ou rotina
operacional clara para evitar falso positivo.

## Alertas adicionados para Synthetic Monitoring

Depois de criar os checks de `deploy/monitoring/synthetics/`, criar tambem:

- `Livro Vivo beta public API health down`;
- `Livro Vivo beta public API readiness down`.

Esses dois alertas usam `probe_success` do Grafana Synthetic Monitoring e testam
a API de fora do VPS. Eles complementam `Livro Vivo beta API down`, que mede o
scrape interno feito pelo Alloy.

## Premissas

Antes de criar os alertas, confirmar que:

- o Alloy esta `ready` e `healthy` no VPS;
- o dashboard `Livro Vivo Beta Overview` esta importado;
- a datasource Prometheus retorna `up{job="livro-vivo-api", environment="beta"}`;
- a datasource Prometheus retorna `up{job="grafana-alloy", environment="beta"}`;
- a datasource Loki retorna logs para `{project="livro-vivo", environment="beta", compose_service="api"}`.

## Criar canal de notificacao

No Grafana Cloud:

1. abrir `Alerting` > `Contact points`;
2. criar um contact point chamado `Livro Vivo Ops`;
3. escolher o canal real de notificacao, por exemplo e-mail;
4. usar `Test` para confirmar que a notificacao chega.

Depois:

1. abrir `Alerting` > `Notification policies`;
2. criar uma policy para labels:
   - `project = livro-vivo`;
   - `environment = beta`;
3. direcionar para o contact point `Livro Vivo Ops`;
4. agrupar por `alertname`, `service` e `severity`.

## Criar regras

Para cada regra de `livro-vivo-beta-alerts.json`:

1. abrir `Alerting` > `Alert rules`;
2. clicar em `New alert rule`;
3. usar folder `Livro Vivo Beta`;
4. usar evaluation group `livro-vivo-beta` com intervalo `1m`;
5. selecionar a datasource indicada em `datasource`;
6. colar o campo `query`;
7. aplicar uma operacao `Reduce` com `Last`;
8. aplicar `Threshold` conforme o campo `condition`;
9. preencher `For`, `No data state` e `Error state`;
10. adicionar labels:
    - `project=livro-vivo`;
    - `environment=beta`;
    - `service=<service do catalogo>`;
    - `severity=<severity do catalogo>`;
11. adicionar annotations:
    - `summary`;
    - `runbook`;
12. salvar.

Na tela atual do Grafana, o estado saudavel aparece como `Normal`. Quando o
catalogo indicar `no_data_state=OK`, selecionar `Normal` na UI.

Regras com `enabled_by_default=false` devem ficar desabilitadas inicialmente.
Elas sao uteis para janelas de teste assistidas, mas podem gerar ruido fora do
horario de homologacao.

## Ordem recomendada

Criar primeiro:

1. `Livro Vivo beta API down`;
2. `Livro Vivo beta public API health down`, depois que o Synthetic Monitoring existir;
3. `Livro Vivo beta public API readiness down`, depois que o Synthetic Monitoring existir;
4. `Livro Vivo beta Alloy down`;
5. `Livro Vivo beta VPS root disk low`;
6. `Livro Vivo beta API 5xx detected`;
7. `Livro Vivo beta API error logs`.

Depois criar:

1. `Livro Vivo beta API p95 latency high`;
2. `Livro Vivo beta VPS memory low`;
3. `Livro Vivo beta Android client errors`.

Por ultimo, avaliar manualmente:

1. `Livro Vivo beta Android telemetry silent`.

## Como validar sem derrubar servicos

Validar cada regra pela tela de preview do Grafana. O esperado para o estado
normal do beta:

- API down: `Normal`;
- public API health down: `Normal`, depois que o check existir;
- public API readiness down: `Normal`, depois que o check existir;
- Alloy down: `Normal`;
- disco baixo: `Normal`;
- memoria baixa: `Normal`;
- 5xx: `Normal` quando nao houve erro recente;
- logs de erro: `Normal` quando nao houve erro recente;
- erros Android: `Normal` quando o app nao enviou erro recente.

Para testar entrega de notificacao, usar o botao `Test` do contact point. Nao
derrubar API, Alloy ou containers apenas para testar alerta.

## Quando um alerta disparar

1. abrir o dashboard `Livro Vivo Beta Overview`;
2. confirmar se o painel correspondente tambem mostra o problema;
3. abrir Explore no datasource correto;
4. usar a mesma janela de tempo do alerta;
5. seguir o campo `runbook` da regra;
6. registrar no changelog interno o alerta, causa e acao tomada.
