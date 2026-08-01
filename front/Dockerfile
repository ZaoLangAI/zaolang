# syntax=docker/dockerfile:1.9

FROM node:22-bookworm-slim AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:22-bookworm-slim AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# `NEXT_PUBLIC_*` values are inlined into the client bundle, so the browser-facing
# API URL has to be known at build time. Server-side reads (`API_INTERNAL_URL`)
# stay runtime configuration.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG SOURCE_REPOSITORY_URL=https://github.com/ZaoLangAI/zaolang
ARG APP_VERSION=0.0.0-dev
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    SOURCE_REPOSITORY_URL=$SOURCE_REPOSITORY_URL \
    APP_VERSION=$APP_VERSION \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:22-bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# `output: 'standalone'` traces exactly the files the server needs, so the image
# carries no dev dependencies and no source.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/zh-CN/discover -o /dev/null || exit 1

CMD ["node", "server.js"]
