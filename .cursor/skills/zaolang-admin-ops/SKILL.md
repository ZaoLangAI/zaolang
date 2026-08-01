---
name: zaolang-admin-ops
description: 造浪后台十个运维域的接口与页面：系统健康、任务运维、供应商与路由、智能体运维、内容审核与举报、用户与权限、积分与对账、配置中心、数据运维、审计与公告。Use when adding or changing a back-office operations screen or endpoint — health probes, job replay/terminate, provider stats, agent runs, moderation queue, reports, user suspension, credit adjustment, reconciliation, backups, storage lifecycle, audit search, or announcements.
disable-model-invocation: true
---

# 后台十个运维域

安全边界、RBAC、外壳与组件族见 `zaolang-admin-console`。本 skill 讲每个域**做什么、数据从哪来、不能怎么改**。

## 域 → 接口 → 页面

| 域 | 后端 | 前端 |
| --- | --- | --- |
| 系统健康 | `admin/observability.py: /health` | `components/admin/health/health-cards.tsx` |
| 任务运维 | `admin/jobs.py`: `/jobs`、`/jobs/{id}`、`/terminate`、`/requeue`、`/events` | `admin/jobs/jobs-console.tsx` |
| 供应商与路由 | `observability.py`: `/providers/stats`、`/jobs/{id}/routing` | `admin/jobs/routing-replay-table.tsx`、`admin/providers/routing-weights-panel.tsx` |
| 智能体运维 | `observability.py`: `/agent-runs`、`/agent-runs/usage`、`/workflow` | `admin/agents/agent-runs-table.tsx` |
| 内容运维 | `admin/content.py`: `/moderation/queue`(+`claim`/`decide`)、`/reports`、`/works/{id}/tombstone|hide|restore`、`/fingerprints/duplicates` | `admin/moderation/*`、`admin/reports/reports-console.tsx` |
| 用户与权限 | `admin/users.py`: `/users`、`/suspend`、`/unsuspend`、`/roles`、`/data-requests` | `admin/users/*` |
| 积分运维 | `admin/ledger.py`: `/credits/ledger`、`/credits/reconciliation`、`/credits/dangling`、`/users/{id}/credits/adjust` | `admin/credits/*` |
| 配置运维 | `admin/config.py`（见 `zaolang-platform-config`） | `admin/config/*` |
| 数据运维 | `admin/data.py`: `/storage/usage`、`/storage/lifecycle`、`/backups`、`/seed` | `admin/data/*` |
| 审计与公告 | `admin/config.py`: `/audit-logs`、`/announcements` | `admin/audit/audit-console.tsx`、`admin/announcements/*` |

## 不可破坏的不变量

1. **健康探针只报告，不修复**。它检查 Postgres / Redis / MinIO / Celery 存活、五个队列积压与消费速率、Alembic 版本、**LLM 网关连通性与当前运行模式**。探测查询必须包在 `begin_nested()` 里——一个失败的探针污染事务会让整页 500。
2. **强制终止任务也走状态机**（`state_machine.transition`），不是直接 UPDATE `status`。终止后必须释放预扣，否则制造悬挂预扣。
3. **卡死重放不制造第二次扣费**：`requeue` 复用原任务与原预扣，不新建 job、不重新 reserve。
4. **全链路回放是只读的**：`JobEvent` + `ProviderAttempt` + 路由候选决策，展示即可，不允许「顺手改一下」。
5. **`ProviderStat` 是累计计数器**，新建行必须显式初始化为 0（`attempts` / `successes` / `total_latency_ms` / `total_cost_minor`）——依赖列默认值会在 flush 前拿到 `None` 并在 `+=` 时炸。
6. **审核决定要留人工痕迹**：`claim` 再 `decide`，决定人、时间、理由都记。自动审核结果与人工确认是两条不同记录，不要相互覆盖。
7. **墓碑/隐藏/恢复三态语义固定**：隐藏可恢复，墓碑是终态（见 `zaolang-domain-licensing-lineage`）。
8. **人工调账只追加**，强制理由 + 二次确认 + 审计（见 `zaolang-credits-billing`）。
9. **对账与悬挂预扣是两个不同指标**，数字不一致是设计使然，不要「对齐」。
10. **seed / reset 在生产环境必须拒绝**，有专门用例守着。备份恢复要留 `BackupRecord`。
11. **公告分站内与维护两类**，维护公告要能在 C 端顶部醒目展示。

## 改造切入点

- **加一个健康探针**：`observability.py` 的 `/health` 加一项 → `health-cards.tsx` 加卡片 → 探测失败必须降级为「未知」而不是抛错。
- **加一个统计口径**：优先在 SQL 里聚合（后台数据量会长），不要拉全表到 Python。列表统一游标分页。
- **加一个批量操作**：后端接受 ID 列表并**逐条走同一个领域函数**（保持单条的全部校验与审计），不要为了性能写一条大 UPDATE。
- **加一个运维页**：见 `zaolang-admin-console` 的四步清单。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/integration/test_admin_ops_runtime.py tests/integration/test_admin_ops_domain.py tests/integration/test_admin_ops_platform.py -v
make test-e2e
```

手工路径：`make seed` 后进 `/admin` —— 系统健康四个依赖全绿、任务台能看到卡死与失败的任务、积分台能看到那条悬挂预扣、用户台能搜到被封禁的 `driftwood`、智能体台能看到一次降级记录。种子数据是专门为这些页面准备的。
