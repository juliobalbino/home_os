# Implantação

O `docker-compose.yml` da raiz é exclusivamente para desenvolvimento local. A produção usa `docker-compose.prod.yml`, com build estático do Vite servido pelo Nginx e Django servido pelo Gunicorn. Nenhum serviço publica portas no host; PostgreSQL fica apenas na rede privada padrão do Compose e mantém os dados no volume `postgres_data`.

## Pré-requisitos e configuração

No VPS Ubuntu 24.04, Docker Compose v2 e a rede externa `pangolin` devem estar disponíveis. O Traefik/Pangolin já encaminha `https://homeos.juliobalbino.com.br` para `http://frontend:5173`. **Esta rota pública não tem login/autenticação do Pangolin, conforme escolha do usuário.** Não altere aqui a configuração do Pangolin ou Traefik.

Crie `.env` na raiz (o arquivo é ignorado pelo Git) com segredos fortes e exclusivos:

```dotenv
DJANGO_SECRET_KEY=gere-um-segredo-longo-e-aleatorio
POSTGRES_PASSWORD=gere-uma-senha-longa-e-aleatoria
POSTGRES_DB=home_os
POSTGRES_USER=home_os
```

Não use os valores de `.env.example` em produção. A configuração exige ambas as variáveis secretas; `DEBUG` é fixado em `false`, e hosts/origem confiáveis são limitados a `homeos.juliobalbino.com.br`.

## Inicialização e migrações

Na raiz do repositório:

```sh
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend python manage.py migrate --noinput
```

O banco precisa estar saudável antes do backend iniciar, e o frontend aguarda o health check do backend.

## Verificação

```sh
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 db backend frontend
curl --fail https://homeos.juliobalbino.com.br/
curl --fail https://homeos.juliobalbino.com.br/api/v1/health
```

O endpoint de saúde deve retornar HTTP 200. Confirme também uma rota SPA recarregada diretamente no navegador.

## Parar e rollback

Para parar os serviços e preservar o banco:

```sh
docker compose -f docker-compose.prod.yml down
```

Para voltar à imagem anterior após uma atualização, faça checkout da revisão anterior e reconstrua/inicie a mesma configuração; migrações de banco não são revertidas automaticamente, então avalie compatibilidade de schema antes do rollback. Mantenha backup do PostgreSQL antes de atualizações que alterem dados. Não use `down -v` a menos que queira apagar permanentemente o volume e os dados do banco.

## Independent test environment

The `tests` branch uses `.github/workflows/tests-ci-cd.yml` and `docker-compose.test.yml`. Pull requests targeting `tests` and pushes to `tests` run the same backend/frontend CI checks as production; only a successful push deploys. Configure dedicated Actions variables `TEST_DEPLOY_HOST`, `TEST_DEPLOY_USER`, `TEST_DEPLOY_PATH` (for example `/home/ubuntu/prj-tests`), and `TEST_DEPLOY_SSH_KNOWN_HOSTS`, plus the dedicated `TEST_DEPLOY_SSH_PRIVATE_KEY` secret. Pin the host key after independently verifying it. The test deployment expects its own persistent `.env` at `${TEST_DEPLOY_PATH}/.env` with strong `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` values; it never reads or changes `/home/ubuntu/prj/.env`.

Releases are retained under `${TEST_DEPLOY_PATH}/releases/<commit>` and deployed using Compose project `homeos-tests` with `docker-compose.test.yml`. This gives the test database its own named volume and the frontend a unique Pangolin alias (`homeos-tests-frontend`), avoiding production resource/DNS conflicts. Deploy runs migrations and checks `https://homeostests.juliobalbino.com.br/api/v1/health`. Keep the test path separate from production.

## GitHub Actions CI/CD

O workflow `.github/workflows/ci-cd.yml` executa CI em pull requests destinados a `main` e em pushes para `main`. O deploy ocorre exclusivamente após CI passar em um push para `main`; pull requests e outras branches nunca fazem deploy. O workflow empacota com `git archive` o conteúdo rastreado do commit verificado e o transfere por tar sobre SSH para um diretório limpo `/home/ubuntu/prj/releases/GITHUB_SHA`. Cada revisão fica isolada no seu próprio diretório. O `.env` ignorado existente em `/home/ubuntu/prj/.env` é preservado e ligado simbolicamente a cada release; o deploy falha se esse arquivo não existir. Nenhum pacote é instalado no VPS.

Os comandos de produção são executados dentro do diretório do release com o nome de projeto Compose explícito `prj`. Isso reutiliza os recursos existentes `prj_default` e `prj_postgres_data`, apesar de o Compose estar sendo executado a partir do subdiretório `releases/GITHUB_SHA`. O deploy constrói e inicia os serviços, executa migrações, verifica o estado dos serviços e aguarda o endpoint público de saúde. A transferência não usa `--delete` e não modifica o `.env` existente.

Configure estes Actions repository variables:

- `DEPLOY_HOST`: `163.176.94.242`
- `DEPLOY_USER`: `ubuntu`
- `DEPLOY_PATH`: `/home/ubuntu/prj` (diretório base; contém o `.env` persistente e a pasta `releases/`)
- `DEPLOY_SSH_KNOWN_HOSTS`: a linha `known_hosts` para o servidor, incluindo host e tipo/chave pública, por exemplo `163.176.94.242 ssh-ed25519 AAAA...`.

Configure o Actions repository secret `DEPLOY_SSH_PRIVATE_KEY` com a chave privada dedicada ao GitHub Actions. Gere um par separado (por exemplo, `ssh-keygen -t ed25519 -C github-actions-deploy`), instale somente a chave pública em `/home/ubuntu/.ssh/authorized_keys` no VPS, e salve a chave privada como secret. Conceda a essa conta acesso de escrita ao diretório base e aos releases, além da execução de `sudo docker compose` nos diretórios de release.

Obtenha a chave/ fingerprint do host por um canal confiável com o administrador do VPS e compare antes de fixá-la. `ssh-keyscan 163.176.94.242` pode coletar a chave apresentada para essa comparação, mas sua saída, sem verificação independente, não é prova de identidade. Salve a linha verificada em `DEPLOY_SSH_KNOWN_HOSTS`; SSH usa `StrictHostKeyChecking=yes` e falha diante de divergência. Não reutilize a chave SSH pessoal.
