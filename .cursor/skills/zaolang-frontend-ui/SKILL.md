---
name: zaolang-frontend-ui
description: 造浪 C 端前端：12 个页面的路由结构、共享组件族与全状态要求、API client 与 token 刷新、登录弹窗与 pendingAction 恢复、Cmd+K 命令面板、断点与无横向溢出约束。Use when adding or changing a consumer-facing page, shared UI component, the API client, the login dialog, the command palette, or responsive behaviour.
disable-model-invocation: true
---

# C 端前端

## 职责

`front/src/app/[locale]/(site)/` 下的 12 个页面与它们共用的组件族。**以现有页面、共享组件与视觉 e2e 为准**，深色主题是验收基准。

## 关键路径

| 路径 | 内容 |
| --- | --- |
| `front/src/app/[locale]/(site)/` | `discover` / `work/[workId]` / `create` / `remix/[workId]` / `jobs/[jobId]` / `publish/[draftId]` / `collection` / `profile` / `profile/settings` / `billing` / `notifications` / `learn` |
| `front/src/components/ui/` | `button` / `dialog` / `field` / `primitives` / `spinner` / `toast` / `icons` |
| `front/src/components/layout/` | `top-bar` / `preference-menu` / `site-footer` / `brand` |
| `front/src/components/auth/` | `login-dialog` / `session-provider` / `sign-in-prompt` |
| `front/src/components/command/command-palette.tsx` | Cmd+K，combobox 无障碍模式 |
| `front/src/lib/api/client.ts` | 浏览器侧 fetch：内存 access token、自动刷新、`Idempotency-Key` |
| `front/src/lib/api/server.ts` | RSC 侧 fetch，走 `API_INTERNAL_URL` |
| `front/src/lib/use-resource.ts`、`use-job-stream.ts` | 数据获取与 SSE hooks |
| `front/src/lib/format.ts` | 货币、日期、数量的地区化格式 |

## 不可破坏的不变量

1. **access token 只在内存**。放进 `localStorage` 会让任意 XSS 变成永久账号接管；长效的一半是 httpOnly refresh cookie。刷新页面后先无 token、再静默换取——所有依赖登录态的组件必须能承受这个中间态。
2. **刷新请求要合并**：`client.ts` 用 `refreshInFlight` 保证并发 401 只触发一次刷新。不要在组件里自己实现重试。
3. **受保护动作走登录墙 + 动作恢复**：拦截 → 打开 `login-dialog` → 成功后按 `pendingAction` 恢复原动作；取消则**放弃**动作，不能悄悄执行。
4. **移动积分的调用必须带 `idempotencyKey`**（提交生成、购买积分）。
5. **每个交互组件实现全部状态**：`default / hover / focus-visible / disabled / loading / error`（+ `selected`）。缺 `focus-visible` 会被无障碍套件抓出来。
6. **不引入 UI 组件库**，避免主题令牌漂移。组件只消费语义令牌（见 `zaolang-theming`），**永不写死颜色**。
7. **三个断点无横向溢出**：1440×1024 / 1024 / 390×844，断言 `scrollWidth === clientWidth`。视觉 QA 套件会逐页检查。
8. **文案一律走 next-intl**，不允许硬编码中文字符串（见 `zaolang-i18n-region`）。
9. **命令面板是 combobox 而不是 dialog**：`role="search"` 容器 + `role="combobox"` 输入 + `role="listbox"`/`role="option"`。这个 ARIA 结构被 axe 检查，改标记前先看 `e2e/a11y.spec.ts`。

## 改造切入点

- **加一个页面**：在 `(site)/` 下建目录（RSC 默认服务端渲染，数据用 `lib/api/server.ts` 取）→ 交互部分拆成 `'use client'` 组件 → 三语文案进 `src/i18n/messages/*.json`（三份都要）→ 加进命令面板的可跳转项 → 视觉与无障碍套件的页面清单（`e2e/visual.spec.ts`、`e2e/a11y.spec.ts`）。
- **加一个共享组件**：放 `components/ui/`，用 `lib/cn.ts` 合并类名，状态齐全，键盘可达。
- **调 API client**：错误一律 `ApiError`（带后端错误码），不要在组件里解析响应体。
- **加一个表单**：用 `components/ui/field.tsx`，把后端 422 的字段路径映射到内联错误，而不是弹一个通用横幅。

## 验证

```bash
make test-front              # tsc --noEmit + next build
make messages                # 三语键一致，且代码引用的键都存在
make test-e2e                # 需要先起后端与种子数据
make test-a11y && make qa-visual
```
