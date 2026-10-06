# iOS Client — roadmap reference

Section names below (D3/D4, M3, M4, contract gap 5, in-progress banner) are what Swift doc comments cite.

## Locked decisions (all shipped)
| Decision | Shipped |
|---|---|
| Session renewal | Client takes over the `zl_refresh` cookie (`CookieCodec` + Keychain); no native refresh channel on the backend |
| Credit purchasing | No StoreKit; `BillingView` is read-only and links to web `/billing` |
| Image editing | Web-only. Since AC-8 images are generated only inside a character / scene / prop card; iOS has no general image studio |
| Asset libraries (角色 / 场景 / 道具创作) | Read-mostly mirror of the web card workspace (AC-10). Writes on iOS: approve a candidate image (any slot), a quick generate of the primary slot only — 定妆照 / scene master / prop hero (quote → confirm → idempotent draftless submit → 3s poll); for a character also set the default voice, generate a voice preview, edit name/descriptions (with AI draft from linked scripts). New cards, new looks / variants, camera poses (orbit), expressions, in-scene, panoramas, adjust/derive, relations, voice settings and cloning stay web-only — every other slot and the detail footer link to `/create/{kind}/{id}?look=` (「在网页端继续」) |
| APNs push | Client chain complete (`PushManager`, `POST/DELETE /v1/me/devices`); backend send is a stub (see open gaps) |

## Done
- **M0 Foundation** — networking, `Page<T>`, design tokens, media cache, trilingual copy.
- **M1 Read-only** — discover (hero, grid, infinite scroll, tags, sort, search), inspiration preview, work detail, lineage, profile, learn; guest-accessible.
- **M2 Account** — `AuthSheet`, `requireAuth`, like/bookmark/follow (optimistic), library (works/drafts/bookmarks/collections), settings, notifications, data export and deletion requests.
- **M3 Creation** — create hub, studio (D3/D4 below), direct uploads, quoting, draft + job submission, job detail (SSE + polling), publish (checkboxes unchecked, `public_view_only`), in-progress banner.
- **M4 Onboarding** — three screens, `iosOnboarding` namespace, seen-flag in `UserDefaults` (independent of login).
- **Character library** — list + detail (造型 outline with relation chips and folded versions, 音色 list with playback), the writes listed under locked decisions.
- **AC-10 asset creation** — hub cards 角色 / 场景 / 道具创作 replace 图片创作 and the 角色库 card; `AssetLibrary/` lists the three kinds with a completeness badge; the 创作 tab is a read-only slot board (completeness over required slots, a turnaround ring from the entries' `camera` poses, per-slot status incl. pending jobs) mirroring `front/src/features/asset-workspace/kind-config.ts` + `completeness.ts`; the studio lost general / cover images and the character picker / 补全侧面背面; image-job notifications open the card (`AssetJobLink`).
- **M5 Store readiness** — `PrivacyInfo.xcprivacy` (email, UGC, device ID), `aps-environment` entitlement, `UIBackgroundModes: remote-notification`. App Store assets, age rating and crash monitoring are manual work in App Store Connect.

## D3/D4 studio shape
One `StudioView`, two modes via `StudioMode`. New: text-to-video / image-to-video + optional prefilled prompt, no source. Remix: `sourceWorkID` only; loads the work, prefills reusable params, requires the attribution checkbox, draft carries `sourceWorkID` for license + lineage at publish. Commit bar pinned with `.safeAreaInset(edge: .bottom)`.

## In-progress banner
`CreateJobBanner` shows the newest non-terminal tracked job; tap → `CreateRoute.jobDetail`; terminal jobs linger 8s (`TimelineView`), dismissible.

## Open
- **Before App Store submission**: switch `aps-environment` in `ios/App/Resources/Zaolang.entitlements` to `production`; set `DEVELOPMENT_TEAM` in `ios/project.yml`; replace the placeholder web domain / `applinks:` in `AppConfig` and the entitlements.
- **APNs send is a logging stub**: `send_push` in `back/app/domain/notifications/push.py` only logs; `_dispatch_push` fans out to every `Device.push_token` of the user. Needs a real HTTP/2 APNs client + certificate.
- **Contract gap 1 — refresh only via httpOnly cookie**: `POST /v1/auth/refresh` reads only the `zl_refresh` cookie; attribute changes silently break iOS renewal.
- **Logout doesn't revoke the refresh token**: `signOut()` posts `/v1/auth/logout` through `APIClient` without `Cookie: zl_refresh`, so the backend's `sid` revocation (`back/app/api/v1/auth.py:logout`) never fires; the Keychain token is only dropped locally. Fix: attach `CookieCodec.requestHeader` like `RefreshTransport`.
- **Contract gap 3 — lists without cursor**: generation jobs, notifications, drafts, bookmarks and profile works return a single page; iOS parses them as `Page<T>` so adding a cursor needs no client change.
- **Contract gap 5 — SSE fallback simplified**: SSE and 5s polling always run together instead of a "fall back after N reconnect failures" state machine. Equivalent for correctness; a "live connection unavailable" hint would need that state machine.
- **Pre-existing copy drift**: the hub and studio still call `createPage.modeTextToVideo*` / `modeImageToVideo*` / `modeRemix*` and `createPage.subtitle`, which the web catalogues no longer have (they render as raw keys); `learnPage.blockRemove` likewise.
- **Not scheduled**: silent push, StoreKit (only if product reverses), more collection management, style presets, iPad/landscape, offline browsing, share extension, onboarding polish (rewrite chips, analytics), canvas/blocking/script surfaces.

## Acceptance checklist (every milestone)
- No `Double`/`Float` amounts; IDs only from responses; private work renders as not-found; generation submit/retry carry an `Idempotency-Key`; cancel only when cancellable, retry only when terminal.
- Every screen: loading/loaded/empty/failed + offline + logged-out; skeletons match content height; commit buttons stay above the bottom safe area.
- A11y as web (`make test-a11y`, `make qa-visual`): contrast 4.5:1 / 3:1, largest text without truncation, labelled icon buttons, ≤50ms transitions with reduced motion, 44×44pt targets.
- Performance: cold start to discover first frame < 1.5s; 60fps grid scroll; detail → playback < 1s.
- Copy keys aligned with `front/src/i18n/messages/`; after `make openapi`, recheck DTOs against `back/openapi.json`.
