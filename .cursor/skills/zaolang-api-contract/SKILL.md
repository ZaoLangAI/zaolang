---
name: zaolang-api-contract
description: 造浪 /v1 REST 契约与横切能力：邮箱密码鉴权（argon2 + JWT + refresh cookie）、统一错误信封与错误码、幂等中间件、分层限流、请求上下文与 OpenAPI 导出。Use when adding or changing an API endpoint, error code, authentication or authorization dependency, idempotency handling, rate limit bucket, or when the OpenAPI schema drifts.
disable-model-invocation: true
---

# /v1 契约与横切能力

## 职责

`back/app/api/` 只做三件事：解析与校验输入、调用 `app/domain/*`、把领域异常翻译成统一错误信封。**业务规则不写在路由里**——路由里出现 if/else 判断业务条件，就是该下沉到 domain 的信号。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/api/v1/*.py` | C 端路由：`auth` / `works` / `drafts` / `jobs` / `uploads` / `credits` / `community` / `profiles` / `privacy` / `gateway` |
| `back/app/api/v1/admin/*.py` | 后台路由，独立命名空间，见 `zaolang-admin-console` |
| `back/app/api/deps.py` | `CurrentUser` / `OptionalUser` / `AdminUser` / `IdempotencyKey` / `rate_limited(bucket)` / `require_admin_role(minimum)` |
| `back/app/api/errors.py` | 统一错误信封与异常处理器注册 |
| `back/app/domain/errors.py` | 全部 `DomainError` 子类，每个自带 `code` 与 `http_status` |
| `back/app/api/idempotency.py` | `hash_request` / `find_replay` / `remember` |
| `back/app/api/rate_limit.py` | `RULES` 桶定义与 Redis 滑窗实现 |
| `back/app/api/middleware.py` | request_id、日志、CORS 相关装配 |
| `back/app/security/tokens.py` / `passwords.py` | JWT 签发与校验、argon2 |
| `back/app/scripts/export_openapi.py` → `back/openapi.json` → `front/src/lib/api/schema.d.ts` | 契约到前端类型的单向链条 |

## 不可破坏的不变量

1. **错误信封只有一种形状**：`{"error": {code, message, details, request_id}}`。新增失败情形要在 `domain/errors.py` 加 `DomainError` 子类（带 `code` 与 `http_status`），**不要直接 `raise HTTPException`**，否则前端的单一错误路径会破。
2. **access token 在内存，refresh 在 httpOnly cookie**。不要把 access token 写进 localStorage 或返回到 cookie，也不要让 refresh token 出现在响应体里。
3. **登录失败不可枚举**：未知邮箱、错误密码、已封禁账号返回同一个 401，不区分。改动登录响应前先读 `tests/integration/test_admin_security.py` 里的同名用例。
4. **C 端 token 与后台 token audience 不同**：C 端 token 打 `/v1/admin/*` 必须 401，反之亦然。
5. **幂等键作用域是 `(user_id, endpoint, key)`**，命中且 request hash 相同 → 回放存储的响应；hash 不同 → `IdempotencyConflict`（409）。所有创建型写接口（提交任务、发布、支付回调）都必须接幂等。
6. **限流分层**，桶定义在 `RULES`：`public_read` 240/60s、`authenticated_write` 90/60s、`auth_attempt` 10/300s、`generation_submit` 12/60s、`upload_presign` 30/60s，后台另有 `admin_read` / `admin_write` / `admin_dangerous`。`RateLimited` 必须带 `Retry-After`。**改这些数字会影响 E2E**（见 `zaolang-testing-qa` 里为什么 E2E 复用会话）。
7. **资源所有权在服务层校验**，不靠路由参数是否可猜。可见性与二创权限一律走 `app/domain/licensing/service.py`。

## 改造切入点

**加一个端点**

1. 请求/响应模型进 `back/app/api/schemas/`，分页统一用 `common.Page`（游标分页）。
2. 路由函数签名用 `deps.py` 的别名声明鉴权与限流：`user: CurrentUser, _: Annotated[None, Depends(rate_limited("authenticated_write"))]`。
3. 业务逻辑调 `app/domain/*`，异常让它自己冒泡。
4. 写集成测试进 `back/tests/integration/`，覆盖成功、未登录、越权、限流四条路径。
5. `make openapi` 并**提交** `back/openapi.json` 与 `front/src/lib/api/schema.d.ts`——`make openapi-check` 就是拦漂移的。

**改错误码**：错误码是对外契约，前端与文档都在引用。加新码优先，改名要同步 `front/src/lib/api/errors.ts` 与 `docs/api.md`。

## 验证

```bash
make test-back                      # tests/integration/test_api_contract.py 逐条比对 04 文档
cd back && conda run -n zaolang pytest tests/integration/test_rate_limits.py -v
make openapi-check                  # 类型没漂移
```
