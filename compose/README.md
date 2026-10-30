# Compose files

Canonical, version-controlled Docker Compose definitions for the ALGO cluster.
Previously these lived as untracked loose files in the cluster root (both on
laptops and on the server), which meant the definition of production was not
in git anywhere.

## Layout

| File | Environment | Domain |
|---|---|---|
| `docker-compose.staging.yml` | **Production** — the live site | product `app.algolab.me`, landing `algolab.me` (see «Domains» below) |
| `docker-compose.preview.yml` | Staging / pre-prod testing | product `stage.algolab.me`, landing `landing.stage.algolab.me` |
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

`NEXT_PUBLIC_AUTH_API_URL`, `NEXT_PUBLIC_EXAM_API_URL` and `NEXT_PUBLIC_DIAG_API_URL` stay **empty** in both server env
files (K3 P1): the frontend then calls the origin the page was opened from, so one image serves every domain. The
frontend takes the address of the landing from the runtime variable `FRONTEND_SITE_URL` (passed to the container as
`SITE_URL`); there is no `NEXT_PUBLIC_SITE_URL`. `CORS_ORIGINS` names only the product origin (`app.algolab.me`,
`stage.algolab.me`) and **never `https://algolab.me`** (the landing). The Azure endpoint must
be a complete Azure chat-completions URL for the configured deployment. Do not
paste keys into terminal output or CI logs.

## Domains (K3)

| Name | What it serves | Where it is defined |
|---|---|---|
| `app.algolab.me` | **the product** (frontend + all APIs except the console's) | `nginx/conf.d/staging.conf` (production stack) |
| `algolab.me`, `www` | today: the product; from K3 step 7: the **landing** (static), `/api/v1/public/` -> auth, 30-day API alias, everything else -> 302 to `app.` | `staging.conf` now; `staging-apex-landing.conf.disabled` is the prepared replacement |
| `console.algolab.me` | «Панель ALGO» (static) + `/api/v1/platform/` | `staging.conf` |
| `stage.algolab.me` | the product on stage (the mirror of `app.`) | `preview.conf` |
| `landing.stage.algolab.me` | the landing on stage (the mirror of `algolab.me`), everything else -> 302 to `stage.algolab.me` | `preview.conf` |

* **Landing statics** are written in place by `algo-landing/deploy/deploy_landing.sh` to `~/algo/landing/{stage,prod}`
  and mounted read-only into `algo-staging-nginx` (`/usr/share/nginx/landing-{stage,prod}`). Never rename or recreate
  these folders: the bind mount would stay on the old inode and nginx would answer 404 until restarted. Create both
  folders before the first `up` (otherwise Docker creates them owned by root).
* **Payment callbacks and any other webhook go only to `https://app.algolab.me/api/v1/…`** (stage: `stage.algolab.me`),
  **never to `algolab.me`** (K3 I11): after step 7 that host is the landing and keeps only a temporary alias of the old API.
* **Env values (server files, not in git):**

  | Variable | `.env.preview` | `.env.staging` now | `.env.staging` after step 7 |
  |---|---|---|---|
  | `FRONTEND_SITE_URL` | `https://landing.stage.algolab.me` | `https://algolab.me` | `https://algolab.me` |
  | `SUPPORT_EMAIL` | optional | optional | optional |
  | `NEXT_PUBLIC_*_API_URL` (3) | empty | empty | empty |

  Addresses for auth-service (`FRONTEND_URL`, `DIAGNOSTIC_BASE_URL`, `SITE_URL`, `CONSOLE_URL`) are in `.env.example`:
  `FRONTEND_URL=https://app.algolab.me` and `DIAGNOSTIC_BASE_URL=https://app.algolab.me/d` from step 7 (stage: `stage.algolab.me`).
* **Step 7 (algolab.me becomes the landing)** is one change, described in the header of
  `nginx/conf.d/staging-apex-landing.conf.disabled` (how to enable and how to roll back). CI rehearses it on every run
  (job «nginx», step «step 7 rehearsal»).
* **Letters and sessions (K2-1):** `MAIL_REPLY_TO` (the support alias, the same on both stacks), `MAIL_ALLOWLIST` (prod: empty = no restriction; stage: the
  only addresses/domains that get a letter, nobody while empty), `MAIL_STAGE_MODE=true` (written in `docker-compose.preview.yml`, never on prod),
  `JWT_REFRESH_TTL_DAYS=14`. K2-2: `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (build arg of the front, the public key of the «Забыли пароль» widget) and `TURNSTILE_HOSTNAMES` of auth must name `app.` and `stage.`. All have defaults in compose; `tests/test_k2_mail_env.py` (CI, job «scripts») fails when the stacks drift apart.
  Before the first walk-through of the stage put the mailboxes of the checkers and the `ADMIN_NOTIFICATION_EMAIL` address into `MAIL_ALLOWLIST` of `.env.preview`.
* Both stacks' env files must contain `FRONTEND_SITE_URL`: compose refuses to start the frontend without it.

### Rollout order of the variables (K3 steps 4–5), as explicit items

1. **Before `git pull`/path-checkout of this infrastructure on the server:** add `FRONTEND_SITE_URL` to `~/algo/.env.preview`
   (`https://landing.stage.algolab.me`) and `~/algo/.env.staging` (`https://algolab.me`). Otherwise every compose command of the
   stack fails with `FRONTEND_SITE_URL is required`, including the deploy jobs that run `nginx -t && reload`. Back up both
   files first; run `config -q` with each file.
2. **Empty the three `NEXT_PUBLIC_*_API_URL` on the server** in both env files (set them to nothing, do not delete the lines
   with other values left behind). Do it together with the first frontend build that contains K3 P1: an older frontend build
   with empty addresses would call `localhost`.
3. Then the order of the spec: the `app.` block (step 5), landing.stage (step 6), apex (step 7).

### Applying this nginx/compose change (step 6, and the same before step 7)

1. Create `~/algo/landing/stage`, `~/algo/landing/prod`, `~/algo/nginx-alias-log` (otherwise Docker creates them owned by root).
2. `nginx -t` of the new `conf.d` in a **separate** container with the same mounts and the real `/etc/letsencrypt`.
3. **Recreate** the nginx container (`up -d --no-deps nginx`): new bind mounts do not appear on `reload`.
4. **Before any reload or smoke test** check the mounts: `docker exec algo-staging-nginx ls /usr/share/nginx/landing-stage/index.html
   /usr/share/nginx/landing-prod /var/log/nginx-alias` (an empty `landing-prod` is fine until the first prod deploy of the landing).
5. Only then the smoke tests; at step 7 the same check precedes the reload (see the header of the `.disabled` file).

### Known differences (accepted by the lead)

* **gzip of JSON on the alias** (`algolab.me`, after step 7): the landing block turns `gzip` on for the whole server, so JSON of the
  transitional API alias is compressed too. Harmless, removed with the alias on day 30.
* **`proxy_pass` without URI on `landing.stage`** (and the alias): the path goes to the upstream as received and is not normalised
  by nginx, exactly as on production. Not exploitable here: the upstreams are our own APIs behind their own routing.
* **Tokens in `error_log` on a 502** (deploy windows): nginx writes the request line of a failed upstream to `error_log`, and that
  line is not masked by the access-log maps. Short windows during deploys; keep `error_log` out of shared channels.
* **`/.well-known/*` on the landing answers 404** (the `^~ /.` rule), except ACME on port 80 handled in `staging.conf`. A future
  `security.txt` needs its own explicit `location = /.well-known/security.txt` line before that rule.
* **Stage `/landing/`** on `stage.algolab.me` still goes to the old container `algo-preview-landing`; it is removed together with
  the old landing on day 7 after step 7 (for stage the same change).
* **Redacted logs:** `$prod_safe_uri` / `$preview_safe_uri` mask `/d|e|invite|diagnostic|set-password/<code>`,
  `/api/v1/auth/password-links/<token>`, `/api/v1/(auth|internal)/diagnostic/<code>`, `/api/v1/auth/invite/<code>`,
  `/api/v1/exams/by-code/<code>[/…]` and `…/session-status/<id>`. The alias log of the landing uses the same map.

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
`https://app.algolab.me/api/version` (stage: `https://stage.algolab.me/api/version`; until K3 step 7 the product still answers on `algolab.me` too).

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
