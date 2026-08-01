---
name: zaolang-theming
description: 造浪的双层设计令牌与深色/浅色/跟随系统三态主题：SSR 无闪烁、cookie 与用户偏好持久化、color-scheme 与 theme-color 同步、浅色主题对比度要求、reduced-motion。Use when changing colours, design tokens, dark/light theme behaviour, the theme switcher, SSR theme hydration, or fixing contrast and reduced-motion issues.
disable-model-invocation: true
---

# 主题与设计令牌

## 职责

深色是设计验收基准，**其色值锁定在 `front/src/app/globals.css` 的 `[data-theme='dark']`，不得漂移**；浅色是同名语义令牌的另一组取值。组件只消费语义令牌。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `front/src/app/globals.css` | 两套令牌 + `@theme inline` 映射到 Tailwind |
| `front/src/lib/theme.ts` | `themePreferences`、`THEME_COOKIE`（`zl_theme`）、`MOTION_COOKIE`、`themeColor`、`themeInitScript` |
| `front/src/components/theme/theme-provider.tsx` | 客户端三态切换与持久化 |
| `front/src/app/[locale]/layout.tsx` | SSR 时把 `data-theme` 渲进 `<html>`，并内联 `themeInitScript` |
| `front/src/components/layout/preference-menu.tsx` | 顶部栏快捷切换 |
| `front/src/components/settings/settings-shell.tsx` | `/profile/settings` 完整三态控件与无障碍设置 |

## 双层令牌

```css
:root, [data-theme='dark'] { --bg:#080b0d; --surface:#101418; --primary:#ff795b; }
[data-theme='light']       { --bg:#f7f4f0; --surface:#ffffff; --primary:#a8321a; }
@theme inline { --color-bg: var(--bg); --color-surface: var(--surface); }
```

## 不可破坏的不变量

1. **组件永不写死颜色**，只用 `bg-surface` / `text-muted` 这类语义类。出现 `#` 或 `rgb(` 在组件里，就是漂移的开始。
2. **深色色值锁定**：`[data-theme='dark']` 里的现有令牌值不得随意改。要新色先查现有语义令牌，没有再新增，而不是改现有值。
3. **浅色逐项过 WCAG AA**。`--primary` 在浅色下是 `#a8321a` 而不是深色的珊瑚色，因为后者在浅底上对白字与对背景都不达标——**改浅色主色前先算对比度**（正文与控件 4.5:1，大字 3:1）。
4. **SSR 无闪烁**：偏好写 cookie，服务端直接把 `data-theme` 渲进 `<html>`；`system` 态服务端无法解析，由 `<head>` 内联脚本在首次绘制前同步修正。不要把这段逻辑挪到 React 生命周期里，那必然闪一下。
5. **切换要同步副作用**：`color-scheme`（表单控件与滚动条）与 `<meta name="theme-color">`（移动端刻痕区）。
6. **未登录存 cookie，登录后并入 `PATCH /v1/me/preferences`**，与 `locale` / `region` 同一套接口。两处不一致时以服务端偏好为准。
7. **媒体适配需要独立令牌**：电影感素材偏暗，海报遮罩、渐变蒙层、卡片投影在浅色下必须另取值，直接复用深色的会糊成一片。
8. **`prefers-reduced-motion` 必须真的生效**：所有动画时长收敛到接近 0。视觉套件会遍历 DOM 断言没有超过 50ms 的过渡。

## 改造切入点

- **加一个语义令牌**：`globals.css` 两套各加一次 + `@theme inline` 加映射。**只加一套是最常见的 bug**，浅色下会回退成继承值。
- **加一个主题态**：不要。三态（`system` / `dark` / `light`）是产品决策，新增态会同时影响 cookie、SSR 脚本、偏好接口与后台。
- **改暗色对比**：先跑 `make test-a11y`，它对两套主题都扫；contrast 违规会给出具体节点。

## 验证

```bash
make test-a11y     # 深浅两套主题的 axe 扫描，含 color-contrast
make qa-visual     # 双主题 × 三视口截图 + reduced-motion 断言
```

手工路径：切到浅色 → 刷新页面**不应闪一下深色** → 切到「跟随系统」→ 改系统外观，页面应实时跟随 → 移动端刻痕区颜色随主题变化。
