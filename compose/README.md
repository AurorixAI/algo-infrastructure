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
