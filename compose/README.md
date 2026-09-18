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

`.env.example` in the cluster root documents the required keys.

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
