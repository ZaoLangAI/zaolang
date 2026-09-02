---
name: zaolang-local-env
description: Local dev environment and command entry points — dual conda/fnm toolchains, OrbStack containers (pgvector 5433, Redis 6380; MinIO 9000 optional/manual), Makefile targets, env vars, port conventions, seed accounts. Use when starting or fixing the local stack, editing the Makefile, docker-compose, .env files, ports, conda/fnm setup, or when `make up` / `make seed` / `make dev` fails.
disable-model-invocation: true
---

# Local Environment & Command Entry Points

## Scope

"Getting it running" collapses into the `Makefile`: containers, migrations, seeding, the five dev processes, and quality gates all have a target. Don't hand-assemble commands in the terminal.

## Key Paths

| Path | Purpose |
| --- | --- |
| `Makefile` | The single entry point. `make help` lists every target |
| `infra/docker-compose.yml` | postgres (pgvector/pg17) / redis / minio / minio-init — `make up` only starts postgres+redis; MinIO is opt-in. `Settings.storage_backend` (and `back/.env.example`) still default to `minio`, but the intended local setup is `STORAGE_BACKEND=tencent_cos` with `COS_*` filled in `back/.env`; if you keep `minio`, run `docker compose -f infra/docker-compose.yml up -d minio minio-init` yourself or `make seed`'s `s3.ensure_bucket()` fails |
| `infra/postgres-init/01-extensions.sql` | container init: creates the `vector` + `pg_trgm` extensions and the `zaolang_test` database (`TEST_DATABASE_URL`) |
| `infra/.env.example` | compose variables (ports, MinIO credentials, bucket names) — MinIO keys only matter if you start the container |
| `back/environment.yml` + `back/requirements*.txt` | conda env `zaolang`, Python 3.12 |
| `back/.env.example` → `back/.env` | backend config, incl. `LLM_API_KEY`, `CORS_ORIGINS` |
| `front/.node-version` | Node version read by fnm |
| `front/.env.example` → `front/.env.local` | `API_INTERNAL_URL` (RSC) and `NEXT_PUBLIC_API_URL` (browser + SSE) |
| `back/app/config.py` | pydantic-settings; the single source for every default |

## Invariants

1. **Ports are deliberately offset**: Postgres `5433`, Redis `6380`, to avoid colliding with services already running on the machine. Changing a container port means updating both `infra/.env.example` and `back/.env`; changing the API/Web ports (`3001`/`3000`) also touches the `Makefile`'s `DEV_API_PORT` / `DEV_WEB_PORT` and `front/.env.example`'s `API_INTERNAL_URL` / `NEXT_PUBLIC_API_URL` (plus `CORS_ORIGINS` in `back/.env`).
2. **Secrets live only in `back/.env`** (gitignored). `.env.example` holds placeholders only — secrets must never be echoed in logs, agent prompts, or the config-center UI.
3. **The two toolchains never mix**: backend commands always run under `conda run -n zaolang`; frontend commands always start with `fnm use`. The Makefile's `CONDA_RUN` / `FNM_ENV` already wrap this.
4. **`make seed ARGS=--reset` truncates business tables** (plain `make seed` is idempotent — it backfills, it doesn't clear tables); use `--reset` only locally and in test environments. The admin seed panel refuses outright in production. After wiping the database, always run `make dev-purge-queues` — stale `job_id`s left in Redis otherwise make the worker report "job not found" and occupy a concurrency slot. That target drops only orphan broker messages and leftover `celery-task-meta`; it does **not** `FLUSHDB` (rate-limit keys and LLM failover stats live on the same db0). Use `ARGS=--empty-queues` only when you intend to discard every queued message.
5. **Alembic has exactly one linear migration chain**; `make migrate` must reach `head` from an empty database.
6. **`make dev`'s Web and API listen on `localhost`** (loopback) by default. Local media signing is pinned to `S3_PUBLIC_ENDPOINT_URL=http://localhost:9000` with `LOCAL_MEDIA_HOST` left empty — never hardcode a machine's LAN IP into either, since a DHCP/network change breaks SigV4 signing and the `/_next/image` allowlist together. Opening the app from another device by IP is not something you fix by changing the signing host. `NEXT_ALLOWED_DEV_ORIGINS` takes hostnames only, for Next.js dev-asset/HMR WebSocket origin checks — never substitute `*` for a credentialed CORS origin.

## Common Targets

```bash
make setup             # create the conda env, install front/back deps, copy .env files
make up                 # start postgres/redis only (MinIO not started — see the compose row above; COS needs no container)
make down               # stop containers (keeps volumes)
make migrate seed       # create tables + seed data
make migration m="..."  # alembic revision --autogenerate
make dev                # run five processes in parallel: API(3001) / Celery worker / poller / beat / Web(3000); reaps leftover listeners on those ports at start and on Ctrl+C
make dev-free-ports     # reap leftover listeners on 3000/3001 and this repo's Celery processes
make dev-worker         # -Q image_generation,video_generation_long,audio_generation,quality_check,webhook_reconcile,media_analysis,platform_distribution,video_analysis
make dev-poller         # provider_task_polling only, concurrency 1, its own -n
make dev-beat           # start only the async-provider-polling and timeout-reclaim scheduler
make dev-purge-queues   # drop orphan Celery messages + result keys (after seed --reset / a DB wipe)
make reset              # destroy the data volume and rebuild (up + migrate + seed)
make check-assets       # dry-run validate assets-pack/manifest.json; make import-assets writes it to the DB
make backup             # pg_dump to .backups/ (infra/scripts/backup.sh); make restore f=.backups/xxx.dump (laptop only)
make hooks              # install pre-commit hooks
make test-llm           # -m live LLM smoke, needs a real key, never part of make check
make logs
```

Seed accounts share the password `Zaolang2026`: `linhai` (author), `mizuki` (remixer), `ava` (third-generation remixer), `reviewer`, `operator`, `admin`, `zaolang_studio` (owner of the curated `CreationSkill` catalogue, plain `USER` role, email `studio@zaolang.dev`), `driftwood` (suspended — for testing 401s and admin user operations). All other emails follow `<handle>@zaolang.dev` (`SEED_USERS` in `back/app/scripts/seed.py`).

## Extension Points

- **Add an external dependency**: add it to `infra/docker-compose.yml` with a health check (`make up` uses `--wait`) → add a config field + default in `back/app/config.py` → add a probe in `back/app/api/health.py`, otherwise it won't show up on the admin system-health page.
- **Add an env var**: add the field in `config.py` → add the placeholder in `back/.env.example`. Missing either and a fresh clone won't run.
- **Add a Celery queue**: register routing in `back/app/workers/celery_app.py`, then sync the Makefile's `dev-worker` `-Q` list, `infra/docker-compose.release.yml` / `infra/docker-compose.prod.yml` worker commands, and the admin health page's queue list. The drama editor's analysis queue is `media_analysis`, already in `dev-worker -Q` — miss it and analysis jobs on uploaded source assets hang forever. A second worker process (the poller) must keep its own `-n` (`zaolang-poller@%h`); sharing `celery@hostname` with `dev-worker` collapses inspect/revoke onto one node.
- **Enable the drama editor locally**: `make seed`'s `_seed_editor_flags` flips seven flags to true (`drama_studio_enabled`, `web_editor_enabled`, `variant_export_enabled`, `editor_ai_enabled`, `editor_mcp_enabled`, `script_studio_enabled`, `video_analysis_enabled`). `DEFAULT_CONFIGS` stays false — empty databases and production default to off. Don't write the local seed's `true` back into the schema defaults.

## Verify

```bash
make up && make migrate && make seed
curl -s localhost:3001/healthz | jq       # process is alive
curl -s localhost:3001/readyz | jq        # Postgres / Redis ready (MinIO is checked on the admin health page)
make dev                                  # all five processes start clean
```

If containers won't start, check `orb start` first. The `vector` extension is created by `infra/postgres-init/01-extensions.sql` on first container init — `psql -c '\dx'` should list it.
