# zaolang-frontend-ui — component & lib reference

Where things live under `front/src/`. `ls` the dir for current files; this lists purpose and owner only.

## Component families (`front/src/components/`)

| Dir | Purpose (owner skill if not this one) |
|---|---|
| `front/src/components/ui/` | primitives: button, field (`TextInput`/`Select`/`Switch`), dialog + sheet (focus trap, portal, opener restore), dropdown-menu, toast, spinner, icons |
| `front/src/components/ui/primitives.tsx` | `Card`, `Badge`, `PageHeading`, `Skeleton`, `EmptyState`, `ErrorNotice`, `StatTile` |
| `front/src/components/ui/confirm-dialog.tsx` | consumer destructive confirm (no reason field; admin uses `DangerConfirm`) |
| `front/src/components/ui/go-back-link.tsx` | `router.back()` with `fallbackHref`; `back-link.tsx` = fixed href; `media-lightbox.tsx` = still preview on `Dialog` |
| `front/src/components/layout/` | `top-bar` + create-menu, search-box, preference-menu (region + theme menus), brand |
| `front/src/components/layout/motion-prefetch.tsx` | idle animejs warm-up; `navigation-fade-watcher.tsx` clears the locale fade (zaolang-i18n-region) |
| `front/src/components/auth/` | `session-provider` (`useSession`: user, `requireAuth`, `openLogin`), `login-dialog-host` (lazy), `login-dialog`, `sign-in-prompt` |
| `front/src/components/command/` | Cmd+K `command-palette` + idle-loaded `command-palette-host` |
| `front/src/components/notifications/` | center provider (single SSE), bell, toast stack, list, `notification-format.ts`. Backend: zaolang-community |
| `front/src/components/create/` | `/create` page: mode cards, tool cards, recent drafts rail (`recent-draft-card.tsx`), recent series, credits tile, shortform hero banner |
| `front/src/components/studio/` | generation studios — see `reference-studios.md` |
| `front/src/components/job/` | `/jobs/[jobId]` page, stage table + readers, awaiting-input panel (`input-request-retry.ts`), promote dialog |
| `front/src/components/media/` | device preview/frame (specs in `front/src/lib/devices.ts`), video-player, posters, output-gallery, download button |
| `front/src/components/media/safe-media-playback.ts` | signed-URL re-sign margin, abort-safe play, duration fallback |
| `front/src/components/work/` | work detail: stage, info panel, rail, card, lineage strip, reusable params, report/appeal/delete dialogs |
| `front/src/components/discover/` | discover wall + hero (zaolang-discovery-search) |
| `front/src/components/collection/` | `/collection` tabs (`library-tabs.tsx`, draft resume hrefs) + collection dialogs (zaolang-community) |
| `front/src/components/profile/` | profile header, activity feed (zaolang-community) |
| `front/src/components/learn/` | learn posts: `learn-body-view` (react-markdown), lazy `markdown-body-editor` (@mdxeditor/editor), publish form (zaolang-community) |
| `front/src/components/settings/` | `/profile/settings`: `settings-shell` (theme, reduce motion, region), `platform-connect` (抖音/快手 accounts) |
| `front/src/components/skills/` | plaza grid/card/detail, create/manage skill dialogs, `skill-mention-menu` (zaolang-creation-library) |
| `front/src/components/characters/` | `/create/characters` library (zaolang-creation-library) |
| `front/src/components/scenes/` | `/create/scenes` library (zaolang-creation-library) |
| `front/src/components/props/` | `/create/props` library + `/create/props/[id]` workspace (zaolang-creation-library) |
| `front/src/components/library/` | `existing-asset-picker-dialog` (shared asset picker) |
| `front/src/components/marketplace/` | access-price field, unlock dialog, remix unlock gate (zaolang-credits-billing) |
| `front/src/components/billing/` | credit packages, ledger, redeem code, spend limit (zaolang-credits-billing) |
| `front/src/components/lineage/` | lineage dialog/explorer/graph (zaolang-lineage-graph) |
| `front/src/components/publish/` | `publish-form`: 202 review flow — stays on page and flips to pending; one idempotency key per attempt |
| `front/src/components/ai/` | `thinking-disclosure` (`aria-live="polite"`) — semantics in zaolang-generation-jobs |
| `front/src/components/theme/` | theme provider + SSR init script (zaolang-theming) |
| `front/src/components/charts/` | recharts wrappers used by admin statistics + drama-dashboard analytics (zaolang-admin-statistics) |
| `front/src/components/admin/` | admin console (zaolang-admin-console) |

## lib helpers (`front/src/lib/`)

| Path | What |
|---|---|
| `front/src/lib/caret-position.ts` | `getCaretCoordinates` — textarea caret pixel position (mirror-div trick) for `@` menus |
| `front/src/lib/skill-mention.ts` | `@query` detection, token strip/match, menu placement constants |
| `front/src/lib/plaza-skills.ts` | `overlayUnlockedSkills` — derive plaza list from latest props + this visit's unlocks |
| `front/src/lib/creation-skill-status.ts` | status → badge tone + `skillLibrary.*` label key (plaza, character, scene libraries) |
| `front/src/lib/prompt-limits.ts` | `STUDIO_PROMPT_MAX_LENGTH` (4096) for studios, `?prompt=` seeding, script batch, blocking |
| `front/src/lib/prefetch-studio.ts` | hover-prefetch of a studio chunk; import paths must equal `create-studio.tsx` |
| `front/src/lib/resource-cache.ts` | `dedupedFetch` + last-response cache behind `use-resource.ts` (no TTL, always refetches) |
| `front/src/lib/devices.ts` | phone specs (`DEVICES`) for framed preview; display params, not measurements |
| `front/src/lib/api/work-loaders.ts` | `getWork` via React `cache()` — one fetch per RSC request |
| `front/src/lib/refresh-media-src.ts` | `refreshAssetUrl` / `refreshJobOutputUrl` / `refreshWorkMediaUrl` / `refreshDraftOutputUrl` — re-sign expired media URLs |
| `front/src/lib/random-id.ts` | `randomUuid` (works on HTTP origins) |
| `front/src/lib/sha256.ts` | `sha256Hex` with software fallback (HTTP origins) |
| `front/src/lib/upload.ts` | `uploadFile`: presign → PUT to storage → register; consent records (zaolang-media-assets) |
| `front/src/lib/search-history.ts` | local recent searches for the top-bar box |
| `front/src/lib/style-gallery.ts` | `styleGalleryLabel` (trilingual labels in one response) |
| `front/src/lib/format.ts` | money / date / count formatting (zaolang-i18n-region) |
| `front/src/lib/characters.ts` | character sheet helpers, `characterManageHref` |
| `front/src/lib/scenes.ts` | scene hero helpers, `sceneManageHref` |
| `front/src/lib/props.ts` | `propManageHref`, `propHeroAsset`, `defaultPropReferenceIds` |
| `front/src/lib/asset-job-href.ts` | where an image job / draft / notification resumes: `assetWorkspaceHref`, `assetJobHref`, `imageDraftHref`, `isRetiredImageJob` |
| `front/src/lib/video-draft.ts` | `isVideoCreationOperation`, `videoCreationStudioHref` |
| `front/src/lib/draft-title.ts` | `draftDisplayTitle` — title, else first prompt line, else untitled |
| `front/src/lib/studio-session.ts` | `studioSessionKey` |
| `front/src/lib/motion.ts` | `loadAnime`, `useReducedMotion`, `useIsomorphicLayoutEffect` (zaolang-theming) |
| `front/src/lib/theme-sync.ts` | `syncThemePreference` — theme → account (zaolang-theming) |
| `front/src/lib/locale-transition.ts` | region-switch fade (zaolang-i18n-region) |
| `front/src/lib/use-media-query.ts` | JS breakpoints (zaolang-theming) |
| `front/src/lib/use-job-stream.ts` | GET job SSE hook (zaolang-generation-jobs); `use-admin-job-stream.ts` = console variant |
| `front/src/lib/admin/` | admin list/fetch helpers (zaolang-admin-console) |
