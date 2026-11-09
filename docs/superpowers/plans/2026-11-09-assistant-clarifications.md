# Esclarecimentos do assistente da casa — plano de implementação

**Objetivo:** Executar pedidos claros sem perguntas e apresentar alternativas clicáveis quando uma decisão indispensável impedir a execução, preservando o contexto do pedido.

**Arquitetura:** O operador recebe uma ferramenta estruturada de esclarecimento. O servidor guarda o pedido original e as respostas em contexto cifrado, limitado por prazo e vinculado ao usuário e à residência. A tela apresenta as alternativas, aceita também resposta digitada e retoma o mesmo pedido com um identificador idempotente. Propostas de ações sensíveis continuam exigindo confirmação distinta.

**Tecnologias:** Django REST, PostgreSQL/SQLite nos testes, Responses API, React, Mantine e Vitest.

## Tarefas

- [x] Testar e implementar a ferramenta `ask_clarification`, instruções de execução direta e tratamento de perguntas em texto.
- [x] Testar e implementar o contexto cifrado, prazo, seleção e isolamento por usuário e residência.
- [x] Expor a continuação e a recuperação da pergunta pendente na API.
- [x] Testar e implementar alternativas clicáveis, resposta digitada e histórico visível na tela.
- [x] Verificar testes, migração, lint e build.
- [x] Integrar à branch `tests`.

## Casos de revisão

- Pedido claro: a ferramenta de escrita é chamada sem pergunta intermediária.
- Dúvida após leitura: nenhuma escrita ocorre antes da escolha.
- Seleção ou texto livre: o pedido original e as respostas anteriores chegam ao operador.
- Outro usuário ou outra residência: não consegue consultar nem responder à pergunta.
- Escolha repetida ou expirada: não duplica uma escrita e apresenta erro claro.
- Foto anexada: continua disponível na retomada sem expor seu conteúdo em texto aberto no banco.
