# Fonte da Verdade: Monitoramento Beta Livro Vivo

Data base: 2026-04-30
Escopo: API, app web, app Android beta, LP, VPS, Cloudflare, e custos operacionais do beta.
Status atual: plano de implementacao aprovado; bootstrap operacional do Alloy, runbook de implantacao e consultas iniciais versionados em `deploy/monitoring/`; `/metrics/` da API, metricas de eventos criticos e endpoint de telemetria client-side instrumentados no codigo; implantacao real no VPS/Grafana ainda pendente.

## 1. Decisao principal

O monitoramento oficial do beta sera centralizado em **Grafana Cloud**.

Grafana Cloud sera o painel unico de operacao para:

- bugs e erros de backend;
- erros de frontend web;
- erros e eventos criticos do app Android;
- saude de API, app web e LP;
- stress de infraestrutura;
- sinais de friccao do usuario;
- custos, cotas e risco de estouro de uso.

Decisao explicita:

- **Nao usar Sentry como painel principal no beta.**
- O `sentry-sdk` da API pode continuar suportado no codigo, mas `SENTRY_DSN` deve ficar vazio ate decisao contraria.
- O beta deve ter uma unica rotina operacional: abrir Grafana, olhar dashboards e alertas.

Motivo:

- Grafana Cloud concentra logs, metricas, alertas, sinteticos e frontend observability no mesmo lugar.
- O free tier atual e suficiente para o beta inicial se o volume for controlado.
- Dividir erro em Sentry, infra em outro lugar e custo em planilha aumenta o risco de ninguem olhar tudo.

Referencias oficiais consultadas:

- Grafana Cloud pricing/free tier: https://grafana.com/pricing/
- Grafana Cloud Synthetic Monitoring: https://grafana.com/docs/grafana-cloud/testing/synthetic-monitoring/
- Grafana Alloy: https://grafana.com/docs/alloy/latest/collect/
- Grafana Frontend Observability/Faro: https://grafana.com/docs/grafana-cloud/monitor-applications/frontend-observability/

## 2. Objetivos do monitoramento

O beta precisa responder rapidamente estas perguntas:

1. A plataforma esta online agora?
2. Usuarios conseguem criar conta, logar, aceitar termos e usar o app?
3. O Android beta esta quebrando em algum aparelho ou etapa?
4. A API esta lenta, sem memoria, sem disco ou reiniciando?
5. Downloads de pecas e e-mails transacionais estao funcionando?
6. Existe erro recorrente que afeta mais de um usuario?
7. Algum servico esta gerando custo inesperado?
8. O link do APK ou algum segredo operacional esta perto de expirar?

## 3. Arquitetura decidida

### Painel unico

Ferramenta:

- Grafana Cloud Free inicialmente.

Dashboards obrigatorios:

- `Livro Vivo - Overview Beta`
- `Livro Vivo - API e VPS`
- `Livro Vivo - Experiencia do Usuario`
- `Livro Vivo - Android Beta`
- `Livro Vivo - Custos e Cotas`
- `Livro Vivo - Incidentes`

### Coleta na VPS

Agente oficial:

- Grafana Alloy rodando no VPS.

Coletas obrigatorias:

- logs Docker da API;
- logs Docker do Caddy;
- metricas de host: CPU, memoria, disco, rede;
- metricas de containers: restarts, memoria, CPU, estado;
- endpoint `/readyz/` e `/health/` via synthetic monitoring externo;
- logs estruturados JSON da API.

### Coleta da API

Fonte primaria:

- logs estruturados ja existentes (`DJANGO_LOG_STRUCTURED=true`).

Eventos obrigatorios em log:

- `api_request_failed`
- `api_request_unhandled_exception`
- `api_readiness_degraded`
- `auth_login_success`
- `auth_login_failed`
- `auth_social_complete_success`
- `auth_social_complete_failed`
- `auth_password_reset_requested`
- `auth_password_reset_confirmed`
- `legal_acceptance_required`
- `legal_acceptance_completed`
- `template_download_token_created`
- `template_download_success`
- `template_download_failed`
- `email_send_success`
- `email_send_failed`
- `client_telemetry_event`

Metricas API obrigatorias na implementacao:

- requests por rota/status;
- latencia p50/p95/p99 por rota;
- taxa de 5xx;
- taxa de 401/403 por rota;
- taxa de throttling;
- contagem de login sucesso/falha;
- contagem de callback social sucesso/falha;
- contagem de aceite de documentos;
- contagem de download de pecas sucesso/falha;
- contagem de e-mail transacional sucesso/falha;
- tamanho de `media/`;
- uso de storage do banco.

Implementacao decidida:

- Fase 1: logs estruturados + Alloy + queries Loki.
- Fase 2: adicionar endpoint Prometheus `/metrics/` na API.
- Fase 3: adicionar metricas customizadas por evento critico.

### Coleta do app web

Ferramenta:

- Grafana Faro Web SDK via Grafana Cloud Frontend Observability.

Capturar:

- erros JS;
- promise rejections;
- navegacao/carregamento;
- Web Vitals;
- API calls lentas;
- eventos manuais de funil.

Eventos manuais obrigatorios:

- `app_open`
- `login_attempt`
- `login_success`
- `login_failed`
- `social_login_start`
- `social_login_success`
- `social_login_failed`
- `legal_gate_shown`
- `legal_acceptance_success`
- `book_open`
- `chapter_open`
- `search_global`
- `template_download_start`
- `template_download_success`
- `template_download_failed`

### Coleta do app Android beta

Decisao:

- O Android beta nao dependera de Sentry neste ciclo.
- O app Android enviara telemetria leve para a API por endpoint proprio.
- A API registrara esses eventos como logs estruturados e metricas, chegando no Grafana via Alloy.

Endpoint implementado na API:

- `POST /telemetry/client-events/`

Payload padrao:

```json
{
  "event_name": "login_failed",
  "platform": "android",
  "app_version": "1.0.0",
  "build_number": "1",
  "session_id": "uuid",
  "user_id_hash": "sha256-or-null",
  "route": "LoginScreen",
  "severity": "warning",
  "properties": {
    "provider": "google",
    "reason": "provider_auth_failed"
  },
  "occurred_at": "2026-04-30T12:00:00Z"
}
```

Regras de privacidade:

- nao enviar e-mail, nome, CPF, conteudo de livro, texto de comentario ou conteudo de peca;
- `user_id_hash` deve ser hash estavel, nao o ID cru;
- `properties` deve aceitar apenas chaves em allowlist;
- payload maximo: 8 KB;
- endpoint com throttle proprio;
- eventos anonimos permitidos antes do login.

Eventos Android obrigatorios:

- `app_open`
- `app_foreground`
- `app_background`
- `screen_view`
- `api_error`
- `api_slow_request`
- `unhandled_error`
- `login_attempt`
- `login_success`
- `login_failed`
- `social_login_start`
- `social_login_callback_received`
- `social_login_success`
- `social_login_failed`
- `legal_gate_shown`
- `legal_acceptance_success`
- `book_open`
- `chapter_open`
- `template_download_start`
- `template_download_success`
- `template_download_failed`

### Coleta da LP

Ferramenta:

- Grafana Faro Web SDK.

Eventos obrigatorios:

- `lp_view`
- `beta_section_view`
- `beta_code_attempt`
- `beta_code_success`
- `beta_code_failed`
- `apk_download_click`
- `cta_app_click`

Observacao:

- o gate atual da LP e operacional, nao seguro.
- o codigo e o link do APK ficam no JavaScript estatico.
- a metrica `beta_code_failed` serve para detectar abuso ou codigo vazado, nao para impedir acesso real.

### Synthetic Monitoring

Checks obrigatorios:

- API health: `GET https://api-178-104-197-8.nip.io/health/` a cada 1 minuto.
- API readiness: `GET https://api-178-104-197-8.nip.io/readyz/` a cada 1 minuto.
- App web home: `GET https://livro-vivo-app.jampa-matos.workers.dev/` a cada 5 minutos.
- LP home: `GET https://livro-vivo-lp.jampa-matos.workers.dev/` a cada 5 minutos.
- Django admin GET: `GET https://api-178-104-197-8.nip.io/admin/` a cada 5 minutos.

Nao implementar browser checks pagos no primeiro momento.

Motivo:

- API checks cobrem disponibilidade real.
- HTTP checks mantem custo previsivel.
- Browser checks ficam reservados para quando houver dominio final e fluxo de pagamento.

## 4. Dashboards obrigatorios

### `Livro Vivo - Overview Beta`

Painel de abertura diaria.

Paineis:

- status API health;
- status API readiness;
- status app web;
- status LP;
- usuarios ativos ultimas 24h;
- logins sucesso/falha ultimas 24h;
- social login sucesso/falha ultimas 24h;
- 5xx ultimas 24h;
- p95 API ultimas 24h;
- erros Android ultimas 24h;
- downloads APK ultimas 24h;
- downloads de pecas sucesso/falha;
- e-mails enviados/falhos;
- custo estimado do mes;
- cota Grafana usada: metrics/logs/synthetics/frontend sessions.

### `Livro Vivo - API e VPS`

Paineis:

- CPU VPS;
- memoria VPS;
- disco `/`;
- tamanho de `/opt/livro-vivo-api/media`;
- rede in/out;
- container API up/down;
- restarts de containers;
- Postgres up/down;
- Redis up/down;
- Caddy 4xx/5xx;
- Gunicorn worker timeouts;
- requests por rota;
- p95 por rota;
- taxa de 5xx;
- endpoints mais lentos;
- logs de erro recentes.

### `Livro Vivo - Experiencia do Usuario`

Paineis:

- funil: LP view -> beta code success -> APK download click;
- funil: app open -> login success -> legal accepted -> book open;
- login por metodo: senha vs Google;
- falhas de login por tipo;
- aceite de termos pendente;
- buscas globais por dia;
- leitura: book/chapter open por dia;
- banco de pecas: download token vs download final;
- telas com mais erros;
- usuarios com mais erros anonimizados.

### `Livro Vivo - Android Beta`

Paineis:

- versoes/builds ativos;
- app opens por versao;
- erros por versao;
- social login callback success/fail;
- API slow requests por tela;
- downloads de peca no Android;
- aparelhos/plataformas agregados se disponivel;
- link APK atual e data de expiracao;
- dias ate expiracao do link APK.

### `Livro Vivo - Custos e Cotas`

Paineis:

- custo fixo VPS Hetzner;
- uso Grafana: logs GB, active series, synthetics executions, frontend sessions;
- Cloudflare: requests e bandwidth;
- Brevo: e-mails enviados, falhas e limite mensal;
- EAS: builds Android no mes;
- storage local: tamanho media;
- estimativa total mensal;
- alerta de budget.

Budget decidido para beta:

- meta: ate R$ 150/mes;
- alerta amarelo: R$ 150 estimado no mes;
- alerta vermelho: R$ 250 estimado no mes;
- se bater alerta vermelho, congelar convites novos ate revisar custo.

### `Livro Vivo - Incidentes`

Paineis:

- incidentes abertos;
- alertas ativos;
- ultimos deploys;
- logs por `X-Request-ID`;
- checklist de rollback;
- links para GitHub Actions, Cloudflare e VPS runbook.

## 5. Alertas obrigatorios

### Criticos

Acionam resposta imediata.

- API `/readyz/` falha por 2 minutos.
- API 5xx acima de 2% por 5 minutos.
- p95 API acima de 2 segundos por 10 minutos.
- container API reinicia 2 vezes em 10 minutos.
- disco VPS acima de 85%.
- Postgres ou Redis fora do ar.
- app Android com `unhandled_error` em 3 usuarios diferentes em 30 minutos.
- login indisponivel: `login_failed` acima de 50% por 10 minutos.
- Google social login falha acima de 30% por 10 minutos.

### Avisos

Revisar no mesmo dia.

- LP indisponivel por 5 minutos.
- app web indisponivel por 5 minutos.
- e-mail transacional com falha acima de 5% em 1 hora.
- download de pecas com falha acima de 10% em 1 hora.
- p95 API acima de 1 segundo por 30 minutos.
- memoria VPS acima de 80% por 30 minutos.
- disco VPS acima de 75%.
- uso de logs Grafana acima de 70% do free tier.
- uso de synthetics acima de 70% do free tier.
- 7 dias ou menos para expiracao do APK publicado na LP.
- custo mensal estimado acima de R$ 150.

## 6. Severidade de incidentes

### SEV1

Plataforma indisponivel ou login indisponivel.

Exemplos:

- API down;
- app nao consegue autenticar;
- banco indisponivel;
- erro em massa no app Android.

Resposta:

- parar convites novos;
- corrigir ou rollback imediato;
- registrar incidente em issue.

### SEV2

Funcionalidade relevante quebrada, mas login e leitura ainda funcionam.

Exemplos:

- download de pecas quebrado;
- e-mail de reset falhando;
- Google login quebrado, mas senha funciona;
- busca global falhando.

Resposta:

- corrigir no mesmo dia;
- comunicar testers afetados se necessario.

### SEV3

Friccao ou bug localizado.

Exemplos:

- layout ruim em aparelho especifico;
- mensagem confusa;
- tela lenta sem erro;
- falha em conteudo especifico.

Resposta:

- backlog priorizado;
- corrigir antes de ampliar beta se afetar onboarding.

## 7. Variaveis de ambiente planejadas

### API

```env
OBSERVABILITY_PROVIDER=grafana
CLIENT_TELEMETRY_ENABLED=true
CLIENT_TELEMETRY_SHARED_SECRET=
CLIENT_TELEMETRY_MAX_BYTES=8192
CLIENT_TELEMETRY_RATE_LIMIT=120/min
GRAFANA_CLOUD_ENVIRONMENT=beta
GRAFANA_CLOUD_LOKI_URL=
GRAFANA_CLOUD_PROMETHEUS_URL=
GRAFANA_CLOUD_OTLP_ENDPOINT=
```

### App web / Android

```env
EXPO_PUBLIC_OBSERVABILITY_ENABLED=true
EXPO_PUBLIC_TELEMETRY_ENDPOINT=https://api-178-104-197-8.nip.io/telemetry/client-events/
EXPO_PUBLIC_TELEMETRY_ENVIRONMENT=beta
EXPO_PUBLIC_APP_VERSION=1.0.0
EXPO_PUBLIC_BUILD_CHANNEL=beta
EXPO_PUBLIC_GRAFANA_FARO_URL=
```

### LP

```env
GRAFANA_FARO_URL=
GRAFANA_FARO_ENVIRONMENT=beta
```

Observacao:

- A LP e estatica hoje; se continuar sem build step, o Faro URL sera inserido diretamente no JS somente quando houver decisao operacional.

## 8. Regras de dados e privacidade

Proibido enviar para monitoramento:

- senha, token JWT, refresh token;
- e-mail em claro;
- nome completo;
- conteudo de livros;
- conteudo de anotacoes;
- conteudo de comentarios;
- texto de pecas juridicas;
- dados juridicos sensiveis;
- arquivos ou URLs assinadas completas.

Permitido:

- `request_id`;
- rota sem query sensivel;
- status HTTP;
- duracao;
- plataforma;
- versao do app;
- hash de usuario;
- tipo de evento;
- erro tecnico sanitizado;
- codigo de resultado controlado, como `provider_auth_failed`.

Retencao beta:

- aceitar retencao padrao do Grafana Free: 14 dias.
- nao usar monitoramento como banco historico de produto.
- indicadores permanentes devem ser gravados no proprio banco apenas quando virarem feature de analytics.

## 9. Implementacao em fases

### Fase 1: painel vivo sem mudanca de codigo

Objetivo:

- ter um dashboard util em 1 dia.

Tarefas:

1. Criar conta Grafana Cloud.
2. Criar stack `livro-vivo-beta`.
3. Configurar Synthetic Monitoring dos 5 endpoints obrigatorios.
4. Instalar Grafana Alloy no VPS.
5. Enviar logs Docker da API e Caddy para Loki.
6. Criar dashboard `Overview Beta`.
7. Criar alertas criticos de disponibilidade.

Pronto quando:

- Grafana mostra API/LP/app web online;
- logs da API aparecem por `request_id`;
- alerta dispara se `/readyz/` falhar.

### Fase 2: metricas de infraestrutura

Objetivo:

- saber se a VPS esta sofrendo.

Tarefas:

1. Coletar CPU, memoria, disco e rede do VPS via Alloy.
2. Coletar status/restarts de containers.
3. Criar dashboard `API e VPS`.
4. Alertar disco, memoria, restart e 5xx.

Pronto quando:

- conseguimos ver causa infra sem SSH.

### Fase 3: metricas da API

Objetivo:

- medir latencia, erro e funis de backend.

Tarefas:

1. Adicionar endpoint `/metrics/` protegido por rede/token ou exposto apenas internamente.
2. Instrumentar requests por rota/status/duracao.
3. Instrumentar eventos de auth, legal, download, e-mail.
4. Criar dashboard `Experiencia do Usuario`.

Implementado no codigo:

- `livro_vivo_api_http_requests_total`
- `livro_vivo_api_http_request_duration_seconds`
- `livro_vivo_api_domain_events_total` para auth, callback social, aceite legal, reset de senha, e-mail transacional e download de pecas.

Pendente:

- publicar a stack no VPS/Grafana Cloud;
- montar o dashboard `Experiencia do Usuario`;
- adicionar metricas de tamanho de `media/` e uso de storage do banco.

Pronto quando:

- login, legal acceptance e download de pecas aparecem no Grafana.

### Fase 4: web e LP

Objetivo:

- enxergar erro real no navegador.

Tarefas:

1. Adicionar Faro Web SDK no app web.
2. Adicionar Faro Web SDK na LP.
3. Instrumentar eventos manuais do funil LP e app web.
4. Criar alertas para erro JS e funil quebrado.

Pronto quando:

- erro JS aparece no dashboard com ambiente, URL e versao.

### Fase 5: Android beta

Objetivo:

- enxergar falhas reais do APK sem depender de print.

Tarefas:

1. Criar `POST /telemetry/client-events/` na API.
2. Criar cliente de telemetria no app.
3. Enviar eventos Android obrigatorios.
4. Capturar unhandled errors no app e enviar evento sanitizado.
5. Criar dashboard `Android Beta`.

Implementado no codigo da API:

- endpoint anonimo com throttle proprio;
- limite de payload por `CLIENT_TELEMETRY_MAX_BYTES`;
- secret opcional por `CLIENT_TELEMETRY_SHARED_SECRET`, enviado no header `X-Client-Telemetry-Secret`;
- allowlist de eventos e propriedades;
- rejeicao de `user_id_hash` que nao seja SHA-256;
- log estruturado `client_telemetry_event`;
- metrica `livro_vivo_api_domain_events_total{event="client_telemetry_event", ...}`.

Pendente:

- criar o cliente de telemetria no app Android;
- enviar os eventos obrigatorios reais do APK;
- montar o dashboard `Android Beta`.

Pronto quando:

- login Google, login senha e erro Android aparecem no Grafana.

### Fase 6: custos e cotas

Objetivo:

- evitar surpresa financeira.

Tarefas:

1. Criar dashboard `Custos e Cotas`.
2. Inserir custo fixo mensal do VPS manualmente como variavel de dashboard.
3. Monitorar cotas Grafana pela propria conta.
4. Registrar contagem de e-mails Brevo por logs/API quando possivel.
5. Registrar builds EAS manualmente no runbook por release.
6. Criar alerta de uso acima de 70% do free tier.

Pronto quando:

- existe uma tela unica com custo estimado e cotas principais.

## 10. Rotina operacional

### Diaria durante beta fechado

Abrir `Livro Vivo - Overview Beta` e conferir:

- API readiness;
- 5xx;
- p95;
- login success/fail;
- Android errors;
- downloads de peca;
- e-mails;
- custo/cotas.

Tempo alvo:

- 5 minutos por dia.

### Apos cada deploy

Conferir por 15 minutos:

- `/readyz/`;
- 5xx;
- p95;
- logs de exception;
- login;
- fluxo afetado pelo deploy.

### Antes de convidar mais usuarios

Conferir:

- nenhum alerta critico aberto;
- p95 abaixo de 1s;
- erro Android sem crescimento;
- disco abaixo de 75%;
- APK nao expira nos proximos 7 dias;
- custo estimado abaixo de R$ 150/mes.

## 11. Indicadores de decisao

Pode ampliar beta se:

- 7 dias sem SEV1;
- login success rate acima de 95%;
- Google social success rate acima de 90%;
- p95 API abaixo de 1s na maior parte do dia;
- menos de 2% de sessoes Android com erro severo;
- custo estimado abaixo de R$ 150/mes.

Nao ampliar beta se:

- qualquer SEV1 nos ultimos 3 dias;
- mais de 5 usuarios reportando o mesmo bug sem dashboard explicar;
- download de pecas instavel;
- e-mail de reset falhando;
- APK perto de expirar;
- disco acima de 75%;
- custo estimado acima de R$ 250/mes.

## 12. Backlog de implementacao tecnica

Ordem obrigatoria:

1. Grafana Cloud + Synthetic Monitoring.
2. Alloy no VPS para logs.
3. Dashboard Overview.
4. Alertas criticos.
5. Metricas VPS.
6. Endpoint `/metrics/` da API.
7. Eventos customizados da API.
8. Faro no app web.
9. Faro na LP.
10. Endpoint `/telemetry/client-events/` da API.
11. Telemetria Android.
12. Dashboard de custos/cotas.

Nao iniciar Sentry antes do item 12.

## 13. Definicao de pronto do monitoramento beta

Monitoramento beta esta pronto quando:

- Grafana e a primeira tela operacional do dia;
- API, app web, LP e VPS aparecem em um dashboard;
- erros da API chegam com `request_id`;
- falhas de login e social login aparecem como grafico;
- app Android envia pelo menos `app_open`, `login_success`, `login_failed`, `unhandled_error`;
- existe alerta para API down;
- existe alerta para disco alto;
- existe alerta para custo/cota;
- existe rotina documentada de incidente.
