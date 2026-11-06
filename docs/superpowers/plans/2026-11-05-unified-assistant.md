# Assistente único da casa — plano de implementação

**Objetivo:** Uma solicitação em linguagem natural deve receber resposta, consultar ou alterar dados da residência automaticamente; ações sensíveis exigem confirmação explícita.

**Arquitetura:** A tela envia texto, foto opcional e um identificador idempotente para o operador. O servidor decide por ferramentas com acesso restrito à residência, devolve as alterações confirmadas separadamente das propostas pendentes e nunca mostra sucesso de escrita sem retorno da ferramenta.

**Tecnologias:** React, TypeScript, Django REST, Responses API com ferramentas.

## Etapas

- [x] Testar fluxo único da tela: sem seletor, envio automático, resultado de escrita e confirmação genérica.
- [x] Implementar tela única e estado fiel às alterações aplicadas e pendentes.
- [x] Testar contrato do operador: foto, raciocínio sem resposta final, escrita confirmada e falhas de ferramenta.
- [x] Implementar contrato no servidor, instruções e descrições de ferramentas.
- [x] Executar testes, lint, build e revisar diff; integrar e enviar para `tests`.

## Cuidados

- Consultas e respostas não devem anunciar alterações.
- Escritas comuns só aparecem como aplicadas após retorno bem-sucedido da ferramenta.
- Exclusões, convites, troca de proprietário e desativação permanecem propostas pendentes.
- Falhas parciais precisam aparecer claramente, sem apagar o registro de escritas que deram certo.
- A foto deve chegar ao operador no formato aceito pela API.
