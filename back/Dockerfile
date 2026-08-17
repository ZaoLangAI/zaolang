# syntax=docker/dockerfile:1.9

# Wheels are built in a throwaway stage so the runtime image carries no compiler
# and no build caches. imagehash pulls in numpy/scipy, which is the reason a
# single-stage build ends up several hundred megabytes larger.
FROM python:3.12-slim-bookworm AS builder

# Both empty by default (upstream Debian/PyPI). Set at build time on a host
# where those are slow/throttled, e.g.
# `--build-arg APT_MIRROR=mirrors.tencentyun.com --build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple`.
ARG APT_MIRROR=
ARG PIP_INDEX_URL=
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim-bookworm AS runtime

ARG APT_MIRROR=

# `pg_dump` is not optional: the admin backup endpoint shells out to it, so an
# image without it would fail only when an operator triggers a backup.
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl postgresql-client ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 zaolang

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

WORKDIR /app
COPY --chown=zaolang:zaolang alembic.ini ./
COPY --chown=zaolang:zaolang alembic ./alembic
COPY --chown=zaolang:zaolang app ./app

USER zaolang
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# The API and the Celery worker ship as one image with different commands, so
# they can never drift to different revisions of the domain code.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
