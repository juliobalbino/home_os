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
- [x] Configurar modelo de usuário apropriado antes da primeira migração (email único normalizado; migration inicial criada).
- [x] Implementar cadastro, login/logout e sessão por cookie com proteção CSRF.
- [x] Implementar `Household`, `Membership` e papéis `owner`, `member` e `viewer`.
- [x] Implementar criação de residência com criador owner.
- [x] Implementar convite por token aleatório de uso único, armazenado como hash e expirável em sete dias; sem envio de e-mail.
- [x] Criar verificação reutilizável de membership ativo e papel.
- [x] Criar interface autenticada e navegação inicial de contas/residências.
- [x] Criar testes de isolamento entre residências.
- [x] Exigir senha de cadastro de pelo menos 6 caracteres alfanuméricos, sem símbolos e sem exigência de maiúsculas; login legado permanece compatível.
- [x] Garantir uma única membership ativa por usuário com constraint parcial no banco e proteção transacional contra concorrência; criação de segunda residência e convite para outra residência conflitam sem alteração de membership.
- [x] Ocultar criação de residência na interface quando já houver uma residência e documentar diagnóstico de duplicatas legadas antes da migration.

Critérios de aceite:
- [x] Dois usuários independentes podem participar da mesma residência via convite de uso único.
- [x] Um usuário não acessa residência alheia manipulando URLs (404 sem revelar sua existência).
- [x] Rotas privadas exigem autenticação.
- [x] Logout invalida a sessão.
- [x] `viewer` não pode executar operações protegidas como escrita/criação de convites.

**Progresso verificado:** suíte backend (8 testes) e frontend (3 testes), lint, formatação, build e checks Django executados localmente; migrations iniciais presentes e `makemigrations --check --dry-run` sem alterações pendentes. Testes usam SQLite em memória somente com `HOME_OS_TEST_SQLITE=true`; PostgreSQL permanece como padrão da aplicação. Docker daemon indisponível nesta máquina; Compose e PostgreSQL real não foram exercitados.

### Fase 2 — Finanças básicas

**Estimativa:** 4–6 dias.

Tarefas:
- [x] Implementar categorias.
- [x] Implementar criação/listagem/detalhe de despesas.
- [x] Implementar divisões iguais, percentuais e valores fixos.
- [x] Implementar pagamentos.
- [x] Implementar orçamento mensal geral ou por categoria.
- [x] Implementar resumo financeiro e saldo por membro.
- [x] Implementar audit log para criação de despesas, pagamentos e definição de orçamento.
- [x] Criar interface para cadastrar/listar despesas, categorias, divisões, pagamentos, orçamento e saldos.
- [x] Cobrir arredondamento, histórico de divisões, pagamentos e saldo com testes.
- [x] Somar orçamento geral com precedência sobre orçamentos por categoria, auditar criação de categoria atomicamente e usar período local.

Critérios de aceite:
- [x] Despesa de R$ 300,00 dividida igualmente gera R$ 150,00 por pessoa.
- [x] A soma das parcelas fecha exatamente o valor da despesa.
- [x] Pagamento parcial não marca automaticamente a despesa como totalmente paga.
- [x] Totais do resumo financeiro correspondem aos registros.
- [x] Operações inválidas não persistem dados parcialmente.

**Progresso verificado:** app modular `finance`, app mínimo `audit`, migrations, endpoints versionados e interface integrados à navegação; membership id exposto na listagem de membros. Payment representa pagamento efetivo externo; os registros Payment são a única fonte de quem pagou. O saldo por membro é pagamentos feitos menos obrigação vigente, sem transferências/reembolsos entre moradores. Divisões antigas são preservadas ao substituir a vigente. `budget_total` considera somente o orçamento geral se existir no mês; caso contrário, soma orçamentos por categoria. O default do período usa `America/Sao_Paulo` no backend e a data local no navegador.

**Verificações executadas:** backend: `HOME_OS_TEST_SQLITE=true python manage.py test` (33 testes), `check`, `makemigrations --check --dry-run`, `migrate --noinput`, Ruff check e format check. Frontend: `npm test` (10 testes), ESLint, Prettier check, build de produção e `npm audit` (0 vulnerabilidades). Os testes/migrações usam SQLite por opção explícita; PostgreSQL real, Compose e integração ponta a ponta navegador/API não foram exercitados nesta execução.

### Fase 3 — Compras e estoque

**Estimativa:** 4–6 dias.

Tarefas:
- [x] Implementar catálogo de produtos e aliases básicos.
- [x] Implementar listas compartilhadas e itens livres.
- [x] Implementar observações de preços manuais e de compra.
- [x] Implementar registro de compra e itens.
- [x] Implementar movimentos e saldo de estoque.
- [x] Integrar compra com despesa financeira sem duplicar valores.
- [x] Implementar idempotência para confirmação de compra (mesmo payload reaproveita; payload divergente retorna 409).
- [x] Criar interface integrada de lista, catálogo, confirmação manual de compra e estoque; contempla viewer read-only e estados de carregamento/vazio/erro/sucesso.
- [ ] Upload/OCR: fora do escopo aprovado desta fase; não implementado.

Critérios de aceite:
- [ ] Os dois moradores veem a lista compartilhada (endpoints compartilhados implementados; teste com dois usuários pendente).
- [x] Confirmar uma compra atualiza financeiro e estoque uma única vez (teste API SQLite: retry sem duplicar Expense/Payment/estoque).
- [ ] O saldo pode ser conciliado com o histórico de movimentos (ledger e saldo implementados; teste abrangente de conciliação pendente).
- [x] Preço observado e preço efetivamente pago são diferenciados por `PriceObservation.source`.
- [x] Cadastro manual funciona sem integração de IA.

**Convenção de unidades:** unidades são strings opacas, comparadas exatamente dentro do produto; sem conversão entre `g`/`kg`, `ml`/`l` ou unidades equivalentes. Quantidades são `Decimal` persistidas em até quatro casas decimais e transmitidas em JSON como strings. Movimentos manuais de ajuste/correção exigem justificativa; saldo negativo é bloqueado.

**Evidência TDD registrada:** os novos testes foram executados antes das alterações de produção: o retry com nova chave para item já comprado reproduziu `DoesNotExist`; o evento de inventário aceitou float; a validação de limites/tipos textuais falhou; e o teste de troca de produto recebeu unidade antiga. Após as correções, as regressões passaram. O retry com a mesma chave permanece coberto como HTTP 200. A auditoria minimizada de compra também está coberta. Idempotência concorrente real não foi exercitada sob PostgreSQL nesta máquina.

**Verificações finais desta revisão:** backend completo: 45 testes; `apps.shopping`: 12 testes; `check`, `makemigrations --check --dry-run` e aplicação de `migrate --noinput` em SQLite passaram. Frontend completo: 15 testes; ESLint, Prettier check, build de produção e `npm audit` (0 vulnerabilidades) passaram. Ruff check e format check passaram. PostgreSQL ao vivo, concorrência PostgreSQL e E2E/browser não foram executados. O teste SQLite valida fluxos transacionais sem simular concorrência entre conexões PostgreSQL; a implementação serializa pelo lock da residência em bancos que suportam `SELECT FOR UPDATE`, com constraint única como guarda final.

### Fase 4 — Tarefas e rotinas

**Estimativa:** 2–4 dias.

Tarefas:
- [x] Implementar tarefas, categorias e responsáveis.
- [x] Implementar prazo e status.
- [x] Implementar conclusão e histórico.
- [x] Implementar recorrências básicas com timezone da residência.
- [x] Evitar ocorrências duplicadas.
- [x] Criar interface de tarefas pendentes e concluídas.
- [x] Criar testes para mudança de horário e recorrência.

Critérios de aceite:
- [x] Cada morador com membership ativo vê tarefas/ocorrências; viewers são somente leitura.
- [x] Concluir tarefa preserva registros em `ChoreCompletion`.
- [x] Reprocessar a geração de recorrências não duplica ocorrências.
- [x] Datas são geradas no timezone configurado e persistidas como instantes UTC.

**Convenção de recorrência:** a faixa de geração contém datas locais inclusivas da residência (limite de 367 dias). `daily`, `weekly` (`weekday` 0–6) e `monthly` (`day` 1–31) aceitam horário local `HH:MM`. Dias de mês inexistentes são ignorados. A conversão zoneinfo usa regras DST vigentes para cada data; o horário de parede local é mantido e o instante UTC muda conforme o offset. Ocorrência pontual usa o instante com timezone fornecido na tarefa. Geração é acionada explicitamente por endpoint/serviço; não foi adicionada infraestrutura de agenda.

**Progresso verificado:** app `chores`, migration, API versionada, autorização por household, validação, auditoria de mutações e UI autenticada integrados. Testes TDD focados cobrem geração idempotente/DST (troca de offset), viewer, validação, histórico e isolamento. O serviço serializa por lock da residência em bancos com suporte a `SELECT FOR UPDATE` e constraint única como garantia final; concorrência PostgreSQL real não foi exercitada.

**Verificações finais desta execução:** backend completo: 45 testes passaram em SQLite; testes focados `apps.chores`: 3 passaram; migrations aplicadas com `migrate --noinput`; `check`, `makemigrations --check --dry-run`, Ruff check e format check passaram. Frontend completo: 17 testes passaram; ESLint e build de produção passaram; `npm audit` reportou 0 vulnerabilidades. `npm run format:check` ainda aponta somente os arquivos preexistentes `src/modules/shopping/Shopping.tsx` e `Shopping.test.tsx`; os arquivos desta fase estão formatados. `git diff --check` passou. Docker Desktop Linux daemon indisponível, portanto Compose, PostgreSQL real e browser E2E não foram executados; concorrência PostgreSQL não foi exercitada.

### Fase 5 — Dashboard integrado e estabilização do MVP

**Estimativa:** 2–4 dias.

Tarefas:
- [x] Criar dashboard com gastos, orçamento, acertos, lista e tarefas via APIs existentes.
- [x] Implementar estados independentes de carregamento, vazio e erro por seção.
- [x] Atalhos acessíveis para os módulos existentes e layout responsivo.
- [x] Cobrir renderização de dados reais simulados, erro isolado de seção e conteúdo disponível.
- [x] Documentar backup/restore PostgreSQL com `pg_dump`/`pg_restore` e restauração somente em banco isolado.
- [x] Verificar build de produção local.
- [ ] Testes ponta a ponta com PostgreSQL/navegador real não executados nesta fase.

Critérios de aceite:
- [x] O dashboard consulta dados reais das APIs existentes.
- [x] O layout responde a telas estreitas; teste E2E em dispositivos reais pendente.
- [x] Testes críticos de componente passam.
- [x] O MVP funciona sem IA.
- [x] Existe procedimento documentado para restaurar o banco; restauração real ainda não validada.

**Evidência TDD:** o teste inicial ficou RED porque o módulo Dashboard não existia; depois da implementação os testes de renderização de resumo/lista/tarefas/atalhos e erro independente passaram. Os dados do dashboard permanecem submetidos aos endpoints já protegidos por sessão e membership; nenhuma API ou migration nova foi necessária.

**Verificações da fase:** backend: 45 testes passaram com `HOME_OS_TEST_SQLITE=true`; migrações SQLite aplicadas; `makemigrations --check --dry-run`, `check`, Ruff check e format check passaram. Frontend: 20 testes passaram; ESLint, Prettier check, build de produção e `npm audit` (0 vulnerabilidades) passaram. Durante validação final, arquivos da Fase 4 que estavam fora do Prettier foram formatados; a verificação completa passou depois da correção. A execução inicial de `migrate` sem flag tentou PostgreSQL e excedeu o timeout; a migração com SQLite explícito passou. PostgreSQL ao vivo, E2E/browser e restore real não foram executados; SQLite não comprova execução PostgreSQL.

### Fase 6 — IA opcional e preparação de produção

**Estimativa:** 3–6 dias de implementação após validar o conector; pode haver espera por elegibilidade/acesso.

Tarefas:
- [x] Validar o método com a documentação oficial Sign in with ChatGPT para OSS; OAuth é executado no computador local via loopback, não em callback hospedado.
- [x] Implementar cliente Responses API concreto condicionado a habilitação explícita e chave Fernet válida.
- [x] Manter connection individual por usuário Home OS, client ID emitido e subject validado; viewers não enviam pedidos.
- [x] Implementar OAuth local com dynamic client registration, redirect exato 127.0.0.1, state, nonce, PKCE, JWKS/claims e validação do scope de uso do plano.
- [x] Cifrar tokens em repouso; implementar refresh/rotação, estado de reautorização e comando de revogação.
- [x] Implementar transferência cifrada para self-hosted VM via bundle e canal externo protegido; cada host mantém ID estável próprio.
- [x] Implementar candidatos de etiqueta estruturados e validação antes de resposta; UI deixa explícito que é necessária confirmação e não persiste alterações.
- [x] Aplicar limites de texto/imagem, timeout de rede, limite local de 10 solicitações por usuário/residência/hora, instruções separadas do conteúdo não confiável e erros concisos.
- [x] Cobrir fail-closed, autorização/escopo/PKCE/JWT, cifra, isolamento, viewer, validação e contrato Responses com testes mockados.
- [ ] Deploy VPS/Traefik/HTTPS/backups externos e verificação em produção não foram realizados nesta fase.

Critérios de aceite:
- [x] A ausência da conexão de IA não afeta os módulos essenciais; recurso permanece desligado por padrão.
- [x] Tokens são isolados por usuário/registro e cifrados; não são enviados ao browser.
- [x] Saída não altera banco financeiro, compras ou estoque; candidatos requerem confirmação externa e não há persistência automática.
- [x] Dados de etiqueta retornam como candidatos explícitos, sem gravação automática.
- [x] Implementação segue o fluxo OSS documentado para OAuth local, VM self-hosted e Responses com `store:false`/`stream:true`.

**Estimativa agregada:** aproximadamente 16–27 dias úteis para o MVP e estabilização, mais o tempo variável da integração de IA e da implantação. As estimativas são orientativas, não garantias.

**Evidência TDD da Fase 6:** readiness RED pela ausência do módulo; GREEN após fail-closed (incluindo chave ausente/inválida). O armazenamento RED pela ausência do modelo; GREEN após teste de cifragem. O parser de candidatos RED pela ausência do schema; GREEN após validação. O teste React RED pela ausência do componente; GREEN depois da interface e ajuste de isolamento/asserção. Evidência OAuth protocol/JWT, membership e Responses foi validada com transporte e chaves simuladas, sem chamada ao vivo. Contagens e comandos finais estão registradas no README e no relatório da execução.

**Verificações desta execução:** suíte backend completa: 66 testes SQLite; migrations aplicadas, `makemigrations --check --dry-run`, `check`, Ruff check e format check. Frontend: 22 testes, ESLint, Prettier, build de produção e npm audit (0 vulnerabilidades); Compose config validado. Não houve OAuth de usuário real, importação real de bundle, chamada ChatGPT, confirmação de elegibilidade, deploy nem validação PostgreSQL/VM ao vivo. Portanto nenhuma conta/solicitação de plano é considerada ativa ou concluída. Testes adicionais cobrem `response.failed` para limites/inelegibilidade/credenciais inválidas, `response.incomplete` e stream interrompido; RED foi observado antes da correção e GREEN depois. Revogação de sessões importadas em outro host tem limitações descritas na documentação oficial; a UI fornece estado e uso, mas o OAuth é iniciado pelo comando local documentado.

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
