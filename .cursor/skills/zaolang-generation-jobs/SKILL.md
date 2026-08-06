---
name: zaolang-generation-jobs
description: 造浪的生成任务与队列：任务状态机与合法迁移表、JobEvent 追加写与 SSE 断线重连、六个 Celery 队列与 pipeline、取消失败重试与积分释放。Use when changing job submission, job status transitions, JobEvent streaming, SSE resumption, Celery tasks or queues, cancellation, retries, or job settlement.
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
| `back/app/models/enums.py` | `JobStatus`、`JOB_TRANSITIONS`、`TERMINAL_JOB_STATUSES`、`CANCELLABLE_JOB_STATUSES`、`JobEventType` |
| `back/app/workers/celery_app.py` | 六个队列的注册与路由 |
| `back/app/workers/pipeline.py` | 安全 → 规划 → 路由 → 供应商 → 质检的实际编排 |
| `back/app/workers/tasks.py` | Celery 任务入口与重试策略 |
| `back/app/realtime/publisher.py` | Redis pubsub 实时推送 |
| `back/app/api/v1/jobs.py` | 提交、查询、取消、SSE `/v1/generation-jobs/{id}/events` |
| `front/src/lib/use-job-stream.ts`、`front/src/components/job/job-progress.tsx` | 前端消费 SSE |

六个队列：`moderation_short`、`image_generation`、`video_generation_long`、`audio_generation`、`quality_check`、`webhook_reconcile`。`Operation.IMAGE_TO_IMAGE` 复用 `image_generation` 队列，`Operation.AUDIO_GENERATION` 走独立的 `audio_generation` 队列（同步调用，不走视频那种建任务+轮询）。

## 不可破坏的不变量

1. **状态迁移只走 `state_machine.transition`**，它用带 `WHERE status IN (...)` 的条件 UPDATE 落地。合法边由 `JOB_TRANSITIONS` 定义，**终态没有出边**：`succeeded/failed/cancelled/expired` 之后任何迁移都必须 `InvalidJobTransition`。乱序或重投的供应商回调正是靠这条被挡住。
2. **恰好一个终态**：两个回调同时到，只有一个能赢，输的那个报错而不是覆盖结果。
3. **`JobEvent.sequence` 从 1 连续递增且不重复**。SSE 重连按 `Last-Event-ID` 从数据库补发，再接 Redis pubsub 实时流；序号有洞客户端会卡住，重复会被跳过。
4. **进入终态必须写 `finished_at`**，并且必须完成积分结算：成功走 `settle_success`（capture 实耗），其余走 `settle_release`（释放预扣）。**没有结算的终态就是悬挂预扣**，会在后台告警里出现。
5. **取消是请求不是命令**：`CANCELLABLE_JOB_STATUSES` 之外不可取消；已提交给供应商的任务可能仍然完成并计费，最终按供应商实际结果结算。
6. **`created` 也能 `expired`**：broker 挂掉时任务永远不会被取走，没有这条边预扣会永久悬挂。
7. **提交入口必须幂等**（`Idempotency-Key`），否则双击提交会扣两次预扣。
8. **报价与预扣在提交事务内完成**，先 `quote_for` 再 `reserve` 再入队；入队失败要释放预扣。

## 改造切入点

- **加一个状态**：`JobStatus` 加值 → `JOB_TRANSITIONS` 补入边与出边（终态记得空 frozenset）→ 若为终态加进 `TERMINAL_JOB_STATUSES` 并处理结算 → 前端 `types.ts` 与三语状态文案 → 属性测试会自动覆盖新状态的走法。
- **加一个事件类型**：`JobEventType` 加值 → 在 `pipeline.py` 对应阶段 `append_event`（`public_message` 是给用户看的，不要泄露供应商名与内部错误）→ 前端时间线加图标与文案。
- **加一个队列**：`celery_app.py` 注册路由 → 同步 `Makefile` 的 `dev-worker -Q` 列表 → 同步后台健康页的队列清单，否则积压看不见。
- **改重试策略**：`tasks.py` 里的重试次数会放大 `effective_cost`（见 `zaolang-agent-gateway` 的路由评分），改动要同步供应商配置的 `retry_amplification`。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_job_state_machine.py tests/integration/test_generation_lifecycle.py tests/integration/test_job_stream.py -v
cd back && conda run -n zaolang pytest tests/concurrency/test_idempotency_and_callbacks.py -v
```

手工路径：起 `make dev-worker`，在 `/create` 提交一次预览档生成，`/jobs/{id}` 的进度条应逐步推进到成功，断网重连后事件不丢不重。
