---
name: zaolang-i18n-region
description: 造浪的三语文案与地区设置：next-intl 路由与 [locale] 结构、zh-CN/en/ja 消息文件与键一致性校验、region 唯一决定 locale（regionLocale 映射）、货币与日期格式、后台 ja 回退到 en。Use when adding UI copy, changing translations, adding a locale or region, formatting currency or dates, or when make messages fails.
disable-model-invocation: true
---

# 三语文案与地区

## 职责

界面语言（`locale`）由所在地区（`region`）**唯一决定**：没有独立的语言切换入口，切地区就是切语言（同时也决定货币）。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `front/src/i18n/routing.ts` | `locales`（`zh-CN` / `en` / `ja`）、`regions`（`CN` / `GLOBAL` / `JP`）、`regionCurrency`、`regionLocale`（region→locale 唯一映射）、`localePrefix: 'always'` |
| `front/src/i18n/request.ts`、`navigation.ts` | next-intl 装配与本地化导航 |
| `front/src/i18n/messages/{zh-CN,en,ja}.json` | 三份消息文件，**键必须完全一致** |
| `front/scripts/check-messages.mjs`、`check-message-usage.mjs` | 键一致性 + 代码引用存在性校验（`make messages`） |
| `front/scripts/fragments/`、`merge-messages.mjs` | 按模块拆分的文案片段与合并 |
| `front/src/lib/format.ts` | 货币、日期、数量格式化 |
| `back/app/models/enums.py` | 后端 `Locale` / `Region` 枚举，与前端一一对应 |

## 不可破坏的不变量

1. **三份消息文件的键集合完全相同**。缺键不是「回退到中文」，而是运行时报错——`make messages` 就是拦这个的，它同时检查「代码引用的键是否存在」。
2. **不允许硬编码界面文案**。中文字面量只应出现在 `messages/zh-CN.json`、测试选择器和注释里。
3. **`localePrefix: 'always'`**：URL 前缀是 `<html lang>` 的唯一来源，分享链接与爬虫看到的语言必须无歧义。不要加「默认语言不带前缀」的优化。
4. **切 region 必须联动切 locale**：唯一映射是 `regionLocale`（`front/src/i18n/routing.ts`）。任何写 region 的地方（`RegionMenu`、设置页地区选项）都要同时 `router.replace(pathname, { locale: regionLocale[region] })` 并把 `locale` 一起写进 `/v1/auth/me/preferences`，不允许只改 region 不改 locale。不存在独立的语言选择控件（`LocaleMenu` 已移除）。
5. **货币跟 region 不跟 locale**：`regionCurrency` 是唯一映射（CN→CNY、GLOBAL→USD、JP→JPY）。价格展示一律走 `lib/format.ts`，不要在组件里拼 `¥`。
6. **日期与数量用 `Intl`**，并显式传 locale；依赖运行环境默认值会让 SSR 与客户端渲染出不同结果（hydration 报错）。
7. **后台 `ja` 回退到 `en`**，这是有意的范围决策，不是缺陷。
8. **金额从后端拿的是整数最小单位**，格式化时才转成显示形式，不要提前除。

## 改造切入点

- **加文案**：改 `front/scripts/fragments/` 下对应模块片段（或直接改三份 `messages/*.json`）→ `make messages` 必须通过 → 引用时用 `useTranslations('namespace')`。
- **加一个 locale**：`routing.ts` 的 `locales` 加值 → 新建完整消息文件（**不能只翻一半**）→ 后端 `Locale` 枚举加值 → 检查所有 `Intl` 调用与日期库的语言包。
- **加一个 region**：`regions` + `regionCurrency` + `regionLocale`（必须指向已存在的 locale）+ 后端 `Region` 枚举，四处齐改；定价相关逻辑读的是 region，要确认档位价格在新地区有定义。
- **E2E 选择器依赖中文文案**：改 `zh-CN` 的可见文案会让 Playwright 用例失败，这是**有意的**——文案是契约的一部分。改完顺手更新 `front/e2e/`。

## 验证

```bash
make messages
make test-front
```

手工路径：region 切到 `JP` → 定价显示 JPY，且 `<html lang="ja">`、导航与页面文案同步切到日文（`regionLocale.JP`）。
