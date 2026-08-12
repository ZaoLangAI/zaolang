---
name: zaolang-project
description: Work safely in the ZaoLang (造浪) repository by routing changes to the current FastAPI, Next.js, Agent/LLM gateway, admin console, infrastructure, or native iOS implementation and its domain invariants. Use for code analysis, feature work, bug fixes, refactors, tests, migrations, API changes, UI changes, agent/provider routing, generation jobs, credits, licensing/lineage, media, admin operations, deployment, or iOS work anywhere in this repository. Do not use as a substitute for inspecting the current code and tests.
---

# ZaoLang project development

Treat the checked-out implementation and tests as the source of truth. Use the existing
`.cursor/skills/` documents as detailed project references, not as unquestioned facts.

## Start every task

1. Run `git status --short` and preserve unrelated user changes.
2. Identify the affected layers and read their current code, tests, and relevant reference below.
3. Trace the dependency direction before editing: model/migration -> domain -> API -> generated contract -> client.
4. State any assumption that changes product behavior; otherwise follow the existing implementation.
5. Make the smallest coherent change and verify it with the narrowest relevant checks before broader gates.

If a reference conflicts with code, follow code and tests, then update the affected reference in the same
change when that documentation is in scope. Never report a documented behavior as implemented without
locating its current code or test.

## Route by modification intent

Read `.cursor/skills/zaolang-overview/SKILL.md` for unfamiliar or cross-cutting work, then load only the
references needed for the task:

| Intent | Read |
| --- | --- |
| Local setup, containers, ports, Make targets | `.cursor/skills/zaolang-local-env/SKILL.md` |
| SQLAlchemy models, enums, indexes, Alembic | `.cursor/skills/zaolang-data-model/SKILL.md` |
| REST endpoints, auth, errors, rate limits, idempotency, OpenAPI | `.cursor/skills/zaolang-api-contract/SKILL.md` |
| Runtime configuration and feature flags | `.cursor/skills/zaolang-platform-config/SKILL.md` |
| Visibility, licensing, publishing, lineage, tombstones | `.cursor/skills/zaolang-domain-licensing-lineage/SKILL.md` |
| Credits, pricing, settlement, royalties, payments | `.cursor/skills/zaolang-credits-billing/SKILL.md` |
| Generation state machine, SSE, Celery, async provider polling | `.cursor/skills/zaolang-generation-jobs/SKILL.md` |
| Agents, prompts, model bindings, provider selection, LLM normalization | `.cursor/skills/zaolang-agent-gateway/SKILL.md` |
| Uploads, MinIO, fingerprints, provenance, asset import | `.cursor/skills/zaolang-media-assets/SKILL.md` |
| Discovery, search, tags, embeddings, style presets | `.cursor/skills/zaolang-discovery-search/SKILL.md` |
| Audit, privacy, retention, backup and restore | `.cursor/skills/zaolang-compliance-audit/SKILL.md` |
| Consumer Next.js routes and shared UI | `.cursor/skills/zaolang-frontend-ui/SKILL.md` |
| Theme tokens, SSR theme hydration, motion | `.cursor/skills/zaolang-theming/SKILL.md` |
| Locale, region, translations and formatting | `.cursor/skills/zaolang-i18n-region/SKILL.md` |
| Web lineage graph and version diff | `.cursor/skills/zaolang-lineage-graph/SKILL.md` |
| Admin security boundary, RBAC and component shell | `.cursor/skills/zaolang-admin-console/SKILL.md` |
| Admin operational domains and pages | `.cursor/skills/zaolang-admin-ops/SKILL.md` |
| Native SwiftUI client and ZaolangKit | `.cursor/skills/zaolang-ios-client/SKILL.md`; read its `roadmap.md` only for scope/history decisions |
| CI, images, release automation and docs | `.cursor/skills/zaolang-ci-release/SKILL.md` |
| Pytest, concurrency, Playwright, a11y and visual QA | `.cursor/skills/zaolang-testing-qa/SKILL.md` |

For cross-module work, load references in dependency order rather than reading all of them.

## Preserve global invariants

- Keep PostgreSQL as the fact source; agent output becomes fact only after domain validation and persistence.
- Keep credits and currency minor units as integers. Preserve reserve -> capture/release semantics.
- Create typed IDs through `back/app/models/base.py:new_id`; do not invent untyped IDs.
- Preserve lineage when content or users are removed; hidden and tombstoned states are not hard deletion.
- Keep consumer and admin sessions, token audiences, cookies, RBAC, rate limits, and API clients isolated.
- Keep hard provider eligibility filters in code and final media-provider selection in the intent-router LLM.
  Do not restore a weighted fallback formula when LLM selection is unavailable.
- Route agent access to business behavior through the controlled domain/tool boundary; do not expose arbitrary
  sessions or SQL to an agent.
- Keep secrets in environment-backed configuration and out of logs, prompts, responses, fixtures, and docs.
- Update `back/openapi.json` and `front/src/lib/api/schema.d.ts` together after contract changes.
- Modify Web theme/i18n sources before regenerating their iOS derivatives; do not hand-edit generated resources.

## Verify proportionally

Use commands from the relevant module reference. Typical order:

1. Run targeted unit or integration tests for the changed invariant.
2. Run the affected typecheck/build/message/OpenAPI check.
3. Run `make check` for broad cross-layer changes when the local environment supports it.
4. For iOS, run `swift build` for ZaolangKit and use Xcode/Xcodebuild for SwiftUI app changes.
5. Report checks not run, environment blockers, and any behavior verified only by static inspection.

When changing project skills or architecture, run:

```bash
python3 .agents/skills/zaolang-project/scripts/audit_skill_docs.py
python3 /Users/mac001/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/zaolang-project
```

Fix genuine errors or explicitly document why a dynamic/example path is intentionally skipped.
