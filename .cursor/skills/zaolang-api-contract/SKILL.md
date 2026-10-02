---
name: zaolang-api-contract
description: /v1 REST cross-cutting contract — error envelope + DomainError codes, idempotency, rate-limit buckets, SSE stream quota, auth deps/JWT audiences, security headers, request-id/logging/OTel, OpenAPI export and drift check. Use when adding an endpoint, error code, auth dependency, idempotency or rate-limit bucket.
---

# /v1 Contract & Cross-Cutting Concerns

**Scope**: routes in `back/app/api/` only parse/validate, call `app/domain/*`, and let `DomainError`s become the envelope. Business if/else in a route belongs in the domain.
Not here → route specifics live with their domain skill; `zaolang-admin-console` (admin role aliases, `AdminRead`/`AdminWrite`/`AdminDangerous`, `DangerousAction`), `zaolang-generation-jobs` (job SSE), `zaolang-testing-qa` (E2E vs rate limits).

## Key Paths

| Path | What |
|---|---|
| `back/app/api/v1/` | consumer routes, registered in `build_router()` (`back/app/main.py`); inventory = `back/openapi.json` |
| `back/app/domain/errors.py` | every `DomainError` subclass with `code` + `http_status` — grep before adding one |
| `back/app/api/errors.py` | envelope `error_body` + exception handlers (domain, 422 validation, Starlette HTTP) |
| `back/app/api/deps.py` | `DbSession`, `CurrentUser`, `OptionalUser`, `AdminUser`, `require_age_gate`, `IdempotencyKey`, `rate_limited(bucket)`, `client_identity`, `require_admin_role`, cookie names |
| `back/app/api/idempotency.py` | `hash_request` / `find_replay` / `remember` over `IdempotencyRecord` |
| `back/app/api/rate_limit.py` | `RULES` buckets, Redis sorted-set sliding window (`rl:{bucket}:{identity}`), `enforce` / `reset` |
| `back/app/api/sse_quota.py` | `reserve`/`touch`/`release`: ≤ `MAX_CONCURRENT_STREAMS_PER_USER` (8) live SSE streams per user per scope, else `RateLimited` |
| `back/app/api/middleware.py` | `CorrelationMiddleware` (`X-Request-Id`, `Server-Timing`), `SecurityHeadersMiddleware` (`/v1/assets*` → `private, no-store`); CORS is in `create_app()` |
| `back/app/security/tokens.py` | JWT issue/decode; audiences `consumer`/`admin`/`refresh` (admin uses its own secret) |
| `back/app/observability/` | `context.py` (request/user/job ContextVars), `logging.py` (JSON logs + `redact`), `tracing.py` (OTel) |
| `front/src/lib/api/schema.d.ts` | generated from `back/openapi.json` by `make openapi` |

## Invariants

1. One envelope: `{"error": {code, message, details, request_id}}`. New failures = `DomainError` subclass; never `raise HTTPException`.
2. 422s: field paths go in `details.fields` (model-level errors under `params`), `"Value error, "` stripped, envelope `message` = first field message. `back/app/api/errors.py:_validation_error`
3. Access token in memory only; refresh token only in httpOnly cookie `zl_refresh`, never in a body. Admin session cookie `zl_admin_session`.
4. Login is non-enumerable: unknown email and wrong password raise identical `AuthRequired`; the inactive-account message is checked only after the password verifies. Guarded by `tests/integration/test_api_contract.py`.
5. Consumer and admin tokens are cross-rejected (audience + secret); MCP uses its own audience (`back/app/mcp/auth.py`). `CurrentUser`/`OptionalUser` prove only a consumer session — never derive staff visibility from `user.roles` on a consumer route (`test_consumer_admin_role_visibility.py`).
6. Idempotency scope is `(user_id, endpoint, key)`, hash of the canonical body: same hash replays `response_snapshot`, different hash or a same-key race in `remember` → `IdempotencyConflict` 409. `remember` runs in the same transaction as the side effect (a rolled-back spend has no replay). The header is optional; unkeyed calls just run. Create-type writes (job submit, publish, payment, credit-moving confirms) must be idempotent via `IdempotencyRecord` or a domain unique key. Records are purged after 14 days (`zaolang-compliance-audit`).
7. Rate limits: every new route declares a bucket, GETs included (`public_read`); pick by cost — `generation_submit` (moves credits), `script_studio_write` (an LLM turn), `editor_write` (autosave), else `authenticated_write`. Identity = `user:<id>`, else `ip:<first X-Forwarded-For>`; `auth_attempt` is enforced inline in `auth.py`; `mcp_tool` is currently unused. Over limit → `RATE_LIMITED` 429 + `Retry-After` (= window) + a folded `SystemLog` `rate_limit` row. Limiter fails open on Redis errors. `test_rate_limits.py` fails on an unbucketed route of `community`/`devices`/`canvas`; changing numbers affects E2E.
8. A route returning `StreamingResponse` sets `status_code` on the response, not the decorator; mid-stream failures can only be `event: error` frames. Call `sse_quota.reserve` before returning the stream.
9. Ownership is checked in the domain, never inferred from unguessable ids; unpaid unlock = `ACCESS_REQUIRED` 402, not-remixable = `LICENSE_NOT_REMIXABLE` 409.
10. Logs: put structured data in `extra={"extra_fields": {...}}` so `redact` masks secrets; correlation ids are added automatically. OTel is off when `otel_exporter="none"`.

## Recipes

**Add an endpoint**
1. Schemas in `back/app/api/schemas/`; pagination is `common.Page` (cursor).
2. Signature: `user: CurrentUser, _: Annotated[None, Depends(rate_limited("authenticated_write"))]`.
3. Call the domain; let exceptions bubble.
4. Integration tests in `back/tests/integration/`: success, 401, 403/404, rate-limited.
5. `make openapi`; commit `back/openapi.json` + `front/src/lib/api/schema.d.ts`.

**Make a write replayable**: `idempotency_key: IdempotencyKey` → `hash_request(...)` → `find_replay` (return the snapshot) → domain call → `remember(...)` → `commit`. Reference: `back/app/api/v1/canvas.py:confirm_canvas_agent_run` (also replays a retry that lost the race, after rollback).

**Add/rename an error code**: prefer a new code; on rename sync `front/src/lib/api/errors.ts` and `docs/api.md`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_api_contract.py tests/integration/test_rate_limits.py tests/integration/test_admin_security.py tests/integration/test_consumer_admin_role_visibility.py -q
make openapi-check              # fails if generated types drift
```
