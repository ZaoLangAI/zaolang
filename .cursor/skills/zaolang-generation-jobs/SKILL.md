---
name: zaolang-generation-jobs
description: 造浪的生成任务与队列：任务状态机与合法迁移表、JobEvent 追加写与 SSE 断线重连、7 个 Celery 队列、异步供应商轮询与 pipeline、取消失败重试与积分释放。Use when changing job submission, job status transitions, JobEvent streaming, SSE resumption, Celery tasks or queues, provider polling, cancellation, retries, or job settlement.
disable-model-invocation: true
---

# 生成任务与队列

## 职责

把一次生成请求变成一条可追踪、可回放、可结算的任务。状态机与事件流是**客户端唯一的进度真相**，不要在别处另存一份进度。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/domain/jobs/state_machine.py` | `transition` / `request_cancel` / `append_event` / `events_since` |
| `back/app/domain/jobs/service.py` | `quote_for` / `submit` / `settle_success` / `settle_release` / `get_owned_job` / `progress_for` |
| `back/app/models/enums.py` | `JobStatus`、`JOB_TRANSITIONS`、`TERMINAL_JOB_STATUSES`、`CANCELLABLE_JOB_STATUSES`、`JobEventType`、`JobOrigin`（`user` / `sandbox`） |
| `back/app/workers/celery_app.py` | 7 个队列的注册与路由 |
| `back/app/workers/pipeline.py` | 安全 → 规划 → 路由 → 供应商 → 质检的实际编排 |
| `back/app/workers/tasks.py` | Celery 任务入口与重试策略 |
| `back/app/workers/async_polling.py` | `poll_once()`：Beat 周期任务的实际逻辑，认领到期的在途供应商任务、轮询、续跑或收尾 |
| `back/app/domain/jobs/async_tasks.py` | `AsyncProviderTask` 的 `suspend` / `claim_due` / `reschedule` / `settle`，以及轮询间隔与超时策略；`cancel_upstream(session, task, provider)` 是唯一的取消入口——调 `provider.cancel()` → 关闭对应 `ProviderAttempt` 为 `CANCELLED` → `settle(task)`，`async_polling.py::_cancel()` 与后台 `admin/jobs.py::terminate()` 都调它，避免两处取消逻辑分叉 |
| `back/app/realtime/publisher.py` | Redis pubsub 实时推送 |
| `back/app/api/v1/jobs.py` | 提交、查询、取消、重试（`retry`，同档位重投）、升级（`promote`，`preview` 档成功后升级到正式档位）、SSE `/v1/generation-jobs/{id}/events`。列表与 `get_owned_job` 过滤 `origin=sandbox` |
| `back/app/api/v1/admin/workflow_templates.py` | 产品沙盒：`POST .../sandbox-run` → 真实 `GenerationJob`（`origin=sandbox`）+ 202 `{job_id}`；草稿图写入 `graph_override_json`，不发布、不 pin live 模板。`GET .../sandbox-runs` 只读列出该 operation 的沙盒任务（游标分页，`prompt_excerpt` / `used_draft`）；详情仍走 `GET /v1/admin/jobs/{id}` |
| `back/app/api/v1/admin/jobs.py` | 后台任务运维；`GET/POST /jobs/{id}/input-request`、`/answer` 供沙盒与运维台回答 `AWAITING_INPUT` |
| `front/src/lib/use-job-stream.ts`、`front/src/lib/use-admin-job-stream.ts`、`front/src/components/job/job-progress.tsx` | C 端 / 后台消费 SSE；后台流额外带 `node_id` |

六个队列：`image_generation`、`video_generation_long`、`audio_generation`、`quality_check`、`webhook_reconcile`、`provider_task_polling`。`Operation.IMAGE_TO_IMAGE` 复用 `image_generation` 队列，`Operation.AUDIO_GENERATION` 走独立的 `audio_generation` 队列（同步调用，不走视频那种建任务+轮询）。`provider_task_polling` 只跑 Beat 周期任务 `poll_async_provider_tasks`，不接收用户提交。

## 不可破坏的不变量

1. **状态迁移只走 `state_machine.transition`**，它用带 `WHERE status IN (...)` 的条件 UPDATE 落地。合法边由 `JOB_TRANSITIONS` 定义，**终态没有出边**：`succeeded/failed/cancelled/expired` 之后任何迁移都必须 `InvalidJobTransition`。乱序或重投的供应商回调正是靠这条被挡住。
2. **恰好一个终态**：两个回调同时到，只有一个能赢，输的那个报错而不是覆盖结果。
3. **`JobEvent.sequence` 从 1 连续递增且不重复**。SSE 重连按 `Last-Event-ID` 从数据库补发，再接 Redis pubsub 实时流；序号有洞客户端会卡住，重复会被跳过。
4. **进入终态必须写 `finished_at`**，并且必须完成积分结算：成功走 `settle_success`（capture 实耗），其余走 `settle_release`（释放预扣）。**没有结算的终态就是悬挂预扣**，会在后台告警里出现。**例外：`origin=sandbox` 的产品沙盒**仍走状态机与 `finished_at`，但 `settle_*` 是 no-op（不 `reserve` / `capture` / `release`），`quoted_credits` 只记「若扣费会是多少」。
5. **取消是请求不是命令**：`CANCELLABLE_JOB_STATUSES` 之外不可取消；已提交给供应商的任务可能仍然完成并计费，最终按供应商实际结果结算。挂起等待外部任务期间用户照样可以点取消，所以 `poll_once()` 每次认领任务都要先看一眼 `cancel_requested_at`，命中就调 `provider.cancel()` 并走 `settle_release` + 迁移到 `CANCELLED`，不再续跑工作流——与 `execute_provider_generate` 里那次取消检查是同一套语义。后台 `admin/jobs.py::terminate()` 命中在途 `AsyncProviderTask` 时也会在同一次请求内同步走 `async_tasks.cancel_upstream()`，不再是"只改状态、不通知供应商"；catalogue 里找不到能力或 `provider.cancel()` 失败都不阻断状态迁移，只落一条 `system_log.emit(level=warning/error, ...)`。
6. **`created` 也能 `expired`**：broker 挂掉时任务永远不会被取走，没有这条边预扣会永久悬挂。
7. **提交入口必须幂等**（`Idempotency-Key`），否则双击提交会扣两次预扣。
8. **报价与预扣在提交事务内完成**，先 `quote_for` 再 `reserve` 再入队；入队失败要释放预扣。沙盒提交仍 `quote_for`，但跳过余额检查与 `reserve`，`reserved_credits=0`。
9. **`RUNNING` 可以跨 Celery 任务边界存续**。异步供应商（AiHubMix 视频）建完任务就返回 `pending=True`，`WorkflowRunner` 落一条 `AsyncProviderTask` 检查点后直接返回，job 仍是 `RUNNING`——**这不是终态、不能结算、不能迁移状态**，剩下的路由由 Beat 周期任务续跑。判断一个 job 是不是卡住，看的是 `AsyncProviderTask.deadline_at` 而不是"多久没换过 worker"。
10. **一条在途任务同一时刻只能被一个 Beat tick 认领**：`claim_due` 用条件 UPDATE 抢 `claimed_at`（同 `state_machine.transition` 的思路），抢不到就跳过。没有这条，两个 tick 会把同一个工作流续跑两次，产出两份结果、结算两次。
11. **H3 轮询每次只查一次且间隔 15 秒**。终态若仍带 `output`，先下载并标记 `partial_output` 后进入现有 Quality 节点；是否可交付由质检决定，不能因为供应商状态失败就丢掉可能已计费的产物。新检查点存 typed references，恢复时仍接受旧 `reference_object_keys` 形状。
12. **Worker 与 Beat 必须同时常驻**。Worker 消费生成队列；Beat 只负责按时投递 `poll_async_provider_tasks`、`expire_stale_jobs` 等周期任务。只有 Worker 没有 Beat 时，外部任务不会轮询，卡死任务也不会释放预扣。视频/音频任务入口共享未装饰的执行函数，禁止一个 `bind=True` 的 Celery Task 直接调用另一个 bound task。
13. **`JobEvent.node_id` 记录的是哪个图节点真正写了这条事件**，不是靠 `event_type` 反查猜的。`custom_agent` 节点固定发 `JobEventType.PROGRESS`，异步轮询心跳、质检重试也发 `PROGRESS`——同一个事件类型在图里可能对应好几个节点，`WorkflowRunner._execute_node` 在调 executor 前把 `ctx.state["_current_node_id"]` 设成当前节点，`nodes.py::_emit` 与 `async_polling.py::_emit`（后者用已知的 `task.node_id`，不用猜）都把它写进 `append_event(node_id=...)`。`node_id` 为空只发生在这列迁移之前写入的历史事件，前端按 `event_type` 回退匹配即可，不代表新代码可以不填。
14. **产品沙盒是真实任务，不是 `dry_run`。** `POST /v1/admin/workflow-templates/{operation}/sandbox-run` 创建 `GenerationJob(origin=sandbox)`，走同一条 Celery pipeline、JobEvent、SSE、质检与资产登记。仅跳过积分账本、C 端列表/通知、Draft/Work。规划/`copy_generate` 的 follow-up 与 C 端相同：进入 `AWAITING_INPUT`，由 `GET/POST /v1/admin/jobs/{id}/input-request|answer` 呈现并续跑（C 端 `/generation-jobs/{id}/input-request` 对 sandbox 仍 404）。`graph_override_json` 让未发布草稿可试跑且 **不得** 回写 `workflow_template_id`。`WorkflowContext.dry_run` 只留给单测「走图但不落库」。成功产物额外入 `POST_GENERATION`（`reason_code=SANDBOX_OUTPUT`）；Safety `NEEDS_REVIEW` 仍入 `PRE_GENERATION`。

## 改造切入点

- **加一个状态**：`JobStatus` 加值 → `JOB_TRANSITIONS` 补入边与出边（终态记得空 frozenset）→ 若为终态加进 `TERMINAL_JOB_STATUSES` 并处理结算 → 前端 `types.ts` 与三语状态文案 → 属性测试会自动覆盖新状态的走法。
- **加一个事件类型**：`JobEventType` 加值 → 在 `pipeline.py` 对应阶段 `append_event`（`public_message` 是给用户看的，不要泄露供应商名与内部错误）→ 前端时间线加图标与文案。
- **加一个队列**：`celery_app.py` 注册路由 → 同步 `Makefile` 的 `dev-worker -Q` 列表与 `infra/docker-compose.release.yml` 的 worker 命令 → 同步后台健康页的队列清单，否则积压看不见。
- **接一个异步供应商**：`GenerationProvider.submit()` 建完外部任务返回 `GenerationResult(pending=True, external_task_id=...)` → 实现 `poll()` 做**一次**状态查询（不要 while 循环占着 worker）→ 其余不用改：`execute_provider_generate` 认 `pending` 落检查点，`poll_once()` 负责心跳事件、续跑与超时。
- **改重试策略**：`tasks.py` 只对瞬时基础设施错误（DB/Redis/网络）做有限 `retry`；`JobNotFoundError`（broker 残留指向已清空的 job）直接返回 `missing`、不重试。改 `max_retries` 会放大 `effective_cost`（交给 `intent_router`，见 `zaolang-agent-gateway`），需同步供应商配置的 `retry_amplification`；不要据此在代码里恢复加权选型公式。
- **"预览后升级"这类衍生提交**：不要给 `GenerationJob` 加候选数组或新的挂起状态——`POST /generation-jobs/{id}/promote`（`back/app/api/v1/jobs.py`）证明了这类需求可以建模成一次普通的 `jobs_service.submit()`，只是业务前置条件不同（`retry` 要求原任务失败/取消/过期且档位不变；`promote` 要求原任务在 `preview` 档成功且目标档位不能仍是 `preview`）。血缘关系记在专门的可空列上（`promoted_from_job_id`，与 `retry_of_job_id` 分开，语义不同：一个是失败后原档重投，一个是预览成功后升档），不需要新 `JobStatus`/`JobEventType`——"等用户挑选预览"是前端在两次独立 job 生命周期之间的本地状态，不是任务状态机的一部分。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_job_state_machine.py tests/unit/test_async_provider_tasks.py tests/integration/test_generation_lifecycle.py tests/integration/test_job_stream.py tests/integration/test_workflow_dry_run.py -v
cd back && conda run -n zaolang pytest tests/concurrency/test_idempotency_and_callbacks.py -v
```

手工路径：起 `make dev-worker`，在 `/create` 提交一次预览档生成，`/jobs/{id}` 的进度条应逐步推进到成功，断网重连后事件不丢不重。
