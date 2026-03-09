# Proposta de Reorganizacao do Admin (A1-02 / UX-A1.2)

Data: 2026-03-09  
Issue: API #47  
Byte alvo: UX-A1.2  
Base: A1-01 + guia de principios UX para operacao juridica

## 1) Objetivo

Reorganizar a navegacao do Django Admin para que operadores nao-tech do Direito executem fluxos criticos com menos friccao, menos erro e menos troca de contexto.

## 2) Problema atual resumido

- agrupamento por modelos tecnicos dificulta leitura por tarefa;
- moderacao e operacao editorial exigem troca frequente de tela;
- acoes de alto impacto ainda estao proximas de acoes de baixo risco.

## 3) Estrutura alvo de navegacao (orientada a jornada)

Menu operacional proposto:

1. Painel operacional

- atalho para filas criticas do dia;
- acesso rapido a pendencias prioritarias.

2. Livros e publicacoes

- `Book`
- `BookVersion`
- `BookChapter`
- foco em criar, revisar e publicar versoes.

3. Conteudo juridico

- `TemplatePiece`
- `CaseLaw`
- foco em curadoria de pecas e jurisprudencia.

4. Comunidade e moderacao

- `Report`
- `Post`
- `Comment`
- `ReportModerationAction`
- `ModerationConfig`
- `UserModerationStatus`
- `UserModerationEvent`
- `Category`

5. Usuarios e notificacoes

- `Profile`
- `NotificationPreference`
- `NotificationEvent`
- `NotificationDispatch`
- `PushDevice`

6. Privacidade e compliance

- `DataPrivacyRequest`

7. Cursos e eventos

- `CoursePost`
- `CourseAsset`
- `LiveEvent`

## 4) Mapa de tarefas criticas por area

### 4.1 Livros e publicacoes

Tarefas principais:

- criar versao pre-carregada;
- revisar capitulos;
- publicar versao com seguranca.

Atalhos recomendados:

- versoes em draft;
- versoes publicadas recentemente;
- capitulos atualizados nas ultimas 24h.

### 4.2 Conteudo juridico

Tarefas principais:

- cadastrar peca (upload ou URL remota);
- publicar/arquivar peca com contexto;
- revisar jurisprudencia por tribunal e data.

Atalhos recomendados:

- pecas em draft;
- pecas sem `published_at`;
- jurisprudencia atualizada recentemente.

### 4.3 Comunidade e moderacao

Tarefas principais:

- triagem de reports;
- decisao de aprovar/remover/escalar/rejeitar;
- banimento com justificativa quando necessario.

Atalhos recomendados:

- reports `open` e `in_review`;
- reports por prioridade alta;
- usuarios banidos recentemente.

### 4.4 Usuarios e notificacoes

Tarefas principais:

- suporte a preferencias e push;
- leitura de eventos e dispatches com falha.

Atalhos recomendados:

- dispatches com erro;
- devices inativos;
- eventos recentes por tipo.

### 4.5 Privacidade e compliance

Tarefas principais:

- consulta e acompanhamento de solicitacoes de privacidade.

Atalhos recomendados:

- solicitacoes abertas;
- solicitacoes por tipo e data de criacao.

## 5) Proposta de rotulacao (PT-BR operacional)

| Rotulo atual (tecnico) | Rotulo alvo (operacional) |
| --- | --- |
| BookVersion | Versoes do livro |
| TemplatePiece | Pecas juridicas |
| Report | Fila de reports |
| UserModerationStatus | Status de moderacao do usuario |
| NotificationDispatch | Envios de notificacao |
| DataPrivacyRequest | Solicitacoes de privacidade |

Observacao: manter nome tecnico interno do modelo e ajustar rotulo exibido no admin.

## 6) Como implementar sem regressao

Passo 1 - reorganizacao de labels e menu

- ajustar `verbose_name`/`verbose_name_plural` nos modelos quando necessario;
- usar agrupamento por app/jornada no admin para leitura operacional;
- preservar regras de permissao atuais por perfil (`staff`, `moderator`, etc.).

Passo 2 - painel operacional com links de fila

- incluir uma pagina inicial de operacao com links para listas filtradas;
- priorizar filas: reports abertos, versoes draft, pecas em draft.

Passo 3 - navegacao cruzada entre telas relacionadas

- incluir links de contexto em listas de moderacao;
- aproximar report, alvo (post/comment) e historico da decisao.

## 7) Criticos para aceitar A1-02

- menu principal permite localizar fluxos sem conhecimento tecnico do modelo;
- tarefas principais exigem menos troca de tela;
- nomenclatura do admin fica consistente e operacional em PT-BR;
- permissoes existentes continuam funcionando sem regressao.

## 8) Entregaveis esperados de A1-02

1. Estrutura de navegacao implementada.
2. Rotulos operacionais aplicados.
3. Atalhos de filas criticas funcionais.
4. Testes de smoke do admin para acesso/permissoes principais.
