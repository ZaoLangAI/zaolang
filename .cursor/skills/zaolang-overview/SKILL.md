---
name: zaolang-overview
description: The ZaoLang repository's master index and routing table — front/back/ios/infra ownership, the boundaries of the 22 module skills, and which one to load explicitly for a given change. Use when working anywhere in this repository, or when the user mentions ZaoLang, works and lineage, the credit ledger, generation jobs, the agent gateway, the admin console, admin statistics, the iOS client, the drama editor, or asks where a feature lives in this codebase.
---

# ZaoLang — Repository Overview

A global AI co-creation sharing platform. **Read this routing table first, then explicitly load the matching module skill** — don't guess and edit blind. This repo's invariants concentrate in three places — the credit ledger, the job state machine, and licensing/lineage — and breaking one won't show up in a type check. The software licence is internal-proprietary (see root `LICENSE`); that's a separate thing from a work's license snapshot / lineage inside the product domain.

## Repository Layout

| Path | Contents |
| --- | --- |
| `back/` | FastAPI + Agno AgentOS, conda env `zaolang`, Python 3.12 |
| `front/` | Next.js 16 App Router + Tailwind v4, fnm reading `front/.node-version`; consumer and admin share one project, isolated in session and API |
| `ios/` | the native iOS client, SwiftUI + Swift Concurrency, an XcodeGen project, a read-only M1 closed loop, no admin capability |
| `infra/` | docker-compose: PostgreSQL 17 (pgvector) on `5433`, Redis on `6380`, MinIO on `9000` |
| `docs/` | the MkDocs site source and ops runbook |
| `assets-pack/` | where a user drops real media; `manifest.example.json` in the repo defines the import contract — for a real import, copy/fill in a local `assets-pack/manifest.json` (not committed by default) |

Backend layering: `api/v1` (the HTTP contract) → `domain/*` (where invariants live) → `models` (SQLAlchemy). `agents` / `teams` / `workflows` / `providers` / `workers` sit on top of domain — **an agent may only reach domain services through the `app/agents/tools.py` whitelist, and its output isn't fact until it's persisted.**

## Load By Intent

| What you're changing | Load |
| --- | --- |
| Starting services, containers, env vars, the Makefile | `zaolang-local-env` |
| Adding a table, a column, writing a migration | `zaolang-data-model` |
| Adding an endpoint, an error code, idempotency, rate limits, auth | `zaolang-api-contract` |
| Tier pricing, provider switches/quotas, feature flags, agent-model bindings | `zaolang-platform-config` |
| Visibility, remix authorization, license snapshots, lineage edges/tombstones, credit-unlock grants | `zaolang-domain-licensing-lineage` |
| Credit reservation and settlement, royalty payback, forced marketplace transfers, reconciliation, payment webhooks, redemption codes | `zaolang-credits-billing` |
| Job submission, the state machine, SSE, Celery queues, cancellation and retries | `zaolang-generation-jobs` |
| The Safety/Planner/Quality/Copy/Intent Router agents, provider hard-filtering and LLM selection, the LLM gateway and response normalization | `zaolang-agent-gateway` |
| Upload presigning, private-object downloads, pHash fingerprinting, AI-provenance manifests | `zaolang-media-assets` |
| Search, tags, inspiration-wall sort, pgvector similar works, style presets | `zaolang-discovery-search` |
| Audit logs, SystemLog security signals, data export/deletion, backups and lifecycle | `zaolang-compliance-audit` |
| Consumer pages, shared components, the login dialog and action recovery, the command palette | `zaolang-frontend-ui` |
| Colour tokens, dark/light theming, flicker-free SSR | `zaolang-theming` |
| Trilingual copy, locale and region, currency/date formatting | `zaolang-i18n-region` |
| The lineage-graph DAG, version-parameter diffing | `zaolang-lineage-graph` |
| The admin shell, its separate login, RBAC nav, tables and dangerous-action components | `zaolang-admin-console` |
| Admin-ops endpoints and pages (incl. the skill library, style gallery, redemption codes, log center) | `zaolang-admin-ops` |
| The admin statistics center, daily-trend timeseries, empty-day zero-fill | `zaolang-admin-statistics` |
| The iOS client (SwiftUI screens, ZaolangKit, XcodeGen, colour/string generation scripts) | `zaolang-ios-client` |
| Local gates, Docker images, the docs site | `zaolang-ci-release` |
| Writing tests, running E2E, accessibility and visual QA | `zaolang-testing-qa` |
| The drama timeline, EditCommand, leases, browser export, editor_planner, Remote MCP | `zaolang-editor-drama` |

For a change spanning modules, load in dependency order: `data-model` → `domain/*` → `api-contract` → frontend.

## Three Global Rules

1. **The implementation is ground truth.** When a requirement is ambiguous, read the existing code, `docs/`, and tests — don't invent product behavior from nothing.
2. **Amounts are always integers** (credits and minor units) — any floating-point number touching an amount calculation is a bug.
3. **IDs carry a type prefix** (`u_` / `w_` / `job_` / `k_`, etc.), generated by `back/app/models/base.py:new_id` — never hand-write an ID string.

## Full Verification

```bash
make check   # lint + typecheck + trilingual copy + OpenAPI drift + the full test suite
```

Per-module commands are in each module skill's "Verify" section.
