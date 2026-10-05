---
name: zaolang-theming
description: Design tokens, dark/light/system theme, and motion — globals.css tokens, flicker-free SSR theme, contrast, reduced motion (CSS + lib/motion), JS breakpoints. Use when changing colours, tokens, theme switching, animations, or breakpoint-dependent JS.
---

# Theming, Tokens & Motion

**Scope**: semantic colour tokens (dark = locked baseline), the three-state theme, reduced motion, JS breakpoints.
Not here → `zaolang-frontend-ui` (components), `zaolang-i18n-region` (locale fade).

## Key Paths

| Path | What |
|---|---|
| `front/src/app/globals.css` | dark + light token sets, `@theme inline`, `--breakpoint-*`, reduced-motion rules |
| `front/src/lib/theme.ts` | `themePreferences`, `THEME_COOKIE` (`zl_theme`), `MOTION_COOKIE` (`zl_reduce_motion`), `themeColor`, `themeInitScript`, `resolveTheme` |
| `front/src/components/theme/theme-provider.tsx` | `useTheme`: preference, `resolved`, `reduceMotion`; writes cookies, applies to `<html>`, View Transition crossfade |
| `front/src/components/theme/theme-init-script.tsx` | injects `themeInitScript` via `useServerInsertedHTML` |
| `front/src/app/[locale]/layout.tsx` | SSR `data-theme` / `data-theme-preference` / `data-reduced-motion` from cookies (`system` → dark) |
| `front/src/components/layout/theme-menu.tsx` | switcher; in top-bar preference menu and editor header |
| `front/src/lib/theme-sync.ts` | `syncThemePreference` → `PATCH /v1/auth/me/preferences`; wired as `onPersist` in `front/src/components/app-providers.tsx` |
| `front/src/lib/motion.ts` | `loadAnime` (lazy animejs), `useReducedMotion`, `useIsomorphicLayoutEffect` |
| `front/src/lib/use-reveal.ts` | `useRevealOnView` — one-shot fade-up on first view |
| `front/src/lib/use-overlay-transition.ts` | returns `render`: mounts a commit after `open`, unmounts after the exit animation |
| `front/src/lib/use-media-query.ts` | `useMediaQuery`, `useMinWidth`, `BREAKPOINTS` (mirrors `--breakpoint-*`: xs 480, sm 760, md 1024, lg 1180, xl 1440 — not Tailwind defaults) |

## Invariants

1. Components use semantic classes (`bg-surface`, `text-muted`), never a literal `#…` / `rgb(`.
2. Dark values are locked. A new colour = new token in dark, light, and `@theme inline`; missing one silently inherits.
3. Light must pass WCAG AA (4.5:1 body, 3:1 large); compute before changing light `--primary`. `--script-*` and `--relation-*` (card management graph, `front/src/components/asset-graph/relations.ts`) tokens aren't axe-scanned (gated / signed-in routes) — recompute by hand; rerun `ios/tools/gen-colors.py` after adding one.
4. SSR is flicker-free: `data-theme` from the cookie; `themeInitScript` resolves `system` before paint. Inject only via `useServerInsertedHTML` — a React `<script>` child errors in React 19; an effect flashes.
5. Switching also sets `color-scheme` and `<meta name="theme-color">` (`themeColor`), inside `document.startViewTransition` unless `shouldSkipViewTransition` (unsupported, reduced motion, hidden tab — it throws there); first mount applies with no transition. axe scans wait for running transitions (`front/e2e/support/axe.ts`) — a mid-fade scan reports false contrast failures.
6. Theme + reduce-motion persist in cookies — the only source SSR reads. `syncThemePreference` also PATCHes the account `theme`, authenticated (normal refresh-and-retry), only when `getAccessToken()` is set, and never on console routes (`ADMIN_PATH` anchored to the locale-less root, so `/profile/admin` still syncs). Web never applies `user.theme` back; the account copy is write-only here.
7. Reduced motion = OS query OR app toggle (`data-reduced-motion`). CSS collapses durations; JS goes through `useReducedMotion` + `loadAnime`, never a static animejs import. `qa-visual` fails any duration > 50 ms.
8. `useMediaQuery` is `false` on the server — behaviour only, layout stays in CSS. A `--breakpoint-*` change must update `BREAKPOINTS`.

## Recipes

1. **Add a token**: dark block + light block + `--color-*` in `@theme inline`; compute contrast in both themes.
2. **Add an animation**: `loadAnime()` inside an effect, bail when `useReducedMotion()`; for overlays use `useOverlayTransition`.
3. **Add a theme state**: don't — cookie, init script and API assume three.

## Verify

```bash
make test-a11y   # axe incl. color-contrast, both themes
make qa-visual   # both themes × 3 viewports + reduced motion
cd front && npx vitest run src/lib/theme-sync.test.ts
```

Manual: light → reload, no dark flash; `system` follows OS live.
