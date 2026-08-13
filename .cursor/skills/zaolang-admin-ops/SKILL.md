---
name: zaolang-admin-ops
description: 造浪后台运维域的接口与页面：系统健康、任务运维、生成供应商与工作流、数据统计中心、智能体（AgentSkill）、内容审核与举报、技能库、用户与权限、积分与兑换码、配置中心、数据运维、日志中心与公告。
disable-model-invocation: true
---

# 后台运维域

安全边界、RBAC、外壳与组件族见 `zaolang-admin-console`。本 skill 讲每个域**做什么、数据从哪来、不能怎么改**。

## 域 → 接口 → 页面

| 域 | 后端 | 前端 |
| --- | --- | --- |
| 系统健康 | `admin/observability.py: /health` | `components/admin/health/health-cards.tsx` |
| 任务运维 | `admin/jobs.py`: `/jobs`、`/jobs/{id}`、`/jobs/{id}/stream`（后台 SSE，payload 带 `node_id`）、`/jobs/{id}/input-request`、`/jobs/{id}/answer`（沙盒与 C 端共用的规划/`copy_generate` 追问，C 端路径对 `origin=sandbox` 404）、`/terminate`、`/requeue`、`/events`（支持 `created_after`/`created_before`）、`/jobs/stats`（按状态/操作分组计数 + 平均完成耗时，声明在 `/jobs/{job_id}` 之前避免路径冲突）。列表可按 `origin` 筛沙盒试跑。列表/详情不再吐裸 id：`AdminJobSummary` 带 `user_display_name`/`user_handle`/`provider_label`/`stuck`/`origin`，`AgentRunView` 带 `agent_display_name` 与 `input_json`/`output_json`，`JobEventView`/`AgentRunView` 带 `node_id`（真正执行的图节点，见 `zaolang-generation-jobs` 不变量 #13），`AdminJobDetail` 带 `async_task: AsyncProviderTaskView | None`（在途外部供应商任务的节点/供应商/轮询次数/截止时间）以及产出 `preview_url`/`mime_type`；`admin/logs.py::/logs` 新增可选 `job_id` 参数，命中时对审计与 SystemLog 两路都按该任务过滤，合并返回 | `admin/jobs/jobs-console.tsx`（含 origin 徽章、「仅沙盒」筛选、`awaiting_input` 追问表单、`stepper` / `duration-bars` 与路由候选对比与 LLM `reason` 说明、异步供应商任务小节、关联日志小节） |
| 智能体 | `admin/agent_skills.py`: AgentProfile 手动供应商/模型绑定、采样参数、Prompt 版本 | `/admin/agents`；模型关系不在配置中心或模型页维护 |
| 供应商与工作流 | `admin/llm_providers.py`: 模型管理目录（`general` 有模型列表/主备/并发；`media` 有单模型/接口协议/模态/超时）。`protocol` 是 HTTP 契约标准名：已实现 OpenAI（图/音频）与 MiniMax（视频），ComfyUI / Google Gemini / DashScope / 火山方舟 / 可灵在目录里但 option 禁用，upsert 422，禁止静默回退 OpenAI。构造 `LlmProviderEndpoint(...)` 必须显式传 `protocol` 并写入 view / audit。`admin/workflow_templates.py`: 工作流模板 DAG；`POST .../sandbox-run` 提交真实 `GenerationJob(origin=sandbox)`（跳过积分，草稿图走 `graph_override_json`），202 `{job_id}`；`GET .../sandbox-runs` 按当前 operation 列出历史试跑（`WorkflowSandboxRunSummary`：`prompt_excerpt` / `used_draft` / 操作人名称，不含 `preview_url`）。沙盒试跑是弹窗，右侧流式消费 `/jobs/{id}/stream`（节点日志 + 最终预览）；`awaiting_input` 时右侧呈现规划/`copy_generate` 追问并 `POST /jobs/{id}/answer` 续跑。`observability.py`: `/jobs/{id}/routing` | `admin/models/llm-providers-panel.tsx`（通用与媒体分区；媒体编辑器「接口协议」下拉，切协议时清掉不兼容模态）、`routing-replay-table.tsx`（LLM 选型理由 + 候选成功率/延迟/成本）、`/admin/routing` 页只剩 `WorkflowEditor`（无权重面板，选谁由 `intent_router` 判定，见 `zaolang-agent-gateway`）；`workflow-sandbox-dialog.tsx` 是试跑弹窗；`workflow-sandbox-history-panel.tsx` 是画布右侧的非模态抽屉，点选一条弹出详情弹窗回放（复用 `GET /jobs/{id}` 与 `SandboxRunInspector`） |
| 数据统计中心 | `observability.py`: `/providers/stats`（供应商统计）、`/agent-runs/usage`（智能体用量）；`admin/jobs.py`: `/jobs/stats`（任务吞吐）；`admin/ledger.py`: `/credits/reconciliation`（积分对账） | `/admin/statistics` 页，一站式聚合以上四类现有指标，不新增数据源 |
| 内容运维 | `admin/content.py`: `/moderation/queue`(+`claim`/`decide`/`detail`/`history`)、`/reports`、`/works/{id}/tombstone|hide|restore`。`generation_job` 队列项列表用 prompt 截断作标题、产出签名图作预览；详情 `ModerationJobDetailView`。对 `generation_job` 的 `decide` 只记 `ModerationResult`，不做 hide/tombstone（产出未发布） | `admin/moderation/*`、`admin/reports/reports-console.tsx` |
| 技能库运维 | `admin/skill_library.py`: 全局技能列表/下架/精选 | `admin/skill-library/skill-library-console.tsx` |
| 用户与权限 | `admin/users.py`: `/users`、`/suspend`、`/unsuspend`、`/roles`、`/data-requests` | `admin/users/*` |
| 积分运维 | `admin/ledger.py` + `admin/redemption.py`: 账本/对账/调账/兑换码 CRUD | `admin/credits/*`（含 `redemption-codes-panel.tsx`） |
| 配置运维 | `admin/config.py`（通用 API 排除 `llm_providers`） | `/admin/config` 只放 Feature Flag 与短视频；其他配置由业务页“刷新”右侧的配置按钮打开弹窗 |
| 数据运维 | `admin/data.py`: `/storage/usage`、`/storage/lifecycle`、`/backups`、`/seed` | `admin/data/*` |
| 日志中心 | `admin/logs.py`: `/logs`（审计 + SystemLog 聚合）；`admin/config.py`: `/audit-logs`（向后兼容） | `admin/audit/log-center-console.tsx`、`admin/announcements/*` |

## 不可破坏的不变量

1. **健康探针只报告，不修复**。它检查 Postgres / Redis / MinIO / Celery 存活、当前 7 个队列积压与消费速率、Alembic 版本、**LLM 网关连通性与当前运行模式**。队列真源是 `back/app/workers/celery_app.py:QUEUE_NAMES`，新增队列时同步健康页。探测查询必须包在 `begin_nested()` 里——一个失败的探针污染事务会让整页 500。
2. **强制终止任务也走状态机**（`state_machine.transition`），不是直接 UPDATE `status`。终止后必须释放预扣，否则制造悬挂预扣。**命中在途 `AsyncProviderTask` 时会在同一次请求内同步尝试 `async_tasks.cancel_upstream()` 通知供应商**，失败（catalogue 里找不到能力、`provider.cancel()` 报错或超时）也不阻断状态迁移，只落一条 `system_log.emit`；审计的 `after_json` 记 `upstream_cancel_attempted`/`upstream_cancel_succeeded` 供事后核对。
3. **卡死重放不制造第二次扣费**：`requeue` 复用原任务与原预扣，不新建 job、不重新 reserve。
4. **全链路回放是只读的**：`JobEvent` + `ProviderAttempt` + 路由候选决策，展示即可，不允许「顺手改一下」。
5. **`ProviderStat` 是累计计数器**，新建行必须显式初始化为 0（`attempts` / `successes` / `total_latency_ms` / `total_cost_minor`）——依赖列默认值会在 flush 前拿到 `None` 并在 `+=` 时炸。
6. **审核决定要留人工痕迹**：`claim` 再 `decide`，决定人、时间、理由都记。**拒绝 = hide（可撤销），tombstone 是单独的高危终态操作**，不要混为一谈。**`generation_job` 主体（含沙盒试跑）例外**：产出未发布，`decide` 只追加 `ModerationResult`，不要 hide/tombstone。
7. **墓碑/隐藏/恢复三态语义固定**：隐藏可 `restore`，墓碑是终态（见 `zaolang-domain-licensing-lineage`）。
8. **人工调账只追加**，强制理由 + 二次确认 + 审计（见 `zaolang-credits-billing`）。
9. **对账与悬挂预扣是两个不同指标**，数字不一致是设计使然，不要「对齐」。
10. **seed / reset 在生产环境必须拒绝**，有专门用例守着。备份恢复要留 `BackupRecord`。
11. **公告分站内与维护两类**，维护公告要能在 C 端顶部醒目展示。
12. **产品沙盒记入任务运维与内容审核，但不扣积分。** 见 `zaolang-generation-jobs` 不变量 #14。不要把产品沙盒改回进程内 `dry_run`。

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

手工路径：`make seed` 后进 `/admin` —— 系统健康四个依赖全绿、任务台能看到卡死与失败的任务、积分台能看到那条悬挂预扣、用户台能搜到被封禁的 `driftwood`、智能体台能看到一次降级记录、数据统计台能看到供应商/智能体/任务/积分四类真实数字。种子数据是专门为这些页面准备的。
