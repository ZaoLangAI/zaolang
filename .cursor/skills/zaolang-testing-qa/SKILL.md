---
name: zaolang-testing-qa
description: Test system — pytest layers (unit/hypothesis/integration/concurrency), conftest guards and fixtures, skill-freshness guard, Playwright e2e/a11y/visual suites and their `make e2e-fixtures` data, vitest. Use when writing or fixing tests, adding property or concurrency tests, debugging flaky/hanging tests, or running e2e/a11y/visual QA.
---

# Testing & QA

**Scope**: how tests are layered, isolated and run. Not here → `zaolang-ci-release` (`make check` gate, pre-commit), `zaolang-local-env` (stack, seed accounts).

## Key Paths

| Path | What |
| --- | --- |
| `back/tests/unit/` | domain invariants, pure functions; `test_credits_properties.py` = hypothesis ledger/state-machine sequences; `test_skill_freshness.py` = `.cursor/skills` drift guard (paths, `path:symbol`, `make` targets, queue names, media whitelists) |
| `back/tests/integration/` | `TestClient` vs `/v1`, incl. admin authz/audit |
| `back/tests/concurrency/` | real threads + independent connections; `conftest.py` has `race()` / `run_in_parallel()` |
| `back/tests/conftest.py` | fixtures `db` (rollback), `committed_db` (commit + `truncate_all`), `client`, `author`/`remixer`/`admin`/`reviewer`/`operator`/`catalog_owner`, `make_user`, `fake_media_catalog`; autouse guards |
| `back/tests/factories.py` | thin builders `make_work` / `make_job` |
| `back/tests/fake_llm_gateway.py` | deterministic LLM fake |
| `back/tests/fake_providers.py` | deterministic media providers; injected by `fake_provider_catalog.py` |
| `back/tests/llm_catalog.py` | `seed_test_llm_catalog` — endpoint + default agent bindings |
| `back/tests/network_guard.py` | loopback-only network guard |
| `back/tests/memory_storage.py` | in-memory object store behind `app.storage.s3` |
| `front/playwright.config.ts` | projects `setup`/`e2e`/`a11y`/`a11y-mobile`/`visual-qa`, `workers: 1`, `webServer` on `PLAYWRIGHT_PORT` (default 3100) |
| `front/e2e/` | `setup/auth.setup.ts`, `flows/{admin,canvas,consumer,editor}.spec.ts`, `a11y.spec.ts`, `visual.spec.ts`, `support/` (session/axe/theme/fixtures) |
| `back/app/scripts/e2e_fixtures.py` | `make e2e-fixtures`: works chain/paid work/paid skill/draft/failed job the specs walk; writes the gitignored manifest `e2e/.fixtures.json` (under `front/`), read via `front/e2e/support/fixtures.ts` |
| `front/vitest.config.ts` | vitest (jsdom); `src/**/*.test.ts(x)` beside sources, run by `npm test` only |

## Invariants

1. Every test gets the fake LLM gateway (autouse). Opt out only with `@pytest.mark.live` (real call; excluded by `-m "not live"`) or `@pytest.mark.real_gateway_seams` (real client logic, mocked transport). Markers: `back/pyproject.toml`.
2. No real storage/network: `conftest.py` pins `STORAGE_BACKEND=minio` and blanks `COS_*` before app import; `_memory_storage` swaps the store (patch `app.storage.s3.get_backend`, not `app.storage.factory.get_backend`); `_block_outbound_network` allows loopback only. `@pytest.mark.real_storage` opts out of the memory store.
3. Real Postgres + Redis: session `engine` runs `drop_all`/`create_all` on `TEST_DATABASE_URL` (`zaolang_test`; schema from models, not Alembic — `make migrate` is the migration check); `_clear_redis_state` deletes `rl:*`/`llmfo:*`/`mediafo:*`/… around every test. Concurrent runs (other worktrees) need their own scratch `TEST_DATABASE_URL` and a non-0 `REDIS_URL` db, else `DeadlockDetected` at setup or rate-limit tests flake.
4. Anything that can hit `IntegrityError` (and all property tests) uses `committed_db`: `credits.service._apply` rolls back the whole session, wiping fixture users.
5. Hypothesis: `suppress_health_check=[HealthCheck.function_scoped_fixture]`, isolate per example (SAVEPOINT or nonce keys); generated text excludes control chars and surrogates.
6. Concurrency: no rollback session; each worker ends its own transaction (`race()` rolls back before re-raise); every session sets `lock_timeout` 5s so deadlocks fail, not hang. `run_in_parallel` returns exceptions; assert exactly one winner and that the loser failed for a concurrency reason (`Conflict`/`InsufficientCredits`/`SQLAlchemyError`).
7. Playwright reuses sessions because `/v1/auth/login` is limited to 10/5 min (`auth_attempt` in `back/app/api/rate_limit.py`). `setup` signs in five accounts into `e2e/.auth/*.json`; each extra stored session costs budget, and two overlapping runs share it. Anonymous tests set `storageState: { cookies: [], origins: [] }`.
8. `baseURL` uses `localhost`, not `127.0.0.1` (admin cookie is `SameSite=Strict`); backend `CORS_ORIGINS` allows only 3000 and 3100. `reuseExistingServer` silently tests whatever already listens on `PLAYWRIGHT_PORT` — from a second checkout use `PLAYWRIGHT_PORT=3000` or `PLAYWRIGHT_BASE_URL`.
9. `watchForPageErrors` allowlist (`EXPECTED_FAILURES` in `front/e2e/support/session.ts`: session-probe 401s, SSE `sse_quota` 429s) stays minimal; spec-specific noise gets a local filter (e.g. `isMissingSeedMedia` in `canvas.spec.ts`, 404s only).
10. Visual suite asserts mechanics only (no horizontal overflow at three viewports, no console errors, reduced-motion ≤50ms); screenshots are for humans. a11y scans both themes incl. `color-contrast`; `expectNoAxeViolations` first waits (≤5s) for finite animations/transitions to end — fix flaky contrast there, never with sleeps or a disabled rule.
11. Desktop-only routes (drama editor, canvas) stay out of `a11y-mobile` and `PUBLIC_PAGES`.
12. `front/.env.local` needs `ALLOW_LOCAL_IMAGE_HOSTS=1` with MinIO (Next blocks private-IP image hosts); never in production.
13. Spec data comes from `make e2e-fixtures`, never `make seed` (accounts + system defaults only). The script is create-once (`idempotency_key="e2e-fixture:<slug>"`) plus a per-run reset of what specs mutate (author's like, buyer balance floor); purchases are permanent, so an owned paid work is withdrawn and a fresh one published. A spec that mutates other state adds its reset there. Specs call `fixtures()` (missing manifest fails with the fix) and use `FIXTURE_TITLES`; failed-job rows mirror the real worker (`async_task_poll_budget_exceeded` / `PROVIDER_TIMEOUT`).

## Recipes

**Add a concurrency test**: build sessions via the concurrency `conftest.py`, wrap each worker in `race()`, run with `run_in_parallel()`, assert one winner + typed loser errors.

**Cover a new module**: unit (domain rules), integration (each endpoint + unauthorized access), concurrency (any race), vitest (pure helpers), one e2e flow.

## Verify

```bash
make test-back                                   # pytest -m "not live" with coverage
cd back && conda run -n zaolang pytest tests/unit/test_network_guard.py tests/unit/test_skill_freshness.py -q
cd front && npm test                             # vitest (not in make check)
make up && make migrate && make seed && make dev-api   # e2e prerequisites (API on 3001)
make test-e2e && make test-a11y && make qa-visual       # test-e2e / qa-visual run `make e2e-fixtures` first
```

`PLAYWRIGHT_BASE_URL` targets a running front (disables `webServer`). New test: break the invariant once, confirm red.
