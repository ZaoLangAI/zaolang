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
| `back/app/api/v1/*.py` | consumer routes registered by `build_router()`: `auth` / `profiles` / `works` / `learning` / `skills` / `drafts` / `jobs` / `prompts` / `shortform` / `characters` / `scenes` / `gateway` / `uploads` / `credits` / `community` / `style_gallery` / `privacy` / `devices` / `editor` / `scripts` / `distribution`; work/skill `POST .../unlock` and skill `PATCH .../pricing`; MCP lives at `POST /mcp` (its own `mcp` audience). There is no `/v1/series` route: `characters.py` only serves `/v1/characters` (the old `kind=cast` roster CRUD was removed with the single-clip studio, see `domain/characters/service.py`'s module docstring), and short drama lives at `/v1/drama-series` + `/v1/drama-episodes` in `editor.py`. Treat the directory listing and `back/app/main.py`'s `build_router()` registration as ground truth |
| `back/app/api/v1/admin/*.py` | admin routes, a separate namespace — see `zaolang-admin-console` |
| `back/app/api/deps.py` | `CurrentUser` / `OptionalUser` / `AdminUser` / `IdempotencyKey` / `rate_limited(bucket)` / `require_admin_role(minimum)`; `require_age_gate` (raises `AgeGateRequired`, 403 `AGE_GATE_REQUIRED`, when `age_gate_confirmed_at` is null — defined but not yet wired into any route; today the gate is enforced at registration via `age_confirmed`); cookie names `REFRESH_COOKIE_NAME = "zl_refresh"` (consumer refresh) and `ADMIN_COOKIE_NAME = "zl_admin_session"` (admin session, also accepted by `get_admin_user` in place of a bearer token) |
| `back/app/api/errors.py` | the unified error envelope and exception-handler registration |
| `back/app/domain/errors.py` | every `DomainError` subclass, each carrying its own `code` and `http_status`. Beyond the licensing pair (`ACCESS_REQUIRED` / `LICENSE_NOT_REMIXABLE`) the public codes include `REVISION_CONFLICT` and `LEASE_HELD` (409, editor optimistic concurrency), `BATCH_ROLLED_BACK` / `OPERATION_TERMINAL` / `BROWSER_REQUIRED` (409), `SCOPE_REQUIRED` / `PROJECT_FORBIDDEN` / `AGE_GATE_REQUIRED` (403), `PLATFORM_NOT_CONFIGURED` (503), `PLATFORM_ACCOUNT_NOT_LINKED` (409), `PLATFORM_OAUTH_FAILED` / `PLATFORM_PUBLISH_FAILED` (502) — grep the file before inventing a new one |
| `back/app/api/idempotency.py` | `hash_request` / `find_replay` / `remember` |
| `back/app/api/rate_limit.py` | `RULES` bucket definitions and the Redis sliding-window implementation |
| `back/app/api/middleware.py` | only two middlewares: `CorrelationMiddleware` (honours/assigns `X-Request-Id`, echoes it plus a `Server-Timing` header) and `SecurityHeadersMiddleware` (nosniff / referrer-policy / `X-Frame-Options: DENY`, `no-store` for `/v1/assets`). CORS is not here — `CORSMiddleware` is added in `main.py`'s `create_app()` from `settings.cors_origins`, exposing `x-request-id` and `retry-after` |
| `back/app/security/tokens.py` / `passwords.py` | JWT issuance and verification, argon2 |
| `back/app/scripts/export_openapi.py` → `back/openapi.json` → `front/src/lib/api/schema.d.ts` | the one-way chain from contract to frontend types. `WorkVersionSummary` incrementally exposes `output_asset_id` (`WorkVersion.primary_output_asset_id`) so a remix studio can put the licensed source clip into `reference_asset_ids` — `media_url` remains the signed playback URL only |

## Invariants

1. **There is exactly one error-envelope shape**: `{"error": {code, message, details, request_id}}`. New failure cases get a `DomainError` subclass (with `code` and `http_status`) in `domain/errors.py` — **never `raise HTTPException` directly**, or the frontend's single error-handling path breaks.
2. **The access token lives in memory; the refresh token lives in an httpOnly cookie.** Never write the access token to localStorage or return it in a cookie, and never let the refresh token appear in a response body.
3. **Login failures are not enumerable**: an unknown email and a wrong password share one branch in `api/v1/auth.py`'s `login` and raise the identical `AuthRequired("邮箱或密码不正确。")`, so the two responses are byte-for-byte indistinguishable. A suspended (`is_active=False`) account is checked only *after* the password verifies and gets `AuthRequired("账号不可用，请联系支持。")` — same 401 status and `AUTH_REQUIRED` code, but a different message; that is deliberate (the caller already proved the password) and must not leak to the unknown/wrong branch. Before changing the login response, read `test_login_does_not_distinguish_unknown_email_from_wrong_password` in `tests/integration/test_api_contract.py` and the admin counterparts in `tests/integration/test_admin_security.py`.
4. **Consumer and admin tokens use different audiences**: a consumer token against `/v1/admin/*` must 401, and vice versa.
5. **Idempotency-key scope is `(user_id, endpoint, key)`**: a hit with a matching request hash replays the stored response; a hit with a different hash raises `IdempotencyConflict` (409). Every create-type write endpoint (submit a job, publish, a payment callback) must implement idempotency. `POST /v1/drafts/{id}/publish` returns **202** `{status: pending, draft_id, work_id: null}` after accepting the intent; the Work is created later by `run_draft_publish`. A second submit while `publish_status=pending` is `Conflict` (409) unless it is the same key replaying.
6. **Rate limiting is tiered**, buckets defined in `RULES`: `public_read` 240/60s, `authenticated_write` 90/60s, `auth_attempt` 10/300s, `generation_submit` 12/60s, `upload_presign` 30/60s, `editor_write` 60/60s, `editor_export` 20/60s, `script_studio_write` 20/60s, `platform_publish` 20/60s, `series_collab_invite` 10/300s (as strict as a login attempt because it notifies a stranger), `mcp_tool` 60/60s; admin has its own `admin_read` 300/60s / `admin_write` 60/60s / `admin_dangerous` 10/300s. `RateLimited` must carry `Retry-After`. **Changing these numbers affects E2E** (see `zaolang-testing-qa` for why E2E reuses sessions).
7. **Resource ownership is checked at the service layer**, never inferred from whether a route param is guessable. Visibility and remix authorization always go through `app/domain/licensing/service.py`. An unpurchased paid unlock is `ACCESS_REQUIRED` (402); a work not open to remixing is `LICENSE_NOT_REMIXABLE` (409) — don't conflate the two.
8. **There is no roster API.** `api/v1/characters.py` exposes only `/v1/characters` (CRUD + `/publish` + `/withdraw`) over `CreationSkill(category=CHARACTER)` rows; the former `/v1/series` `kind=cast` roster and its episode sub-routes were removed together with the single-clip studio, and every remaining `Series` is created with `kind=drama`. `Series` and `DramaEpisode`/`EpisodeContentLink` are managed exclusively by `api/v1/editor.py` (`/v1/drama-series/{id}`, `/v1/drama-series/{id}/episodes`, `/v1/drama-episodes/{id}` and its `content-links` / `set-canonical-work` / `cuts` / `exports` sub-routes) — don't resurrect a second route family for them. MCP uses only the `mcp` audience — never a consumer or admin token. See `zaolang-editor-drama`. Admin daily trends live at `/v1/admin/statistics/*` — see `zaolang-admin-statistics`.
9. **A route returning a `StreamingResponse` directly must set `status_code` on the response itself, not the decorator.** `@router.post(..., status_code=202)` only applies when FastAPI auto-serializes a returned value; returning a `Response` subclass bypasses that entirely and the response's own default (200) wins instead. `/v1/scripts`'s SSE endpoints (`event: start`/`delta`/`thinking`/`complete`/`error` frames — `thinking` carries the model's live reasoning chunks and is best-effort per provider, and a bare comment line may precede the first frame as a heartbeat) learned this the hard way. A mid-stream failure can only be reported as an `event: error` frame, never an HTTP status — headers are already sent by the time a streamed turn can fail. See `zaolang-editor-drama` invariant #18 for the matching server-side session-handling rule.

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
make test-back                      # tests/integration/test_api_contract.py: auth (register/age gate/login non-enumeration), error envelope + request_id, ownership/visibility, discovery, quote
cd back && conda run -n zaolang pytest tests/integration/test_rate_limits.py -v
make openapi-check                  # confirms no type drift
```
