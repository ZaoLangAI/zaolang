---
name: zaolang-remote-deploy
description: Single-host remote deploy and update — rsync the working tree to the production box, rebuild infra/docker-compose.prod.yml, run Alembic via the migrate service, and (only when the operator names it) overwrite the remote database from a local dump. Use when deploying or updating ZaoLang on the remote server, rsyncing to production, running make prod-up, pushing a local Postgres dump, or the user mentions 124.223.45.115 / the Ubuntu prod host.
disable-model-invocation: true
---

# Single-Host Remote Deploy

## Scope

The one production box. Local gates and `make release-up` stay in `zaolang-ci-release`. Ask the operator for SSH auth each time (agent / key / `sshpass`); **never write the password, JWT, Postgres, MinIO, or COS secrets into this skill, the repo, or a commit.**

## Host

| | |
| --- | --- |
| Address | `124.223.45.115` |
| User | `ubuntu` |
| Repo | `/home/ubuntu/zaolang` |
| Compose | `infra/docker-compose.prod.yml` + `infra/.env.prod` (server-only, gitignored) |
| Entry | `make prod-up` → `docker compose … up -d --build` |
| Public | HTTP `:80` only (`PUBLIC_HOST=124.223.45.115`) |

## Key Paths

| File | Contents |
| --- | --- |
| `infra/docker-compose.prod.yml` | postgres / redis / minio / minio-init / migrate / api / worker / poller / beat / web / nginx. Only nginx publishes a host port (`:80`); the API container listens on `8000` internally (`API_INTERNAL_URL=http://api:8000`, not the laptop's `3001`). Worker `-Q` mirrors `make dev-worker` (incl. `platform_distribution`, `video_analysis`), `--concurrency=${WORKER_CONCURRENCY:-4}` |
| `infra/.env.prod.example` | placeholder template; real values live only on the server. Besides secrets: `COOKIE_SECURE=false` (HTTP-only box, flip on HTTPS), `WORKER_CONCURRENCY`, `REDIS_MAXMEMORY`, build-time-only `APT_MIRROR` / `PIP_INDEX_URL` |
| `infra/nginx/prod.conf.template` | `/v1` `/mcp` health + MinIO `location /${MEDIA_BUCKET}/` (envsubst'd at container start; compose sets `MEDIA_BUCKET` from `S3_BUCKET`) + Next.js. Upstreams resolve per request through Docker DNS (`resolver 127.0.0.11` + `proxy_pass $api_upstream` / `$web_upstream` / `$minio_upstream`), so a recreated container is picked up without touching nginx |
| `Makefile` `prod-up` / `prod-down` / `prod-logs` | remote compose wrappers |
| `infra/scripts/backup.sh` | local `pg_dump` only — not the remote restore path |

## Invariants

1. **Default later updates keep the remote database.** Probe → rsync the working tree → `make prod-up` (the `migrate` service reaches Alembic head) → verify. No dump, no restore, no Redis `FLUSHDB`, no seed, no `down -v`.
2. **`push_local` (overwrite the remote DB from the laptop) is high-risk and only runs when the operator names it.** Backup the remote DB first; stop `api` / `worker` / `poller` / `beat`; `pg_restore --clean --if-exists --no-owner --no-privileges` into the compose Postgres; Redis `FLUSHDB`; then migrate and `prod-up`. Local role `zaolang` ≠ remote password — `--no-owner` is required. Refresh tokens signed with the laptop `JWT_SECRET` will not match the server; users re-login.
3. **Never seed in production.** `python -m app.scripts.seed` raises when `APP_ENV=production`. The admin HTTP seed is also refused. Do not `down -v`. When the operator names a catalogue backfill, run `python -m app.scripts.ensure_catalog` inside the `api` container — additive `CreationSkill` / `LearnPost` rows (and shipped covers) only; an existing `zaolang_studio` password is never rotated.
4. **`make restore` / `infra/scripts/restore.sh` must not target the remote box** — the script refuses a URL containing `prod` and defaults to laptop `:5433`. Remote restore is `docker compose exec -T postgres pg_restore …`.
5. **Never overwrite `infra/.env.prod` with rsync.** Exclude `.git`, `node_modules`, `.next`, `__pycache__`, `back/.env`, `front/.env.local`, and `infra/.env.prod`. Append new keys; do not rotate JWT / Postgres / MinIO secrets on an update.
6. **`object_key` rows and `STORAGE_BACKEND` must agree.** On the host prefer `STORAGE_BACKEND=tencent_cos` against the same bucket as the laptop (append `COS_*` to the server's `.env.prod`); the committed `infra/.env.prod.example` and the compose default (`${STORAGE_BACKEND:-minio}`) still say `minio` — do not assume the template matches the box, read the server file. MinIO can stay running unused. nginx `/${MEDIA_BUCKET}/` only proxies MinIO path-style signed URLs — COS objects are fetched from `*.myqcloud.com`.
7. **Do not put a date diary or a fixed-incident write-up in this skill.** Keep constraints that still apply.

## Default update (code + migrate)

```bash
# Probe: repo present, compose ps, disk, SELECT version_num FROM alembic_version
rsync -az --delete \
  --exclude='.git' --exclude='node_modules' --exclude='.next' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
  --exclude='.backups' --exclude='back/.env' --exclude='front/.env.local' \
  --exclude='infra/.env.prod' --exclude='.pytest_cache' --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  ./ ubuntu@124.223.45.115:/home/ubuntu/zaolang/
# on the server, from /home/ubuntu/zaolang:
make prod-up
```

`make prod-up` recreates `api` / `web` / the Celery services (new container IPs) but leaves `nginx` running. That is fine: nginx re-resolves `api` / `web` / `minio` through Docker DNS (`valid=10s`), so it reaches the new containers within ~10s without a restart.

If the rsync changed `infra/nginx/prod.conf.template` itself, `up -d` still leaves nginx alone — the bind-mounted file changed, the compose config did not. Restart it afterwards. `nginx -s reload` is not enough: the template is only envsubst-rendered when the container starts.

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod restart nginx
```

## Catalogue backfill (only when named)

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod \
  exec -T api python -m app.scripts.ensure_catalog
```

## `push_local` (only when named)

1. Remote custom-format `pg_dump` to `~/zaolang-backup/` (do this before overwrite).
2. Laptop: `pg_dump --format=custom --no-owner --no-privileges` from `postgresql://zaolang:zaolang@localhost:5433/zaolang`; scp the file.
3. rsync as above; append `STORAGE_BACKEND` / `COS_*` to the **existing** server `.env.prod` if missing. Do not replace the file.
4. Keep `postgres` healthy; stop writers; restore; `FLUSHDB` on redis; `docker compose run --rm migrate`; `make prod-up`.

## Extension Points

- **New compose env var**: add it to `x-backend` `environment` in `docker-compose.prod.yml` **and** a placeholder in `.env.prod.example`. On the next update, append the key to the server `.env.prod` — do not rsync a replacement file.
- **New Celery queue**: `back/app/workers/celery_app.py` + `Makefile` `dev-worker` `-Q` + this prod compose `worker` command + the admin health page. Miss the prod list and those jobs hang on the box.
- **New nginx upstream / location**: `proxy_pass` through a lowercase `$<name>_upstream` variable set next to the others (URI-less — no path after the variable), plus a matching `proxy_redirect`. A literal `proxy_pass http://host:port` pins the IP from nginx's startup and 502s once that container is recreated.
- **Second host**: copy the Host table; do not fork a second skill.

## Verify

```bash
curl -sS http://124.223.45.115/healthz
curl -sS http://124.223.45.115/readyz
# on the server: alembic_version == laptop `alembic heads`
```

A 502 for up to ~10s right after `prod-up` is nginx's DNS cache expiring. If `/healthz` keeps returning 502 while `docker compose ps` shows `api` healthy, nginx is dialing a stale upstream (error log: `connect() failed (111: Connection refused) while connecting to upstream`). Check that the running config has the resolver; if it doesn't, the template on the box predates runtime resolution or nginx was never restarted after it changed — restart nginx as above.

```bash
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod logs --tail=20 nginx
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod exec nginx nginx -T | grep resolver
```

Then in the browser: consumer login, `/admin`, one work whose cover loads from COS (not a 404). Admin health: Postgres / Redis / Celery green. MinIO may still report green (container up) while business I/O uses COS.
