---
name: zaolang-api-contract
description: The /v1 REST contract and cross-cutting concerns — email/password auth (argon2 + JWT + refresh cookie), a unified error envelope and error codes, idempotency middleware, tiered rate limiting, request context, OpenAPI export. Use when adding or changing an API endpoint, error code, authentication or authorization dependency, idempotency handling, rate limit bucket, or when the OpenAPI schema drifts.
disable-model-invocation: true
---

# The /v1 Contract & Cross-Cutting Concerns

## Scope

`back/app/api/` does exactly three things: parse and validate input, call into `app/domain/*`, and translate domain exceptions into the unified error envelope. **Business rules do not live in routes** — an if/else on a business condition inside a route is a signal that logic belongs in the domain layer instead.

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/api/v1/*.py` | consumer routes: `auth` / `works` / `drafts` / `jobs` / `uploads` / `credits` / `community` / `profiles` / `privacy` / `gateway` / `characters` / `devices` / `learning` / `shortform` / `skills` / `editor` / `scripts`; work/skill `POST .../unlock` and skill `PATCH .../pricing`; MCP lives at `POST /mcp` (its own `mcp` audience); `/v1/series` only ever returns `kind=cast`, drama production projects use `/v1/drama-series`. Treat the directory listing and `back/app/main.py`'s `build_router()` registration as ground truth |
| `back/app/api/v1/admin/*.py` | admin routes, a separate namespace — see `zaolang-admin-console` |
| `back/app/api/deps.py` | `CurrentUser` / `OptionalUser` / `AdminUser` / `IdempotencyKey` / `rate_limited(bucket)` / `require_admin_role(minimum)` |
| `back/app/api/errors.py` | the unified error envelope and exception-handler registration |
| `back/app/domain/errors.py` | every `DomainError` subclass, each carrying its own `code` and `http_status` |
| `back/app/api/idempotency.py` | `hash_request` / `find_replay` / `remember` |
| `back/app/api/rate_limit.py` | `RULES` bucket definitions and the Redis sliding-window implementation |
| `back/app/api/middleware.py` | request_id, logging, CORS wiring |
| `back/app/security/tokens.py` / `passwords.py` | JWT issuance and verification, argon2 |
| `back/app/scripts/export_openapi.py` → `back/openapi.json` → `front/src/lib/api/schema.d.ts` | the one-way chain from contract to frontend types |

## Invariants

1. **There is exactly one error-envelope shape**: `{"error": {code, message, details, request_id}}`. New failure cases get a `DomainError` subclass (with `code` and `http_status`) in `domain/errors.py` — **never `raise HTTPException` directly**, or the frontend's single error-handling path breaks.
2. **The access token lives in memory; the refresh token lives in an httpOnly cookie.** Never write the access token to localStorage or return it in a cookie, and never let the refresh token appear in a response body.
3. **Login failures are not enumerable**: an unknown email, a wrong password, and a suspended account all return the same 401, indistinguishably. Before changing the login response, read the matching test names in `tests/integration/test_admin_security.py`.
4. **Consumer and admin tokens use different audiences**: a consumer token against `/v1/admin/*` must 401, and vice versa.
5. **Idempotency-key scope is `(user_id, endpoint, key)`**: a hit with a matching request hash replays the stored response; a hit with a different hash raises `IdempotencyConflict` (409). Every create-type write endpoint (submit a job, publish, a payment callback) must implement idempotency.
6. **Rate limiting is tiered**, buckets defined in `RULES`: `public_read` 240/60s, `authenticated_write` 90/60s, `auth_attempt` 10/300s, `generation_submit` 12/60s, `upload_presign` 30/60s, `script_studio_write` 20/60s; admin has its own `admin_read` / `admin_write` / `admin_dangerous`. `RateLimited` must carry `Retry-After`. **Changing these numbers affects E2E** (see `zaolang-testing-qa` for why E2E reuses sessions).
7. **Resource ownership is checked at the service layer**, never inferred from whether a route param is guessable. Visibility and remix authorization always go through `app/domain/licensing/service.py`. An unpurchased paid unlock is `ACCESS_REQUIRED` (402); a work not open to remixing is `LICENSE_NOT_REMIXABLE` (409) — don't conflate the two.
8. **`/v1/series` and `/v1/drama-series` are isolated.** The roster API only ever returns `kind=cast`; a drama id against `/v1/series/{id}` must 404 (indistinguishable from not-found). MCP uses only the `mcp` audience — never a consumer or admin token. See `zaolang-editor-drama`. Admin daily trends live at `/v1/admin/statistics/*` — see `zaolang-admin-statistics`.
9. **A route returning a `StreamingResponse` directly must set `status_code` on the response itself, not the decorator.** `@router.post(..., status_code=202)` only applies when FastAPI auto-serializes a returned value; returning a `Response` subclass bypasses that entirely and the response's own default (200) wins instead. `/v1/scripts`'s SSE endpoints (`event: start`/`delta`/`complete`/`error` frames) learned this the hard way. A mid-stream failure can only be reported as an `event: error` frame, never an HTTP status — headers are already sent by the time a streamed turn can fail. See `zaolang-editor-drama` invariant #17 for the matching server-side session-handling rule.

## Extension Points

**Add an endpoint**

1. Put request/response models in `back/app/api/schemas/`; pagination is always `common.Page` (cursor-based).
2. Declare auth and rate limiting in the route signature via `deps.py` aliases: `user: CurrentUser, _: Annotated[None, Depends(rate_limited("authenticated_write"))]`.
3. Call into `app/domain/*` for business logic and let exceptions bubble.
4. Add integration tests under `back/tests/integration/`, covering success, unauthenticated, unauthorized, and rate-limited paths.
5. Run `make openapi` and **commit** both `back/openapi.json` and `front/src/lib/api/schema.d.ts` — `make openapi-check` is what catches drift.

**Change an error code**: error codes are a public contract that the frontend and docs reference. Prefer adding a new code; if renaming, sync `front/src/lib/api/errors.ts` and `docs/api.md`.

## Verify

```bash
make test-back                      # tests/integration/test_api_contract.py checks against doc 04 line by line
cd back && conda run -n zaolang pytest tests/integration/test_rate_limits.py -v
make openapi-check                  # confirms no type drift
```
