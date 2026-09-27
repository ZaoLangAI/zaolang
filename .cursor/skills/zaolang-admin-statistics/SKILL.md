---
name: zaolang-admin-statistics
description: Admin statistics center — UTC-day SQL timeseries for jobs, providers, agents, costs, credits, content, users. Use when changing /admin/statistics, /v1/admin/statistics/*, back/app/domain/statistics, zero-fill, or shared recharts wrappers in front/src/components/charts.
---

# Admin Statistics Center

**Scope**: day-by-day trends (`/v1/admin/statistics/*`) and the shared chart wrappers. "Right now" snapshots stay on older endpoints (`/providers/stats`, `/agent-runs/usage`, `/jobs/stats`, `/credits/reconciliation`, `/health`).
Not here → `zaolang-admin-ops` (snapshots), `zaolang-admin-console` (RBAC), `zaolang-theming` (tokens).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/statistics/service.py` | `*_daily`, `cost_by_provider_daily`, `cost_by_model`, `users_growth`; helpers `_window`, `_day_bucket` |
| `back/app/api/v1/admin/statistics.py` | routes, `days` 1–180 (default 30), `Viewer` + `AdminRead` |
| `back/app/api/schemas/admin.py` | `*TimeseriesView` / `*DailyPoint` |
| `front/src/app/[locale]/(admin)/admin/(console)/statistics/page.tsx` | RSC: snapshots + 30-day series via `adminFetchOrNull` |
| `front/src/components/admin/statistics/` | `statistics-workspace.tsx` (`TABS`, `RANGES` 7/30/90) + one panel per tab |
| `front/src/components/charts/` | `trend-chart.tsx`, `bar-comparison-chart.tsx`, `channel-share-pie-chart.tsx`; also used by `front/src/features/drama-dashboard/` series analytics |

## Invariants

1. Aggregate in SQL (`date_trunc` + `group_by`); never load a whole table into Python to group.
2. Buckets are UTC days: `_day_bucket` passes `'UTC'` explicitly; bare `date_trunc('day', col)` follows session TZ.
3. Zero-fill: window is `[today - days + 1, today]`, empty days return 0, never omitted.
4. Read-only over existing fact tables (`GenerationJob`, `ProviderAttempt`, `AgentRun`, `CreditLedgerEntry`, `Work`, `LineageEdge`, `User`); no summary tables/materialized views.
5. Viewer-readable, no write endpoints in this module.
6. One failing endpoint degrades to an empty series/card (`adminFetchOrNull`), never a page 500.
7. `recharts` only inside `front/src/components/charts/` wrappers (colors bound to `--color-*`); admin panels and drama-dashboard never import it directly — new chart type = new wrapper.
8. Cost series are micro-USD: LLM `AgentRun.cost_micro_usd` vs media `ProviderAttempt.cost_micro_usd`.

## Recipes

**Add a daily series**: `*_daily` in `service.py` (reuse `_window`/`_day_bucket`, zero-fill) → `*DailyPoint`/`*TimeseriesView` schema → route in `statistics.py` → panel/series in `statistics-workspace.tsx` via `TrendChart` → zero-fill + auth tests. Worked example: `cost_daily` + `/costs/breakdown` + `costs-panel.tsx`.

**Change a metric definition**: SQL + tests first, then `adminStatistics.*` copy.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_statistics.py -v
cd front && npm run typecheck
```
