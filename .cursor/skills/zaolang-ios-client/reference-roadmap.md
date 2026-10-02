# iOS Client — roadmap reference

Section names below (D3/D4, M3, M4, contract gap 5, in-progress banner) are what Swift doc comments cite.

## Locked decisions (all shipped)
| Decision | Shipped |
|---|---|
| Session renewal | Client takes over the `zl_refresh` cookie (`CookieCodec` + Keychain); no native refresh channel on the backend |
| Credit purchasing | No StoreKit; `BillingView` is read-only and links to web `/billing` |
| APNs push | Client chain complete (`PushManager`, `POST/DELETE /v1/me/devices`); backend send is a stub (see open gaps) |

## Done
- **M0 Foundation** — networking, `Page<T>`, design tokens, media cache, trilingual copy.
- **M1 Read-only** — discover (hero, grid, infinite scroll, tags, sort, search), inspiration preview, work detail, lineage, profile, learn; guest-accessible.
- **M2 Account** — `AuthSheet`, `requireAuth`, like/bookmark/follow (optimistic), library (works/drafts/bookmarks/collections), settings, notifications, data export and deletion requests.
- **M3 Creation** — create hub, studio (D3/D4 below), direct uploads, quoting, draft + job submission, job detail (SSE + polling), publish (checkboxes unchecked, `public_view_only`), in-progress banner.
- **M4 Onboarding** — three screens, `iosOnboarding` namespace, seen-flag in `UserDefaults` (independent of login).
- **M5 Store readiness** — `PrivacyInfo.xcprivacy` (email, UGC, device ID), `aps-environment` entitlement, `UIBackgroundModes: remote-notification`. App Store assets, age rating and crash monitoring are manual work in App Store Connect.

## D3/D4 studio shape
One `StudioView`, two modes via `StudioMode`. New: operation + optional prefilled prompt, no source. Remix: `sourceWorkID` only; loads the work, prefills reusable params, requires the attribution checkbox, draft carries `sourceWorkID` for license + lineage at publish. Commit bar pinned with `.safeAreaInset(edge: .bottom)`.

## In-progress banner
`CreateJobBanner` shows the newest non-terminal tracked job; tap → `CreateRoute.jobDetail`; terminal jobs linger 8s (`TimelineView`), dismissible.

## Open
- **Before App Store submission**: switch `aps-environment` in `ios/App/Resources/Zaolang.entitlements` to `production`; set `DEVELOPMENT_TEAM` in `ios/project.yml`; replace the placeholder web domain / `applinks:` in `AppConfig` and the entitlements.
- **APNs send is a logging stub**: `send_push` in `back/app/domain/notifications/push.py` only logs; `_dispatch_push` fans out to every `Device.push_token` of the user. Needs a real HTTP/2 APNs client + certificate.
- **Contract gap 1 — refresh only via httpOnly cookie**: `POST /v1/auth/refresh` reads only the `zl_refresh` cookie; attribute changes silently break iOS renewal.
- **Logout doesn't revoke the refresh token**: `signOut()` posts `/v1/auth/logout` through `APIClient` without `Cookie: zl_refresh`, so the backend's `sid` revocation (`back/app/api/v1/auth.py:logout`) never fires; the Keychain token is only dropped locally. Fix: attach `CookieCodec.requestHeader` like `RefreshTransport`.
- **Contract gap 3 — lists without cursor**: generation jobs, notifications, drafts, bookmarks and profile works return a single page; iOS parses them as `Page<T>` so adding a cursor needs no client change.
- **Contract gap 5 — SSE fallback simplified**: SSE and 5s polling always run together instead of a "fall back after N reconnect failures" state machine. Equivalent for correctness; a "live connection unavailable" hint would need that state machine.
- **Not scheduled**: silent push, StoreKit (only if product reverses), more collection management, style presets, iPad/landscape, offline browsing, share extension, onboarding polish (rewrite chips, analytics), canvas/blocking/script surfaces.

## Acceptance checklist (every milestone)
- No `Double`/`Float` amounts; IDs only from responses; private work renders as not-found; generation submit/retry carry an `Idempotency-Key`; cancel only when cancellable, retry only when terminal.
- Every screen: loading/loaded/empty/failed + offline + logged-out; skeletons match content height; commit buttons stay above the bottom safe area.
- A11y as web (`make test-a11y`, `make qa-visual`): contrast 4.5:1 / 3:1, largest text without truncation, labelled icon buttons, ≤50ms transitions with reduced motion, 44×44pt targets.
- Performance: cold start to discover first frame < 1.5s; 60fps grid scroll; detail → playback < 1s.
- Copy keys aligned with `front/src/i18n/messages/`; after `make openapi`, recheck DTOs against `back/openapi.json`.
