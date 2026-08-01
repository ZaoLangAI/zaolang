# 接口参考

下面的文档由后端 `make openapi` 导出的 `openapi.json` 直接渲染，因此不会和运行中的 API 漂移。本地也可以直接开 <http://localhost:8000/docs>。

## 约定

- **鉴权**：`Authorization: Bearer <access_token>`。refresh token 走 httpOnly cookie，前端拿不到也就无法被 XSS 偷走。
- **后台命名空间**：`/v1/admin/*` 只认 audience 为 `admin` 的 token，存在独立 cookie `zl_admin_session` 里。
- **幂等**：所有产生副作用的 POST 接受 `Idempotency-Key`。同键重放返回首次结果；同键不同 body 返回 `409 IDEMPOTENCY_CONFLICT`。
- **分页**：游标分页（`cursor` + `next_cursor` + `has_more`），不用 offset。运维列表在被读的同时也在被写，offset 会漏行或重复行。
- **金额**：全部是整数。积分是整数个，货币是最小货币单位（分）。浮点数不参与账务计算。
- **限流**：超限返回 `429` 并带 `Retry-After` 头。C 端与后台是两套独立的分层桶。

## 统一错误结构

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "请求参数不合法。",
    "details": { "fields": { "reason": "String should have at least 4 characters" } },
    "request_id": "req_05809e3652d04fe8318000c8"
  }
}
```

`request_id` 会同时出现在响应头 `x-request-id`、结构化日志与 `AuditLog` 里，是排查线上问题的唯一串联键。

## 交互式文档

<swagger-ui src="./openapi.json"/>
