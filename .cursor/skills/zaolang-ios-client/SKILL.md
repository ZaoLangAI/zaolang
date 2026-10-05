---
name: zaolang-ios-client
description: Native iOS client under ios/ — SwiftUI, XcodeGen project.yml, ZaolangKit (networking, zl_refresh session, DTOs, SSE), four-tab shell, generated colours/strings. Use when adding or changing an iOS screen, ZaolangKit endpoint, route, colour token or localized string.
---

# ZaoLang iOS Client

**Scope**: `ios/` — native client on the same backend contract (`back/openapi.json`) as `front/`. Guest-readable discover/work/lineage/profile/learn plus login and write flows (studio, jobs, publish, library, settings, notifications, billing, push, onboarding). No admin surface. Canvas, blocking, script and drama-editor are web-only; iOS has no stance on them yet. Credits are bought on web (no StoreKit).
Not here → `zaolang-api-contract` (errors, idempotency), `zaolang-generation-jobs` (SSE), `zaolang-i18n-region` (copy), `zaolang-theming` (tokens), `zaolang-community` (push backend).

## Key Paths

| Path | What |
|---|---|
| `ios/project.yml` | XcodeGen source of truth (`.xcodeproj` is not committed). `SWIFT_VERSION` 5.10, `SWIFT_STRICT_CONCURRENCY: minimal`, iOS 17, iPhone only |
| `ios/Packages/ZaolangKit/Package.swift` | Single library target, `.iOS(.v17)` + `.macOS(.v13)` so `swift build` works without Xcode; no test target, no third-party deps |
| `ios/Packages/ZaolangKit/Sources/ZaolangKit/Networking/` | `APIClient` + feature-split `APIClient+*.swift`, `ApiError`, `IdempotencyKeyStore` |
| `ios/Packages/ZaolangKit/Sources/ZaolangKit/Models/` | DTOs; enums wrapped in `RawOrUnknown<T>` so unknown backend values don't crash |
| `ios/Packages/ZaolangKit/Sources/ZaolangKit/Session/` | `SessionManager`, `CookieCodec`, `AuthTransport`, `RefreshTransport`, `KeychainStore`, `URLSessionFactory` |
| `ios/Packages/ZaolangKit/Sources/ZaolangKit/Streaming/` | `EventStreamClient.swift` (actor, 1/2/5/10/30s reconnect via `SSEReconnectPolicy`), `JobEventStream.swift` (`jobEvents(jobID:)`), `SSEFrameParser` |
| `ios/Packages/ZaolangKit/Sources/ZaolangKit/Media/` | `UploadTransport` (direct PUT to presigned URL); `AssetCache` (UI images skip it, loading signed URLs via `App/Sources/Media/`) |
| `ios/App/Sources/Shell/` | `RootView`, `RootTabView` (custom 4-tab bar over `AppTab`, one `NavigationStack` each), `AppRouter`, `Routes`, `DeepLink`, `DebugSessionView` |
| `ios/App/Sources/Support/` | `AppEnvironment` (`requireAuth`, `trackJob`, push token), `AppConfig`, `L10n`, `PushManager`, `GenerationOperation`, `ReachabilityMonitor` (global offline banner) |
| `ios/App/Sources/Common/` | `LoadableState`, `StateViews`, `SharedComponents`, `Date+ZL.swift` (`ZLClock`) |
| `ios/App/Sources/DesignSystem/` | `Color.zl.*`, radius/shadow, `zlMotion`, `.zlEyebrow()`, `.zlSkeletonPulse()` |
| `ios/App/Sources/Create/` | Create hub, `StudioView`/`StudioViewModel`, job detail, publish, draft detail, `CreateJobBanner`, `AssetLibrary/LibraryPickerSheet.swift` |
| `ios/App/Sources/CharacterLibrary/` | 角色库 (create hub card → `CreateRoute.characterLibrary` / `.characterDetail`): list, detail with 造型 \| 音色 tabs over `GET /v1/characters/{id}/graph`; `CharacterGraphModel` = phone outline of the web DAG (depth-indented looks, version folding mirrors `front/src/components/asset-graph/versions.ts`) |
| `ios/App/Resources/` | `Assets.xcassets`, `Localizable.xcstrings`, `Info.plist`, `PrivacyInfo.xcprivacy`, `Zaolang.entitlements` (`aps-environment` = development) |
| `ios/tools/gen-colors.py` | Generates `Assets.xcassets/Colors` from `front/src/app/globals.css` (light + dark blocks) |
| `ios/tools/gen-strings.py` | Generates `Localizable.xcstrings` from the JSON files in `front/src/i18n/messages/`; `NAMESPACES` = exported set |

Other feature dirs under `ios/App/Sources/` pair `*View` + `*ViewModel`. Learn uses `MarkdownUI`, the App target's only third-party dependency.

## Invariants

1. Generated files are never hand-edited: `Assets.xcassets/Colors` and `Localizable.xcstrings` — change the front source and rerun the script.
2. Never invent an i18n key. Copy must already exist in all three front message files; if its namespace is missing, add it to `NAMESPACES` in `ios/tools/gen-strings.py` and rerun. `iosOnboarding` lives in front's messages but only iOS consumes it.
3. `ApiError.notFound` merges 404 and `WORK_PRIVATE` — never reveal a private work with "no permission" copy.
4. `zl_refresh` is taken over manually: `URLSessionFactory` sets `httpShouldSetCookies = false`, `CookieCodec` parses `Set-Cookie` into Keychain, `SessionManager.inFlightRefresh` single-flights 401s. Changing the cookie (`back/app/api/deps.py:REFRESH_COOKIE_NAME`) or its attributes silently breaks renewal.
5. Reduced motion: read `@Environment(\.zlMotion)` (system OR server `reduce_motion`, merged in `RootView`), never `accessibilityReduceMotion` directly. Gate every new animation/transition on it.
6. `ref` (inspiration) ≠ `source_work_id` (remix → lineage edge + license). Both go through one `StudioView`/`StudioViewModel` distinguished by `StudioMode` — never split. See `reference-write-flows.md`.
7. Parse every list as `Page<T>` even when the backend only takes `limit` (of the lists iOS calls, only `/v1/works`, `/v1/credits/ledger`, `/v1/learn/posts` take `cursor`). Exception: `/v1/characters` and `/v1/scenes` return bare arrays — decode `[T]` (`APIClient+AssetLibrary.swift`; the 角色库 list passes `summary: true`, so its rows have no `looks` and lead with `heroUrl`); `/v1/characters/{id}/graph` is one object (`AssetGraphResponse`, `Models/AssetGraph.swift`).
8. Lineage graph requests depth 3 (`LineageViewModel.depth`), not the API default 4 — phone width. Deliberate.
9. Amounts are `Int`; enum raw values follow `back/app/models/enums.py`; mirror backend enum additions (`Operation`, `ImageAssetKind`, `CharacterViewAngle` in `Models/Enums.swift`) in the same change. Known drift: `Operation` lacks `music_generation`/`video_analysis` (response DTOs decode them as unknown via `RawOrUnknown`).
10. XcodeGen 2.46.0's top-level `resources:` emits no resources phase. Put new resource files in the target's `sources:` with `buildPhase: resources`, as `project.yml` does.
11. `GENERATE_INFOPLIST_FILE: NO` → `App/Resources/Info.plist` must keep `CFBundleIdentifier`/`Executable`/`PackageType`/`Name`/`InfoDictionaryVersion` by hand, or install fails.
12. `Operation` collides with `Foundation.Operation`, and `ZaolangKit.Operation` hits the namespace enum `ZaolangKit.ZaolangKit`. Files importing Foundation use the `GenerationOperation` alias (`Support/GenerationOperation.swift`).
13. Login wall = `AppEnvironment.requireAuth(actionLabel:action:)` + `AuthSheet`: runs now if signed in, once after login, discarded on cancel. `actionLabel` is an existing i18n key. Removed: `LoginWallSheet` — don't restore.
14. Every displayed timestamp goes through `ZLClock` (pinned to `Asia/Shanghai`, mirrors web `DISPLAY_TIME_ZONE`), never `Date.formatted` with the system zone.
15. A View with a non-wrapped `private let/var` gets a `private` memberwise init — hand-write `init` if another file constructs it.
16. `ios/README.md` is stale (M0/M1 scope); code and this skill win.

## Recipes

**Add an endpoint**: method in `Networking/APIClient+<Feature>.swift` → DTO in `Models/` → `swift build` → call from a ViewModel.

**Add a write screen**: new `App/Sources/<Feature>/` with `*View` + `*ViewModel` → wrap the entry in `environment.requireAuth` → add a Route case in `Shell/Routes.swift` → wire it in the matching `*Destination` builder in `RootTabView`. Cover loading/loaded/empty/failed via `LoadableState`; offline banner is global; logged-out is `requireAuth`, not a data state. Empty state = one sentence + one way out.

**Add a string / colour**: confirm the key exists in all three locale files under `front/src/i18n/messages/` (or both theme blocks in `globals.css`) → rerun `gen-strings.py` / `gen-colors.py` → use `L10n.t("ns.key", ["var": v])` / `Color.zl.*`. No raw literals.

**Add a discover sort**: `WorksSort` (`Models/Work.swift`) + `sortLabel` in `DiscoverView` + `discover.sort*` keys. Wall defaults to `recent`, Hero is `popular`.

## Verify

```bash
cd ios/Packages/ZaolangKit && swift build       # networking/session/DTO changes
cd ios && xcodegen generate                      # after target/dependency/resource changes
xcodebuild -project ios/Zaolang.xcodeproj -scheme Zaolang \
  -destination 'platform=iOS Simulator,name=iPhone 17' build
```

Manual runs need `make up && make migrate && make seed && make dev-api` (port 3001 = `AppConfig.apiBaseURL`). A11y bar = web's: no truncation at largest text, labelled icon buttons, 44×44pt targets.

## References

- `reference-write-flows.md` — read when touching auth, studio/remix, job detail, publish, character view completion, push, or billing.
- `reference-roadmap.md` — read before scoping new iOS work: shipped milestones, locked decisions, open contract gaps.
