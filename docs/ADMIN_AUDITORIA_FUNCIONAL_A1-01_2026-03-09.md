# Auditoria Funcional do Admin (A1-01 / UX-A1.1)

Data: 2026-03-09  
Issue: API #46  
Byte alvo: UX-A1.1  
Ciclo: UI/UX 2026-03-09

## 1) Objetivo

Produzir um diagnostico funcional reproduzivel do Django Admin atual para orientar:

- A1-02 (navegacao e arquitetura da informacao do admin)
- A1-03 (formularios e listagens operacionais do admin)

## 2) Escopo auditado

Arquivos auditados (ordem do backlog):

1. `accounts/admin.py`
2. `library/admin.py`
3. `courses/admin.py`
4. `templates_bank/admin.py`
5. `community/admin.py`
6. `caselaw/admin.py`
7. `README.md` (secao admin)

## 3) Inventario de telas e fluxos criticos

Resumo estrutural:

- 22 `ModelAdmin` registrados (6 accounts, 3 library, 3 courses, 1 templates_bank, 8 community, 1 caselaw).
- Fluxos de maior impacto operacional: publicacao de versao do livro, moderacao da comunidade, publicacao/arquivamento de pecas, preferencias/disparos de notificacao.

### 3.1 Accounts

ModelAdmins:

- `ProfileAdmin`
- `DataPrivacyRequestAdmin` (somente leitura)
- `NotificationPreferenceAdmin`
- `NotificationEventAdmin`
- `NotificationDispatchAdmin`
- `PushDeviceAdmin`

Fluxos criticos:

- consulta de perfil/role por usuario;
- acompanhamento de solicitacoes LGPD;
- inspeção de pipeline de notificacoes (evento -> dispatch -> device).

### 3.2 Library

ModelAdmins:

- `BookAdmin`
- `BookVersionAdmin` (com `BookChapterInline` e acao `create_preloaded_version`)
- `BookChapterAdmin`

Fluxos criticos:

- clonar versao atual para nova versao pre-carregada;
- publicar versao com changelog;
- editar capitulo rich text com sanitizacao e preview;
- reordenar capitulos.

### 3.3 Courses

ModelAdmins:

- `CoursePostAdmin`
- `CourseAssetAdmin`
- `LiveEventAdmin`

Fluxos criticos:

- publicar/editar post de curso (rich text);
- cadastrar ativos (materiais);
- agendar live e registrar gravacao.

### 3.4 Templates Bank

ModelAdmin:

- `TemplatePieceAdmin` (acoes `mark_published`, `mark_archived`)

Fluxos criticos:

- cadastro de peca com upload ou URL remota;
- validacao de metadados de arquivo;
- publicacao/arquivamento em massa.

### 3.5 Community

ModelAdmins:

- `ReportAdmin`
- `PostAdmin`
- `CommentAdmin`
- `CategoryAdmin`
- `ReportModerationActionAdmin`
- `ModerationConfigAdmin`
- `UserModerationStatusAdmin`
- `UserModerationEventAdmin`

Fluxos criticos:

- triagem e decisao de reports (aprovar/remover/escalar/rejeitar);
- banimento por report e banimento manual;
- acompanhamento de trilha de moderacao;
- configuracao de politicas de moderacao.

### 3.6 CaseLaw

ModelAdmin:

- `CaseLawAdmin`

Fluxos criticos:

- cadastro/edicao de jurisprudencia com ementa rich/plain;
- vinculacao por anchors e tags;
- consulta e ajuste de metadados de acordao.

## 4) Friccoes identificadas (classificacao por severidade)

Legenda:

- Alta: risco operacional direto (erro irreversivel, impacto em usuarios, ou alto retrabalho).
- Media: reduz produtividade/clareza, mas com mitigacao manual.
- Baixa: friccao de usabilidade/consistencia sem risco imediato.

| ID | Dominio | Friccao | Severidade | Evidencia no codigo |
| --- | --- | --- | --- | --- |
| A1F-01 | Community | Acoes em massa de alto risco (remove/escalate/reject/ban) no mesmo bloco, sem guardrail explicito de confirmacao por impacto. | Alta | `ReportAdmin.actions`, `ban_report_authors` |
| A1F-02 | Library | Publicacao de `BookVersion` dispara notificacao no `save_model` sem etapa explicita de pre-flight (ex.: preview de audiencia/impacto). | Alta | `BookVersionAdmin.save_model` |
| A1F-03 | Templates Bank | Acoes `mark_published`/`mark_archived` usam `queryset.update(...)`, com baixo contexto operacional para mudanca sensivel de estado. | Alta | `TemplatePieceAdmin.mark_*` |
| A1F-04 | Admin global | Navegacao segue agrupamento tecnico por app/model, sem arquitetura orientada a tarefa operacional. | Alta | ausencia de custom `AdminSite`/agrupamento por fluxo |
| A1F-05 | Data Privacy | Solicitações LGPD ficam 100% read-only no admin; nao ha trilha operacional explicita de tratamento no proprio fluxo de tela. | Media | `DataPrivacyRequestAdmin` sem `change/add/delete` |
| A1F-06 | Library | Acao de clonagem de versao depende de campos extras no dropdown de action, com discoverability baixa para operadores. | Media | `BookVersionActionForm` + action de changelist |
| A1F-07 | Community | Fluxo de moderacao fragmentado em 8 telas sem atalhos de navegacao cruzada entre fila e entidades alvo. | Media | `Report/Post/Comment/UserModeration*` em telas separadas |
| A1F-08 | CaseLaw | Nao ha widget rich text dedicado na edicao de ementa, diferente do padrao adotado em Library/Courses. | Media | `CaseLawAdmin` sem `ModelForm` TinyMCE |
| A1F-09 | Formulacao | Microcopy e labels misturam PT/EN em partes criticas de operacao. | Media | mensagens em `library/admin.py`, `community/admin.py` |
| A1F-10 | Listagens | Falta de vistas operacionais prontas para "pendencias" (ex.: reports abertos, versoes draft, pecas sem publish_at). | Media | ausencia de filtros/default views por fila |
| A1F-11 | UI base | Customizacao visual limitada a CSS de editor/previews, sem base unificada para componentes de admin. | Baixa | apenas `library/static/library/admin/chapter_rich_editor.css` |
| A1F-12 | Onboarding interno | Falta de runbook curto por fluxo administrativo critico no proprio repo da API. | Baixa | README lista recursos, mas sem roteiro por tarefa |

## 5) Backlog priorizado de intervencoes (base para A1-02/A1-03)

Escala:

- Impacto: Alto / Medio / Baixo
- Esforco: P / M / G

| Prioridade | Intervencao | Alvo | Impacto | Esforco |
| --- | --- | --- | --- | --- |
| P1 | Reorganizar navegacao por dominio/tarefa (catalogo operacional do admin em vez de agrupamento tecnico). | A1-02 | Alto | M |
| P2 | Introduzir guardrails para acoes destrutivas de moderacao (confirmacao contextual + nota obrigatoria para remover/banir). | A1-03 | Alto | M |
| P3 | Tornar publish de versao do livro um fluxo explicitamente assistido (pre-flight + feedback claro). | A1-03 | Alto | M |
| P4 | Revisar acoes de estado no banco de pecas com contexto operacional (publicar/arquivar com criterio e feedback). | A1-03 | Alto | P |
| P5 | Padronizar formularios/listagens de library/courses/templates/community com fieldsets/filtros focados em operacao diaria. | A1-03 | Alto | G |
| P6 | Criar atalhos cruzados entre fila de reports e objetos alvo (post/comment/status de usuario). | A1-02 | Medio | M |
| P7 | Adotar editor rich text padrao tambem em jurisprudencia (caselaw). | A1-03 | Medio | P |
| P8 | Padronizar microcopy PT-BR nos fluxos de admin criticos. | A1-02 | Medio | P |
| P9 | Definir vistas operacionais de pendencias (drafts, reports abertos, itens sem publish). | A1-03 | Medio | M |
| P10 | Consolidar base visual de admin (componentes/tokens) sem quebrar comportamento nativo do Django Admin. | A2-01 | Medio | M |
| P11 | Refinar visual das telas com maior frequencia de uso interno. | A2-02 | Medio | M |
| P12 | Publicar runbook operacional curto por fluxo (versoes, moderacao, pecas, notificacoes). | Gate UX / README | Baixo | P |

## 6) Mapa objetivo para as proximas issues

Direcionamento para A1-02 (navegacao/IA):

- reduzir fragmentacao por modelos;
- aproximar telas por jornada operacional;
- padronizar nomenclatura orientada a tarefa.

Direcionamento para A1-03 (formularios/listagens):

- minimizar risco de acao destrutiva;
- melhorar filtros/fieldsets para trabalho diario;
- deixar feedback de estado mais previsivel.

## 7) Checklist de aceite da A1-01

- [x] Inventario de telas e fluxos criticos documentado.
- [x] Friccoes classificadas por severidade (alta/media/baixa).
- [x] Backlog de intervencoes priorizado para A1-02 e A1-03.

## 8) Artefatos derivados para continuidade

- Guia de principios UX do admin para operacao juridica:
  - `docs/ADMIN_PRINCIPIOS_UX_OPERACAO_JURIDICA_2026-03-09.md`
- Proposta concreta de reorganizacao de navegacao (A1-02):
  - `docs/ADMIN_PROPOSTA_ARQUITETURA_A1-02_2026-03-09.md`
