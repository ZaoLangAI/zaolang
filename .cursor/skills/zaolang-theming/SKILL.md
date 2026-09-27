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
| `front/src/lib/theme.ts` | `themePreferences`, `THEME_COOKIE` (`zl_theme`), `MOTION_COOKIE`, `themeColor`, `themeInitScript` |
| `front/src/components/theme/theme-provider.tsx` | `useTheme`: preference, `reduceMotion`, cookies, side-effect sync |
| `front/src/components/theme/theme-init-script.tsx` | injects `themeInitScript` via `useServerInsertedHTML` |
| `front/src/app/[locale]/layout.tsx` | SSR `data-theme` / `data-reduced-motion` from cookies |
| `front/src/components/layout/theme-menu.tsx` | switcher; in top-bar preference menu and editor header |
| `front/src/components/app-providers.tsx` | `persistTheme` → `PATCH /v1/auth/me/preferences` |
| `front/src/lib/motion.ts` | `loadAnime` (lazy animejs), `useReducedMotion` |
| `front/src/lib/use-reveal.ts` | `useRevealOnView` — one-shot fade-up on first view |
| `front/src/lib/use-overlay-transition.ts` | keeps overlays mounted through their exit animation |
| `front/src/lib/use-media-query.ts` | `useMediaQuery`, `useMinWidth`, `BREAKPOINTS` (mirrors `--breakpoint-*`) |

## Invariants

1. Components use semantic classes (`bg-surface`, `text-muted`), never a literal `#…` / `rgb(`.
2. Dark values are locked. A new colour = new token in dark, light, and `@theme inline`; missing one silently inherits.
3. Light must pass WCAG AA (4.5:1 body, 3:1 large); compute before changing light `--primary`. `--script-*` tokens aren't axe-scanned (gated route) — recompute by hand.
4. SSR is flicker-free: `data-theme` from the cookie; `themeInitScript` resolves `system` before paint. Inject only via `useServerInsertedHTML` — a React `<script>` child errors in React 19; an effect flashes.
5. Switching also sets `color-scheme` and `<meta name="theme-color">` (`themeColor`).
6. Theme + reduce-motion persist in cookies. `persistTheme` also PATCHes preferences (`anonymous: true`) and skips `ADMIN_PATH` — console routes must not call the consumer preferences API.
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
```

Manual: light → reload, no dark flash; `system` follows OS live.
