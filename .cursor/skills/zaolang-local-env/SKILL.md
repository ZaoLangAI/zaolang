---
name: zaolang-local-env
description: Local dev stack — conda `zaolang` + fnm, compose Postgres 5433 / Redis 6380 / optional MinIO 9000, Makefile dev targets, .env files, seed. Use when starting or fixing the local stack, editing infra/docker-compose.yml, .env files or ports, or when `make up`/`make seed`/`make dev` fails.
---

# Local Environment

**Scope**: getting the stack running; every step has a `make` target (`make help` lists them) — don't hand-assemble commands. Not here → `zaolang-ci-release` (`make check`), `zaolang-testing-qa` (e2e prerequisites), `zaolang-platform-config` (flags), `zaolang-remote-deploy` (prod).

## Key Paths

| Path | What |
| --- | --- |
| `Makefile` | single entry point; `CONDA_RUN` / `FNM_ENV` wrappers, `DEV_API_PORT` 3001 / `DEV_WEB_PORT` 3000 |
| `infra/docker-compose.yml` | postgres (pgvector) / redis / minio / minio-init |
| `infra/postgres-init/01-extensions.sql` | `vector` + `pg_trgm` extensions, `zaolang_test` DB |
| `infra/.env.example` | compose ports and MinIO credentials |
| `back/environment.yml` | conda env `zaolang` (Python 3.12) + `back/requirements.txt` |
| `back/.env.example` | template for `back/.env` (secrets live only there, gitignored) |
| `back/app/config.py` | pydantic-settings; source of every default |
| `front/.node-version` | Node version for fnm |
| `front/.env.example` | template for `front/.env.local` (`API_INTERNAL_URL`, `NEXT_PUBLIC_API_URL`) |
| `back/app/scripts/seed.py` | seed data, `SEED_USERS`, `SEED_PASSWORD`, `_seed_editor_flags` |

## Invariants

1. Ports are offset on purpose: Postgres `5433`, Redis `6380`, MinIO `9000`, API `3001`, Web `3000`. Changing one means `infra/.env.example` + `back/.env` (and for API/Web also Makefile vars, `front/.env.example` URLs, `CORS_ORIGINS`).
2. Toolchains never mix: backend under `conda run -n zaolang`, frontend after `fnm use` — use the Makefile wrappers.
3. Storage: `make up` starts only postgres + redis. `Settings.storage_backend` defaults to `minio`, but the usual local setup is `STORAGE_BACKEND=tencent_cos` + `COS_*` in `back/.env`. Keeping `minio` → start `minio minio-init` via compose yourself or `make seed`'s bucket check fails.
4. Media signing stays on `S3_PUBLIC_ENDPOINT_URL=http://localhost:9000` with `LOCAL_MEDIA_HOST` empty; never hardcode a LAN IP. `NEXT_ALLOWED_DEV_ORIGINS` takes hostnames, never `*`.
5. `make seed` is idempotent; `make seed ARGS=--reset` truncates business tables (local/test only; seed refuses in production). After any DB wipe run `make dev-purge-queues` (drops orphan Celery messages/results, never `FLUSHDB` — rate-limit keys share db0).
6. Seed turns on the local creation/editor feature flags (list: `_seed_editor_flags` in `back/app/scripts/seed.py`); schema defaults stay off — don't copy seed values into `FeatureFlags` defaults.
7. One linear Alembic chain; `make migrate` must reach head from an empty DB.
8. `/healthz` and `/readyz` (Postgres + Redis) live in `back/app/api/health.py`; the admin system-health probes (storage, Celery, async polling) live in `back/app/api/v1/admin/observability.py`.

## Recipes

**First run**: `orb start` → `make setup` → fill `back/.env` → `make up && make migrate && make seed` → `make dev` (API, worker, poller, Beat, Web).

**Add an env var**: field + default in `back/app/config.py` → placeholder in `back/.env.example`.

**Add an external service**: compose service with a healthcheck (`make up` uses `--wait`) → config field → a probe in `back/app/api/v1/admin/observability.py`.

## Verify

```bash
make up && make migrate && make seed
make dev
curl -s localhost:3001/healthz
curl -s localhost:3001/readyz
make check
```

Seed accounts share `SEED_PASSWORD` (`linhai` author, `mizuki` remixer, `admin`, `reviewer`, `operator`, …; emails mostly `<handle>@zaolang.dev`). Missing `vector` extension → `psql -c '\dx'` on the container.
