# Home OS

Monólito modular com API Django/DRF, interface React/TypeScript e PostgreSQL. As Fases 1 (contas/residências) e 2 (finanças básicas) estão implementadas e verificadas conforme o [plano](PLAN.md). A integração de IA permanece pendente e não bloqueia o MVP.

## Executar com Docker Compose

Requer Docker Desktop com o daemon em execução e Docker Compose v2.

```sh
cp .env.example .env
docker compose up --build
```

Abra <http://localhost:5173>. A interface consulta `GET /api/v1/health` via proxy do Vite. A API está em <http://localhost:8000/api/v1/health>. O health check retorna `200` quando consegue conectar ao PostgreSQL, ou `503` sem revelar detalhes internos.

Para parar, use `docker compose down`; os dados permanecem no volume `postgres_data`. Para remover também os dados locais, use `docker compose down -v`.

## Verificações locais sem Docker

Requer Python compatível com as dependências e Node.js 22. Para execução local normal, configure PostgreSQL e as variáveis descritas em `.env.example`, ajustando `POSTGRES_HOST=localhost`. O Django local não carrega arquivos `.env`; o Compose injeta variáveis via `env_file`. Não use credenciais reais em arquivos versionados.

Backend, a partir de `backend/`:

```sh
python -m venv .venv
# Ative .venv conforme seu sistema operacional
python -m pip install -r requirements.txt
python manage.py check
python manage.py migrate
HOME_OS_TEST_SQLITE=true python manage.py test
ruff check .
ruff format --check .
```

Os testes sem Docker/PostgreSQL usam SQLite em memória somente quando explicitamente habilitado. O ambiente também precisa estar configurado para `manage.py check` fora dos testes. Bash:

```sh
HOME_OS_TEST_SQLITE=true python manage.py test
HOME_OS_TEST_SQLITE=true python manage.py makemigrations --check --dry-run
```

PowerShell: `$env:HOME_OS_TEST_SQLITE='true'; python manage.py test`. PostgreSQL continua sendo o banco padrão para execução normal. Migrations devem ser aplicadas com `python manage.py migrate` antes de iniciar a API.

### Contas e residências

- `GET /api/v1/auth/csrf` fornece o token CSRF para os formulários e chamadas unsafe.
- `POST /api/v1/auth/register` aceita `email`, `name` e senha com pelo menos 6 caracteres alfanuméricos (somente letras e números, sem símbolos) e inicia a sessão. Senhas fracas são permitidas; maiúsculas não são obrigatórias. A regra se aplica somente ao cadastro: login aceita senhas legadas com pontuação.
- `POST /api/v1/auth/login` e `POST /api/v1/auth/logout` usam sessão Django por cookie e exigem CSRF.
- `GET /api/v1/me`, `GET/POST /api/v1/households`, `GET /api/v1/households/{id}` e `GET /api/v1/households/{id}/members` exigem sessão.
- Owner cria convite por `POST /api/v1/households/{id}/invitations` com `role` igual a `member` ou `viewer`. A resposta contém o token em claro uma única vez para cópia segura; o banco guarda somente seu hash. Expira em sete dias.
- Um usuário autenticado aceita em `POST /api/v1/invitations/{token}/accept`. O token só pode ser usado uma vez.
- Membership ativo é verificado no servidor. `viewer` não pode executar operações de escrita autorizadas para membros; convites são restritos ao owner.
- Cada usuário pode ter somente uma membership ativa, garantida por constraint única parcial no banco e validação transacional. Criar residência ou aceitar convite de outra residência retorna `409 Conflict` quando já participa de uma. A interface oculta o formulário de criação enquanto participa de uma residência.

### Finanças (Fase 2)

Todas as rotas abaixo usam `/api/v1/`, sessão autenticada e isolamento por membership ativo da residência. Escritas exigem CSRF; `viewer` tem somente leitura. Valores monetários na API são inteiros positivos `amount_minor` em centavos; valores decimais/float não são aceitos.

| Método e endpoint | Payload/resultado |
|---|---|
| `GET /finance/categories?household_id={uuid}` | Lista `{id,name,kind}`. |
| `POST /finance/categories` | `{household_id,name,kind?}`; cria categoria ativa. |
| `GET /households/{id}/members` | Inclui `id` (membership), `name`, `email`, `role`. |
| `GET /households/{id}/expenses` | Lista detalhes com valor, status, pagamentos e divisões vigentes. |
| `POST /households/{id}/expenses` | `{description,category_id,amount_minor,incurred_on,split_method,splits:[...]}`. `split_method`: `equal` (`membership_id`), `percentage` (`membership_id,percent` decimal com até 4 casas, somando exatamente 100; envie como string) ou `fixed` (`membership_id,amount_minor` somando total). |
| `GET /expenses/{id}` | Detalhe; residência alheia ou inexistente responde 404. |
| `PUT /expenses/{id}/splits` | `{split_method,splits:[...]}`; substitui a divisão vigente atomicamente, preservando versões antigas. |
| `POST /expenses/{id}/payments` | `{payer_id,amount_minor,notes?}`. O valor representa pagamento efetivo à conta/fornecedor. |
| `GET /households/{id}/budgets/{AAAA-MM}` | Lista orçamentos do mês (`category_id: null` é geral). |
| `PUT /households/{id}/budgets/{AAAA-MM}` | `{amount_minor,category_id?}`; cria/atualiza orçamento geral ou de categoria. |
| `GET /households/{id}/financial-summary?period={AAAA-MM}` | `spent_total`, `budget_total` e despesas do mês. |
| `GET /households/{id}/settlements` | Por membro: `paid_minor`, `owed_minor`, `balance_minor`. |

Pagamentos são a fonte única para saber quem pagou; não existe atribuição duplicada `paid_by` na despesa. `paid_total` é a soma dos pagamentos; status é `unpaid`, `partial` ou `paid` comparado ao total. Obrigação de cada morador permanece na divisão mesmo após pagamento: saldo = pagamentos feitos por ele menos sua parcela vigente (positivo é crédito; negativo é dívida). Não há transferências nem reembolsos entre moradores nesta fase. Percentuais aceitam até 4 casas decimais e são calculados por unidades inteiras escaladas (sem float); o rateio em centavos usa maiores restos, com desempate por membership id. Divisões iguais distribuem sobras também por membership id. Criação de categorias, despesas, pagamentos e orçamentos é registrada em `AuditEvent` minimizado. Resumos rejeitam períodos inválidos com HTTP 400, e a interface oculta controles de escrita para viewers enquanto mantém a consulta financeira.

`budget_total` usa o orçamento geral do mês quando definido, sem somar categorias adicionais; se não houver orçamento geral, soma os orçamentos por categoria. O período financeiro padrão usa a data local `America/Sao_Paulo` no backend e o ano/mês locais do navegador na interface.

Validação financeira local com SQLite de teste: `HOME_OS_TEST_SQLITE=true python manage.py test apps.finance` (PowerShell: `$env:HOME_OS_TEST_SQLITE='true'; python manage.py test apps.finance`). A aplicação permanece configurada para PostgreSQL por padrão; esses testes não demonstram execução real em PostgreSQL.

Antes de aplicar a migration que adiciona a unicidade, diagnostique possíveis duplicatas legadas sem alterá-las automaticamente:

```sql
SELECT user_id, COUNT(*) AS memberships_ativas,
       ARRAY_AGG(id ORDER BY id) AS membership_ids,
       ARRAY_AGG(household_id ORDER BY id) AS household_ids
FROM households_membership
WHERE status = 'active'
GROUP BY user_id
HAVING COUNT(*) > 1;
```

Se houver resultados, a migration da constraint falhará intencionalmente. Avalie e resolva cada caso explicitamente, preservando o histórico; nenhum membership será apagado automaticamente.

As rotas da API são versionadas em `/api/v1/`. Cookie de sessão é HttpOnly e SameSite=Lax; em produção os cookies Secure são habilitados quando `DEBUG=false`. Para desenvolvimento HTTP local, habilite `DJANGO_DEBUG=true` no ambiente do processo.

Frontend, a partir de `frontend/`:

```sh
npm ci
npm test
npm run lint
npm run format:check
npm run build
npm audit
```

Para rodar o frontend fora do Compose, inicie a API local e configure `VITE_API_BASE_URL` se necessário. Os comandos `npm` usam dependências locais do projeto, sem instalação global.

## Estrutura

- `backend/apps/`: apps de domínio Django, mantendo o monólito modular.
- `backend/config/`: configuração e roteamento HTTP.
- `frontend/src/`: interface, estilos e testes.
- `docker-compose.yml`: frontend, API e banco para desenvolvimento.

Listas/compras, estoque, tarefas e IA permanecem fora das Fases 1 e 2.
