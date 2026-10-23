# Home OS — Plano de desenvolvimento

**Versão:** 1.0
**Data:** 2026-10-23
**Objetivo:** desenvolver localmente uma aplicação residencial modular para finanças compartilhadas, compras/estoque e tarefas, preparada para implantação em VPS com Docker Compose e Traefik.

---

## 1. Instruções para o Codex

Use este documento como plano de implementação do projeto Home OS.

### Regras de trabalho

1. Antes de implementar, inspecione o repositório existente e preserve código e decisões válidas.
2. Se o repositório estiver vazio, crie a estrutura descrita neste plano.
3. Implemente em fases pequenas, funcionais e verificáveis. Não tente gerar todo o sistema em uma única alteração.
4. Antes de cada fase, apresente um resumo curto do que será feito e dos arquivos que provavelmente serão alterados.
5. Ao concluir cada fase:
   - execute os testes relevantes;
   - corrija falhas introduzidas;
   - atualize este arquivo marcando os itens concluídos;
   - documente comandos para executar e validar a funcionalidade.
6. Não remova funcionalidades nem sobrescreva arquivos existentes sem necessidade clara.
7. Não coloque segredos, tokens, senhas ou dados pessoais reais no repositório.
8. Não afirme que um teste passou se ele não foi executado.
9. Prefira soluções simples e explícitas a abstrações prematuras.
10. Se houver uma decisão bloqueadora ou ambiguidade relevante, explique o impacto e faça uma pergunta antes de escolher uma solução irreversível.

### Escopo inicial

O MVP inclui:
- contas individuais;
- residências e membros;
- orçamento e despesas compartilhadas;
- divisão configurável de despesas;
- listas de compras;
- catálogo de produtos e histórico de preços;
- compras registradas e controle básico de estoque;
- tarefas, responsáveis, prazos e recorrências básicas;
- dashboard consolidado;
- testes, segurança e execução local por Docker Compose.

A integração de IA será um componente opcional e isolado. Não deve bloquear o MVP.

---

## 2. Objetivos e princípios arquiteturais

### Objetivos

- Permitir que duas ou mais pessoas compartilhem a gestão de uma residência.
- Manter finanças, compras e tarefas em módulos separados, mas integrados.
- Preservar histórico de alterações importantes.
- Evitar inconsistências financeiras e de estoque.
- Ser executável localmente e implantável posteriormente em um VPS.
- Permitir acrescentar módulos sem reescrever a base da aplicação.

### Princípios

- Monólito modular, não microsserviços.
- Backend como autoridade para validações e permissões.
- PostgreSQL como fonte persistente dos dados.
- Dinheiro armazenado em centavos inteiros ou `Decimal`, nunca `float`.
- Datas e horários armazenados com timezone; residência possui fuso horário configurável.
- Toda entidade compartilhada pertence a uma residência, diretamente ou por relacionamento validado.
- Operações que alterem vários registros relacionados devem usar transações.
- Endpoints versionados em `/api/v1/`.
- IA não executa SQL arbitrário nem ignora permissões.
- Funcionalidades essenciais devem funcionar mesmo sem o provedor de IA.

---

## 3. Stack técnica proposta

### Backend
- Python em versão estável suportada pelas dependências selecionadas.
- Django.
- Django REST Framework.
- PostgreSQL.
- Testes com Django TestCase ou pytest/pytest-django.
- Documentação OpenAPI, por exemplo com `drf-spectacular`.

### Frontend
- React.
- TypeScript.
- Vite.
- React Router.
- Biblioteca de requisições HTTP centralizada.
- Vitest e React Testing Library.
- Playwright para testes ponta a ponta.

Escolha versões estáveis compatíveis e fixe versões/dependências no projeto. Não atualize major versions sem necessidade.

### Infraestrutura
- Docker Compose para desenvolvimento local.
- PostgreSQL em container com volume persistente.
- Traefik na implantação futura.
- Arquivo `.env.example` com nomes de variáveis e valores fictícios.
- Nenhuma senha ou chave real versionada.

### Decisão de autenticação
Usar autenticação própria do Home OS para usuários e sessões da aplicação. A conexão com IA, caso habilitada, é uma autorização adicional e não substitui o login do Home OS.

Para uma aplicação web, avaliar sessão por cookie seguro e proteção CSRF. Não armazenar tokens de sessão em `localStorage`. Se a implementação escolher JWT por uma razão técnica justificada, documentar armazenamento, expiração, renovação e revogação com atenção especial à segurança.

---

## 4. Estrutura inicial do repositório

```text
home-os/
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── households/
│   │   ├── finance/
│   │   ├── shopping/
│   │   ├── inventory/
│   │   ├── chores/
│   │   ├── assistant/
│   │   └── audit/
│   ├── common/
│   ├── tests/
│   ├── Dockerfile
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── modules/
│   │   │   ├── dashboard/
│   │   │   ├── finance/
│   │   │   ├── shopping/
│   │   │   ├── inventory/
│   │   │   └── chores/
│   │   ├── components/
│   │   ├── services/
│   │   └── test/
│   ├── Dockerfile
│   └── package.json
├── deploy/
│   └── README.md
├── docs/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── PLAN.md
└── README.md
```

Cada app Django deve separar responsabilidades, quando fizer sentido:
- `models.py`: modelos persistentes;
- `serializers.py`: validação e representação da API;
- `services.py`: comandos e regras de negócio;
- `selectors.py`: consultas e relatórios;
- `views.py`/`api.py` e `urls.py`: endpoints;
- `tests/`: testes do domínio.

Não crie camadas vazias apenas para seguir o padrão. Mantenha o código pequeno enquanto o domínio for simples.

---

## 5. Modelo de domínio e dados

Os nomes abaixo são conceituais. Defina nomes consistentes em inglês no código e apresente a interface ao usuário em português.

### 5.1 Contas e residência

#### `User`
- id
- email único normalizado
- nome
- password hash gerenciado pelo Django, caso haja senha local
- is_active
- timestamps

#### `Household`
- id
- name
- currency (inicialmente `BRL`)
- timezone
- created_by
- timestamps

#### `Membership`
- id
- household
- user
- role: `owner`, `member`, `viewer`
- status: `active`, `invited`, `removed`
- joined_at
- restrição única para household + user

#### `Invitation` (fase posterior da fundação, se necessária)
- household
- email
- token armazenado de forma segura, preferencialmente hash
- expires_at
- accepted_at
- created_by

### 5.2 Auditoria

#### `AuditEvent`
- household
- actor
- action
- entity_type
- entity_id
- timestamp
- metadata JSON com dados não secretos e minimizados

Não registrar senhas, tokens, conteúdo sensível desnecessário ou credenciais nos logs.

### 5.3 Finanças

#### `ExpenseCategory`
- household
- name
- kind
- is_active

#### `Expense`
- household
- description
- category
- amount_minor (inteiro em centavos)
- currency
- incurred_on
- created_by
- paid_by (opcional)
- status
- notes (opcional)
- timestamps

#### `ExpenseSplit`
- expense
- membership
- amount_minor
- share_percent (opcional, para registrar a regra aplicada)
- status ou valor liquidado, conforme modelo escolhido

#### `Payment`
- household
- expense (ou vínculo de acerto definido pelo domínio)
- payer
- amount_minor
- paid_at
- notes opcionais

#### `Budget`
- household
- category opcional (nulo significa orçamento geral)
- period_start
- amount_minor
- currency

#### `RecurringExpense` (pode ficar fora do MVP se ameaçar o prazo)
- household
- descrição/categoria/valor
- regra de divisão
- recurrence rule
- next_run_at
- is_active

**Invariantes financeiros:**
- A soma de `ExpenseSplit.amount_minor` deve ser igual ao valor da despesa.
- Valores devem ser positivos, exceto se houver um fluxo explícito para estornos.
- Arredondamento de divisões percentuais deve ocorrer em centavos e ser determinístico; a soma final deve fechar exatamente.
- Registrar uma despesa não significa que ela foi paga.
- Não duplicar o valor total da despesa ao registrar suas parcelas.
- Definir claramente o significado de “saldo a acertar” e cobrir com testes.
- Mudanças de divisão devem ser atômicas.
- Não excluir fisicamente registros financeiros relevantes sem uma política explícita; preferir cancelamento/estorno auditável.

### 5.4 Compras e estoque

#### `Product`
- household
- name
- brand opcional
- category opcional
- package_quantity opcional
- package_unit opcional (g, kg, ml, l, unit)
- barcode opcional
- is_active

#### `ProductAlias`
- product
- alias
- source opcional

#### `PriceObservation`
- household
- product
- store_name opcional
- price_minor
- observed_at
- quantity/unit observados
- source: `manual`, `label_photo`, `purchase`
- attachment opcional

#### `ShoppingList`
- household
- name
- status: `active`, `completed`, `archived`
- created_by
- timestamps

#### `ShoppingListItem`
- shopping_list
- product opcional (permitir item livre)
- free_text_name opcional
- quantity
- unit opcional
- priority
- status: `needed`, `purchased`, `skipped`
- added_by
- notes opcionais

#### `Purchase`
- household
- purchased_at
- store_name opcional
- total_amount_minor
- created_by
- idempotency key ou mecanismo equivalente para evitar duplicação acidental

#### `PurchaseItem`
- purchase
- product
- quantity
- unit_price_minor
- line_total_minor
- quantidade/unidade efetivamente comprada

#### `InventoryItem`
- household
- product
- quantity_on_hand (tipo decimal apropriado, não float)
- unit
- updated_at

#### `InventoryEvent`
- inventory_item
- event_type: `purchase`, `consumption`, `adjustment`, `loss`, `correction`
- quantity_delta
- occurred_at
- created_by
- source_purchase_item opcional
- notes opcionais

**Invariantes de compras e estoque:**
- Confirmar uma compra deve criar o registro da compra, itens, observações de preço e entradas de estoque de forma atômica.
- Repetir a mesma requisição não pode duplicar compra ou movimentos se houver uma chave de idempotência.
- O saldo do estoque deve ser conciliável com o histórico de movimentos.
- Permitir saldo negativo apenas se houver uma decisão explícita; padrão recomendado: bloquear ou exigir ajuste justificado.
- Itens livres na lista podem existir sem cadastro canônico de produto.
- Uma foto de etiqueta cria dados candidatos; o usuário confirma antes de gravar preço/estoque/finanças.
- Preço observado não é necessariamente preço efetivamente pago; manter essa distinção.

### 5.5 Tarefas

#### `Chore`
- household
- title
- description opcional
- category opcional
- recurrence_rule opcional
- is_active
- created_by

#### `ChoreAssignment`
- chore
- membership
- regra ou posição de rodízio, se aplicável

#### `ChoreOccurrence`
- chore
- due_at
- assigned_to opcional
- status: `pending`, `completed`, `skipped`, `cancelled`
- completed_at
- created_at

#### `ChoreCompletion`
Pode ser um registro separado ou campos de conclusão em `ChoreOccurrence`. Escolher a opção mais simples que preserve histórico suficiente.

**Invariantes de tarefas:**
- Uma ocorrência recorrente não deve ser gerada duas vezes para a mesma tarefa e período.
- Concluir uma ocorrência não apaga a definição da tarefa.
- A recorrência deve usar o fuso horário da residência.
- Mudanças futuras na regra não devem reescrever o histórico concluído.

### 5.6 IA opcional

#### `AIConnection`
- user
- provider
- status
- scopes/permissões concedidas, quando aplicável
- connected_at
- metadados mínimos, sem tokens sensíveis

#### `AIRequestLog`
- user
- household opcional
- purpose
- status
- created_at
- metadados de uso apenas quando disponíveis

#### `AIActionProposal`
- household
- requested_by
- action_type
- payload validado
- status: `pending`, `approved`, `rejected`, `executed`, `failed`
- expires_at
- executed_at

**Regras de IA:**
- Não guardar tokens OAuth persistentes no banco do VPS sem que o fluxo oficial permita explicitamente esse armazenamento.
- Não compartilhar a conexão de um morador com outro.
- Não assumir que a assinatura ChatGPT/Codex dá acesso ilimitado ou autoriza qualquer uso em aplicações hospedadas.
- Validar elegibilidade, fluxo OAuth, armazenamento permitido, limites e regras de automação antes de integrar.
- Criar uma interface `AIProvider` substituível.
- Se o conector não estiver configurado, retornar um erro funcional claro e manter os outros módulos operacionais.
- A IA não deve executar operações financeiras automaticamente sem uma confirmação explícita apropriada.
- Validar todo JSON produzido pelo modelo contra schemas internos.
- Não aceitar instruções recebidas em fotos ou outros conteúdos externos como comandos privilegiados.

---

## 6. API REST planejada

Prefixo global: `/api/v1/`.

Todas as operações de residência devem verificar, no backend, que o usuário possui membership ativo na residência correspondente.

### Autenticação e residência

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/auth/login` | Login |
| `POST` | `/auth/logout` | Logout |
| `GET` | `/me` | Usuário atual |
| `GET` | `/households` | Residências do usuário |
| `POST` | `/households` | Criar residência |
| `GET` | `/households/{id}` | Consultar residência |
| `GET` | `/households/{id}/members` | Listar membros |
| `POST` | `/households/{id}/invitations` | Criar convite, se implementado |
| `POST` | `/invitations/{token}/accept` | Aceitar convite, se implementado |

### Finanças

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/households/{id}/expenses` | Listar despesas com filtros/paginação |
| `POST` | `/households/{id}/expenses` | Criar despesa e divisão |
| `GET` | `/expenses/{id}` | Detalhar despesa |
| `PATCH` | `/expenses/{id}` | Editar campos permitidos |
| `POST` | `/expenses/{id}/payments` | Registrar pagamento |
| `PUT` | `/expenses/{id}/splits` | Substituir divisão de forma atômica |
| `GET` | `/households/{id}/budgets` | Consultar orçamentos |
| `PUT` | `/households/{id}/budgets/{period}` | Definir orçamento do período |
| `GET` | `/households/{id}/financial-summary` | Resumo financeiro |
| `GET` | `/households/{id}/settlements` | Resumo de saldos/acertos |

### Compras e estoque

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/households/{id}/products` | Pesquisar produtos |
| `POST` | `/households/{id}/products` | Criar produto |
| `POST` | `/households/{id}/price-observations` | Registrar preço observado |
| `GET` | `/households/{id}/shopping-lists` | Listar listas |
| `POST` | `/households/{id}/shopping-lists` | Criar lista |
| `POST` | `/shopping-lists/{id}/items` | Adicionar item |
| `PATCH` | `/shopping-items/{id}` | Atualizar quantidade/status |
| `POST` | `/households/{id}/purchases` | Confirmar compra e seus itens |
| `GET` | `/households/{id}/inventory` | Consultar estoque |
| `POST` | `/inventory/{id}/events` | Registrar consumo/ajuste |
| `POST` | `/households/{id}/attachments` | Upload de imagem, se implementado |

### Tarefas

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/households/{id}/chores` | Listar tarefas |
| `POST` | `/households/{id}/chores` | Criar tarefa |
| `PATCH` | `/chores/{id}` | Editar tarefa |
| `GET` | `/households/{id}/chore-occurrences` | Listar ocorrências |
| `POST` | `/chore-occurrences/{id}/complete` | Concluir ocorrência |
| `POST` | `/chores/{id}/assignments` | Definir responsáveis |

### IA opcional, somente após validação de elegibilidade

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/ai/status` | Estado da integração |
| `POST` | `/ai/interpret-product-label` | Extrair campos candidatos de uma etiqueta |
| `POST` | `/ai/assistant` | Perguntar ao assistente |
| `POST` | `/ai/proposals/{id}/approve` | Aprovar proposta |
| `POST` | `/ai/proposals/{id}/reject` | Rejeitar proposta |

### Convenções da API

- Retornar códigos HTTP apropriados (`400`, `401`, `403`, `404`, `409`, `422` quando fizer sentido e `500` sem expor detalhes internos).
- Usar paginação em listas extensas.
- Validar filtros e ordenar de forma explícita.
- Documentar contratos com OpenAPI.
- Não expor IDs ou dados de outra residência.
- Usar transações para operações compostas.
- Implementar idempotência em operações que possam ser repetidas por timeout ou reenvio.
- Nunca confiar em valores de total enviados pelo frontend sem recalcular/validar no backend.

---

## 7. Fases de implementação

### Fase 0 — Inspeção, setup e decisões técnicas

**Estimativa:** 1–2 dias.

Tarefas:
- [x] Inspecionar o repositório e o ambiente local: inicialmente continha apenas este plano; Docker CLI está disponível, mas o daemon Linux não está ativo.
- [x] Criar ou validar `.gitignore` e `.env.example` com valores ilustrativos e sem segredos reais.
- [x] Criar Dockerfiles e Compose de desenvolvimento (execução integrada ainda não exercitada, pois o daemon está indisponível).
- [x] Configurar Django, DRF e PostgreSQL; o endpoint verifica a conectividade ao banco. A conexão a PostgreSQL real ainda não foi exercitada.
- [x] Configurar React, TypeScript e Vite.
- [x] Criar health check e endpoint `/api/v1/health`.
- [x] Definir lint, formatação e comandos de teste; verificações locais estão documentadas no `README.md`.
- [ ] Prototipar separadamente a elegibilidade e o fluxo de autorização da IA. Decisão explicitamente pendente e não bloqueante; nenhum fluxo foi prototipado nesta fase.

Critérios de aceite:
- [ ] Aplicação inicia com um comando documentado. Compose não executado: Docker Desktop Linux está indisponível.
- [ ] Backend conecta ao PostgreSQL. Verificação de conectividade está implementada e coberta com mocks, mas banco real não foi conectado.
- [ ] Frontend consegue consultar o health endpoint. Consulta e testes de componente foram implementados; integração frontend/API ao vivo não foi exercitada.
- [x] Nenhum segredo real foi adicionado; `.env.example` contém apenas valores fictícios para desenvolvimento local.
- [x] Decisão sobre IA está documentada como pendente e não bloqueia o MVP.

**Progresso verificado:** testes do endpoint (com conexão simulada), testes do frontend, lint, formatação e build do frontend foram executados localmente. Compose, banco PostgreSQL ao vivo e integração frontend/API não foram exercitados por indisponibilidade do daemon Docker.

### Fase 1 — Contas, residência e permissões

**Estimativa:** 3–5 dias.

Tarefas:
- [ ] Configurar modelo de usuário apropriado antes da primeira migração.
- [ ] Implementar login/logout e sessão segura.
- [ ] Implementar `Household` e `Membership`.
- [ ] Implementar criação de residência.
- [ ] Implementar inclusão de segundo membro (convite ou fluxo inicial administrativo seguro).
- [ ] Criar verificações reutilizáveis de membership e papel.
- [ ] Criar layout autenticado e navegação principal.
- [ ] Criar testes de isolamento entre residências.

Critérios de aceite:
- [ ] Dois usuários independentes podem participar da mesma residência.
- [ ] Um usuário não acessa dados de residência alheia manipulando URLs.
- [ ] Rotas privadas exigem autenticação.
- [ ] Logout invalida a sessão.
- [ ] O papel `viewer`, se implementado, não consegue escrever.

### Fase 2 — Finanças básicas

**Estimativa:** 4–6 dias.

Tarefas:
- [ ] Implementar categorias.
- [ ] Implementar criação/listagem/detalhe de despesas.
- [ ] Implementar divisões iguais, percentuais e valores fixos.
- [ ] Implementar pagamentos.
- [ ] Implementar orçamento mensal.
- [ ] Implementar resumo financeiro.
- [ ] Implementar audit log para alterações relevantes.
- [ ] Criar interface para cadastrar e visualizar despesas.
- [ ] Cobrir arredondamento e saldo a acertar com testes.

Critérios de aceite:
- [ ] Despesa de R$ 300,00 dividida igualmente gera R$ 150,00 por pessoa.
- [ ] A soma das parcelas fecha exatamente o valor da despesa.
- [ ] Pagamento parcial não marca automaticamente a despesa como totalmente paga.
- [ ] Totais do dashboard correspondem aos registros.
- [ ] Operações inválidas não persistem dados parcialmente.

### Fase 3 — Compras e estoque

**Estimativa:** 4–6 dias.

Tarefas:
- [ ] Implementar catálogo de produtos e aliases básicos.
- [ ] Implementar listas compartilhadas e itens livres.
- [ ] Implementar observações de preços.
- [ ] Implementar registro de compra e itens.
- [ ] Implementar movimentos e saldo de estoque.
- [ ] Integrar compra com despesa financeira sem duplicar valores.
- [ ] Implementar idempotência para confirmação de compra.
- [ ] Criar interface de lista, catálogo, compra e estoque.
- [ ] Adicionar suporte a upload somente se o fluxo principal já estiver estável.

Critérios de aceite:
- [ ] Os dois moradores veem a lista compartilhada.
- [ ] Confirmar uma compra atualiza financeiro e estoque uma única vez.
- [ ] O saldo pode ser conciliado com o histórico de movimentos.
- [ ] Preço observado e preço efetivamente pago são diferenciados.
- [ ] Cadastro manual funciona sem integração de IA.

### Fase 4 — Tarefas e rotinas

**Estimativa:** 2–4 dias.

Tarefas:
- [ ] Implementar tarefas, categorias e responsáveis.
- [ ] Implementar prazo e status.
- [ ] Implementar conclusão e histórico.
- [ ] Implementar recorrências básicas com timezone da residência.
- [ ] Evitar ocorrências duplicadas.
- [ ] Criar interface de tarefas pendentes e concluídas.
- [ ] Criar testes para mudança de horário e recorrência.

Critérios de aceite:
- [ ] Cada morador vê as tarefas atribuídas e compartilhadas conforme as permissões.
- [ ] Concluir tarefa preserva o histórico.
- [ ] Reprocessar a geração de recorrências não duplica ocorrências.
- [ ] Datas são exibidas no fuso horário configurado.

### Fase 5 — Dashboard integrado e estabilização do MVP

**Estimativa:** 2–4 dias.

Tarefas:
- [ ] Criar dashboard com gastos, orçamento, acertos, lista e tarefas.
- [ ] Implementar estados de carregamento, vazio e erro.
- [ ] Melhorar validação e mensagens de erro.
- [ ] Executar testes de integração e ponta a ponta.
- [ ] Configurar logging sem segredos.
- [ ] Documentar backup e restauração.
- [ ] Testar build de produção local.

Critérios de aceite:
- [ ] O dashboard usa dados reais da API.
- [ ] Os principais fluxos funcionam em desktop e celular.
- [ ] Testes críticos passam.
- [ ] O MVP funciona sem IA.
- [ ] Existe procedimento documentado para restaurar o banco.

### Fase 6 — IA opcional e preparação de produção

**Estimativa:** 3–6 dias de implementação após validar o conector; pode haver espera por elegibilidade/acesso.

Tarefas:
- [ ] Validar o método de autorização permitido para este cenário.
- [ ] Implementar `AIProvider` e uma implementação concreta somente se elegível.
- [ ] Garantir que cada morador autorize a própria conexão, se necessário.
- [ ] Implementar interpretação de etiqueta com schema estruturado.
- [ ] Mostrar os dados extraídos para confirmação antes de persistir.
- [ ] Implementar limites, timeout, tratamento de falhas e logs mínimos.
- [ ] Implementar propostas de ação e aprovação explícita.
- [ ] Testar falhas de provedor e respostas inválidas.
- [ ] Preparar configuração de VPS, Traefik, HTTPS e backups externos.

Critérios de aceite:
- [ ] A ausência da conexão de IA não afeta os módulos essenciais.
- [ ] Tokens não são compartilhados entre usuários.
- [ ] Nenhuma ação financeira é executada a partir de saída não validada.
- [ ] Dados extraídos de imagem exigem confirmação.
- [ ] A integração cumpre as regras do fluxo oficial utilizado.

**Estimativa agregada:** aproximadamente 16–27 dias úteis para o MVP e estabilização, mais o tempo variável da integração de IA e da implantação. As estimativas são orientativas, não garantias.

---

## 8. Interface e experiência do usuário

### Navegação principal

- Dashboard
- Finanças
- Compras
- Estoque
- Tarefas
- Configurações da residência

### Dashboard inicial

Exibir:
- gastos do mês e orçamento restante;
- despesas pendentes e acertos entre moradores;
- itens da lista de compras;
- tarefas atrasadas ou próximas do prazo;
- ações rápidas para adicionar despesa, produto ou tarefa.

### Requisitos de UX

- Interface em português brasileiro.
- Valores em BRL com formato local.
- Layout responsivo e utilizável em celular.
- Estados de loading, vazio, sucesso e erro.
- Formulários com validação e mensagens acionáveis.
- Confirmação para ações destrutivas ou financeiramente relevantes.
- Não depender de cor isoladamente para comunicar status.
- Acessibilidade básica: labels, foco de teclado e contraste adequado.

---

## 9. Segurança e privacidade

- Todas as rotas protegidas devem verificar autenticação e autorização no servidor.
- A autorização deve considerar o membership ativo na residência.
- Validar uploads por tamanho, extensão e conteúdo; não confiar apenas no `Content-Type`.
- Não publicar PostgreSQL na interface pública do VPS.
- Usar HTTPS e cookies seguros em produção.
- Configurar CSRF e CORS de forma restritiva.
- Aplicar rate limiting nos endpoints sensíveis, especialmente login e IA.
- Não registrar senhas, cookies, tokens, chaves ou imagens em logs de aplicação.
- Minimizar dados enviados a provedores externos.
- Definir política de retenção e exclusão de anexos.
- Registrar operações financeiras relevantes em auditoria.
- Manter dependências atualizadas e verificar vulnerabilidades.
- Usar backups criptografados quando suportado pelo ambiente e testar restauração.
- Não assumir que um arquivo `.env` é seguro se tiver permissões abertas ou estiver incluído no backup público.

---

## 10. Estratégia de testes

### Backend

- Testes unitários para divisão de despesas, arredondamento, orçamento, saldo e movimentos de estoque.
- Testes de API para todos os endpoints principais.
- Testes de autorização com usuário sem membership, membro de outra residência e usuário `viewer`.
- Testes de transação: falha no meio da compra não pode deixar registros parciais.
- Testes de idempotência: repetir requisição não duplica movimentos.
- Testes de recorrência e timezone.

### Frontend

- Testes de componentes e formulários com Vitest/React Testing Library.
- Testes de validação, erros da API e estados vazios.
- Testes responsivos para fluxos críticos.

### Ponta a ponta

Com Playwright, validar pelo menos:
1. Criar conta e residência.
2. Adicionar segundo morador.
3. Registrar uma despesa e dividir entre duas pessoas.
4. Registrar pagamento e consultar saldo.
5. Criar lista, adicionar produto e confirmar compra.
6. Verificar atualização do estoque e financeiro.
7. Criar tarefa, atribuir responsável e concluir.
8. Verificar bloqueio de acesso a outra residência.

### Testes de IA

- Usar respostas simuladas no CI; não exigir chamadas pagas para a suíte padrão.
- Testar JSON inválido, baixa confiança, timeout, limite excedido e provedor indisponível.
- Confirmar que nenhuma mutação acontece antes da aprovação.
- Testar que conteúdo malicioso presente em uma imagem não altera permissões nem instruções do sistema.

### Critérios mínimos antes de cada release

- Todos os testes unitários e de integração críticos passam.
- Migrações são aplicadas em banco limpo e em cópia de versão anterior.
- Build de frontend e backend passa.
- Nenhum segredo é detectado no diff.
- Fluxos críticos de autorização foram testados.
- Backup e restauração foram validados antes da primeira publicação em produção.

---

## 11. Desenvolvimento local

O projeto deve documentar um fluxo semelhante a:

```bash
# Copiar as variáveis de exemplo e preencher valores locais
cp .env.example .env

# Iniciar serviços
docker compose up --build -d

# Aplicar migrações
docker compose exec backend python manage.py migrate

# Criar usuário administrador de desenvolvimento
docker compose exec backend python manage.py createsuperuser

# Executar testes do backend
docker compose exec backend python manage.py test

# Consultar logs
docker compose logs -f backend frontend db
```

Ajuste os comandos de acordo com os nomes reais dos serviços definidos no Compose.

### Variáveis esperadas

O `.env.example` pode conter nomes como:
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL` ou variáveis `POSTGRES_*`
- `CSRF_TRUSTED_ORIGINS`
- `PUBLIC_APP_URL`
- configurações opcionais do conector de IA, somente quando necessárias

Use valores locais fictícios no exemplo. Não incluir chaves reais.

---

## 12. Implantação futura no VPS

- [ ] Definir domínio e DNS.
- [ ] Conectar serviços à rede externa correta do Traefik.
- [ ] Configurar routers, entrypoints, TLS e certificados.
- [ ] Garantir que o backend só seja exposto pelas rotas previstas.
- [ ] Manter o banco sem portas públicas.
- [ ] Definir health checks e política de reinício.
- [ ] Configurar backup externo de PostgreSQL e anexos.
- [ ] Documentar atualização, rollback e recuperação.
- [ ] Definir limites de upload e armazenamento.
- [ ] Verificar logs, métricas e alertas de disco.
- [ ] Testar restauração em ambiente isolado.

O Compose de desenvolvimento pode diferir do Compose de produção. Não copie segredos nem exponha serviços internos por conveniência.

---

## 13. Definition of Done

Uma funcionalidade está concluída quando:
1. A regra de negócio está implementada no backend.
2. Entradas inválidas são rejeitadas com erros claros.
3. Permissões são verificadas no servidor.
4. Dados são persistidos com migrações.
5. A interface cobre estados de sucesso, carregamento, vazio e erro.
6. Testes unitários e de integração relevantes foram executados.
7. A documentação de uso foi atualizada.
8. Logs não revelam segredos.
9. Operações compostas são transacionais e idempotentes quando necessário.
10. Os critérios de aceite da fase foram demonstrados.

---

## 14. Próxima ação recomendada para o Codex

Comece pela **Fase 0**. Inspecione o repositório, informe o estado atual, identifique ferramentas e dependências existentes e proponha um plano de arquivos. Em seguida, implemente apenas o setup inicial e o health check, execute os testes e atualize este documento.

Não comece a implementar todos os módulos simultaneamente. Avance fase a fase, mantendo o MVP utilizável e verificável.
