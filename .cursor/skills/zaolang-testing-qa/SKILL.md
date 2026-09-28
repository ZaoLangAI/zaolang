---
name: zaolang-testing-qa
description: Test system — pytest layers (unit/hypothesis/integration/concurrency), conftest guards and fixtures, Playwright e2e/a11y/visual suites, vitest. Use when writing or fixing tests, adding property or concurrency tests, debugging flaky/hanging tests, or running e2e/a11y/visual QA.
---

# Testing & QA

**Scope**: how tests are layered, isolated and run. Not here → `zaolang-ci-release` (`make check` gate, pre-commit), `zaolang-local-env` (stack, seed accounts).

## Key Paths

| Path | What |
| --- | --- |
| `back/tests/unit/` | domain invariants, pure functions; `test_credits_properties.py` = hypothesis ledger/state-machine sequences |
| `back/tests/integration/` | `TestClient` vs `/v1`, incl. admin authz/audit |
| `back/tests/concurrency/` | real threads + independent connections; `conftest.py` has `race()` / `run_in_parallel()` |
| `back/tests/conftest.py` | fixtures `db` (rollback), `committed_db` (commit + `truncate_all`), `client`, `author`/`admin`/`reviewer`/`operator`, `make_user`; autouse guards |
| `back/tests/fake_llm_gateway.py` | deterministic LLM fake |
| `back/tests/fake_providers.py` | deterministic media providers; injected by `fake_provider_catalog.py` |
| `back/tests/llm_catalog.py` | `seed_test_llm_catalog` — endpoint + default agent bindings |
| `back/tests/network_guard.py` | loopback-only network guard |
| `back/tests/memory_storage.py` | in-memory object store behind `app.storage.s3` |
| `front/playwright.config.ts` | projects, `workers: 1`, `webServer` on 3100 — read it for the project matrix |
| `front/e2e/` | `setup/auth.setup.ts`, `flows/*.spec.ts`, `a11y.spec.ts`, `visual.spec.ts`, `support/` (session/axe/theme/fixtures) |
| `back/app/scripts/e2e_fixtures.py` | `make e2e-fixtures`: works/paid skill/draft/failed job the specs walk; writes `front/e2e/.fixtures.json`, read via `front/e2e/support/fixtures.ts` |
| `front/vitest.config.ts` | vitest; `*.test.ts(x)` beside sources, run by `npm test` only |

## Invariants

1. Every test gets the fake LLM gateway (autouse). Opt out only with `@pytest.mark.live` (real call; excluded by `-m "not live"`) or `@pytest.mark.real_gateway_seams` (real client logic, mocked transport). Markers: `back/pyproject.toml`.
2. No real storage/network: `conftest.py` pins `STORAGE_BACKEND=minio` and blanks `COS_*` before app import; `_memory_storage` swaps the store (patch `app.storage.s3.get_backend`, not `app.storage.factory.get_backend`); `_block_outbound_network` allows loopback only. `@pytest.mark.real_storage` opts out of the memory store.
3. Anything that can hit `IntegrityError` (and all property tests) uses `committed_db`: `credits.service._apply` rolls back the whole session, wiping fixture users.
4. Hypothesis: `suppress_health_check=[HealthCheck.function_scoped_fixture]`, isolate per example (SAVEPOINT or nonce keys); generated text excludes control chars and surrogates.
5. Concurrency: no rollback session; each worker ends its own transaction (`race()` rolls back before re-raise); every session sets `lock_timeout` 5s so deadlocks fail, not hang. `run_in_parallel` returns exceptions; assert exactly one winner and that the loser failed for a concurrency reason (`Conflict`/`InsufficientCredits`/`SQLAlchemyError`).
6. Playwright reuses sessions because `/v1/auth/login` is limited to 10/5 min (`auth_attempt` in `back/app/api/rate_limit.py`). `setup` signs in five accounts into `e2e/.auth/*.json`; each extra stored session costs budget. Anonymous tests set `storageState: { cookies: [], origins: [] }`.
7. `baseURL` uses `localhost`, not `127.0.0.1` (admin cookie is `SameSite=Strict`); backend `CORS_ORIGINS` must include 3000 and 3100.
8. `watchForPageErrors` allowlist (`EXPECTED_FAILURES` in `front/e2e/support/session.ts`) stays minimal; spec-specific noise gets a local filter (e.g. `isMissingSeedMedia` in `canvas.spec.ts`).
9. Visual suite asserts mechanics only (no horizontal overflow at three viewports, no console errors, reduced-motion ≤50ms); screenshots are for humans. a11y scans both themes incl. `color-contrast`.
10. Desktop-only routes (drama editor, canvas) stay out of `a11y-mobile` and `PUBLIC_PAGES`.
11. `front/.env.local` needs `ALLOW_LOCAL_IMAGE_HOSTS=1` with MinIO (Next blocks private-IP image hosts); never in production.
12. Spec data comes from `make e2e-fixtures`, never `make seed` (seed stays accounts + system defaults only). The script is create-once (marker `idempotency_key="e2e-fixture:<slug>"`) plus a per-run reset of what specs mutate (the author's like, the buyer's balance floor). Purchases are never undone — the ledger key is one per buyer and subject — so a paid work the buyer owns is withdrawn and a new generation published. A spec that changes other state must add its reset there. Specs call `fixtures()` so a missing manifest fails with the fix, and reference titles via `FIXTURE_TITLES`; failed-job fixtures mirror what the real worker writes (`async_task_poll_budget_exceeded` / `PROVIDER_TIMEOUT`), not invented signals.

## Recipes

**Add a concurrency test**: build sessions via the concurrency `conftest.py`, wrap each worker in `race()`, run with `run_in_parallel()`, assert one winner + typed loser errors.

**Cover a new module**: unit (domain rules), integration (each endpoint + unauthorized access), concurrency (any race), vitest (pure helpers), one e2e flow.

## Verify

```bash
make test-back                                   # pytest -m "not live" with coverage
cd back && conda run -n zaolang pytest tests/unit/test_network_guard.py -v
cd front && npm test                             # vitest (not in make check)
make up && make migrate && make seed && make dev-api   # e2e prerequisites (API on 3001)
make test-e2e && make test-a11y && make qa-visual       # test-e2e / qa-visual run `make e2e-fixtures` first
```

`PLAYWRIGHT_BASE_URL` targets a running front (disables `webServer`). New test: break the invariant once, confirm red.
