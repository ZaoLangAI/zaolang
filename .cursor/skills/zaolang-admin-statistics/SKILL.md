---
name: zaolang-admin-statistics
description: 造浪后台数据统计中心：按 UTC 日 SQL 聚合的任务/供应商/智能体/积分/内容/用户增长 timeseries，以及仍走旧快照接口的系统健康与存储用量。Use when changing /admin/statistics, /v1/admin/statistics/*, daily timeseries aggregation, empty-day zero-fill, or the recharts trend charts.
disable-model-invocation: true
---

# 后台数据统计中心

快照接口回答「此刻怎样」，本模块补「按日怎么走」。不要为统计新建事实表，也不要把全表拉进 Python 再分组。

## 关键路径

| 路径 | 内容 |
| --- | --- |
| `back/app/domain/statistics/service.py` | `jobs_daily` / `providers_daily` / `agents_daily` / `credits_daily` / `content_daily` / `users_growth`：`date_trunc(..., 'UTC')` + `group_by`，窗口内空日补零 |
| `back/app/api/v1/admin/statistics.py` | `/v1/admin/statistics/{jobs,providers,agents,credits,content,users}`，`days` 1–180，`Viewer` + `AdminRead` |
| `back/app/api/schemas/admin.py` | `*TimeseriesView` / `*DailyPoint` |
| `front/src/app/[locale]/(admin)/admin/(console)/statistics/page.tsx` | RSC 一次拉齐快照 + 默认 30 日序列，单接口失败用 `adminFetchOrNull` 降级为空 |
| `front/src/components/admin/statistics/` | 七个 tab：`overview` / `jobs` / `providers` / `credits` / `content` / `users` / `system`；`recharts` 只在此模块 |
| `back/tests/integration/test_admin_statistics.py` | 窗口补零、viewer 可读、越权拒绝 |

快照仍走旧接口，不要搬进 `statistics.py`：

- `/v1/admin/providers/stats`
- `/v1/admin/agent-runs/usage`
- `/v1/admin/jobs/stats`
- `/v1/admin/credits/reconciliation`
- `/v1/admin/health`
- `/v1/admin/storage/usage`

外壳、RBAC、限流见 `zaolang-admin-console`。运维域清单见 `zaolang-admin-ops`。

## 不可破坏的不变量

1. **聚合在 SQL 里完成。** `date_trunc` + `group_by`，禁止 `session.scalars(select(整表)).all()` 再在 Python 里按日分组。后台数据量会长。
2. **日历日是 UTC。** `_day_bucket` 必须传 `'UTC'`。裸 `date_trunc('day', col)` 跟会话时区走，会把跨日点算错。
3. **空日补零，不省略。** 窗口是闭区间 `[today - days + 1, today]`，无活动的日子仍返回 0。图表跳过空日会把冷清读成缺数。
4. **只读、不写事实表。** 统计读现有 `GenerationJob` / `ProviderAttempt` / `AgentRun` / `CreditLedgerEntry` / `Work` / `LineageEdge` / `User`。不要为趋势新建汇总表或物化视图，除非产品明确要求且另开迁移。
5. **viewer 可看、不可改。** 路由是 `Viewer` + `AdminRead`。不要在本模块加写接口或调账入口。
6. **单接口失败页面仍渲染。** RSC 用 `adminFetchOrNull`；网络/5xx 降为空序列或空快照，不要让整页 500。
7. **`recharts` 不出本目录。** C 端与其它后台页继续用手写组件，避免主题令牌漂移。
8. **窗口上限 180 天。** 查询参数 `ge=1, le=180`。前端档位是 7 / 30 / 90；不要默默把默认窗口拉到 180。

## 改造切入点

- **加一条日序列**：`service.py` 写 `*_daily`（复用 `_window` / `_day_bucket`，空日补零）→ schema 加 `*DailyPoint` / `*TimeseriesView` → `statistics.py` 加 `GET` → 前端加 panel 或在现有 tab 加系列 → `test_admin_statistics.py` 覆盖补零与越权。
- **加一个快照卡片**：继续打旧运维接口，不要为「此刻」再写一份聚合。
- **改口径**：先改 SQL 与测试，再改三语文案 `adminStatistics.*`。不要只改图表标签。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_statistics.py -v
```

手工路径：`make seed` 后以 viewer 打开 `/admin/statistics`，七个 tab 都能出数；把 API 停掉再刷新，页面应是空图而不是白屏。
