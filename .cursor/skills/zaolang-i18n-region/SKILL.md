---
name: zaolang-i18n-region
description: Trilingual copy and region settings — next-intl routing and the [locale] structure, zh-CN/en/ja message files with key-consistency checks, region as the sole determinant of locale (regionLocale mapping), currency/date formatting, admin ja falling back to en. Use when adding UI copy, changing translations, adding a locale or region, formatting currency or dates, or when `make messages` fails.
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
| `front/scripts/check-messages.mjs`, `check-message-usage.mjs` | key-consistency + code-reference-existence checks (`make messages`) |
| `front/scripts/fragments/`, `merge-messages.mjs` | per-module copy fragments and their merge step |
| `front/src/lib/format.ts` | currency, date, and quantity formatting |
| `back/app/models/enums.py` | backend `Locale` / `Region` enums, mirroring the frontend one-to-one |

## Invariants

1. **The three message files' key sets must be identical.** A missing key is not "falls back to Chinese" — it's a runtime error. `make messages` is what catches this, and it also checks that every key referenced in code actually exists.
2. **No hardcoded interface copy.** Chinese literals should appear only in `messages/zh-CN.json`, test selectors, and comments.
3. **`localePrefix: 'always'`**: the URL prefix is the single source of `<html lang>`. Shared links and crawlers must see an unambiguous language. Don't add a "default locale has no prefix" optimization.
4. **Changing region must change locale with it**: the sole mapping is `regionLocale` (`front/src/i18n/routing.ts`). Anywhere region is written (`RegionMenu`, the settings-page region option) must also `router.replace(pathname, { locale: regionLocale[region] })` and write `locale` together with region into `/v1/auth/me/preferences` — never update region without locale. There is no standalone language control (`LocaleMenu` has been removed).
5. **Currency follows region, not locale**: `regionCurrency` is the sole mapping (CN→CNY, GLOBAL→USD, JP→JPY). Price display always goes through `lib/format.ts` — never concatenate `¥` in a component.
6. **Dates and quantities use `Intl`** with an explicit locale argument; relying on the runtime's default locale makes SSR and client renders diverge (hydration errors).
7. **Admin `ja` falls back to `en`** — this is a deliberate scope decision, not a gap.
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
