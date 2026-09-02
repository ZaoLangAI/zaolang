---
name: zaolang-testing-qa
description: The testing and QA system — four pytest layers (unit / hypothesis property / integration / real concurrency), fixtures and committed_db, the Playwright projects (setup / e2e / a11y / a11y-mobile / visual-qa), vitest unit tests, session reuse and rate limiting, dual-theme three-viewport and reduced-motion checks. Use when writing or fixing tests, adding a property or concurrency test, debugging a flaky or hanging test, or running the E2E, accessibility and visual QA suites.
disable-model-invocation: true
---

# Testing & QA

## Backend: Four Layers

| Directory | What it runs | When to add a case |
| --- | --- | --- |
| `back/tests/unit/` | domain invariants, pure functions | any `app/domain/*` change |
| `back/tests/unit/test_credits_properties.py` | hypothesis-generated sequences of ledger operations and their state-machine paths | any ledger or state-machine change |
| `back/tests/integration/` | `TestClient` against `/v1`, admin unauthorized-access and audit checks | any endpoint change |
| `back/tests/concurrency/` | real threads with independent connections, racing | any concurrency-sensitive path (ledger, idempotency, callbacks, credit unlocks) |

Key fixtures live in `back/tests/conftest.py`: `db` (rollback-style, used by most tests), `committed_db` (real commit + `truncate_all` afterward), `client`, `author` / `admin` / `reviewer` / `operator`, `make_user`; `viewer` is not a shared fixture — the integration tests that need it define it locally (`tests/integration/test_admin_security.py`, `tests/integration/test_system_log.py`). Data builders live in `back/tests/factories.py` (`make_job`, etc.). Other root-level helpers: `fake_llm_gateway.py` (the autouse fake), `fake_providers.py` + `fake_provider_catalog.py` (deterministic media providers and the test-only capability catalogue that injects them), `llm_catalog.py` (`seed_test_llm_catalog` — writes an `llm_providers` endpoint and binds the default agents, since product code no longer invents model names), and `test_llm_live.py` (the `@pytest.mark.live` smoke, run via `make test-llm`).

## Invariants

1. **An autouse fixture in `conftest.py` swaps the LLM gateway for `tests/fake_llm_gateway.py`'s deterministic fake, for every test** — production code has no stub/auto mode any more, only "real gateway or error," so this fixture is what keeps the suite offline and deterministic instead of an env var flipping a production code path. `@pytest.mark.live` (real network call) and `@pytest.mark.real_gateway_seams` (tests the real client's own failover/circuit-breaker/error logic) opt out; `make test-back` already excludes `live` via `-m "not live"`.
2. **Property tests and any case that triggers `IntegrityError` must use `committed_db`**: `credits._apply` calls `session.rollback()` on `IntegrityError`, discarding the whole unit of work — including fixture-created users. A rollback-style `db` produces false failures like "foreign key points at a nonexistent user."
3. **hypothesis needs `suppress_health_check=[HealthCheck.function_scoped_fixture]`**: rebuilding the schema for every example would be unusably slow, so each example isolates itself instead — via a SAVEPOINT, or a unique key with a nonce.
4. **Generated strings must exclude control characters and surrogate pairs**: Postgres text columns reject NUL, and HTTP headers can't carry them either.
5. **Concurrency tests can't use a rollback-style session**: two transactions racing each other are invisible inside a single transaction. Two rules apply — miss either and a failure turns into a hang:
   - every worker **must end its own transaction** (`tests/concurrency/conftest.py`'s `race()` rolls back before re-raising on any exception), or the loser sits on a row lock forever while the winner waits;
   - every session sets a `lock_timeout` (5s default), so an unexpected deadlock shows up as a failed test, not a hung suite.
   `run_in_parallel()` uses a barrier to align workers, daemon threads with a bounded join, and **returns exceptions rather than raising them** — "losing" a race is the correct outcome; judging it is the test's job.
6. **Race-condition assertions take the shape "exactly one winner"**, and must confirm the loser failed for a concurrency reason (`Conflict` / `InsufficientCredits` / `SQLAlchemyError`) rather than coincidentally failing for something else.

## Frontend: Playwright Projects + vitest

`front/playwright.config.ts` defines five projects for three suites: `setup` (log in and store sessions) → `e2e` (`e2e/flows/*.spec.ts`, incl. the desktop-only `editor.spec.ts`; `npm run test:e2e`), `a11y` + `a11y-mobile` (both run `e2e/a11y.spec.ts`, desktop 1440 vs phone 390 viewport; `npm run test:a11y` runs both), `visual-qa` (`e2e/visual.spec.ts`, depends on `setup`; `npm run qa:visual`). All run with `workers: 1` — the suites share one seeded database, and parallel publishing would cross-contaminate assertions. Frontend unit tests are separate: `front/vitest.config.ts` + `src/**/*.test.ts(x)`, run with `npm test` in `front/` only (not in `make test-front` or `make check`). `/studio-editor/{cutId}` (the cut editor; the legacy `/create/short/{cutId}` only redirects there) is deliberately excluded from both `a11y-mobile` and `PUBLIC_PAGES` — it's a dynamic route anyway, but the desktop-only `EditorGate` is the reason even if it weren't. `/create/short` itself (the drama-series dashboard) is a plain sign-in-gated page and is already in both lists.

Support files: `e2e/support/session.ts` (`ACCOUNTS` / `STATE_FILES` / `signIn` / `watchForPageErrors`), `support/axe.ts`, `support/theme.ts`, `setup/auth.setup.ts`.

1. **Session reuse isn't about speed** — `/v1/auth/login` is rate-limited to 10 attempts/5 min/address, correct product behavior. Every test logging in for real would turn that protection into flaky failures. So `setup` logs in exactly four times and stores `e2e/.auth/*.json` (gitignored); other tests use `test.use({ storageState })`. **Tests specifically about login still log in for real.**
2. **Anonymous tests must explicitly clear session state**: `test.use({ storageState: { cookies: [], origins: [] } })`, or they inherit the previous project's session.
3. **`baseURL` uses `localhost`, not `127.0.0.1`**: the admin session cookie is `SameSite=Strict`, and browsers treat these hostnames as different sites. The backend's `CORS_ORIGINS` must include both 3000 and 3100.
4. **`watchForPageErrors` only allows a known set of expected failures** (the session probe's 401); every other 4xx/5xx and any JS exception counts as a failure. Don't widen the allowlist to make a test pass — that's exactly what this check exists to catch.
5. **The visual suite asserts mechanical facts**: no horizontal overflow at three viewports (`scrollWidth === clientWidth`), no console errors, no reduced-motion transition over 50ms. Screenshots are attached to the report for human review only — they don't gate pass/fail.
6. **The accessibility suite scans both themes**, including `color-contrast`. The command palette is a combobox, not a dialog — changing its markup risks breaking the ARIA rule. The drama editor is a hard desktop gate — don't add it to `a11y-mobile` for coverage's sake.
7. **The admin statistics page still counts as passing when a single endpoint fails.** `/admin/statistics` uses `adminFetchOrNull` — don't write an e2e test that expects "any 5xx turns the whole page red." Daily-trend semantics: see `zaolang-admin-statistics`.

## E2E Prerequisites

```bash
make up && make migrate && make seed          # a real database and seed data
make dev-api                                   # backend must be on 3001
make test-e2e && make test-a11y && make qa-visual
```

The `webServer` block in `playwright.config.ts` builds and starts the front on `3100` itself (`npm run build && npm run start -- --port 3100`, 180s timeout, reuses an existing listener) — you don't start it by hand. Set `PLAYWRIGHT_BASE_URL` to point at an already-running server instead, which disables `webServer` entirely.

`front/.env.local` needs `ALLOW_LOCAL_IMAGE_HOSTS=1` when `STORAGE_BACKEND=minio` (still the `Settings` default; `front/.env.example` already ships it as `1`): Next 16 rejects image optimization against private-address hosts by default (SSRF protection), and the local MinIO instance is exactly that — skip this and every cover image 400s. With `tencent_cos` it's unnecessary (COS serves from `*.myqcloud.com`, already in `remotePatterns`). Never set this in production.

## Verify

```bash
make test-back      # 1700+ cases (-m "not live"), coverage printed to the terminal
make check          # the full local gate
```

After writing a test, ask: **can it actually fail?** Temporarily break the invariant under test, confirm the test goes red, then revert.
