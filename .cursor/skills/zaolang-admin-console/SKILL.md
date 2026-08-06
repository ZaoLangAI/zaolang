---
name: zaolang-admin-console
description: 造浪后台的安全边界与前端外壳：独立 /v1/admin 命名空间与 admin audience token、四级 RBAC、二次确认与强制理由、独立限流、审计装饰器，以及 (admin) 路由组的独立 layout、登录页、RBAC 导航与数据密集型组件族。Use when adding a back-office endpoint or page, changing admin roles and permissions, the admin session, dangerous-action confirmation, or the console's tables/drawers/diff components.
disable-model-invocation: true
---

# 后台安全边界与控制台外壳

## 职责

后台代码住在 `front/` 与 `back/` 内部，但**会话、命名空间、限流、权限、外壳全部与 C 端隔离**。C 端 token 打后台必须 401。

## 关键路径

### 后端

| 文件 | 内容 |
| --- | --- |
| `back/app/api/v1/admin/deps.py` | `Viewer` / `Reviewer` / `Operator` / `Admin` 四个等级别名；`AdminRead` / `AdminWrite` / `AdminDangerous` 限流；`require_confirmation` |
| `back/app/api/v1/admin/auth.py` | `/admin/login`、会话查询、登出；签发 audience 为 `admin` 的 token，存 `zl_admin_session` cookie |
| `back/app/api/v1/admin/*.py` | `config` / `content` / `data` / `jobs` / `ledger` / `logs` / `observability` / `users` / `llm_providers` / `agent_skills` / `skill_library` / `redemption` / `learning` |
| `back/app/domain/audit/service.py` | 写操作留痕 |
| `back/tests/integration/test_admin_security.py` | 37 个越权与高危操作用例，改权限前先读它 |

### 前端

| 文件 | 内容 |
| --- | --- |
| `front/src/app/[locale]/(admin)/admin/login/page.tsx` | 独立登录页（不复用 C 端登录弹窗） |
| `front/src/app/[locale]/(admin)/admin/(console)/layout.tsx` | 控制台外壳 |
| `front/src/components/admin/admin-session-provider.tsx` | 后台会话上下文 |
| `front/src/components/admin/admin-sidebar.tsx` + `front/src/lib/admin/rbac.ts` | `NAV_GROUPS` / `visibleGroups(role)` / `atLeast` |
| `front/src/components/admin/` | `data-table` / `filter-bar`（含 `daterange`）/ `detail-drawer` / `danger-confirm` / `json-diff` / `timeline` / `stepper` / `duration-bars` / `agent-node-graph` / `agent-skill-editor` / `providers/llm-providers-panel`（扁平主备列表 + 端点级主备）/ `log-center-console` |
| `front/src/lib/api/admin-client.ts`、`admin-server.ts`、`use-admin-list.ts` | 后台专用客户端与列表 hook |

## 不可破坏的不变量

1. **两套会话互不通用**：C 端 token 打 `/v1/admin/*` 401，后台 token 打 C 端接口 401。cookie 名、audience、登录页都独立。
2. **服务端强制 RBAC**，前端导航裁剪只是体验优化。`rbac.ts` 里 `requires` 与后端路由的等级别名要一致，但**任何隐藏的路由被直接访问时仍由后端拒绝**。等级：`viewer < reviewer < operator < admin`，高等级自动满足低要求。
3. **读写等级分离**：例如配置读是 viewer 级、写与回滚是 admin 级。因此「operator 能打开配置页但没有保存按钮」是正确行为，不是漏洞。
4. **高危操作两道闸**：`require_confirmation(confirmed)` + schema 强制的 `reason`。缺一必须 4xx，理由进 `AuditLog`。前端一律用 `danger-confirm.tsx`。
5. **所有 `/v1/admin/*` 写操作都要审计**，包括失败的高危尝试。
6. **后台限流按管理员维度独立计量**：`admin_read` 300/60s、`admin_write` 60/60s、`admin_dangerous` 10/300s。
7. **管理员不能自己摘掉自己的 admin 角色**（避免把系统锁死），有专门用例守着。
8. **被封禁的管理员立即失去访问**，不等 token 过期。
9. **后台复用同一套设计令牌与三态主题**，但组件族与 C 端截然不同（表格、筛选、游标分页、批量操作、抽屉、JSON diff、时间线）。后台文案 `zh-CN` 与 `en`，`ja` 回退 `en`。

## 改造切入点

**加一个后台接口**

1. 选等级别名（`Viewer` / `Reviewer` / `Operator` / `Admin`）与限流别名（`AdminRead` / `AdminWrite` / `AdminDangerous`）。
2. 高危的话：schema 里带 `confirm: bool` 与 `reason: str`，函数体先 `require_confirmation`。
3. 写操作接审计装饰器，`before`/`after` 只放摘要。
4. 在 `test_admin_security.py` 加「低一级角色被拒」与「审计留痕」两条用例。

**加一个后台页面**

1. `(console)/` 下建目录 → 用 `use-admin-list.ts` + `data-table.tsx` 组装。
2. `rbac.ts` 的 `NAV_GROUPS` 加导航项并写清 `requires`。
3. 三语文案（`ja` 复用 `en` 值）。
4. `front/e2e/flows/admin.spec.ts` 加一条「页面能打开且有真实数据」的用例。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_security.py -v
make test-e2e     # e2e/flows/admin.spec.ts 覆盖登录边界、十个以上运维页与 RBAC 导航
```
