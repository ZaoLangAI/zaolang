---
name: zaolang-local-env
description: Local dev environment and command entry points — dual conda/fnm toolchains, OrbStack containers (pgvector 5433, Redis 6380, MinIO 9000), Makefile targets, env vars, port conventions, seed accounts. Use when starting or fixing the local stack, editing the Makefile, docker-compose, .env files, ports, conda/fnm setup, or when `make up` / `make seed` / `make dev` fails.
disable-model-invocation: true
---

# Local Environment & Command Entry Points

## Scope

"Getting it running" collapses into the `Makefile`: containers, migrations, seeding, the three dev processes, and quality gates all have a target. Don't hand-assemble commands in the terminal.

## Key Paths

| Path | Purpose |
| --- | --- |
| `Makefile` | The single entry point. `make help` lists every target |
| `infra/docker-compose.yml` | postgres (pgvector/pg17) / redis / minio / minio-init |
| `infra/.env.example` | compose variables (ports, MinIO credentials, bucket names) |
| `back/environment.yml` + `back/requirements*.txt` | conda env `zaolang`, Python 3.12 |
| `back/.env.example` → `back/.env` | backend config, incl. `LLM_API_KEY`, `CORS_ORIGINS` |
| `front/.node-version` | Node version read by fnm |
| `front/.env.example` → `front/.env.local` | `API_INTERNAL_URL` (RSC) and `NEXT_PUBLIC_API_URL` (browser + SSE) |
| `back/app/config.py` | pydantic-settings; the single source for every default |

## Invariants

1. **Ports are deliberately offset**: Postgres `5433`, Redis `6380`, to avoid colliding with services already running on the machine. Changing a port means updating both `infra/.env.example` and `back/.env`.
2. **Secrets live only in `back/.env`** (gitignored). `.env.example` holds placeholders only — secrets must never be echoed in logs, agent prompts, or the config-center UI.
3. **The two toolchains never mix**: backend commands always run under `conda run -n zaolang`; frontend commands always start with `fnm use`. The Makefile's `CONDA_RUN` / `FNM_ENV` already wrap this.
4. **`make seed ARGS=--reset` truncates business tables** (plain `make seed` is idempotent — it backfills, it doesn't clear tables); use `--reset` only locally and in test environments. The admin seed panel refuses outright in production. After wiping the database, always run `make dev-purge-queues` (stop the worker first) — stale `job_id`s left in Redis otherwise make the worker report "job not found".
5. **Alembic has exactly one linear migration chain**; `make migrate` must reach `head` from an empty database.
6. **`make dev`'s Web and API listen on `localhost`** (loopback) by default. Local media signing is pinned to `S3_PUBLIC_ENDPOINT_URL=http://localhost:9000` with `LOCAL_MEDIA_HOST` left empty — never hardcode a machine's LAN IP into either, since a DHCP/network change breaks SigV4 signing and the `/_next/image` allowlist together. Opening the app from another device by IP is not something you fix by changing the signing host. `NEXT_ALLOWED_DEV_ORIGINS` takes hostnames only, for Next.js dev-asset/HMR WebSocket origin checks — never substitute `*` for a credentialed CORS origin.

## Common Targets

```bash
make setup             # create the conda env, install front/back deps, copy .env files
make up                 # start containers and create MinIO buckets
make migrate seed       # create tables + seed data
make dev                # run API(8000) / Celery worker / Celery beat / Web(3000) in parallel
make dev-beat           # start only the async-provider-polling and timeout-reclaim scheduler
make dev-purge-queues   # flush Celery queues (after seed --reset / a DB wipe; stop the worker first)
make reset              # destroy the data volume and rebuild (up + migrate + seed)
make logs
```

Seed accounts share the password `Zaolang2026`: `linhai` (author), `mizuki` (remixer), `reviewer`, `operator`, `admin`, `driftwood` (suspended — for testing 401s and admin user operations). All emails follow `<handle>@zaolang.dev`.

## Extension Points

- **Add an external dependency**: add it to `infra/docker-compose.yml` with a health check (`make up` uses `--wait`) → add a config field + default in `back/app/config.py` → add a probe in `back/app/api/health.py`, otherwise it won't show up on the admin system-health page.
- **Add an env var**: add the field in `config.py` → add the placeholder in `back/.env.example`. Missing either and a fresh clone won't run.
- **Add a Celery queue**: register routing in `back/app/workers/celery_app.py`, then sync the Makefile's `dev-worker` `-Q` list and the admin health page's queue list. The drama editor's analysis queue is `media_analysis`, already in `dev-worker -Q` — miss it and analysis jobs on uploaded source assets hang forever.
- **Enable the drama editor locally**: `make seed`'s `_seed_editor_flags` flips five editor flags to true and gives `linhai` one `kind=drama` demo project. `DEFAULT_CONFIGS` stays false — empty databases and production default to off. Don't write the local seed's `true` back into the schema defaults.

## Verify

```bash
make up && make migrate && make seed
curl -s localhost:8000/healthz | jq       # process is alive
curl -s localhost:8000/readyz | jq        # Postgres / Redis ready (MinIO is checked on the admin health page)
make dev                                  # all three processes start clean
```

If containers won't start, check `orb start` first. The `pgvector` extension is created by a migration — `psql -c '\dx'` should list it.
