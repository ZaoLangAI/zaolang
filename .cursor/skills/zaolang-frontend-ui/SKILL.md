---
name: zaolang-frontend-ui
description: Consumer Next.js shell — (site)/(studio) routes, component families, generation studios (image/video/audio/music), API client + token refresh, login wall, Cmd+K, notification center, overflow/a11y rules. Use when adding a consumer route, shared component, studio control, or front/src/lib helper.
---

# Consumer Frontend

**Scope**: consumer routes under `front/src/app/[locale]/(site)/` and `(studio)/`, shared components in `front/src/components/`, and `front/src/lib/` client plumbing. Stack (`front/package.json`): Next 16.3 App Router + RSC, React 19.2, Tailwind 4, next-intl 4, zustand 5 (editor store only), animejs 4 (lazy), @mdxeditor/editor + react-markdown (learn posts), @xyflow/react, three, mediabunny. Dark theme is the visual baseline.
Not here → `zaolang-theming` (tokens, motion), `zaolang-i18n-region` (copy, locale), `zaolang-editor-drama` (文案创作 script, clip studio, cut editor, `/create/short`), `zaolang-canvas`, `zaolang-blocking-studio` (白膜), `zaolang-generation-jobs` (job SSE, thinking frames, video analysis), `zaolang-data-model` (draft `latest_job_id`/`applied_job_id`), `zaolang-creation-library` (skill plaza, character/scene libraries), `zaolang-community` (learn, profile, notifications, collections), `zaolang-discovery-search` (discover wall), `zaolang-admin-console` (`(admin)`), `zaolang-platform-config` (flags).

## Key Paths

| Path | What |
|---|---|
| `front/src/app/[locale]/(site)/` | top-bar routes (discover, work, create/*, remix, jobs, publish, skills, collection, profile, billing, notifications, learn) |
| `front/src/app/[locale]/(site)/layout.tsx` | `SessionProvider` › `NotificationCenterProvider` › TopBar, `LoginDialogHost`, `CommandPaletteHost`, toast stack |
| `front/src/app/[locale]/(studio)/` | chrome-less full-screen group; `studio-auth-gate.tsx` sends anonymous users to `/`. Hosts cut editor + canvas |
| `front/src/app/[locale]/(site)/create/new/page.tsx` | studio entry: `?mode=`, `?draftId=`/`?jobId=` resume, jump-out params → `CreateStudio` keyed by `studioSessionKey` |
| `front/src/components/studio/` | generation studios + shared shell, prompt composer, version history — `reference-studios.md` |
| `front/src/components/job/` | `/jobs/[jobId]` page, `job-stages.ts` stage table, `job-stage-state.ts` / `job-outputs.ts` readers |
| `front/src/components/ui/` | in-house primitives (field, dialog, sheet, dropdown-menu, toast, lightbox, back links…) — no UI library; focus regression test `dialog.test.tsx` |
| `front/src/components/layout/` | top bar and its menus (create, search, region, theme), motion prefetch, locale-fade watcher |
| `front/src/components/auth/` | `session-provider` (`useSession`, `requireAuth`), lazy `login-dialog-host` |
| `front/src/components/notifications/` | single-stream notification center, bell, toast stack, `notification-format.ts` |
| `front/src/components/command/` | Cmd+K `command-palette.tsx` (idle-loaded by `command-palette-host.tsx`) |
| `front/src/components/create/` | `/create`: `create-mode-cards.tsx`, flag-aware `create-tool-cards.tsx`, recent drafts/series |
| `front/src/components/asset-graph/` | card management graph (`/create/{characters,scenes,props}/[id]`): `asset-graph-workspace.tsx` (state, docked inspector, narrow-screen outline + Sheet) loads `asset-graph-canvas.tsx` (React Flow + dagre `layout.ts`) via `next/dynamic`; `graph-model.ts` is the pure payload → nodes/edges mapping; listed in `heavyDependencyBoundaries` |
| `front/src/features/` | big surfaces: `script`, `editor`, `drama-dashboard` (editor-drama), `canvas`, `blocking`, `video-analysis` (generation-jobs) |
| `front/src/lib/api/client.ts` | browser fetch: in-memory token, coalesced refresh, `Idempotency-Key`, `ApiError` |
| `front/src/lib/api/server.ts` | RSC `serverFetch` via `API_INTERNAL_URL`; uncached unless `revalidate` is passed; `serverFetchOrNull` |
| `front/src/lib/api/work-loaders.ts` | `getWork` — React `cache()` so `generateMetadata` and page share one fetch |
| `front/src/lib/api/schema.d.ts` | generated OpenAPI types (`npm run gen:api`); aliases in `front/src/lib/api/types.ts` |
| `front/src/lib/use-resource.ts` | GET hook over `resource-cache.ts`: dedupes in-flight calls, paints last response, always refetches |
| `front/src/lib/sse-post.ts` | `streamPost` — POST-initiated SSE reader |
| `front/src/lib/use-generation-submit.ts` | shared submit: login wall, draft reuse, idempotency, `onSubmitted` |
| `front/src/lib/` | other helpers (caret, mentions, devices, uploads…) — purpose + owner in `reference-components.md` |

## Invariants

1. Access token lives only in memory (`client.ts` `accessToken`); the durable half is the httpOnly refresh cookie. Auth-dependent UI must tolerate the "no token yet, refreshing" moment after reload.
2. Refresh is coalesced by `refreshInFlight` in `client.ts`; no retry loops in components. Errors are always `ApiError` (`front/src/lib/api/errors.ts`) — never parse response bodies in a component.
3. `send()` omits `content-type` for a `FormData` body so the browser sets the multipart boundary; setting it by hand breaks uploads such as `POST /v1/scripts/extract`.
4. Protected actions call `useSession().requireAuth({ label, run })`: `run` executes after login, is discarded on cancel. Never mount `LoginDialog` directly — `LoginDialogHost` lazy-loads it on first `loginPrompt.open`.
5. Credit-moving POSTs pass `idempotencyKey`, one key per logical attempt held in a ref (`pendingIdempotencyKey` in `use-generation-submit.ts`, `publish-form.tsx`), reused on retry, reset after success or `IDEMPOTENCY_CONFLICT`.
6. Mint ids with `randomUuid` (`front/src/lib/random-id.ts`; idempotency keys via its wrapper `newIdempotencyKey` in `front/src/lib/api/client.ts`) and hashes with `sha256Hex` (`front/src/lib/sha256.ts`) — never `crypto.randomUUID` / `crypto.subtle` directly. Why: production is a plain-HTTP origin where both are undefined.
7. No UI component library; semantic tokens only, never a literal colour (zaolang-theming); merge classes with `front/src/lib/cn.ts`. Every interactive element covers default / hover / focus-visible / disabled / loading / error (+ selected).
8. No horizontal overflow at 1440×1024, 1024×768, 390×844 — `expectNoHorizontalOverflow` (`front/e2e/support/axe.ts`), run by `front/e2e/visual.spec.ts` and `front/e2e/a11y.spec.ts`.
9. All copy goes through next-intl; no hardcoded Chinese (zaolang-i18n-region).
10. Command palette is a combobox, not a dialog: `role="search"` › `role="combobox"` input › `role="listbox"` / `option`; axe-checked in `front/e2e/a11y.spec.ts`. Flag-gated entries are filtered on `user.features`.
11. RSC pages degrade: `serverFetchOrNull` turns not-found / auth / unavailable into `null` → empty state, never a site-wide 500.
12. `PAGES` (visual) and `PUBLIC_PAGES` (a11y) list anonymous-reachable pages only. Never add a flag-gated route: `/create/script` and its `clip` / `blocking` children, `/create/tools/canvas`, `/canvas/{id}`, `/create/tools/video-analysis`, `/studio-editor/{cutId}`. Nor the signed-in card libraries and workspaces (`/create/{characters,scenes,props}` and `…/[id]`; anonymous they only render `SignInPrompt`) — `front/e2e/flows/asset-workspace.spec.ts` covers them as the seeded author.
13. Flag-gated cards declare `flag?: keyof Me['features']` (`create-mode-cards.tsx`, `create-tool-cards.tsx`) and fail open while the session loads (`user?.features[flag] ?? true`); the backend enforces the real gate.
14. POST-initiated SSE (`streamPost`: `thinking` / `delta` / `complete` / `error`) has no `Last-Event-ID` / reconnect; a failed response is parsed into `ApiError`. Don't reuse `use-job-stream.ts` for it. GET job-stream semantics: zaolang-generation-jobs.
15. `NotificationCenterProvider` is the only opener of `use-notification-stream.ts`. Creation toasts are keyed by `target_id` and limited to `CREATION_TARGET_TYPES` (`notification-format.ts`), which must match the backend upsert targets. They are deliberately independent of `components/ui/toast.tsx`.
16. Image/video creation never navigates to `/jobs/[jobId]`: studios pass `onSubmitted` to `useGenerationSubmit` and render inline; audio/music still push `/jobs/{id}`. `jobs/[jobId]/page.tsx` and `targetHref` redirect an image/video job with a `draft_id` to `imageCreationStudioHref` / `videoCreationStudioHref`.
17. `/create/new` keys `CreateStudio` with `studioSessionKey` (`front/src/lib/studio-session.ts`) because a query-only navigation doesn't remount it. Never `router.replace` a `draftId` onto the URL after submit — it changes the key and tears down the live job. `returnTo` only via `sanitizeReturnTo`.
18. Stage dots derive only from `jobStageState` (`job-stage-state.ts`); a new event type goes into `STAGE_FOR_EVENT` in `job-stages.ts`, never a consumer. Single/multi outputs go through `jobOutputs`.
19. Heavy code is lazy: studios (`create-studio.tsx` `dynamic`), login dialog, palette, animejs (`loadAnime`), MDX editor. `prefetch-studio.ts` import paths must equal `create-studio.tsx`'s. `check:bundle-size` enforces `front/scripts/bundle-budget.json`; `heavyDependencyBoundaries` in `front/eslint.config.mjs` restrict heavy imports (caveat: the per-package entries all set `no-restricted-imports`, so the last one — animejs — overrides the rest; only it is enforced today).
20. Downloads use `downloadAsset` (`front/src/lib/download-asset.ts`): mint an attachment signed URL via `GET /v1/assets/{id}?download=true`, open in a new tab — never `<a download>` (ignored cross-origin) or a blob fetch.
21. Non-editor code imports only `front/src/features/editor/from-job.ts`, never the `features/editor` barrel (pulls WASM) — see zaolang-editor-drama.
22. Server reads whose payload carries presigned media URLs (works, covers, posts, skills) must stay out of Next's data cache: `serverFetch` is `no-store` unless the caller passes `revalidate`, allowed only for signed-URL-free payloads (today just discover's `/v1/tags`). Stale-while-revalidate serves expired signatures → `/_next/image` 403. Pinned by `front/src/lib/api/server.test.ts`.
23. `eslint-config-next` 16 ships react-hooks v7 (`set-state-in-effect`, `refs`), run by `make lint`. Derived/seeded/reset state is set during render (`wasOpen` pattern in `link-episode-dialog.tsx`, latch in `login-dialog-host.tsx`), not with a synchronous `setState` in an effect; latest-callback refs are assigned in `useIsomorphicLayoutEffect` (`front/src/lib/motion.ts`), never during render; async effects drop late responses via a `cancelled` flag.
24. `Dialog` / `Sheet` focus the panel only once it is mounted (`open && render` — `useOverlayTransition` mounts a commit after `open`), capture the opener in a layout effect on `open`, and keep an `autoFocus` field's focus. `Sheet` ignores keys bubbling from portalled children (a nested dialog owns its Escape). Never add `.focus()` workarounds in specs.

## Recipes

1. **Add a page**: dir under `(site)/` (RSC, fetch via `lib/api/server.ts`) → `'use client'` islands → copy in all three catalogues (`make messages`) → palette entry in `command-palette.tsx` → add to `PAGES` / `PUBLIC_PAGES` only if anonymous-reachable. Full-screen, top-bar-less surfaces go under `(studio)/`.
2. **Add a gated create tool**: backend flag (zaolang-platform-config) → `Me.features` key → card in `create-tool-cards.tsx` with `flag` → API 404s / page hides when off; keep it out of `PAGES` / `PUBLIC_PAGES`.
3. **Add a shared primitive**: `components/ui/`, `cn()`, full state set, keyboard reachable, overlays via `useOverlayTransition` (`front/src/lib/use-overlay-transition.ts`) — anything touching the panel ref keys on its `render`, not `open`.
4. **Add a form**: `components/ui/field.tsx`; map a 422's field paths to inline errors, not a banner.
5. **Add a toast-worthy notification type**: rendering in `notification-format.ts` first; add to `CREATION_TARGET_TYPES` only if the backend upserts one row per target (zaolang-community).

## Verify

```bash
make lint                # eslint (react-hooks v7, heavy-import boundaries) + prettier --check, both stacks
make test-front          # tsc --noEmit + next build + check:bundle-size
cd front && npm test     # vitest (jsdom): lib/*.test.ts, dialog.test.tsx, server.test.ts
make messages            # catalogue parity + referenced keys exist
make test-e2e            # needs backend + seed running
make test-a11y && make qa-visual
```

## References

- `reference-studios.md` — read when touching `/create/new`, remix, any generation studio, inline results, version history, or `/jobs/[jobId]`.
- `reference-components.md` — read when locating a component family or `front/src/lib/` helper and its owning skill.
