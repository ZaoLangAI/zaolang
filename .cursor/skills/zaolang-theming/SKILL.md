---
name: zaolang-theming
description: Two-layer design tokens and the dark/light/system three-state theme — flicker-free SSR, cookie and user-preference persistence, color-scheme/theme-color sync, light-theme contrast requirements, reduced-motion. Use when changing colours, design tokens, dark/light theme behaviour, the theme switcher, SSR theme hydration, or fixing contrast and reduced-motion issues.
disable-model-invocation: true
---

# Theming & Design Tokens

## Scope

Dark is the design-acceptance baseline — its values are locked in `front/src/app/globals.css` under `[data-theme='dark']` and must not drift. Light is a second set of values for the same semantic tokens. Components consume semantic tokens only.

## Key Paths

| File | Contents |
| --- | --- |
| `front/src/app/globals.css` | both token sets + `@theme inline` mapping into Tailwind |
| `front/src/lib/theme.ts` | `themePreferences`, `THEME_COOKIE` (`zl_theme`), `MOTION_COOKIE`, `themeColor`, `themeInitScript` |
| `front/src/components/theme/theme-init-script.tsx` | injects `themeInitScript` into `<head>` via `useServerInsertedHTML` (not a React child) |
| `front/src/components/theme/theme-provider.tsx` | client-side three-state switching and persistence |
| `front/src/app/[locale]/layout.tsx` | renders `data-theme` onto `<html>` at SSR time and mounts `ThemeInitScript` |
| `front/src/components/layout/theme-menu.tsx` | **the** theme switcher: `themePreferences` → three `DropdownMenuRadioItem`s (`IconMonitor` / `IconMoon` / `IconSun`). It has two mount points, not one — `layout/preference-menu.tsx` (now just `<RegionMenu /> + <ThemeMenu />` in the site top bar) and `features/editor/studio/editor-header.tsx`, since the chrome-less `(studio)` group has no top bar. A change here shows up in both |
| `front/src/components/layout/preference-menu.tsx` | the top-bar composition of `RegionMenu` + `ThemeMenu` — no logic of its own |
| `front/src/components/settings/settings-shell.tsx` | full three-state control + accessibility settings at `/profile/settings` |

## Two-Layer Tokens

```css
:root, [data-theme='dark'] { --bg:#080b0d; --surface:#101418; --primary:#ff795b; }
[data-theme='light']       { --bg:#f7f4f0; --surface:#ffffff; --primary:#a8321a; }
@theme inline { --color-bg: var(--bg); --color-surface: var(--surface); }
```

## Invariants

1. **Components never hardcode a colour** — only semantic classes like `bg-surface` / `text-muted`. A literal `#` or `rgb(` inside a component is where drift starts.
2. **Dark values are locked**: existing tokens under `[data-theme='dark']` must not be casually changed. Need a new colour? Check existing semantic tokens first; add one rather than repurposing an existing value.
3. **Light must pass WCAG AA item by item.** `--primary` in light is `#a8321a`, not dark's coral, because the coral fails contrast against both white text and light backgrounds — **compute contrast before changing the light primary** (body/controls 4.5:1, large text 3:1).
4. **SSR is flicker-free**: the preference is stored in a cookie and the server renders `data-theme` directly onto `<html>`; `system` can't be resolved server-side, so an inline `<head>` script corrects it synchronously before first paint. Inject that script with `useServerInsertedHTML` (`theme-init-script.tsx`) — never as a React `<script>` child (React 19 errors on the client) and never from a React lifecycle (that will flash).
5. **Switching syncs side effects**: `color-scheme` (form controls, scrollbars) and `<meta name="theme-color">` (mobile notch/status-bar area).
6. **Anonymous users get a cookie; logged-in users get it merged into `PATCH /v1/auth/me/preferences`**, alongside `locale` / `region` — the same endpoint `settings-shell.tsx` and `layout/region-menu.tsx` write to. The theme write is `front/src/components/app-providers.tsx`'s `persistTheme` (`ThemeProvider`'s `onPersist`), sent with `anonymous: true` and a swallowed failure, and **skipped entirely when the pathname matches `ADMIN_PATH`** — a console route must not touch the consumer preferences API, because that 401 would redeem `/v1/auth/refresh`. Server-side preference wins on mismatch.
7. **Media needs independent tokens**: cinematic material skews dark, so poster overlays, gradient scrims, and card shadows need distinct light-mode values — reusing the dark ones muddies into a blur.
8. **`prefers-reduced-motion` must actually take effect**: every animation duration collapses to near-zero. The visual QA suite walks the DOM asserting no transition exceeds 50ms.

## Extension Points

- **Add a semantic token**: add it to both sets in `globals.css` + add the `@theme inline` mapping. **Adding it to only one set is the most common bug** — light silently falls back to an inherited value. Recent example: `--script-scene` / `--script-action` / `--script-camera` / `--script-dialogue` / `--script-breakpoint` (script writing's colour-coded block legend, `front/src/features/script/script-block.tsx`) — added as five new hues rather than reusing `amber`/`success`/`danger`, since those already carry a warning/positive/error meaning that doesn't apply to "this line is a camera direction." `--script-breakpoint` is the fifth and the only neutral one (a warm grey, `#9a958c` dark / `#726b60` light) — a 切分 chip is a structural marker between shootable segments, not content, so it must read quieter than the four content hues; it lives in the same three places as its siblings (`globals.css`'s dark block, light block, and the `--color-script-breakpoint` `@theme inline` mapping). Contrast was computed directly (WCAG formula) rather than assumed from the analogy to `--success`/`--danger`'s lightness band: for the four content hues, label text at full opacity clears 6.2:1+ against its own theme's `--surface` in both themes, and body text over each colour's 10%-opacity tint clears 11.9:1+ — both far past the 4.5:1 floor; the neutral `--script-breakpoint` sits lower by design (≈6.2:1 dark, ≈5.3:1 light against `--surface`), still above 4.5:1 for the 11px chip label `script-block.tsx` renders in it. `make test-a11y`'s axe scan doesn't reach `/create/script` (see `zaolang-frontend-ui` invariant #14), so this manual check is the only coverage those five tokens get — recompute it if their hex values ever change.
- **Add a theme state**: don't. The three states (`system` / `dark` / `light`) are a product decision; a fourth would touch the cookie, the SSR script, the preferences endpoint, and admin all at once.
- **Adjust dark contrast**: run `make test-a11y` first — it scans both themes and reports the exact offending node for any contrast violation.

## Verify

```bash
make test-a11y     # axe scan across both themes, incl. color-contrast
make qa-visual      # dual-theme × three-viewport screenshots + reduced-motion assertions
```

Manual path: switch to light → reload → the page **must not flash dark first** → switch to "follow system" → change the OS appearance → the page should follow live → the mobile notch area's colour should track the theme.
