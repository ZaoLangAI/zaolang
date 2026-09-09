---
name: zaolang-i18n-region
description: Trilingual copy and region settings — next-intl routing and the [locale] structure, zh-CN/en/ja message files with key-consistency checks, region as the sole determinant of locale (regionLocale mapping), currency/date formatting, admin copy in ja.json deliberately left in English (keys still required, no runtime fallback). Use when adding UI copy, changing translations, adding a locale or region, formatting currency or dates, or when `make messages` fails.
disable-model-invocation: true
---

# Trilingual Copy & Region

## Scope

Interface language (`locale`) is **determined solely** by the user's region (`region`) — there is no independent language switcher; changing region changes language (and currency) together.

## Key Paths

| File | Contents |
| --- | --- |
| `front/src/i18n/routing.ts` | `locales` (`zh-CN` / `en` / `ja`), `regions` (`CN` / `GLOBAL` / `JP`), `regionCurrency`, `regionLocale` (the sole region→locale mapping), `localePrefix: 'always'` |
| `front/src/i18n/request.ts`, `navigation.ts` | next-intl wiring and localized navigation |
| `front/src/i18n/messages/{zh-CN,en,ja}.json` | three message files — **their key sets must match exactly** |
| `front/scripts/check-messages.mjs`, `check-message-usage.mjs` | key-consistency + code-reference-existence checks (`make messages`). **`check-message-usage.mjs` resolves one namespace per binding *name* per file** — it collects `const t = useTranslations('x')` into a `Map` keyed by the variable, so a file declaring `t` twice for two namespaces keeps only the last, and every `t('…')` in that file is then checked against the wrong namespace. A false "missing message key" that names keys you can see in `messages/en.json` is this bug, not your copy; give the second binding a different name (`tMedia`) rather than editing the catalogues |
| `front/scripts/fragments/`, `merge-messages.mjs` | per-module copy fragments and their merge step. A fragment supplies one module's keys for all three locales; `merge-messages.mjs` falls back to the fragment's `en` value when a locale is missing, which is how admin copy ends up as English text under the `ja` key — a **build-time** copy, not a runtime fallback (invariant #7). `canvas.json` is the newest fragment and the only new top-level namespace |
| `front/src/lib/format.ts` | currency, date, and quantity formatting — plus `parseInstant` (a naive API datetime is UTC, not local), `isLocalDateTime` / `localDateTimeToIso` (a `datetime-local` admin filter's wall-clock value ↔ an offset ISO string, stamped with `DISPLAY_TIME_ZONE` — `lib/admin/use-admin-list.ts`'s `zonedFilterQuery` is the caller), `formatRelative` and `formatBytes` |
| `back/app/models/enums.py` | backend `Locale` / `Region` enums, mirroring the frontend one-to-one |

## Invariants

1. **The three message files' key sets must be identical.** A missing key is not "falls back to Chinese" — it's a runtime error. `make messages` is what catches this, and it also checks that every key referenced in code actually exists.
2. **No hardcoded interface copy.** Chinese literals should appear only in `messages/zh-CN.json`, test selectors, and comments.
3. **`localePrefix: 'always'`**: the URL prefix is the single source of `<html lang>`. Shared links and crawlers must see an unambiguous language. Don't add a "default locale has no prefix" optimization.
4. **Changing region must change locale with it**: the sole mapping is `regionLocale` (`front/src/i18n/routing.ts`). Anywhere region is written (`RegionMenu`, the settings-page region option) must also `router.replace(pathname, { locale: regionLocale[region] })` and write `locale` together with region into `/v1/auth/me/preferences` — never update region without locale. There is no standalone language control (`LocaleMenu` has been removed).
5. **Currency follows region, not locale**: `regionCurrency` is the sole mapping (CN→CNY, GLOBAL→USD, JP→JPY). Price display always goes through `lib/format.ts` — never concatenate `¥` in a component.
6. **Dates and quantities use `Intl`** with an explicit locale argument; relying on the runtime's default locale makes SSR and client renders diverge (hydration errors). Display timezone is `DISPLAY_TIME_ZONE` (`Asia/Shanghai`, defined in `routing.ts` alongside the `localeTimeZone` map that points all three locales at it) for every locale — language only changes copy, not the clock. **iOS mirrors this**, in `ios/App/Sources/Common/Date+ZL.swift`'s `ZLClock` (see `zaolang-ios-client` invariant #16); the two must move together or the same job reads two different times on two devices. `formatDate` / `formatDateTime` must parse naive API datetimes as UTC (`parseInstant`), never `new Date('2026-09-02T05:35:00')` which the browser treats as local.
7. **Admin copy in `ja.json` is often English text under the `ja` key — there is no runtime ja→en fallback.** `front/src/i18n/request.ts` always loads exactly `messages/${locale}.json` (no `getMessageFallback`, no merged bundle), so an admin key missing from `ja.json` is the same runtime error as any other missing key (invariant #1), not a graceful degrade. Leaving the admin console's *values* in English inside `ja.json` is a deliberate scope decision, not a gap — the keys must still exist in all three files and `make messages` still enforces parity on them.
8. **Amounts arrive from the backend as integer minor units**; convert to display form only at format time, never divide early.

## Extension Points

- **Add copy**: edit the relevant module fragment under `front/scripts/fragments/` (or edit all three `messages/*.json` directly) → `make messages` must pass → consume it via `useTranslations('namespace')`. Job-progress thinking uses `jobPage.thinkingLabel` / `jobPage.thinkingLive` (also generated into iOS via `gen-strings.py`); prompt polish / editor / admin debug-chat / sandbox use the matching `thinkingLive` key in their own namespace. A remix-rail label such as `remixPage.sourceVideo` (源视频 / Source video / 元の動画) must exist in all three files before the rail can show it.
- **Add a locale**: add the value to `routing.ts`'s `locales` → create a complete message file (**never a partial translation**) → add the value to the backend `Locale` enum → check every `Intl` call and date-library language pack.
- **Add a region**: add to `regions` + `regionCurrency` + `regionLocale` (must point at an existing locale) + the backend `Region` enum — all four together; pricing logic reads region, so confirm tier prices are defined for the new region.
- **E2E selectors depend on Chinese copy**: changing visible `zh-CN` text breaks Playwright specs — this is **intentional**, copy is part of the contract. Update `front/e2e/` alongside any copy change.

## Verify

```bash
make messages
make test-front
```

Manual path: switch region to `JP` → pricing shows JPY, and `<html lang="ja">`, navigation, and page copy switch to Japanese together (`regionLocale.JP`).
