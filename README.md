# Home OS

Base inicial de um monólito modular: API Django/DRF, interface React/TypeScript e PostgreSQL. O escopo implementado está limitado à Fase 0 do [plano](PLAN.md); a decisão sobre integração de IA permanece pendente e não bloqueia o MVP.

## Executar com Docker Compose

Requer Docker Desktop com o daemon em execução e Docker Compose v2.

```sh
cp .env.example .env
docker compose up --build
```

Abra <http://localhost:5173>. A interface consulta `GET /api/v1/health` via proxy do Vite. A API está em <http://localhost:8000/api/v1/health>. O health check retorna `200` quando consegue conectar ao PostgreSQL, ou `503` sem revelar detalhes internos.

Para parar, use `docker compose down`; os dados permanecem no volume `postgres_data`. Para remover também os dados locais, use `docker compose down -v`.

## Verificações locais sem Docker

Requer Python 3.12 e Node.js 22. Com PostgreSQL local disponível, configure no ambiente do processo as variáveis de `.env.example`, ajustando `POSTGRES_HOST=localhost`. O Django local não carrega `.env` automaticamente; o Compose injeta as variáveis via `env_file`.

Backend, a partir de `backend/`:

```sh
python -m venv .venv
# Ative .venv conforme seu sistema operacional
python -m pip install -r requirements.txt
python manage.py check
python manage.py test
ruff check .
ruff format --check .
```

Os testes do health endpoint substituem a conexão com mock; não necessitam de banco em execução. O backend usa PostgreSQL como configuração padrão.

Frontend, a partir de `frontend/`:

```sh
npm ci
npm test
npm run lint
npm run format:check
npm run build
```

Para rodar o frontend fora do Compose, inicie a API local e configure `VITE_API_BASE_URL` se necessário. Os comandos `npm` usam dependências locais do projeto, sem instalação global.

## Estrutura

- `backend/apps/`: apps de domínio Django, mantendo o monólito modular.
- `backend/config/`: configuração e roteamento HTTP.
- `frontend/src/`: interface, estilos e testes.
- `docker-compose.yml`: frontend, API e banco para desenvolvimento.

Não existem funcionalidades de domínio de fases posteriores neste setup.
