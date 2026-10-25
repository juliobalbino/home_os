# Home OS

Monólito modular com API Django/DRF, interface React/TypeScript e PostgreSQL. As Fases 1–5 estão implementadas; a Fase 6 inclui integração opcional de Sign in with ChatGPT para candidatos de produtos, ainda sem verificação ao vivo. Consulte [PLAN.md](PLAN.md) para evidências e limites. O projeto é distribuído sob a licença MIT ([LICENSE](LICENSE)).

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

### Compras e estoque (Fase 3)

As APIs de catálogo, aliases, observações de preço manuais, listas compartilhadas, itens livres/de produto, compras e consulta de estoque estão sob `/api/v1/households/{id}/...`; a confirmação de compra exige `Idempotency-Key`. Envie `quantity` como decimal string e `unit_price_minor` como inteiro positivo; o backend calcula `line_total_minor` por Decimal com `ROUND_HALF_UP` ao centavo e rejeita um total de linha enviado que não coincida. Cada item pode informar `shopping_list_item_id` para vincular apenas item da lista ainda `needed` e com o mesmo produto; vínculo inválido ou indisponível retorna 409 e reverte a transação. Itens livres não são convertidos automaticamente em produtos. Itens usam `Decimal` serializado como string, até quatro casas decimais. As unidades são identificadores opacos e devem coincidir exatamente (`kg` não converte para `g`; `l` não converte para `ml`). Uma compra validada cria Purchase/PurchaseItem, PriceObservation de origem `purchase`, eventos/saldo, uma Expense em `Compras`, ExpenseSplits iguais para memberships ativos, um Payment integral pelo comprador atual e um evento minimizado `purchase.confirmed`, dentro de uma transação. O resumo financeiro permanece baseado em Expense.

Rotas adicionais: `POST /products/{id}/aliases`, `POST /households/{id}/price-observations`, `POST /shopping-lists/{id}/items`, `PATCH /shopping-items/{id}`, `GET /households/{id}/inventory` e `POST /inventory/{id}/events`. PATCH aceita status `purchased`/`skipped`; a interface expõe essas ações. Eventos manuais não aceitam `purchase`; consumo/perda requerem delta negativo; ajuste/correção exigem justificativa. Valores de preço manual são inteiros positivos e bool/float são rejeitados; quantidades e deltas aceitam apenas int/Decimal/string (não bool/float), são finitos e têm no máximo quatro casas; notas limitam-se a 240 caracteres. Campos textuais e prioridade da lista são validados antes de persistir. Saldo negativo é rejeitado sob lock transacional. Escritas respeitam membership e bloqueiam viewer. Produto e texto livre são mutuamente exclusivos e validados também por constraint no banco. Na confirmação de compra, a unidade da linha acompanha o produto selecionado no catálogo.

Verificações finais desta revisão: backend completo (45 testes) e `apps.shopping` (12 testes) passaram em SQLite; `check`, `makemigrations --check --dry-run` e aplicação de `migrate --noinput` passaram. Ruff check/format passaram. Frontend completo: 15 testes passaram; ESLint, Prettier check, build de produção e `npm audit` (0 vulnerabilidades) passaram. RED/GREEN observado: item de lista já comprado reproduziu `DoesNotExist`; float em evento de estoque e unidade de produto desatualizada falharam nos testes antes da correção; os novos testes passaram após implementação. O retry com a mesma chave continua coberto como 200. Concorrência PostgreSQL e E2E/browser não foram executados.

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

### Tarefas e rotinas (Fase 4)

`GET/POST /api/v1/households/{id}/chores`, `PATCH /api/v1/chores/{id}`, `GET /api/v1/households/{id}/chore-occurrences`, `POST /api/v1/chores/{id}/generate-occurrences` e `POST /api/v1/chore-occurrences/{id}/complete` implementam tarefas, responsáveis por membership ativo, estado ativo/inativo e ocorrência com histórico de conclusão. Somente membership ativo acessa os dados; viewers leem, mas não alteram nem geram ocorrências.

Recorrências aceitam `daily`, `weekly` (`weekday`: 0–6, segunda a domingo) e `monthly` (`day`: 1–31), com horário local `time` (`HH:MM`). Ocorrências são para datas-calendário locais inclusivas, e horários são convertidos para UTC na persistência; DST altera o offset UTC, não o horário local solicitado. A chave única `(chore, due_at)`, `get_or_create` e transação com lock da residência tornam repetição idempotente; concorrência foi validada via constraint/SQLite, não sob PostgreSQL nesta execução. Período máximo: 367 dias. O serviço/API é explícito, sem cron ou notificações. Para gerar manualmente, faça POST autenticado com CSRF para cada tarefa ativa e payload `{"start_date":"AAAA-MM-DD","end_date":"AAAA-MM-DD"}` (o atalho `"today"` usa a data corrente do fuso da residência). Isso cria somente datas daquela faixa e pode ser reexecutado com segurança.

Migre com `python manage.py migrate`. A interface autenticada inclui criação, edição de título, ativação/desativação, listagem e conclusão, além da ação manual de gerar as ocorrências de hoje; datas são exibidas no fuso configurado para a residência.

### Dashboard integrado e estabilização (Fase 5)

O painel de cada residência consulta APIs existentes para gastos e orçamento restante do mês, saldos por membro, itens `needed` em listas ativas e ocorrências pendentes (com indicação de atraso). Cada seção carrega e apresenta falha/estado vazio independentemente das demais. Os atalhos abrem os módulos correspondentes. O layout reorganiza cartões em uma coluna em telas estreitas.

### Backup e restauração PostgreSQL

Execute em ambiente autorizado, usando o usuário/container PostgreSQL configurado no Compose. O formato custom do `pg_dump` permite restauração seletiva e compressão. Armazene o backup fora do repositório, com acesso restrito e criptografia no destino. Não coloque senhas na linha de comando; use o mecanismo de credenciais aprovado no ambiente (por exemplo `.pgpass` com permissões restritas ou `PGPASSWORD` injetada pelo secret manager). Exemplos para serviço Compose `db`:

```sh
# Backup consistente; substitua nomes pelo ambiente configurado.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > home-os-$(date +%Y%m%d-%H%M%S).dump

# Validar a listagem de conteúdo sem restaurar.
pg_restore --list home-os-YYYYMMDD-HHMMSS.dump

# Restaurar APENAS em banco vazio/isolado previamente criado; nunca use --clean no banco ativo.
pg_restore --exit-on-error --no-owner --no-privileges -h localhost -U "$POSTGRES_USER" -d "$RESTORE_DATABASE" home-os-YYYYMMDD-HHMMSS.dump
```

Configure o acesso `pg_dump`/`pg_restore` conforme o ambiente; o redirecionamento gera arquivo no host que executa o comando. Restaure primeiro em banco isolado, aplique validações funcionais e confira migrations antes de qualquer recuperação operacional. Estes comandos são documentados; restauração PostgreSQL real ainda precisa ser exercitada em ambiente isolado antes de produção. Os testes/migrations locais habilitados com `HOME_OS_TEST_SQLITE=true` usam SQLite e não substituem backup/restore nem comprovam compatibilidade operacional com PostgreSQL ao vivo.

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

IA permanece fora das Fases 1–4.

### Assistente opcional e Sign in with ChatGPT (Fase 6)

A integração usa o fluxo oficial open-source de uso do plano ChatGPT (sem API key nem client secret). Cada morador autoriza sua própria conta; viewer pode consultar o estado, mas não enviar solicitações. A ausência de configuração mantém o recurso desligado e não afeta os demais módulos.

**Configuração fail-closed:** defina `ASSISTANT_ENABLED=true` e `ASSISTANT_ENCRYPTION_KEY` no ambiente do processo somente após decidir habilitar o recurso. A chave deve ser Fernet válida: URL-safe Base64 dos 32 bytes de chave; gere-a com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; configure-a por secret manager/variável de ambiente no backend e no host de execução. Não a coloque em código, `.env.example`, logs ou no mesmo canal/destino da cópia de credenciais. O status informa `disabled` ou `missing_or_invalid_encryption_key` até os requisitos serem satisfeitos. Testes usam SQLite por `HOME_OS_TEST_SQLITE=true` e `override_settings` com chave Fernet sintética definida nos próprios testes; nenhum segredo externo ou conta real é necessário. Nunca use uma conta real nem faça chamada ao vivo na suíte.

**OAuth local:** após instalar dependências e configurar a chave Fernet, execute no backend. Para exportar credenciais para uma VM, não é necessário ter uma conta Home OS local:

```sh
python manage.py assistant_oauth --host-id urn:uuid:UUID-PERSISTIDO
```

O comando abre o navegador e escuta somente em `http://127.0.0.1:1455/auth/callback`, usa state/nonce/PKCE, dynamic client registration (`dynamic_agent_client`) e valida ID token/JWKS e scope. Mantenha o host ID opaco e estável; use `--client-id oaiapp_...` para reautorizar um registro existente e acrescente `--consent` somente para repetir consentimento após recusa/ausência de scope. Sem `--user-id`, grava somente o bundle cifrado; com `--user-id`, também associa credenciais à conta Home OS local. Para exportação, tokens ficam somente no bundle cifrado indicado por `--output`; o arquivo contém dados sensíveis cifrados, deve ter acesso restrito e não pode ser versionado. O callback nunca é uma rota hospedada.

**VM self-hosted:** gere e persista um `ext_agent_host_id` próprio da VM antes de importar (UUIDv4 `urn:uuid:...` aceito). Faça OAuth no computador local, depois transfira o bundle cifrado para a VM por canal protegido, por exemplo `scp` sobre SSH; não transfira a chave Fernet junto do arquivo. Configure o mesmo segredo no secret manager da VM e importe para o usuário Home OS correspondente:

```sh
python manage.py assistant_oauth --import-file /caminho/protegido/chatgpt-credentials.enc --user-id 1 --host-id urn:uuid:UUID-PERSISTIDO-DA-VM
```

A importação re-cifra as credenciais no banco da VM. Preserve o host ID da VM, não copie o ID do computador local como ID da VM. A VM passa a gerir renovações; a limitação atual do fluxo é que atribuição de uso específica ao host e revogação para sessão transferida não estão disponíveis no protocolo. A integração permanece inativa enquanto o ambiente estiver desligado/mal configurado ou sem scope. Revogue localmente com `python manage.py assistant_oauth --revoke-client-id oaiapp_... --user-id 1`; o comando consulta o revocation endpoint oficial, tenta novamente com backoff limitado em falha de rede/5xx e, se a revogação remota não for confirmada, apaga os tokens locais e instrui a desconexão em ChatGPT Settings.

**Ativar no ambiente de testes:** `docker-compose.test.yml` define `ASSISTANT_ENABLED=true` por padrão para o test VM, mas o recurso permanece fail-closed enquanto `ASSISTANT_ENCRYPTION_KEY` estiver ausente ou inválida. Gere uma chave Fernet no computador local confiável e adicione `ASSISTANT_ENABLED=true` e `ASSISTANT_ENCRYPTION_KEY=<chave>` ao `.env` persistente do test VM usando um método local seguro (por exemplo, editor por SSH com host verificado). Configure a mesma chave no ambiente do backend local antes de executar o comando OAuth de exportação; o comando local e a VM precisam da mesma chave para exportar/importar o bundle. Transfira somente o bundle cifrado por canal protegido. Não envie nem faça commit da chave e não a inclua em `.env.example`.

`POST /api/v1/households/{id}/assistant` aceita `mode: "text"` ou `mode: "label"`, texto até 4000 caracteres e imagem JPEG/PNG/WebP até 5 MiB. Aplica limite local de 10 solicitações por usuário/residência/hora; erros do provedor são curtos e não incluem credenciais. Respostas/candidatos não são persistidos; candidatos mostram que confirmação explícita é necessária. O Responses request usa catálogo de modelos da conta e somente campos aceitos nesta integração, sempre `store:false` e `stream:true`; sem ferramentas ou mutações automáticas. Confira limites compartilhados do plano em [ChatGPT Settings → Usage](https://chatgpt.com/settings/usage).

Referências oficiais: [open-source token sharing](https://developers.openai.com/siwc/token-sharing-open-source/), [sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in/), [profiles and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions/), [models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference/), [self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms/), [errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery/) e [preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations/).

O fluxo e as requisições OpenAI não foram exercitados ao vivo; não se afirma que uma conta ChatGPT esteja conectada nem que uma solicitação de plano tenha sido concluída. Elegibilidade, comportamento do provedor e consentimento dependem de OAuth real pelo usuário.

**Verificações desta implementação:** `HOME_OS_TEST_SQLITE=true python manage.py test` (**66 testes backend**), `migrate --noinput`, `makemigrations --check --dry-run`, `check`, Ruff check/format; frontend `npm test` (**22 testes**), ESLint, Prettier check, build de produção e `npm audit` (0 vulnerabilidades). `docker compose config --quiet` também passou. Os testes OpenAI são simulados; não foram feitos OAuth/requisições ao vivo, PostgreSQL real, Compose com serviços iniciados, VM ou deploy. Os testes usam SQLite explicitamente; isso não comprova comportamento concorrente PostgreSQL. Testes de `response.failed`, `response.incomplete` e stream interrompido foram observados RED antes da correção e passaram GREEN depois.

**TDD RED/GREEN documentado:** teste de readiness inicialmente falhou pela ausência de `apps.assistant.configuration`, depois passou com fail-closed; teste de cifragem iniciou falhando pela ausência de `ChatGPTConnection`, depois passou; teste de schema estruturado iniciou falhando sem `parse_candidate_output`, depois passou com validação; teste React iniciou falhando porque o componente ainda não existia e passou após implementação (incluindo teste viewer read-only); teste de modo texto iniciou falhando por argumento `mode` não suportado e passou quando foi implementado. O teste adicional da readiness com chave Fernet inválida também foi observado RED antes da validação e GREEN depois dela. Os testes de contrato Responses verificam `store=false` e `stream=true` com catálogo e stream simulados.
