---
name: zaolang-i18n-region
description: Trilingual copy (zh-CN/en/ja) and region — next-intl [locale] routing, message catalogues + fragments, region→locale/currency mapping, locale fade, display timezone, money/date formatting. Use when adding UI copy, a locale or region, or when make messages fails.
---

# Trilingual Copy & Region

**Scope**: `locale` is derived from `region` only — no language switcher; changing region changes language and currency.
Not here → `zaolang-ios-client` (iOS strings), `zaolang-theming`.

## Key Paths

| Path | What |
|---|---|
| `front/src/i18n/routing.ts` | `locales`, `regions`, `regionLocale`, `regionCurrency`, `DISPLAY_TIME_ZONE`, `localePrefix: 'always'`, `zl_locale` cookie |
| `front/src/i18n/navigation.ts` | locale-aware `Link` / `useRouter` / `usePathname` / `redirect` |
| `front/src/proxy.ts` | next-intl middleware (Next 16 `proxy` convention) resolving the locale prefix |
| `front/src/i18n/request.ts` | loads exactly `messages/${locale}.json` — no runtime fallback |
| `front/src/i18n/messages/zh-CN.json` | runtime catalogue (+ `en.json`, `ja.json`); top-level key = namespace |
| `front/scripts/merge-messages.mjs` | merges a per-locale fragment into all three; missing locale → `en` |
| `front/scripts/fragments/` | per-feature fragments (authoring aid, not read at build; must not contain deleted keys) |
| `front/scripts/check-messages.mjs` | parity of the three catalogues (zh-CN is the reference) |
| `front/scripts/check-message-usage.mjs` | every literal `t('key')` exists in zh-CN, resolved against the nearest preceding `useTranslations` / `getTranslations` binding of that name |
| `front/src/lib/format.ts` | `formatMoney`, `formatDate`, `parseInstant`, `formatRelative`, `formatBytes` |
| `front/src/lib/locale-transition.ts` | `beginLocaleTransition` → `html[data-navigating]` fade, 4 s fallback |

## Invariants

1. Key sets of the three catalogues must match; a missing key renders the raw path. `make messages` enforces parity + usage.
2. No hardcoded copy.
3. `localePrefix: 'always'` — URL alone decides `<html lang>`.
4. Region writers (`region-menu.tsx`, `settings-shell.tsx`) PATCH `region` + `locale: regionLocale[region]` together (signed in only), call `beginLocaleTransition()`, then `router.replace(pathname, { locale })` from `@/i18n/navigation` — which also persists the `zl_locale` cookie, so a signed-out pick sticks. Use that module's `Link`/`useRouter`/`usePathname`, not `next/navigation`'s.
5. Currency follows region (`regionCurrency`), not locale; prices go through `formatMoney` with integer minor units.
6. `Intl` gets an explicit locale; display tz is `DISPLAY_TIME_ZONE` for all locales. Naive API datetimes are UTC (`parseInstant`). iOS `ZLClock` in `ios/App/Sources/Common/Date+ZL.swift` must match.
7. Admin values in `ja.json` may be English — keys still required.
8. `check-message-usage.mjs` only sees literal single-quoted namespaces/keys: template keys (``t(`region.${value}`)``) are unchecked, and nothing detects unused keys. Several components in one file may each bind `t` to a different namespace (e.g. `devicePreview` + `media` in `device-preview.tsx`); two namespaces in one scope still need distinct names (`tTheme`).
9. `ios/tools/gen-strings.py` builds iOS strings from `NAMESPACES` in these catalogues — renaming keys there affects iOS.

## Recipes

1. **Add copy / namespace**: edit all three catalogues, or `cd front && node scripts/merge-messages.mjs <fragment>` → `make messages`.
2. **Add a locale/region**: `routing.ts` (`locales`, or `regions` + `regionCurrency` + `regionLocale`) + `Locale`/`Region` in `back/app/models/enums.py` + a complete catalogue.
3. **Remove keys**: grep for template-key uses first, delete from all three catalogues and from any `front/scripts/fragments/` file (`merge-messages.mjs` only adds — re-running a stale fragment resurrects them), check iOS `NAMESPACES`.
4. Changing zh-CN visible text can break `front/e2e/` selectors — update them together.

## Verify

```bash
make messages
make test-front
```
