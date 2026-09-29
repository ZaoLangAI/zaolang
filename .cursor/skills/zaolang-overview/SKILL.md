---
name: zaolang-overview
description: ZaoLang repo map and skill router — stack, front/back/ios/infra layout, backend layering, global rules, and which zaolang-* module skill owns a change. Use when starting any work in this repo or when unsure where a feature lives.
---

# ZaoLang — Repository Overview

Global AI co-creation sharing platform. Read the routing table, then load the owning module skill before editing. Invariants concentrate in the credit ledger, the job state machine and licensing/lineage — breaking one won't show up in a type check. Software licence: Apache-2.0 (root `LICENSE`), unrelated to in-product work licences.

## Stack & Layout

| Path | Contents |
| --- | --- |
| `back/` | FastAPI 0.141 + Agno 2.8, SQLAlchemy 2 + Alembic, Celery 5 + Redis, Pydantic 2; conda env `zaolang`, Python 3.12 |
| `front/` | Next.js 16.3 App Router, React 19.2, Tailwind 4, next-intl 4, zustand 5, @xyflow/react 12, three 0.185, mediabunny 1.29; Node via fnm (`front/.node-version`). Consumer `(site)`/`(studio)` and `(admin)` share one app, isolated in session + API |
| `ios/` | SwiftUI iOS 17 client, XcodeGen `ios/project.yml`, `ios/Packages/ZaolangKit`; no admin |
| `infra/` | docker-compose: Postgres 17 + pgvector `5433`, Redis `6380`, MinIO `9000` (opt-in; `make up` starts only postgres+redis) |
| `docs/` | MkDocs site source and ops runbooks |
| `assets-pack/` | real-media drop zone; `assets-pack/manifest.example.json` defines the import contract |
| `third_party/` | vendored `opencut-classic` Rust workspace → `front/public/wasm/opencut/` compositor (drama editor); never hand-edited |

Backend layering: `back/app/api/v1` (HTTP contract) → `back/app/domain/*` (invariants) → `back/app/models` (SQLAlchemy). `agents`/`teams`/`llm`/`providers`/`workflows`/`workers` sit on top of domain; an agent reaches domain only via the `back/app/agents/tools.py` whitelist, and its output isn't fact until persisted.

## Routing Table

| Changing… | Load |
| --- | --- |
| Local stack, compose, `.env`, Makefile dev targets, seed | `zaolang-local-env` |
| Tables, columns, enums, migrations, ID prefixes | `zaolang-data-model` |
| New endpoint, error code, idempotency, rate limit, auth deps, logging/OTel | `zaolang-api-contract` |
| Runtime config, feature flags, model prices | `zaolang-platform-config` |
| Visibility, remix auth, paid unlocks, license snapshots, lineage, publish | `zaolang-domain-licensing-lineage` |
| Credits reserve/settle, royalties, payments, redemption, reconciliation | `zaolang-credits-billing` |
| Job state machine, SSE, Celery/Beat, retries, workflow graphs, video analysis | `zaolang-generation-jobs` |
| Agents, LLM client, provider routing/quirks, prompt polish, `/gateway/status` | `zaolang-agent-gateway` |
| Uploads, signed downloads, pHash, provenance, storage, assets-pack | `zaolang-media-assets` |
| Search, tags, feeds, similar works, style presets/gallery | `zaolang-discovery-search` |
| Skill library, characters, scenes, `/skills` plaza, @-mention apply | `zaolang-creation-library` |
| Learning posts, notifications/push devices, profiles, collections, follows, reports | `zaolang-community` |
| Audit, SystemLog, data export/deletion, consent, retention, backups | `zaolang-compliance-audit` |
| Consumer routes, shared components, studios, API client, login wall, Cmd+K | `zaolang-frontend-ui` |
| Colour tokens, dark/light, motion, breakpoints | `zaolang-theming` |
| UI copy (zh-CN/en/ja), locale/region, formatting | `zaolang-i18n-region` |
| Lineage-graph DAG UI, version diff | `zaolang-lineage-graph` |
| Infinite canvas, `/graph-ops`, change feed, canvas Agent | `zaolang-canvas` |
| Short drama: series/episodes, timeline editor, exports, MCP, 文案创作, shortform | `zaolang-editor-drama` |
| 白膜 3D blockout studio, motion-guide reference video | `zaolang-blocking-studio` |
| Admin shell, admin login, RBAC, nav | `zaolang-admin-console` |
| Admin domain endpoints/pages, moderation queue, keyword gates | `zaolang-admin-ops` |
| Admin statistics timeseries | `zaolang-admin-statistics` |
| iOS client | `zaolang-ios-client` |
| `make check` gate, pre-commit, lint/format config, Docker images, dependency pins, versions, docs site | `zaolang-ci-release` |
| Single-host prod deploy | `zaolang-remote-deploy` |
| Tests, e2e + `make e2e-fixtures`, a11y, visual QA, skill-freshness guard | `zaolang-testing-qa` |

Cross-module change order: `zaolang-data-model` → domain skill → `zaolang-api-contract` → frontend/iOS skill.

## Global Rules

1. The implementation is ground truth — resolve ambiguity from code, `docs/` and tests, not invention.
2. Money is always integer (credits, minor units, micro-USD); a float in an amount path is a bug.
3. IDs carry a type prefix (`usr_`, `wrk_`, `job_`, `ast_`…) from `back/app/models/base.py:new_id` via each model's `id_column(prefix)`; never hand-write an ID.

## Verify

```bash
make check   # lint + typecheck + messages + openapi-check + test-back + test-front (no vitest/e2e)
```
Per-module commands live in each skill's Verify section.
