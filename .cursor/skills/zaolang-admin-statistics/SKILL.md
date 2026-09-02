---
name: zaolang-admin-statistics
description: Admin data-statistics center — UTC-day SQL-aggregated job/provider/agent/cost/credit/content/user-growth timeseries (incl. the model-spend cost breakdown by provider and model), plus job/provider/agent/credit reconciliation and system-health snapshots still served by the older snapshot endpoints. Use when changing /admin/statistics, /v1/admin/statistics/*, daily timeseries aggregation, empty-day zero-fill, or the shared recharts trend-chart wrappers.
disable-model-invocation: true
---

# Admin Data-Statistics Center

The snapshot endpoints answer "how does it look right now"; this module answers "how did it trend day by day." Don't create new fact tables for statistics, and don't pull whole tables into Python to group them.

## Key Paths

| Path | Contents |
| --- | --- |
| `back/app/domain/statistics/service.py` | `jobs_daily` / `providers_daily` / `agents_daily` / `credits_daily` / `content_daily` / `users_growth`, plus the cost family `cost_daily` (daily model spend in micro-USD, LLM `AgentRun.cost_micro_usd` vs. media `ProviderAttempt.cost_micro_usd`) / `cost_by_provider_daily` / `cost_by_model`: `date_trunc(..., 'UTC')` + `group_by`, zero-filling empty days inside the window |
| `back/app/api/v1/admin/statistics.py` | `/v1/admin/statistics/{jobs,providers,agents,costs,credits,content,users}` + `/statistics/costs/breakdown` (per-provider daily series + per-model totals), `days` 1–180, `Viewer` + `AdminRead` |
| `back/app/api/schemas/admin.py` | `*TimeseriesView` / `*DailyPoint` |
| `front/src/app/[locale]/(admin)/admin/(console)/statistics/page.tsx` | RSC fetching snapshots + a default 30-day series in one pass; falls back gracefully via `adminFetchOrNull` if a single endpoint fails |
| `front/src/components/admin/statistics/` | `statistics-workspace.tsx` with seven tabs: `overview` / `jobs` / `providers` / `costs` / `credits` / `content` / `users` (the agents series lives inside `providers-agents-panel.tsx` on the providers tab; `costs-panel.tsx` renders `CostsPanel` from `/costs` + `/costs/breakdown`). Panels draw through the shared `@/components/charts/trend-chart` wrapper rather than importing `recharts` directly |
| `front/src/components/charts/` | `trend-chart.tsx` (`TrendChart`, the only `recharts` line-chart wrapper), `bar-comparison-chart.tsx`, `channel-share-pie-chart.tsx` — shared with the consumer `features/drama-dashboard/*` analytics pages; theme colors come from `--color-*` tokens |
| `back/tests/integration/test_admin_statistics.py` | window zero-fill, viewer readability, unauthorized-access rejection |

Snapshots still go through the older endpoints — don't move them into `statistics.py`:

- `/v1/admin/providers/stats`
- `/v1/admin/agent-runs/usage`
- `/v1/admin/jobs/stats`
- `/v1/admin/credits/reconciliation`
- `/v1/admin/health` (overview queue backlog)

Shell, RBAC, and rate limiting: see `zaolang-admin-console`. The full admin-ops domain list: see `zaolang-admin-ops`.

## Invariants

1. **Aggregation happens in SQL.** `date_trunc` + `group_by` — never `session.scalars(select(whole_table)).all()` followed by grouping in Python. Admin data volume only grows.
2. **Calendar days are UTC.** `_day_bucket` must pass `'UTC'` explicitly. A bare `date_trunc('day', col)` follows the session's timezone and miscounts points near a day boundary.
3. **Empty days are zero-filled, never omitted.** The window is the closed interval `[today - days + 1, today]`; days with no activity still return 0. Skipping empty days on a chart reads as missing data, not as quiet.
4. **Read-only — never writes fact tables.** Statistics reads existing `GenerationJob` / `ProviderAttempt` / `AgentRun` / `CreditLedgerEntry` / `Work` / `LineageEdge` / `User`. Don't create summary tables or materialized views for trends unless the product explicitly requires it, via a separate migration.
5. **Viewer can read, cannot write.** Routes require `Viewer` + `AdminRead`. Don't add a write endpoint or adjustment entry point in this module.
6. **A single failing endpoint must still let the page render.** The RSC uses `adminFetchOrNull`; a network error or 5xx degrades to an empty series or empty snapshot rather than a full-page 500.
7. **`recharts` is reached only through the shared wrappers in `front/src/components/charts/`** (`TrendChart` / `BarComparisonChart` / `ChannelSharePieChart`). Neither an admin panel nor a consumer page imports `recharts` directly — colors are bound to `--color-*` tokens inside the wrappers, so a new chart type means a new wrapper there, not an inline `<LineChart>`; that is what keeps the admin and `drama-dashboard` charts from drifting off the theme.
8. **The window caps at 180 days.** The query param is `ge=1, le=180`. Frontend presets are 7 / 30 / 90 — don't silently push the default window to 180.

## Extension Points

- **Add a daily series**: write `*_daily` in `service.py` (reuse `_window` / `_day_bucket`, zero-fill empty days) → add `*DailyPoint` / `*TimeseriesView` to the schema → add the `GET` route in `statistics.py` → fetch it in `statistics-workspace.tsx` and add a panel or a series on an existing tab (via `TrendChart`) → cover zero-fill and unauthorized access in `test_admin_statistics.py`. `cost_daily` / `cost_by_provider_daily` / `cost_by_model` + `CostsPanel` are the worked example of a series plus a breakdown endpoint.
- **Add a snapshot card**: keep hitting the older admin-ops endpoint — don't write a second aggregation for "right now."
- **Change a metric's definition**: change the SQL and tests first, then the trilingual copy `adminStatistics.*`. Don't just relabel the chart.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_statistics.py -v
```

Manual path: after `make seed`, open `/admin/statistics` as viewer — all seven tabs should show data; stop the API and reload — the page should show empty charts, not a blank screen.
