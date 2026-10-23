# Home OS

Monólito modular com API Django/DRF, interface React/TypeScript e PostgreSQL. A Fase 1 implementa contas, sessões, residências e permissões; o progresso confirmado está no [plano](PLAN.md). A integração de IA permanece pendente e não bloqueia o MVP.

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

Finanças, listas/compras, estoque, tarefas e IA não estão implementados nesta fase.
