# Fonte da Verdade: Estado Atual do Beta Livro Vivo

Data base: 2026-05-04
Escopo: API, app web, app Android beta, LP, infraestrutura, operacao, administracao, monitoramento e pontos que precisam ser revisitados antes da producao final.
Status: beta funcional, publicado, validado em ambiente online e monitorado no Grafana Cloud com dashboard e alertas iniciais ativos.

## 1. Objetivo deste documento

Este documento registra o estado atual do Beta para que, ao encerrar o beta e iniciar a producao final, fique claro:

- o que foi criado;
- o que foi configurado;
- o que foi alterado por necessidade operacional de beta;
- o que ja esta validado;
- o que ainda e temporario e deve ser substituido antes do lancamento final.

Este documento nao substitui os runbooks especificos. Ele e o inventario consolidado do beta.

Documentos relacionados:

- `docs/FONTE_DA_VERDADE_MONITORAMENTO_BETA_2026-04-30.md`
- `../deploy/monitoring/README.md`
- `../deploy/monitoring/GRAFANA_QUERIES.md`
- `../deploy/monitoring/dashboards/README.md`
- `../deploy/monitoring/alerts/README.md`
- `../deploy/monitoring/alerts/livro-vivo-beta-alerts.json`

## 2. Publicacoes e URLs atuais

### API

- Repositorio: `jampamatos/livro-vivo-api`
- Branch publicada: `main`
- Hospedagem: VPS propria com Docker Compose + Caddy
- URL publica: `https://api-178-104-197-8.nip.io`
- Admin Django: `https://api-178-104-197-8.nip.io/admin/`
- Healthcheck publico: `https://api-178-104-197-8.nip.io/health/`
- Readiness publico: `https://api-178-104-197-8.nip.io/readyz/`

Estado validado:

- `health/` retorna `status: ok`
- `readyz/` retorna `database: ok` e `cache: ok`
- Caddy emite TLS automatico via Let's Encrypt
- `DJANGO_SECURE_SSL_REDIRECT=true`
- API esta atras de Caddy com proxy HTTPS
- deploy automatico via GitHub Actions esta funcionando

### App web

- Repositorio: `jampamatos/livro-vivo-app`
- Branch publicada: `main`
- Hospedagem: Cloudflare Workers & Pages como Worker com Static Assets
- URL publica: `https://livro-vivo-app.jampa-matos.workers.dev`
- API configurada: `https://api-178-104-197-8.nip.io`

Estado validado:

- app web abre online
- login por e-mail/senha funciona
- login Google funciona no web
- aceite legal obrigatorio funciona
- Minha Conta mostra documentos, contas vinculadas e privacidade

### Landing page

- Repositorio: `jampamatos/livro-vivo-lp`
- Branch publicada: `main`
- Hospedagem: Cloudflare Workers & Pages como Worker com Static Assets
- URL publica: `https://livro-vivo-lp.jampa-matos.workers.dev/`

Estado validado:

- LP online
- paginas estaticas legais e contato publicadas
- secao Beta Android publicada
- gate simples por codigo funciona
- link do APK abre corretamente

### Android beta

- Repositorio: `jampamatos/livro-vivo-app`
- Build oficial do beta: EAS `preview`
- Formato: APK
- Distribuicao atual: link EAS exposto na LP apos codigo beta
- Codigo beta atual na LP: `LV-BETA-2026`
- Link APK atual registrado na LP: `https://expo.dev/artifacts/eas/4MbP4TNVSRTmWbETyMQSKk.apk`
- Expiracao conhecida do link EAS atual: `2026-05-18`

Estado validado:

- APK instala em Android real
- login por e-mail/senha funciona
- login Google funciona no Android com deep link nativo
- app consome API de producao beta
- telemetria Android leve chega na API e aparece no Grafana como `client_telemetry_event`

## 3. Infraestrutura criada

### VPS

Servidor:

- IP: `178.104.197.8`
- acesso operacional local via alias SSH `livro-vivo`
- diretorio da API: `/opt/livro-vivo-api`

Alias SSH local recomendado:

```sshconfig
Host livro-vivo
    HostName 178.104.197.8
    User root
    IdentityFile ~/.ssh/livro_vivo_hetzner
```

Stack Docker:

- `api`: Django + Gunicorn
- `postgres`: PostgreSQL 16
- `redis`: Redis 7
- `caddy`: reverse proxy + TLS

Monitoramento no VPS:

- diretorio da stack de monitoramento: `/opt/livro-vivo-monitoring`
- agente: Grafana Alloy via Docker Compose
- painel local do Alloy: `http://127.0.0.1:12345`, acessivel apenas no proprio VPS
- logs enviados ao Grafana Loki: API e Caddy
- metricas enviadas ao Grafana Prometheus: API, Alloy e VPS
- credenciais reais do Grafana Cloud ficam somente em `/opt/livro-vivo-monitoring/.env`
- token real de `/metrics/` fica em `/opt/livro-vivo-api/.env` e e repetido no `.env` do monitoramento

Volumes persistentes:

- dados Postgres
- dados Redis
- arquivos de media
- dados/config Caddy

Backup operacional conhecido:

- `.env` bootstrap salvo no servidor em `/root/bootstrap-secrets/livro-vivo-api.env.bootstrap`

### Cloudflare

Projetos criados:

- `livro-vivo-app`
- `livro-vivo-lp`

Ambos estao em Workers & Pages como Workers com Static Assets.

Decisao beta:

- usar `workers.dev` enquanto nao houver dominio final
- nao tratar esses deploys como `pages.dev`

### GitHub Actions

API:

- workflow de deploy para VPS configurado
- merge na `main` dispara deploy automatico
- deploy faz pull no VPS e roda Docker Compose com rebuild

Secrets esperados no repositorio da API:

- `VPS_HOST`
- `VPS_PORT`
- `VPS_USER`
- `DEPLOY_PATH`
- `VPS_SSH_KEY`

## 4. Configuracoes operacionais atuais

### API

Configuracoes relevantes do `.env` no VPS:

- `DJANGO_ENV=production` ou equivalente operacional de beta
- `DEBUG=false`
- `DJANGO_ALLOWED_HOSTS` inclui `api-178-104-197-8.nip.io`
- `DJANGO_CORS_ALLOWED_ORIGINS` inclui o app web publicado
- `DJANGO_CSRF_TRUSTED_ORIGINS` inclui o app web publicado
- `DJANGO_SECURE_SSL_REDIRECT=true`
- `DJANGO_SECURE_PROXY_SSL_HEADER_ENABLED=true`
- `REDIS_URL` aponta para Redis do Compose
- `DATABASE_URL` aponta para Postgres do Compose
- `APP_VERSION=beta`
- `DJANGO_METRICS_ENABLED=true`
- `DJANGO_METRICS_BEARER_TOKEN` configurado com token forte no VPS
- `CLIENT_TELEMETRY_ENABLED=true`
- `CLIENT_TELEMETRY_MAX_BYTES=8192`
- `CLIENT_TELEMETRY_RATE_LIMIT=120/min`
- `GRAFANA_BETA_DASHBOARD_URL` configurado para exibir o atalho `Monitoramento beta` no Admin

Configuracoes sensiveis:

- `.env` nao deve ser commitado
- segredos nao devem aparecer em docs, prints ou logs
- `DJANGO_SECRET_KEY`, credenciais Postgres, SMTP, Google OAuth, Grafana e tokens de deploy ficam apenas nos ambientes apropriados

### Caddy

Estado atual:

- publica portas `80` e `443`
- redireciona HTTP para HTTPS
- faz reverse proxy para API na rede Docker
- gerencia certificado TLS automaticamente

### SMTP

Fornecedor atual:

- Brevo SMTP

Estado:

- reset de senha validado online
- e-mail chega corretamente

Decisao temporaria do beta:

- remetente ainda pode estar usando e-mail pessoal/autorizado provisoriamente

Antes da producao final:

- configurar remetente oficial do Livro Vivo
- validar dominio e autenticacao de e-mail
- validar SPF, DKIM e DMARC
- atualizar `DJANGO_DEFAULT_FROM_EMAIL` no VPS

## 5. Autenticacao e contas

### Login local

Implementado:

- cadastro por e-mail/senha
- login por e-mail/senha
- refresh JWT
- logout
- reset de senha por e-mail
- troca de senha em Minha Conta

Decisoes:

- `username` segue baseado em e-mail
- fluxo de reset e transacional, via SMTP
- cadastro nao deve expor enumeracao desnecessaria de e-mails

### Login social

Implementado:

- Google login no web
- Google login no Android
- deep link Android: `livrovivo://auth/callback`
- inicio de fluxo via backend
- callback OAuth no backend
- conclusao do login no app
- vinculacao e desvinculacao de contas sociais em Minha Conta
- definicao de senha para conta criada por social login

Decisoes:

- Google e o unico provedor ativo no beta
- LinkedIn esta modelado, mas desligado por feature flag
- nao ha auto-link por e-mail
- se o e-mail ja existe, o usuario precisa entrar pelo metodo atual e vincular o Google manualmente
- tokens de provedor social nao sao persistidos no beta

Configuracoes importantes:

- `SOCIAL_AUTH_GOOGLE_ENABLED=true`
- `SOCIAL_AUTH_GOOGLE_CLIENT_ID`
- `SOCIAL_AUTH_GOOGLE_CLIENT_SECRET`
- `SOCIAL_AUTH_ALLOWED_REDIRECT_URIS` deve incluir:
  - app web publicado
  - callback de teste local quando usado
  - `livrovivo://auth/callback`

Antes da producao final:

- revisar nome publico do OAuth Consent Screen
- revisar politica de privacidade e termos ligados no Google Cloud
- decidir se LinkedIn entra no lancamento final ou permanece desligado
- criar OAuth clients finais se houver dominio final e pacote Android final

## 6. Documentos legais e consentimento

Implementado:

- `LegalDocumentVersion`
- `UserLegalAcceptance`
- documentos ativos por tipo:
  - `terms_of_use`
  - `privacy_policy`
- aceite obrigatorio antes do uso do app
- enforcement no backend
- historico de aceite em Minha Conta
- painel admin para documentos legais

Decisoes:

- o beta usa clickwrap versionado
- nao ha assinatura eletronica avancada no beta
- ao ativar uma nova versao de documento, versoes anteriores ativas do mesmo tipo sao desativadas automaticamente
- documento ja publicado nao deve ser editado; publica-se nova versao

Antes da producao final:

- substituir textos de teste por termos e politica revisados juridicamente
- validar dados de controlador, contato, base legal, retencao, cookies/analytics e politicas de suporte
- publicar nova versao final e exigir novo aceite

## 7. Administracao e papeis

Perfis implementados:

- `Membro`
- `Moderador`
- `Dono`

Estado atual:

- `Moderador` e `Dono` ganham acesso staff ao admin
- `Dono` e sincronizado com o grupo Django `Livro Vivo - Dono`
- `Livro Vivo - Dono` recebe permissoes de `view/add/change` nos modelos operacionais
- `Livro Vivo - Dono` nao recebe permissao de `delete` por padrao

Motivo:

- o dono do site precisa publicar e alterar conteudo
- exclusao permanente deve continuar restrita para reduzir risco operacional

Modelos cobertos pelo papel Dono:

- usuarios/perfis e fluxos administrativos essenciais
- assinaturas e direitos de acesso
- biblioteca
- curso
- banco de pecas
- jurisprudencia
- comunidade e moderacao
- anotacoes

Conta operacional criada:

- perfil do Prof. Vitor Guglinski como `Dono`

Antes da producao final:

- revisar usuarios staff
- remover contas de teste
- confirmar principio de menor privilegio
- manter pelo menos um superuser tecnico separado do dono/editorial

## 8. Conteudo e produto implementados

### Biblioteca

Implementado:

- `Book`
- `BookVersion`
- `BookChapter`
- fluxo chapter-first
- versoes de livro com changelog
- publicacao/arquivamento de versoes
- editor rich text no admin
- sumario no app
- leitura de capitulos
- busca por capitulo
- anotacoes por selecao

### Curso

Implementado:

- `CoursePost`
- `CourseAsset`
- `LiveEvent`
- feed no app
- detalhe rich text
- materiais e lives/gravacoes
- gating Profissional
- notificacoes de publicacao

### Banco de Pecas

Implementado:

- `TemplatePiece`
- upload de arquivo
- URL remota
- metadados
- download protegido por token temporario
- TTL de token de download reduzido para `60` segundos
- gating Profissional

Decisao:

- token curto e suficiente porque cada tentativa de download pela plataforma gera um novo token

### Jurisprudencia

Implementado:

- cadastro via admin
- ementa rich/plain
- tags e busca
- detalhe no app
- copia de ementa
- abertura de acordao/link externo

### Comunidade

Implementado:

- categorias
- posts
- comentarios
- denuncias
- follow/unfollow de posts
- fila de moderacao
- acoes de moderacao
- status/eventos de moderacao de usuario
- banimento por escopo

### Notificacoes

Implementado:

- preferencias por usuario
- eventos de notificacao
- dispatches
- inbox in-app
- registro de devices push
- dispatcher de push

Antes da producao final:

- decidir provedor push definitivo
- validar push real em Android distribuido fora da loja e depois em build de loja

## 9. App web e Android

Implementado no app:

- login/cadastro
- reset de senha
- login Google
- aceite legal obrigatorio
- Minha Conta
- contas vinculadas
- privacidade/LGPD
- biblioteca
- leitor
- anotacoes
- busca global
- jurisprudencia
- curso
- banco de pecas
- comunidade
- notificacoes/inbox
- registro de push device
- cache/offline parcial

Estado Android:

- APK preview via EAS
- distribuicao fora da loja pela LP
- deep link Google validado
- app usa API beta online

Antes da producao final:

- definir estrategia de distribuicao final:
  - Google Play interna/fechada ou producao
  - assinatura definitiva do app
  - package name definitivo
  - politica de privacidade publica final
- substituir link temporario EAS por canal estavel

## 10. Landing page

Implementado:

- LP institucional estatica
- hero
- funcionalidades
- sobre o autor
- planos
- FAQ
- termos
- politica de privacidade
- contato
- secao Beta Android com gate por codigo
- `_headers` com headers de seguranca/cache

Decisao beta:

- gate por codigo na LP e apenas friccao operacional
- nao e seguranca real, pois codigo e link ficam no JavaScript entregue ao navegador

Antes da producao final:

- conectar dominio final
- revisar copy institucional
- revisar SEO, metadata, favicon e analytics
- remover ou substituir gate simples por fluxo definitivo
- atualizar links para app e planos reais

## 11. Monitoramento

Decisao oficial:

- Grafana Cloud e o painel unico do beta
- Sentry nao e painel principal do beta

Implementado/versionado:

- plano fonte da verdade de monitoramento
- estrutura `deploy/monitoring/`
- exemplo de `docker-compose.monitoring`
- exemplo de `monitoring.env`
- exemplo de configuracao Grafana Alloy
- dashboard beta versionado
- catalogo de alertas versionado
- consultas Grafana/Loki/Prometheus documentadas
- endpoint `/metrics/` na API
- metricas de eventos criticos na API
- endpoint `POST /telemetry/client-events/`
- telemetria Android integrada ao app e recebida pela API

Implantado/validado no ambiente beta:

- stack Grafana Cloud `livro-vivo-beta`
- datasource Prometheus `grafanacloud-livrovivo-prom`
- datasource Loki `grafanacloud-livrovivo-logs`
- Grafana Alloy rodando no VPS em `/opt/livro-vivo-monitoring`
- API, Alloy e host com metricas visiveis no Grafana
- logs da API/Caddy consultaveis no Grafana Loki
- dashboard `Livro Vivo Beta Overview` importado
- atalho `Monitoramento beta` no Django Admin
- contact point `Livro Vivo Ops`
- 8 alertas iniciais ativos e em estado `Normal`:
  - `Livro Vivo beta API down`
  - `Livro Vivo beta Alloy down`
  - `Livro Vivo beta VPS root disk low`
  - `Livro Vivo beta API 5xx detected`
  - `Livro Vivo beta API error logs`
  - `Livro Vivo beta API p95 latency high`
  - `Livro Vivo beta VPS memory low`
  - `Livro Vivo beta Android client errors`

Alerta catalogado, mas ainda nao ativo por padrao:

- `Livro Vivo beta Android telemetry silent`

Ainda planejado:

- Synthetic Monitoring para API, app web, LP e admin
- Grafana Faro/Frontend Observability para app web e LP
- dashboard/alertas de custos e cotas
- rotina formal de incidentes e escalation

Objetivos monitorados:

- disponibilidade
- erros API
- latencia
- readiness
- stress de VPS
- containers via logs Docker da API/Caddy
- login e auth social
- reset de senha
- aceite legal
- download de pecas
- eventos Android
- custos e cotas

Antes da producao final:

- validar rotina diaria de olhar Grafana
- consolidar escalation, horarios de resposta e registro de incidentes
- revisar se o alerta `Android telemetry silent` deve ser ativado em janelas controladas
- criar Synthetic Monitoring externo para endpoints publicos
- instrumentar app web e LP com Faro se o beta exigir visibilidade de navegador
- revisar retencao e sampling
- revisar dados pessoais em telemetria
- revisar orcamento e limites de custo

## 12. Custos e riscos operacionais atuais

Componentes com custo ou risco de cota:

- VPS
- Cloudflare Workers & Pages
- Grafana Cloud
- Brevo SMTP
- EAS builds/artefatos
- Google OAuth
- eventual storage externo futuro

Decisao de beta:

- acompanhar custos no Grafana como painel unico operacional
- alvo de custo mensal do beta: ate `R$150`
- alerta de atencao: `R$150`
- alerta critico: `R$250`

Antes da producao final:

- revisar plano VPS
- revisar custo de e-mail transacional
- revisar custo de observabilidade
- definir storage de midia/arquivos definitivo
- definir politica de backup

## 13. Seguranca e hardening feitos

Implementado:

- HTTPS via Caddy
- redirect HTTPS no Django
- CORS/CSRF restritos ao app publicado
- JWT com refresh
- sanitizacao de segredos em query string nos logs
- tokens temporarios para download de pecas
- TTL curto para download de pecas
- validacao de avatar por tipo/tamanho/dimensao
- backend enforcement de aceite legal
- no social login, sem auto-link por e-mail
- grupo Dono sem permissao de delete por padrao

Antes da producao final:

- trocar `nip.io` por dominio final
- revisar `ALLOWED_HOSTS`, CORS e CSRF com dominios finais
- revisar secrets e rotacionar os que foram usados no beta se necessario
- configurar backup automatico de banco e media
- revisar politica de acesso SSH
- revisar usuarios staff/superuser
- revisar headers finais em API e LP
- validar `check --deploy`

## 14. Decisoes temporarias do beta

Estas escolhas foram feitas para acelerar validacao e devem ser revistas antes da producao final:

- API em dominio `nip.io`
- app web em `workers.dev`
- LP em `workers.dev`
- APK distribuido por link EAS temporario
- gate de APK em JavaScript estatico
- remetente SMTP ainda provisiorio
- LinkedIn desligado
- textos juridicos podem ainda nao ser finais
- storage de media/arquivos deve ser revisado para producao
- dashboard e alertas iniciais estao configurados; ainda falta rotina operacional consolidada e escalation
- push provider definitivo ainda precisa validacao

## 15. Checklist de transicao beta para producao final

Obrigatorio antes de producao final:

1. Definir e apontar dominios finais.
2. Atualizar `DJANGO_ALLOWED_HOSTS`, CORS e CSRF.
3. Revisar termos e politica de privacidade finais.
4. Publicar novas versoes legais e exigir novo aceite.
5. Configurar remetente oficial de e-mail com SPF/DKIM/DMARC.
6. Decidir Google OAuth final e revisar consent screen.
7. Decidir se LinkedIn entra ou permanece desligado.
8. Substituir distribuicao APK por canal final.
9. Definir backup automatico de Postgres e media.
10. Definir storage definitivo para media e arquivos.
11. Consolidar rotina operacional de Grafana, alertas e incidentes.
12. Revisar usuarios staff e superusers.
13. Remover dados e contas de teste.
14. Rodar suite completa de API, app e LP.
15. Rodar checks de deploy e auditorias de dependencias.
16. Fazer teste ponta a ponta em web e Android.
17. Congelar changelog da versao final.

## 16. Comandos de referencia rapida

### VPS

```bash
ssh livro-vivo
cd /opt/livro-vivo-api
docker compose ps
docker compose logs api --tail 100
curl -sS https://api-178-104-197-8.nip.io/readyz/
```

### API local

```bash
cd /home/jampamatos/workspace/livro-vivo/livro-vivo-api
./.venv/bin/python manage.py test
./.venv/bin/python manage.py check --deploy --fail-level WARNING
```

### App local

```bash
cd /home/jampamatos/workspace/livro-vivo/livro-vivo-app
npm run typecheck
npm test -- --runInBand --ci
RELEASE_BUILD=true EXPO_PUBLIC_API_BASE_URL=https://api-178-104-197-8.nip.io npm run validate:release-config
```

### Android APK

```bash
cd /home/jampamatos/workspace/livro-vivo/livro-vivo-app
npx eas-cli build --platform android --profile preview --non-interactive
```

### LP local

```bash
cd /home/jampamatos/workspace/livro-vivo/livro-vivo-lp
python3 -m unittest discover -s tests -p "test_*.py" -v
python3 -m py_compile runserver.py
```

## 17. Criterio atual de sucesso do beta

O beta esta operacional quando:

- API `readyz` retorna `ok`;
- app web abre e autentica;
- Android APK instala e autentica;
- Google login funciona no web e Android;
- reset de senha envia e-mail;
- usuario aceita documentos legais;
- dono/editor consegue publicar conteudo no admin;
- livro/capitulo abre no app;
- banco de pecas baixa arquivo por token;
- LP entrega link APK mediante codigo beta;
- Grafana recebe sinais suficientes para diagnosticar incidentes;
- dashboard beta mostra API e Alloy como `UP`;
- alertas iniciais do beta estao em estado `Normal`.
