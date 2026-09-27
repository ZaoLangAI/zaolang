---
name: zaolang-admin-console
description: Back-office security boundary and shell — separate admin login/session, four-tier RBAC, confirm+reason for dangerous actions, admin rate limits, audit-on-write, sidebar nav. Use when adding an admin endpoint or page, changing admin roles, NAV_GROUPS, admin auth deps or the (admin) layout.
---

# Admin Console Shell & Security

**Scope**: admin session (own cookie/audience/login), RBAC on both sides, dangerous-action gates, rate tiers, console shell and primitives.
Not here → `zaolang-admin-ops` (domains, route map), `zaolang-api-contract` (consumer auth), `zaolang-compliance-audit` (`AuditLog`), `zaolang-i18n-region` (admin copy).

## Key Paths

| Path | What |
|---|---|
| `back/app/api/deps.py` | `get_admin_user` (admin audience, `zl_admin_session` cookie or bearer), `require_admin_role` (rank from `ADMIN_ROLE_RANK` in `back/app/models/enums.py`) |
| `back/app/api/v1/admin/deps.py` | `Viewer`/`Reviewer`/`Operator`/`Admin`, `AdminRead`/`AdminWrite`/`AdminDangerous`, `require_confirmation` |
| `back/app/api/v1/admin/auth.py` | `/v1/admin/auth/login`, `/me`, `/logout`; sets httpOnly cookie |
| `back/app/api/rate_limit.py` | `admin_read` 300/60s, `admin_write` 60/60s, `admin_dangerous` 10/300s (per admin) |
| `back/app/api/schemas/admin.py` | `DangerousAction` base (`confirm` + non-empty `reason`) |
| `front/src/app/[locale]/(admin)/admin/login/page.tsx` | standalone login (never the consumer dialog) |
| `front/src/app/[locale]/(admin)/admin/(console)/layout.tsx` | shell: resolves `/auth/me` once, else redirects to admin login |
| `front/src/lib/admin/rbac.ts` | `NAV_GROUPS`, `visibleGroups(role)`, `atLeast`, `highestRole` |
| `front/src/components/admin/` | top level: shared primitives (`data-table`, `filter-bar`, `detail-drawer`, `danger-confirm`, `json-diff`, `timeline`, sidebar, session provider); subdirs: one per domain page |
| `front/src/lib/api/admin-server.ts` | RSC `adminFetch`/`adminFetchOrNull`/`hasAdminSession`; client twin `admin-client.ts`; list hook `front/src/lib/admin/use-admin-list.ts` |

## Invariants

1. Sessions never cross: consumer token on `/v1/admin/*` → 401 and vice versa (audience + cookie differ).
2. RBAC is server-side; `NAV_GROUPS` only hides links. Ladder `viewer < reviewer < operator < admin`; `requires` must match the route's alias.
3. Read/write tiers differ (config: read `Viewer`, write `Admin`) — no save button for lower roles is correct.
4. Dangerous action = `AdminDangerous` + payload extending `DangerousAction` + `require_confirmation(payload.confirm)` first; UI uses `danger-confirm.tsx`.
5. Every admin write calls `audit.record(...)` explicitly — no decorator (see zaolang-compliance-audit › audit).
6. Admin login: unknown email, wrong password and no-console-role all return the same error (`auth.py`).
7. An admin can't strip their own admin role; a suspended admin loses access on the next request (tests in `test_admin_security.py`).
8. Lists show resolved names (`user_display_name`, `provider_label`, …) with raw IDs only as tooltip; the schema adds the name field beside the ID.
9. `/admin/reports` is only a redirect to `/admin/moderation?tab=reports`, not a nav page.

## Recipes

**Add an admin endpoint**
1. Pick role alias + rate tier from `back/app/api/v1/admin/deps.py`.
2. Dangerous: schema extends `DangerousAction`; call `require_confirmation` first.
3. `audit.record(...)` before commit.
4. Add lower-role-rejected + audited cases to `back/tests/integration/test_admin_security.py`.

**Add an admin page**
1. `(console)/<name>/page.tsx`; table via `use-admin-list.ts` + `data-table.tsx`; components in a domain subdir.
2. `NAV_GROUPS` entry with explicit `requires` (+ icon union).
3. Copy in all locales (`make messages`).
4. Case in `front/e2e/flows/admin.spec.ts`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_security.py -v
make messages
make test-e2e   # front/e2e/flows/admin.spec.ts
```
