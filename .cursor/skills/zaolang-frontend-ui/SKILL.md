---
name: zaolang-frontend-ui
description: Consumer Next.js frontend — the current discover/work/create/character/short-video/job/publish/skills/learning/profile/billing route families, shared components and full-state requirements, the API client and token refresh, the login dialog with pendingAction recovery, the Cmd+K command palette, and no-horizontal-overflow responsive constraints. Use when adding or changing a consumer-facing route, shared UI component, the API client, the login dialog, the command palette, or responsive behaviour.
disable-model-invocation: true
---

# Consumer Frontend

## Scope

The current consumer routes under `front/src/app/[locale]/(site)/` and the component families they share. **Trust the actual `page.tsx` files, shared components, and visual e2e specs**, not a fixed page count from a doc — dark theme is the acceptance baseline.

## Key Paths

| Path | Contents |
| --- | --- |
| `front/src/app/[locale]/(site)/` | home (redirects to `discover`), `discover`, `work/[workId]`, `create` (incl. `new` / `short` / `characters` / `drama`), `remix/[workId]`, `jobs/[jobId]`, `publish/[draftId]`, `skills`, `collection`, `profile` (incl. `[handle]` / `settings`), `billing`, `notifications`, `learn` (incl. `[postId]` / `publish`); credit-unlock pricing for works/skills appears in the publish form, work detail, remix gate, and skill marketplace |
| `front/src/components/discover/` | the inspiration wall: `tag-filter` (`TagFilter` + `DiscoverSort`), `inspiration-masonry`, the hero carousel; sort/tags live in the URL — see `zaolang-discovery-search` |
| `front/src/components/ui/` | `button` / `dialog` / `field` / `primitives` / `spinner` / `toast` / `icons` |
| `front/src/components/layout/` | `top-bar` / `preference-menu` / `site-footer` (brand + build version, not a source-code link) / `brand` |
| `front/src/components/auth/` | `login-dialog` / `session-provider` / `sign-in-prompt` |
| `front/src/components/command/command-palette.tsx` | Cmd+K, an accessible combobox pattern |
| `front/src/lib/api/client.ts` | browser-side fetch: in-memory access token, automatic refresh, `Idempotency-Key` |
| `front/src/lib/api/server.ts` | RSC-side fetch via `API_INTERNAL_URL`; list pages (discover, profile, etc.) use `serverFetchOrNull`, degrading network failures and 5xxs to empty rather than a site-wide 500 |
| `front/src/lib/use-resource.ts`, `use-job-stream.ts` | data-fetching and SSE hooks |
| `front/src/lib/format.ts` | region-aware currency, date, and quantity formatting |

## Invariants

1. **The access token lives only in memory.** Storing it in `localStorage` turns any XSS into permanent account takeover; the durable half is the httpOnly refresh cookie. On reload, every component that depends on auth state must tolerate the intermediate "no token yet, silently refreshing" moment.
2. **Refresh requests are coalesced**: `client.ts`'s `refreshInFlight` guarantees concurrent 401s trigger only one refresh. Don't implement your own retry inside a component.
3. **Protected actions go through the login wall + action recovery**: intercept → open `login-dialog` → on success, resume via `pendingAction`; on cancel, the action is **discarded**, never silently executed.
4. **Any endpoint that moves credits requires an `idempotencyKey`** (submitting a generation, purchasing credits).
5. **Every interactive component implements the full state set**: `default / hover / focus-visible / disabled / loading / error` (+ `selected`). Missing `focus-visible` gets caught by the accessibility suite.
6. **No UI component library** — that's how theme-token drift starts. Components consume semantic tokens only (see `zaolang-theming`); **never a hardcoded colour**.
7. **No horizontal overflow at any of the three breakpoints**: 1440×1024 / 1024 / 390×844, asserted as `scrollWidth === clientWidth`. The visual QA suite checks this page by page.
8. **All copy goes through next-intl** — hardcoded Chinese strings are never allowed (see `zaolang-i18n-region`).
9. **The command palette is a combobox, not a dialog**: `role="search"` container + `role="combobox"` input + `role="listbox"`/`role="option"`. This ARIA structure is checked by axe — read `e2e/a11y.spec.ts` before touching the markup.
10. **Video creation parameters must stay provider-safe**: H3's user controls only ever submit 4–15 seconds, six aspect ratios, 2K, an optional seed, and mutually exclusive normal-reference/first-last-frame modes. Uploads only ever pass a platform `Asset.id` — never a webhook, external URL, or arbitrary provider JSON inside `extra`.
11. **`/create/drama` is a hard desktop Chrome/Edge gate.** Narrow screens get a notice only, never the timeline — don't reuse the studio's mobile bottom sheet here. This route is excluded from `a11y-mobile` scanning. A job page's "enter editing" link imports only `front/src/features/editor/from-job.ts` — never the `features/editor` barrel (that pulls WASM/mediabunny into the job page). `export-runner.ts` dynamically imports `mediabunny`. Details: `zaolang-editor-drama`.
12. **RSC list pages degrade gracefully when the API is unavailable — never a blank screen.** `serverFetchOrNull` / `adminFetchOrNull` collapse network failures and 5xxs into `null` (`ApiError.isUnavailable`). Discover, profile work lists, and admin statistics already follow this. The route-level fallback is `front/src/app/[locale]/error.tsx`.

## Extension Points

- **Add a page**: create a directory under `(site)/` (RSC renders server-side by default, fetching via `lib/api/server.ts`) → split interactive pieces into `'use client'` components → add trilingual copy to `src/i18n/messages/*.json` (all three files) → add it to the command palette's navigable items → add it to the visual and accessibility suites' page lists (`e2e/visual.spec.ts`, `e2e/a11y.spec.ts`).
- **Change discover filtering/sorting**: `TagFilter` / `DiscoverSort` write `q`/`tag`/`sort` via `Link`; the default `popular` is omitted from the query. The Hero is pinned to popular. Contract: `zaolang-discovery-search`.
- **Add a shared component**: place it in `components/ui/`, merge classes via `lib/cn.ts`, implement every state, keep it keyboard-reachable.
- **Modify the API client**: errors are always `ApiError` (carrying the backend error code) — never parse a response body inside a component.
- **Add a form**: use `components/ui/field.tsx`, mapping a backend 422's field paths to inline errors rather than a generic banner.

## Verify

```bash
make test-front              # tsc --noEmit + next build
make messages                # trilingual key consistency, plus every code-referenced key exists
make test-e2e                # needs the backend and seed data running first
make test-a11y && make qa-visual
```
