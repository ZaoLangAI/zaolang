---
name: zaolang-admin-statistics
description: Admin data-statistics center — UTC-day SQL-aggregated job/provider/agent/credit/content/user-growth timeseries, plus job/provider/agent/credit reconciliation and system-health snapshots still served by the older snapshot endpoints. Use when changing /admin/statistics, /v1/admin/statistics/*, daily timeseries aggregation, empty-day zero-fill, or the recharts trend charts.
disable-model-invocation: true
---

# Admin Data-Statistics Center

The snapshot endpoints answer "how does it look right now"; this module answers "how did it trend day by day." Don't create new fact tables for statistics, and don't pull whole tables into Python to group them.

## Key Paths

| Path | Contents |
| --- | --- |
| `back/app/domain/statistics/service.py` | `jobs_daily` / `providers_daily` / `agents_daily` / `credits_daily` / `content_daily` / `users_growth`: `date_trunc(..., 'UTC')` + `group_by`, zero-filling empty days inside the window |
| `back/app/api/v1/admin/statistics.py` | `/v1/admin/statistics/{jobs,providers,agents,credits,content,users}`, `days` 1–180, `Viewer` + `AdminRead` |
| `back/app/api/schemas/admin.py` | `*TimeseriesView` / `*DailyPoint` |
| `front/src/app/[locale]/(admin)/admin/(console)/statistics/page.tsx` | RSC fetching snapshots + a default 30-day series in one pass; falls back gracefully via `adminFetchOrNull` if a single endpoint fails |
| `front/src/components/admin/statistics/` | six tabs: `overview` / `jobs` / `providers` / `credits` / `content` / `users`; `recharts` is used only in this module |
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
7. **`recharts` stays inside this directory.** The consumer app and other admin pages keep their hand-written components to avoid theme-token drift.
8. **The window caps at 180 days.** The query param is `ge=1, le=180`. Frontend presets are 7 / 30 / 90 — don't silently push the default window to 180.

## Extension Points

- **Add a daily series**: write `*_daily` in `service.py` (reuse `_window` / `_day_bucket`, zero-fill empty days) → add `*DailyPoint` / `*TimeseriesView` to the schema → add the `GET` route in `statistics.py` → add a panel or a series on an existing tab → cover zero-fill and unauthorized access in `test_admin_statistics.py`.
- **Add a snapshot card**: keep hitting the older admin-ops endpoint — don't write a second aggregation for "right now."
- **Change a metric's definition**: change the SQL and tests first, then the trilingual copy `adminStatistics.*`. Don't just relabel the chart.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_statistics.py -v
```

Manual path: after `make seed`, open `/admin/statistics` as viewer — all six tabs should show data; stop the API and reload — the page should show empty charts, not a blank screen.
