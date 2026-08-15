---
name: zaolang-admin-console
description: Admin security boundary and shell — the separate /v1/admin namespace and admin-audience token, four-tier RBAC, dangerous-action confirmation with mandatory reason, independent rate limits, the audit decorator, plus the (admin) route group's own layout, login page, RBAC nav, and data-dense component family. Use when adding a back-office endpoint or page, changing admin roles and permissions, the admin session, dangerous-action confirmation, or the console's tables/drawers/diff components.
disable-model-invocation: true
---

# Admin Security Boundary & Console Shell

## Scope

Admin code lives inside `front/` and `back/`, but **its session, namespace, rate limits, permissions, and shell are fully isolated from the consumer app.** A consumer token against admin must 401.

## Key Paths

### Backend

| File | Contents |
| --- | --- |
| `back/app/api/v1/admin/deps.py` | the four role aliases `Viewer` / `Reviewer` / `Operator` / `Admin`; the `AdminRead` / `AdminWrite` / `AdminDangerous` rate-limit tiers; `require_confirmation` |
| `back/app/api/v1/admin/auth.py` | `/admin/login`, session lookup, logout; issues a token with audience `admin`, stored in the `zl_admin_session` cookie |
| `back/app/api/v1/admin/*.py` | `config` / `content` / `data` / `jobs` / `ledger` / `logs` / `observability` / `statistics` / `users` / `llm_providers` / `agent_skills` / `skill_library` / `redemption` / `learning` |
| `back/app/domain/audit/service.py` | write-operation trail |
| `back/tests/integration/test_admin_security.py` | 37 unauthorized-access and dangerous-operation cases — read this before changing permissions |

### Frontend

| File | Contents |
| --- | --- |
| `front/src/app/[locale]/(admin)/admin/login/page.tsx` | a standalone login page (never reuses the consumer login dialog) |
| `front/src/app/[locale]/(admin)/admin/(console)/layout.tsx` | the console shell |
| `front/src/components/admin/admin-session-provider.tsx` | the admin session context |
| `front/src/components/admin/admin-sidebar.tsx` + `front/src/lib/admin/rbac.ts` | `NAV_GROUPS` / `visibleGroups(role)` / `atLeast` |
| `front/src/components/admin/` | `data-table` / `filter-bar` (incl. `daterange`) / `detail-drawer` / `danger-confirm` / `json-diff` / `timeline` / `stepper` / `duration-bars` / `agents/agent-skills-panel` / `agents/agent-profile-dialog` / `workflows/workflow-editor` (sandbox run history is a floating window over the canvas — see `zaolang-admin-ops`) / `models/llm-providers-panel` (model management: a flat primary/backup list + per-endpoint primary/backup) / `audit/log-center-console` / `statistics/*` (daily trends, see `zaolang-admin-statistics`) |
| `front/src/lib/api/admin-client.ts`, `admin-server.ts`, `use-admin-list.ts` | admin-only client and list hook |

## Invariants

1. **The two sessions are never interchangeable**: a consumer token against `/v1/admin/*` 401s, and an admin token against a consumer endpoint 401s. Cookie name, audience, and login page are all separate.
2. **RBAC is enforced server-side; frontend nav trimming is only a convenience.** `rbac.ts`'s `requires` must match the backend's role aliases, but **any hidden route hit directly is still rejected by the backend.** Tiers: `viewer < reviewer < operator < admin`, with a higher tier automatically satisfying a lower requirement.
3. **Read and write access are separated by tier**: e.g. reading config requires `viewer`, writing or rolling it back requires `admin`. "An operator can open the config page but has no save button" is correct behavior, not a bug.
4. **High-risk operations need two locks**: `require_confirmation(confirmed)` plus a schema-enforced `reason`. Missing either must 4xx, and the reason gets written to `AuditLog`. The frontend always uses `danger-confirm.tsx`.
5. **Every `/v1/admin/*` write is audited**, including failed high-risk attempts.
6. **Admin rate limits are metered per admin, independently**: `admin_read` 300/60s, `admin_write` 60/60s, `admin_dangerous` 10/300s.
7. **An admin can't remove their own admin role** (a lockout guard), enforced by a dedicated test.
8. **A suspended admin loses access immediately**, not waiting for their token to expire.
9. **Admin reuses the same design tokens and three-state theme as consumer**, but its component family is entirely different (tables, filters, cursor pagination, bulk actions, drawers, JSON diffs, timelines). Admin copy is `zh-CN` and `en`; `ja` falls back to `en`.
10. **Lists and detail views show human-readable names first, with raw IDs tucked into a tooltip** — never dump a bare `usr_.../job_.../ep_...` directly into the body copy. Convention: the backend schema keeps the raw ID field but adds a resolved name field alongside it (e.g. `user_display_name`/`provider_label`/`agent_display_name`); the frontend renders the name and uses the ID only as a `title` tooltip or secondary note — see the user/provider/AgentRuns columns in `jobs-console.tsx` for the pattern. Any new admin page listing users, providers, or agents must follow this, or operators are left guessing at raw IDs.

## Extension Points

**Add an admin endpoint**

1. Choose a role alias (`Viewer` / `Reviewer` / `Operator` / `Admin`) and a rate-limit alias (`AdminRead` / `AdminWrite` / `AdminDangerous`).
2. If it's dangerous: the schema carries `confirm: bool` and `reason: str`, and the function body starts with `require_confirmation`.
3. Attach the audit decorator to any write; `before`/`after` should hold only a summary.
4. Add "a lower-tier role gets rejected" and "the action is audited" cases to `test_admin_security.py`.

**Add an admin page**

1. Create a directory under `(console)/` → assemble it with `use-admin-list.ts` + `data-table.tsx`.
2. Add a nav item to `rbac.ts`'s `NAV_GROUPS` with an explicit `requires`.
3. Add trilingual copy (`ja` reuses the `en` value).
4. Add a "the page opens and shows real data" case to `front/e2e/flows/admin.spec.ts`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_security.py -v
make test-e2e     # e2e/flows/admin.spec.ts covers the login boundary, 10+ ops pages, and RBAC nav
```
