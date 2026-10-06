# Stage deploy: штатный путь через CI

Актуально: 6 октября 2026. Stage = `stage.algolab.me`, compose project `algo-preview`.
**Prod = project `algo-staging` = ветка `main`; деплой только с явного одобрения владельца.**
nginx (`algo-staging-nginx`) общий для stage и prod: любой deploy делает `nginx -t && nginx -s reload`
и применяет **все** файлы из `~/algo/algo-infrastructure/nginx/conf.d` (bind-mount каталога).

## Нормальный путь

1. Изменения в репозиториях лежат в `CEO`, CI на `CEO` зелёный (CEO сам ничего не деплоит).
2. С одобрения владельца: `git push origin CEO:develop` (fast-forward) в нужном репозитории.
   Workflow `deploy.yml` сам: тесты, `git archive` точного SHA, build с `source.compose.json`,
   `up -d --no-build --no-deps <svc>`, `nginx -t && reload`, проверки health/revision/200.
3. Сервисы выкатывать по одному, дожидаясь зелёного job. Compose берётся из
   `~/algo/algo-infrastructure/compose/docker-compose.preview.yml`, секреты из `~/algo/.env.preview`.
4. NEXT_PUBLIC_* для frontend подставляются из `.env.preview` (все три = `https://stage.algolab.me`)
   как build args; CI ничего не передаёт сам. Для `main` те же args берутся из `.env.staging` (`https://algolab.me`).

## Разовая подготовка сервера (до первого CI-деплоя на stage)

Сейчас checkout инфраструктуры: `main@433b74c` + 2 локальные правки; контейнеры stage запущены с
ручными overlay `releases/p03|p06|p06f|p06ui/*.json`. Overlay задаёт только `image`, build-labels и
`RELEASE_*` (и для diagnostic значения CAT, совпадающие с дефолтами CEO-compose), поэтому CEO-compose
для stage достаточен без добавлений. Prod-файлы **не трогаем** (путь-checkout, HEAD не двигаем):

```bash
ssh algo@91.99.183.252 'bash -s' <<'EOF'
set -euo pipefail
cd ~/algo/algo-infrastructure
B=~/algo/backups/infra-switch-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p $B
cp -a compose nginx $B/ && (cd $B && sha256sum compose/*.yml nginx/conf.d/*.conf > SHA256SUMS)
docker exec algo-staging-nginx nginx -t
git fetch origin CEO && CEO=$(git rev-parse FETCH_HEAD) && echo "CEO=$CEO"   # ожидается 1c9b883... или новее
git checkout "$CEO" -- compose/docker-compose.preview.yml nginx/conf.d/preview.conf
(cd $B && sha256sum -c SHA256SUMS | grep -v ': OK' || true)  # допустим только FAILED у docker-compose.preview.yml
docker compose -f compose/docker-compose.preview.yml -p algo-preview --env-file ../.env.preview config -q && echo compose-ok
docker exec algo-staging-nginx nginx -t
EOF
```

Ожидаемые sha256 prod-файлов (должны остаться): `staging.yml 36b92011…8959`, `staging.conf 0696f1d4…901a`,
`preview.conf 0a9ca158…321d` (preview.conf совпадает с CEO, reload не нужен).
Не делать `git checkout CEO` целиком и не `git pull`: это заменит `staging.yml` и `staging.conf` (см. ниже).

## Проверка после каждого деплоя

```bash
C=algo-preview-<frontend|auth|content|diagnostic|exam>
docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' $C   # нет releases/p0*
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' $C | grep ^RELEASE_   # RELEASE_SHA == commit из CI
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$(docker inspect --format '{{.Image}}' $C)"   # == commit
docker inspect --format '{{.State.Health.Status}}' $C   # healthy (у frontend healthcheck нет: running + curl 200)
```

Diagnostic: CEO head миграций `009_answer_task_evidence`, на stage сейчас `008_durable_auth_sync`. Первый деплой
diagnostic применит 009 при старте (`migration_runner` в CMD). Перед ним: `pg_dump` БД
`algo_diagnostic` из `algo-preview-diagnostic-db` в `~/algo/backups/`. Тот же приём для content/auth/exam
(их heads на stage совпадают с CEO: `q8r9s0t1u2v3`, `q7r8s9t0u1v`, `015_repair_derivative_distractor`).
Проверить env diagnostic: `CLASSIFICATION_MIN_ITEMS=20`, `CLASSIFICATION_SE_THRESHOLD=0.40`,
`CLASSIFICATION_CONFIDENCE_THRESHOLD=0.90`, `MIN_ITEMS=12`, `MAX_ITEMS=42`.

## Откат

CI сохраняет `~/algo/releases/git-<svc>-<sha>-<run>/release-record.json` (`previous_image_id`, `rollback_tag`
вида `algolab-rollback-algo-preview-<svc>:<sha12>-<run>`); также он в artifact `release-manifest-<sha>`.

```bash
cd ~/algo
echo '{"services":{"<svc>":{"image":"<rollback_tag>"}}}' > /tmp/rollback.json
RELEASE_SHA=<старый sha|unknown> docker compose -f algo-infrastructure/compose/docker-compose.preview.yml \
  -f /tmp/rollback.json -p algo-preview --env-file .env.preview up -d --no-build --no-deps <svc>
```

**Diagnostic:** образ старше миграции 009 нельзя запускать на БД с 009. Сначала, пока работает
образ с 009: `docker exec algo-preview-diagnostic alembic downgrade 008_durable_auth_sync`,
затем откат образа. Данные 009 при downgrade могут быть потеряны: сперва `pg_dump`.
Альтернатива откату: revert commit в `develop` и штатный CI.

## Prod (`main`): что отличается и почему нельзя «просто влить»

На сервере `staging.yml` и `staging.conf` старее CEO. При любом деплое (stage тоже!) выполняется reload,
поэтому до осознанного prod-релиза их не синхронизируем:

- `staging.conf` (CEO): убран публичный `location /api/v1/content/` (security fix, отдавал ключи ответов).
  Frontend его не использует, за 72 ч в логах nginx 0 обращений, но это изменение поведения prod при reload.
- `staging.yml` (CEO): `RELEASE_*`, `INTERNAL_SERVICE_TOKEN` (обязателен), `CORS_ORIGINS` (обязателен для diagnostic/exam),
  diagnostic `MIN_ITEMS=12 MAX_ITEMS=42 WARMUP_ITEMS=5 MIN_SECTION_COVERAGE=5`, `mem_limit: 1536m` у одного сервиса.
  В `.env.staging` нет `INTERNAL_SERVICE_TOKEN`, `MIN_ITEMS`, `MIN_SECTION_COVERAGE`; в запущенных prod-контейнерах
  токена нет. Деплой `main` с CEO-compose упадёт на `INTERNAL_SERVICE_TOKEN is required`, а тихо
  поменяется лимит адаптивной диагностики (в `.env.staging` `MAX_ITEMS=25`, `WARMUP_ITEMS=3`).
- Prod-релиз = отдельный план: токен, env, сразу все сервисы (межсервисная аутентификация), backup 4 БД,
  одобрение владельца. До этого `main` не пушить.
