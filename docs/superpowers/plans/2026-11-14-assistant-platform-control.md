# Controle amplo do Home OS pelo assistente

## Objetivo

Dar ao assistente acesso operacional aos dados e ações que a plataforma oferece, sem perder escopo por usuário/residência, idempotência, prévia de exclusões nem atualização imediata da tela.

## Contrato

- Consultas incluem IDs e registros ativos e inativos. Busca por entidade e nome/ID permite encontrar registros além dos primeiros 100 resultados; retornos são limitados e não incluem segredos.
- Pedidos claros usam ferramentas de escrita diretamente. Detalhes indispensáveis ausentes usam esclarecimento estruturado. Exclusões e mudanças sensíveis usam proposta com confirmação.
- Ampliar ferramentas para editar metadados de listas, categorias financeiras e residência; criar/ajustar estoque quando o produto ainda não tem item.
- Todas as mutações usam serviços de domínio quando existentes, validam o usuário e a residência no servidor, registram auditoria e preservam idempotência por solicitação.
- A interface mostra mudanças confirmadas e atualiza o painel sem recarga manual.

## Implementação e verificação

1. Testar consultas de registros inativos, IDs de estoque e busca paginada/por nome; observar falhas, implementar e verificar.
2. Testar e implementar as operações de escrita que faltam, com validação e escopo.
3. Confirmar que as propostas sensíveis existentes continuam exigindo confirmação e que a interface atualiza os dados após ações aplicadas.
4. Rodar suíte do assistente, lint, verificações do Django e integrar à branch `tests`.
