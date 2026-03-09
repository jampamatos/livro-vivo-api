# Guia de Principios UX do Admin para Operacao Juridica

Data: 2026-03-09  
Escopo: A1-02 (navegacao/IA) e A1-03 (formularios/listagens)  
Base: auditoria A1-01 (`docs/ADMIN_AUDITORIA_FUNCIONAL_A1-01_2026-03-09.md`)

## 1) Premissa do produto

O admin do Livro Vivo e uma ferramenta de operacao para pessoas do Direito.  
Quem publica versoes, organiza conteudo e faz moderacao nao precisa ser da area tech.

Decisao de produto: a UX do admin deve priorizar clareza operacional, seguranca de decisao e velocidade de execucao para publico nao-tech.

## 2) Perfis operacionais alvo

1. Operacao editorial juridica

- publica livros e versoes;
- revisa capitulos e changelog;
- precisa reduzir risco em acoes de publish.

2. Curadoria de conteudo juridico

- publica/arquiva pecas e jurisprudencia;
- valida metadados, tags e qualidade de texto;
- precisa de formulario objetivo e filtros por pendencia.

3. Moderacao de comunidade

- triagem de reports;
- decisoes de aprovar, remover, escalar e banir;
- precisa de guardrails para acoes de alto impacto.

4. Suporte/compliance

- consulta eventos, dispatches e dispositivos;
- acompanha solicitacoes de privacidade;
- precisa de trilha de auditoria e linguagem clara.

## 3) Principios obrigatorios

1. Linguagem de negocio (PT-BR)

- usar rotulos orientados a tarefa: "Publicar versao", "Arquivar peca", "Fila de reports";
- remover jargao tecnico sempre que possivel;
- manter consistencia terminologica entre telas.

2. Navegacao por jornada operacional

- organizar por fluxo real do trabalho e nao por estrutura de modelo;
- aproximar telas que sao usadas na mesma tarefa;
- reduzir mudanca de contexto entre listagem, detalhe e decisao.

3. Contexto antes da acao

- cada tela deve responder "o que e isso?", "o que devo fazer agora?" e "o que acontece depois?";
- acoes com impacto devem mostrar resumo de estado atual e efeito esperado.

4. Seguranca para estados perigosos

- publish/remove/ban/arquivar exigem confirmacao contextual;
- quando aplicavel, exigir justificativa para rastreabilidade;
- evitar acoes em massa sem feedback de resultado.

5. Previsibilidade de fluxo

- padronizar onde ficam filtros, acoes e mensagens;
- evitar variacao de microcopy para a mesma acao;
- sucesso e erro devem apontar o proximo passo.

6. Carga cognitiva baixa

- destacar apenas 1-2 acoes principais por tela;
- usar fieldsets por objetivo operacional;
- esconder ruido tecnico que nao ajuda a decisao.

7. Rastreabilidade e auditoria

- registrar quem decidiu, quando e com qual justificativa;
- facilitar leitura de historico em linguagem operacional;
- preservar trilha para casos de revisao interna.

## 4) Regras praticas por tipo de tela

### 4.1 Listagens

- filtros prontos para pendencias reais ("abertos", "draft", "aguardando publicacao");
- colunas com prioridade, estado e ultima atualizacao;
- acoes em massa separadas por risco.

### 4.2 Formularios

- ordem dos campos segue a ordem de decisao do operador;
- campos de risco ficam em bloco proprio, com texto de contexto;
- campos tecnicos ficam em blocos secundarios.

### 4.3 Confirmacoes e guardrails

- confirmar impacto: "voce esta prestes a...";
- mostrar quantidade de itens afetados;
- pedir nota obrigatoria em acoes destrutivas.

### 4.4 Feedback

- sucesso: confirmar o que foi feito + proximo passo recomendado;
- erro: explicar motivo em linguagem simples + como corrigir;
- aviso: sinalizar risco sem bloquear quando houver opcao segura.

## 5) Criterios de aceitacao UX (publico nao-tech)

Uma entrega de admin so e aceita se:

- um operador nao-tech consegue concluir o fluxo critico sem ajuda da equipe de desenvolvimento;
- a tela usa termos operacionais e nao termos de engenharia;
- acoes de alto risco possuem guardrail explicito;
- o caminho de navegacao reduz cliques e troca de tela desnecessaria.

## 6) Metricas para validar na pratica

1. Tempo de execucao por tarefa critica (antes vs depois).
2. Taxa de erro operacional em publish/moderacao.
3. Numero de pedidos de suporte para executar rotinas do admin.
4. Tempo para treinamento de novo operador interno.

## 7) Aplicacao direta nas proximas issues

A1-02 (navegacao/IA):

- reorganizar menu e labels por jornada;
- incluir atalhos para filas operacionais;
- padronizar nomes em PT-BR.

A1-03 (formularios/listagens):

- revisar fieldsets/filtros com foco em decisao;
- separar acoes por risco e incluir confirmacoes;
- tornar feedback de acao mais claro e acionavel.
