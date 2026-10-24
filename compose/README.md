# Compose files

Canonical, version-controlled Docker Compose definitions for the ALGO cluster.
Previously these lived as untracked loose files in the cluster root (both on
laptops and on the server), which meant the definition of production was not
in git anywhere.

## Layout

| File | Environment | Domain |
|---|---|---|
| `docker-compose.staging.yml` | **Production** — the live site | `algolab.me` |
| `docker-compose.preview.yml` | Staging / pre-prod testing | `stage.algolab.me` |
| `docker-compose.local.yml` | Local development | `localhost` |

> **Naming note.** `docker-compose.staging.yml` and the `algo-staging-*`
> containers it creates are, despite the name, **production** — they serve
> `algolab.me`. The name is historical: the cluster was deployed as "staging"
> and became the live site without being renamed. Renaming the compose project
> would change the Docker volume prefix (`algo-staging_content-db-data` →
> `algo-prod_content-db-data`), which creates *new empty volumes* and orphans
> the real databases. That migration needs to be done deliberately, not as a
> side effect. Until then: **`staging` = prod, `preview` = stage.**

## Paths

Build contexts and bind mounts are written relative to this directory
(`../../auth-services`, `../nginx/conf.d/...`), so the sibling service repos
resolve correctly when compose is invoked from the cluster root:

```bash
cd ~/algo
docker compose -f algo-infrastructure/compose/docker-compose.staging.yml \
  -p algo-staging --env-file .env.staging up -d
```

Verify path resolution after any edit — this prints the fully-resolved config
without touching running containers:

```bash
docker compose -f algo-infrastructure/compose/docker-compose.staging.yml \
  -p algo-staging --env-file .env.staging config
```

## Env files

Env files hold secrets and stay **out of git**, on the server only:

| Compose file | Env file | Project name |
|---|---|---|
| `docker-compose.staging.yml` | `~/algo/.env.staging` | `algo-staging` |
| `docker-compose.preview.yml` | `~/algo/.env.preview` | `algo-preview` |

[`compose/.env.example`](.env.example) documents the versioned schema. Copy
it to the **cluster root** as `.env.staging` or `.env.preview`; never put real
values into the repository. `INTERNAL_SERVICE_TOKEN` is required and must be
identical in auth, diagnostic and exam containers of one stack. A root `.env`
file is not loaded by Docker Compose when `--env-file` is specified, so it is
not a substitute for the named server env-file.

Before a rollout, run the resolved-config check with the exact server env-file:

```bash
docker compose -f algo-infrastructure/compose/docker-compose.staging.yml \
  -p algo-staging --env-file .env.staging config -q
```

Use `algolab.me` in `CORS_ORIGINS` and all `NEXT_PUBLIC_*_API_URL` values for
production; use only `stage.algolab.me` for preview. The Azure endpoint must
be a complete Azure chat-completions URL for the configured deployment. Do not
paste keys into terminal output or CI logs.

## Release identity and verification

Every application deployment carries three **non-secret**, runtime-only values:
`RELEASE_SHA`, `RELEASE_REF`, and `RELEASED_AT`. They are supplied by the
service deployment workflow, not stored in either server env file. Thus a
single stack can correctly show different revisions while services are rolled
out one at a time.

The existing `/health` routes retain their dependency-focused contract. Release
identity is intentionally separate:

| Component | Route | Reachability |
|---|---|---|
| auth | `/version` | container network / server shell |
| diagnostic | `/version` | container network / server shell |
| exam | `/version` | container network / server shell |
| content | `/api/v1/version` | container network / server shell |
| frontend | `/api/version` | public, no credentials or secrets |

Before enabling a service workflow that checks revision metadata, update the
`algo-infrastructure` checkout on the target server to the matching release
branch. Otherwise the older compose definition will omit the `RELEASE_*`
environment values and the workflow will fail intentionally rather than mark
an unverifiable deployment as successful.

After a deployment, validate a backend container without exposing its internal
route through Nginx (example for production diagnostic):

```bash
docker exec algo-staging-diagnostic curl -fsS http://localhost:8002/version
```

The deployment job also stores `release-manifest.txt` as a CI artifact with the
service, source SHA/ref, container image ID and deployment time. For frontend,
the same non-secret identity can be viewed at
`https://algolab.me/api/version` (or the preview domain).

### Rollback rule

Application code may be rolled back only to a previously recorded SHA after
checking the migration history for the target service. A database migration is
**not** rolled back implicitly. If a newer migration is incompatible with the
old code, restore a verified database backup or execute a separately reviewed
downgrade procedure before starting the old container.

## Database ports

Both server stacks bind Postgres to `127.0.0.1` only — never `0.0.0.0`. They
are reachable exclusively through an SSH tunnel, so the databases are not
exposed to the internet regardless of firewall state.

| Database | Prod (staging) | Stage (preview) |
|---|---|---|
| auth | 5432 | 15432 |
| diagnostic | 5433 | 15433 |
| content | 5434 | 15434 |
| exam | 5435 | 15435 |

## Подготовка сервера

Одноразовая (идемпотентная) подготовка хоста Hetzner — скрипт
[`../scripts/server_prep.sh`](../scripts/server_prep.sh), запускается на
сервере под `sudo`:

```bash
cd ~/algo
sudo ./algo-infrastructure/scripts/server_prep.sh                  # всё, кроме рестарта docker
sudo ./algo-infrastructure/scripts/server_prep.sh --restart-docker # + рестарт dockerd
```

Что делает:

- swap 4G (`/swapfile`, запись в `/etc/fstab`) и `vm.swappiness=10` (`/etc/sysctl.d/99-algo.conf`);
- `/etc/docker/daemon.json`: `json-file`, `max-size=10m`, `max-file=3` (мерж с существующим JSON, копия в `daemon.json.bak`);
- cron `/etc/cron.d/algo-maintenance`: 03:30 бэкап prod-БД контента
  (`algo-staging-content-db`, `backup_algo_content.sh`, дампы в `~/backups/algo_content`, хранится 14 дней),
  04:30 `docker image prune -f` и `docker builder prune -f --filter until=72h`;
- в конце печатает `free -h`, `swapon --show`, `df -h /`.

**Рестарт docker.** Без `--restart-docker` скрипт только сообщает, что рестарт нужен.
`systemctl restart docker` перезапускает ВСЕ контейнеры (prod и stage) — запускать
в тихое время. Новые лимиты логов применяются только к заново созданным контейнерам
(следующий деплой или `up -d --force-recreate`). Лимиты памяти из compose-файлов
(`mem_limit`) тоже вступают в силу при пересоздании контейнера.

## Уборка диска сервера

Скрипт [`../scripts/server_housekeeping.sh`](../scripts/server_housekeeping.sh)
(раз в неделю). Правило утверждено владельцем: **удаление дампов только под
страховкой свежего проверенного ночного бэкапа прода**. Прежнее правило «два
последних на префикс» отменено (у каждой волны свой префикс — оно ничего бы не
удаляло и не касалось `*.dump`).

- `docker builder prune -af --filter until=168h` — только кэш сборок, **образы не
  удаляются** (откатные образы целы);
- удаляет файлы `*.sql.gz` и `*.dump`, лежащие прямо в `~/release_dumps`, старше
  `KEEP_DAYS` (14, минимум 7; меньшее значение → WARNING и 7). Всё остальное там
  (`.jsonl`, `.sh`, `.txt`, `.tar.gz`, симлинки, подкаталоги) не трогается никогда;
- **возраст — по mtime файла**. Копия, сделанная `cp -p`/`rsync -t`, сохраняет
  исходное время (старый дамп остаётся «старым»); обычный `cp` даёт новое mtime, и
  такая копия проживёт ещё 14 дней — это принято;
- **страховка** — самый новый (по имени) каталог в `/home/algo/backups/prod_nightly`
  (`YYYYMMDD`, пишет `algo-backup-prod.sh`) должен: быть настоящим каталогом (не
  симлинком) с реальной календарной датой в имени; быть не из будущего и не
  старше 2 дней; содержать `SHA256SUMS`, который проходит `sha256sum -c --strict`
  (в этом каталоге; на macOS запасной `shasum -a 256 -c`) и перечисляет не меньше
  4 файлов; содержать не меньше 4 непустых `*.dump`. Иначе скрипт печатает
  `WARNING: nightly backup missing/stale (причина) -- dump cleanup skipped`, дампы
  не удаляет, кэш сборок всё равно чистит и завершается с кодом 0 (cron не шумит);
- шаги независимы: сбой `docker builder prune` или `rm` — WARNING, работа
  продолжается; `df -h /` «после» печатается всегда; код выхода 0 (2 — только
  при неверных аргументах);
- имена файлов обрабатываются NUL-безопасно; если `HOME` не задан, берётся
  `/home/algo`;
- настройки через окружение: `DUMP_DIR`, `NIGHTLY_DIR`, `KEEP_DAYS`,
  `NIGHTLY_MAX_AGE_DAYS`, `NIGHTLY_MIN_DUMPS`, `BUILD_CACHE_AGE`.

Сначала посмотреть, что будет удалено:

```bash
~/algo/algo-infrastructure/scripts/server_housekeeping.sh --dry-run
```

Cron пользователя `algo` — воскресенье 04:00 по Ташкенту (на сервере TZ часто UTC:
04:00 Asia/Tashkent = 23:00 UTC субботы; `CRON_TZ` поддерживается cron Debian/Ubuntu).
**Не установлен автоматически**, ставится вручную (`crontab -e` под `algo`):

```cron
CRON_TZ=Asia/Tashkent
0 4 * * 0 $HOME/algo/algo-infrastructure/scripts/server_housekeeping.sh >> $HOME/housekeeping.log 2>&1
```

Либо одной командой (не затирая существующий crontab):

```bash
( crontab -l 2>/dev/null; echo 'CRON_TZ=Asia/Tashkent'; echo '0 4 * * 0 $HOME/algo/algo-infrastructure/scripts/server_housekeeping.sh >> $HOME/housekeeping.log 2>&1' ) | crontab -
```

Замечание: `server_prep.sh` уже кладёт в `/etc/cron.d/algo-maintenance` ежедневный
`docker image prune -f` (только неиспользуемые dangling-образы, теги откатов не
затрагивает) и `docker builder prune -f --filter until=72h`.

## Git-first stage releases

CEO runs checks without an automatic deployment. See the current [Git-first stage runbook](../docs/releases/GIT_FIRST_STAGE.md) for committed-source exports, legacy runtime provenance, immutable image checks and separate code/database rollback.
