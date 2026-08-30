# 后端性能深度审计报告

统计时间：2026-08-29。范围：`back/app/models/`、`back/app/workers/`、`back/app/api/`、`back/app/domain/*/service.py`、Redis 全部使用点、`infra/docker-compose*.yml`。方法：逐文件读取 + 全仓 grep 交叉核验，所有结论都带 `file:line` 证据，未核实的猜测一律不写入本报告。

## 总体结论

写路径和「按主键/外键」的读路径设计是扎实的：ID 生成方案（`new_id`，48bit 毫秒时间戳前缀保证索引局部性）、`CreditAccount` 物化余额（读余额不扫账本历史）、pgvector 的 HNSW 索引、SSE 的会话生命周期管理（不长期占用 DB 连接池）都做对了。

真正的风险集中在**「随时间/流量增长」这个维度**，具体是六类问题，按对生产稳定性的影响从高到低：

1. 日志/事件/幂等类 append-only 表完全没有 retention 或分区策略；
2. 异步供应商任务的轮询器对已死的外部任务**刻意设计为无限轮询**，是唯一会导致「无效任务长期占用资源」的确认项；
3. 限流用的 Redis ZSET 在持续攻击流量下是无界增长的（先写后判）；
4. 列表类 API 普遍存在 N+1 查询，是当前对用户可感知延迟影响最大的问题；
5. 部分统计/排序查询的索引与实际查询列不匹配（甚至完全没建索引）；
6. 代码库中有一小批已确认零调用/零门控的死代码和历史遗留字段。

优先级标注：**P0** = 一旦触发即造成资源无限占用或数据不可控增长，应最先修复；**P1** = 明确影响响应速度或资源效率，规模变大后会持续恶化；**P2** = 增量收益，风险低、可顺手做。

---

## 一、数据库设计（长期数据增长）

### 高增长 / append-only 表盘点

| 表 | 模型位置 | 现有关键索引 | 时间列索引 | 清理/分区策略 |
| --- | --- | --- | --- | --- |
| `job_events` | `generation.py:207-236` | `uq`+`ix (job_id, sequence)` | 无 `created_at` | 无 |
| `provider_attempts` | `generation.py:239-271` | `uq(job_id, attempt)`；`(provider, status)` | 无 | 无 |
| `agent_runs` | `generation.py:300-359` | `(job_id)`；`(agent_name, created_at)` | 仅复合左列 | 无 |
| `credit_ledger_entries` | `credits.py:53-84` | `(account_id, created_at)`；`type`；多个唯一约束 | 无裸 `created_at` | 无（合规要求长期保留，不能删） |
| `audit_logs` | `platform.py:200-228` | `created_at`；actor；target；action | 有 | 无 |
| `system_logs` | `system_log.py:22-62` | `created_at`；`(source, event)`；`job_id` | 有，但**查询用 `updated_at`**（见下） | 无 |
| `idempotency_records` | `platform.py:231-253` | 仅唯一约束 `(user, endpoint, key)` | 无 | 无 TTL |
| `webhook_events` | `credits.py:129-148` | 唯一约束 `(provider, external_event_id)` | 无 | 无 |
| `notifications` | `platform.py:126-153` | `(user, created_at)`；`(user, updated_at)` | 有 | 无 |

**已有的清理机制只有**：Celery `purge_expired_exports`（`celery_app.py:133-138`，`compliance/service.py:215-239`）——只删 `DataRequest` 导出对象存储，不删任何行；`expire_stale_jobs` 等是业务态过期，不是历史表 retention。**全库没有任何 partitioning，没有任何 append-only 大表的归档任务。**

### P0-1：日志/事件/幂等类表无 retention

百万级 `job_events` / `agent_runs` / `system_logs` / `idempotency_records` / `webhook_events` 之后，磁盘占用、`autovacuum` 效率、备份窗口都会先于业务逻辑本身出问题。

修复方案（按表定义不同保留期，做成新的 Beat 周期任务）：

- `idempotency_records`：7–14 天。
- `webhook_events`：处理成功后 90 天（或只留 `external_event_id` 去重表，丢弃 `payload_json`）。
- `system_logs`：90 天。
- `job_events` / editor 相关的命令/操作事件表：job 进入终态后 30–90 天，SSE 重连不再需要更早的历史。
- `audit_logs` / `credit_ledger_entries`：**不删**，合规与账本要求长期保留；长期方案是按月分区 + 冷存储 detach，不是清理任务。

### P1-1：统计查询与索引错配

| 问题 | 证据 | 影响 |
| --- | --- | --- |
| `ProviderAttempt` 统计只按 `created_at` 过滤 | `statistics/service.py:143,344,397,460` | 无 `created_at` 索引 → 全表扫 |
| `AgentRun` 统计/网关降级计数只按裸 `created_at` | `statistics/service.py:186+`；`gateway.py:48-52`；`observability.py:138` | `(agent_name, created_at)` 左列限制，裸时间范围查询打不上 |
| `CreditLedgerEntry` 全局按日统计 | `statistics/service.py:251` | `(account_id, created_at)` 不服务无 account 的范围扫 |
| Admin 悬挂预扣扫描按 `type` | `admin/ledger.py:118-135` | 随账本增长线性变差 |
| **`SystemLog.search()` 按 `updated_at` 排序/过滤，但索引建在 `created_at`** | `system_log/service.py:132-149` vs `system_log.py:59` | **索引完全打不上**，是本节最明确的一处错配 |
| `GenerationJob` 日统计/列表按裸 `created_at` | `statistics/service.py:89`；`admin/jobs.py:94,108` | 只有 `(status, created_at)` |
| `LineageEdge` / `User` 的 `created_at` 日统计 | `statistics/service.py:286-288,497-499` | 无索引 |
| `works.like_count` / `remix_count` 排序 | 无对应索引 | discover 的"热门"/"最多二创"排序无索引支撑 |
| `collections.owner_user_id`、`CollectionItem.collection_id` | 无索引 | 见第二节 N+1 |

修复：为上述每个"裸时间范围/排序列"补对应索引（详见附录 DDL 清单）；`SystemLog` 需要新增 `ix_system_logs_updated_at`，并评估是否可以下线 `ix_system_logs_created_at`。

### P2-1：连接池与大字段

- `back/app/db.py` 的 `create_engine` 未设置 `pool_recycle`（默认 `-1`），经云数据库/负载均衡的部署可能遇到连接被服务端悄悄断开后才发现。`pool_size=10, max_overflow=20` 是显式配置的，但需要按「uvicorn worker 数 × Celery 并发数」整体规划，避免打满 Postgres `max_connections`。
- `AgentRun.input_json` 存完整 prompt 全文，`WebhookEvent.payload_json` 长期保留入站原始 payload，百万行后行宽和 TOAST/备份体积会显著放大。
- `ix_job_events_job_id_sequence` 与唯一约束 `uq_job_events_job_sequence`（`generation.py:234-235`）重复——唯一约束本身已经能服务查询，这个索引是纯粹的写放大，可以下线。

### 已确认设计合理、无需改动

- pgvector `WorkEmbedding` 在初始迁移里已经建好 HNSW（`cosine_distance` 用法与索引类型匹配，`search.py:32-38`，`20260801_0709_initial_schema.py:588`）。
- ID 方案（`new_id`）自带索引局部性，等价于 UUIDv7 的效果。
- 核心业务表（`users`/`works`/`generation_jobs`/`assets`/`access_grants`/`creation_skills`）的 FK/状态复合索引质量良好。

---

## 二、增删改查性能（响应速度 / 资源占用）

### P0-2：列表类接口的 N+1 查询

这是当前对用户可感知延迟影响最大的一类问题。

**`GET /v1/works`（discover/works 列表）**：每条结果都调用 `_summary`，`works.py:107-111` 循环内对每条作品串行调用：

```475:501:back/app/api/v1/works.py
def _summary(...):
    cover_size = media_urls.asset_size(session, version.cover_asset_id)   # Asset get
    ...
    cover_url=media_urls.asset_url(session, version.cover_asset_id),     # Asset get 再次
    media_type=media_urls.media_type_of(session, version.primary_output_asset_id),
    author=_author(...),          # Profile + 可能 avatar Asset
    tags=_tags(...),              # 单独 SELECT
    viewer_unlocked=access_service.viewer_unlocked_work(...),  # 可能 AccessGrant
```

`limit=24` 时约 150-200 次 round-trip（再加多次对象存储 presign）。同一模式还用于 `/works/{id}/similar`、`/profiles/{handle}/works`、`/me/bookmarks`、`/me/trash`。

**`GET /v1/generation-jobs`（任务列表）**：`jobs.py:444-505` 的 `_job_response` 每行一次 `progress_for`（`jobs/service.py:337-351` 的 `ORDER BY sequence DESC LIMIT 1`）+ 多次 Asset 查询；且列表查询 `select(GenerationJob)` 会拉整行，包括仅详情页需要的 `request_json`/`routing_trace_json`/`graph_override_json`/`analysis_result_json`。

**`GET /v1/collections`**：`community.py:70-77` 无 `LIMIT`，`_collection_response`（`:396-419`）每个 collection 一次 `COUNT` + 逐条 `get(Work)`/`get(WorkVersion)`/`get(Asset)`。

**Style presets 列表**：`community.py:181-195` 逐条查 `Profile`，且列表直接回传完整 `params_json`。

修复方向：批量 `IN` 预加载（Profile/Tag/Asset/AccessGrant 一次性拉齐，同一 `cover_asset_id` 只取一次）+ 窄列投影（列表场景不要整行拉大 JSON 列）。

### P1-2：分页不完整

- `collections`/`characters`/`scenes` 列表**完全没有 limit**（`.all()`），随数据增长会变成全表拉取。
- `jobs`/`notifications`/style-presets 列表**有 limit 但无 cursor**，无法稳定翻页（重复/漏项风险）。

### P1-3：关键词搜索无法走索引

```190:201:back/app/domain/search/service.py
pattern = f"%{text.lower()}%"
stmt = _visible_works().where(
    or_(
        func.lower(WorkVersion.title).like(pattern),
        func.lower(func.coalesce(WorkVersion.description, "")).like(pattern),
    )
)
```

前导 `%` 的 `LIKE` 无法使用 B-tree 索引；`search()` 还会拉 `limit * 4` 候选再在内存里融合排序（`CANDIDATE_MULTIPLIER = 4`，`service.py:26,148-179`）。对照之下，向量检索（HNSW + `LIMIT`）设计是对的。

修复：加 `pg_trgm` GIN 索引（或 `tsvector` + GIN 全文索引），把排序尽量下推到 SQL。

### P1-4：input-request 应答同步跑工作流

```302:319:back/app/api/v1/jobs.py
# "runs inline in the request rather than off a scheduler tick"
job = input_requests.answer(session, job, raw_answers)
```

代码注释自己也承认这里和 `submit()` 不同——在 HTTP worker 线程里同步续跑图。修复：改成只写状态再 `dispatch` 到 Celery，客户端仍用已有的 SSE 跟进度，不需要新的前端改动。

### 已确认设计合理、无需改动

- `CreditAccount.available_balance`/`reserved_balance` 是物化余额，读取不扫 `credit_ledger_entries` 历史（`credits/service.py:39-49`）。
- Admin 日趋势统计全部走 SQL `GROUP BY`/`date_trunc` 聚合，没有拉全表到 Python 里算。
- Job/Notification 的 SSE 在整个连接生命周期内不占用 DB 连接池（backfill 在 generator 外完成，直播走 Redis pubsub）。

---

## 三、异步任务健壮性（避免无效任务占用线程/资源）

### Celery 配置快照

| 项 | 值 | 位置 |
| --- | --- | --- |
| Broker/backend | 同一个 Redis（`redis://localhost:6380/0`） | `celery_app.py:19`，`config.py:28` |
| 9 个队列 | `image_generation`/`video_generation_long`/`audio_generation`/`quality_check`/`webhook_reconcile`/`provider_task_polling`/`media_analysis`/`platform_distribution`/`video_analysis` | `celery_app.py:35-56` |
| `task_acks_late` / `task_reject_on_worker_lost` | `True` / `True` | `:68-69` |
| `worker_prefetch_multiplier` | `1` | `:70` |
| `task_ignore_result` / `result_expires` | `True` / 86400s | `:74-75` |
| `task_time_limit` / `soft_time_limit` | **未配置** | 全仓无匹配 |
| `visibility_timeout` | **未配置**（Redis 默认约 3600s） | 全仓无匹配 |
| `worker_concurrency` | **未在配置中设置**（走 CLI/CPU 默认） | — |

### P0-3：死上游任务无限轮询（本次审计中最明确的"无效任务占用资源"问题）

```32:37:back/app/domain/jobs/async_tasks.py
# Platform policy, not a provider's: how often to check on an external render.
# `TASK_TIMEOUT_SECONDS` is the lease `expire_stale_jobs` uses to tell a live
# poll apart from a dead Beat — `reschedule` renews it. The poller itself
# keeps asking until the upstream returns succeeded or failed.
```

这是**刻意设计**的行为，且有测试固化了这个语义：`test_a_render_past_its_deadline_keeps_polling`（`tests/unit/test_async_provider_tasks.py:522-545`）。同时 `expire_stale_jobs`（`tasks.py:235-266`）只要 job 上还挂着 `AsyncProviderTask` 就直接跳过，30 分钟的 `STALE_JOB_TIMEOUT` 完全碰不到它。

后果：一个死掉的外部供应商任务会——每 15 秒打一次外部 API + 数据库 + Redis 心跳；`deadline_at` 被无限续租；`poll_count` 无上限；对应的积分预留长期占用，永远不会被释放。`deadline_at` 目前只用于续租语义和 admin 的"疑似卡住"展示（`admin/jobs.py:691-706`），**不是**自动放弃的上限，这与模型注释（`models/async_tasks.py:61-62`）和 `aihubmix_media.py:107-110` 里"平台放弃渲染"的措辞矛盾。

修复：给 `poll_count` 或墙钟时间加硬上限（例如 1-2 小时，或 `TASK_TIMEOUT_SECONDS(480s) × N` 次续租），超过后主动判定 `PROVIDER_TIMEOUT`，走 `settle_release` 释放积分预留并转入失败态，而不是无限续租。需要同步更新 `test_a_render_past_its_deadline_keeps_polling` 的断言（该用例目前断言"过期后仍继续轮询"，实现放弃语义后这个断言本身要改成"超过硬上限后停止并结算失败"）。

### P1-5：无 Celery 硬超时 + broker visibility_timeout 未配置

全仓库没有配置 `task_time_limit`/`soft_time_limit`；也没有配置 `broker_transport_options.visibility_timeout`（Redis broker 默认约 3600s）。二者叠加 `task_acks_late=True` 时，一个长时间不 ack 的任务在 visibility_timeout 到期后可能被重新投递，造成重复执行。

修复：按队列分级设置软硬超时（例如图片类 300s 软/360s 硬，`video_analysis` 600-900s），并设置 `visibility_timeout` ≥ 所有队列里最大的硬超时 + 缓冲。长视频渲染本身应该继续走"创建后挂起+轮询"的模式，不应该把多分钟渲染绑定在一个 worker 槽位上等待。

### P1-6：生产 worker 无显式并发数 + 一处路由遗漏

- `infra/docker-compose.prod.yml`/`release.yml` 和 `Makefile` 的 worker 命令都没有设置 `--concurrency`，主 worker 单进程要吃 8 个异构队列（含高频 Beat 的 `webhook_reconcile` 和长耗时的 `video_generation_long`），容易被长任务"饿死"短任务。
- `reconcile_credits` 在 Beat 里有调度，但在 `task_routes`（`celery_app.py:115-118`）里没有对应路由，默认落到 `task_default_queue`（`image_generation`），会和真正的生成任务抢同一个 worker 槽位。

修复：生产环境固定合理的 `--concurrency`；把 `reconcile_credits` 路由到 `webhook_reconcile`，和其它对账/清理类任务保持一致。

### P2-2：轮询查询效率与背压

- `claim_due` 逐行条件 `UPDATE`，pending 状态每 tick 额外查一次 `max(JobEvent.progress)` 做心跳（`async_polling.py:176-178`），可以用 `task.poll_count`/内存缓存代替，减少一次查询。
- 没有队列深度上限或死信队列（DLQ），背压完全依赖 HTTP 层的 `generation_submit`（12/60s）限流；Redis list 本身无界，worker/Beat 长时间停摆时消息会持续堆积，只能靠人工 `make dev-purge-queues` 清理。

### 已确认设计合理、无需改动

- 队列按延迟拆分、poller 独占 `provider_task_polling` 队列且 `--concurrency=1`，长任务不会饿死轮询。
- `acks_late` + `reject_on_worker_lost` + `prefetch=1` 的组合是对的。
- `claim_due` 用条件 UPDATE 防止双重 resume；任务参数只传 ID，重载荷都在数据库里。
- 图遍历有 `HARD_MAX_NODE_VISITS=20` 硬顶，供应商选路 `route_score.max_attempts` 默认 2，都不会无限循环。

---

## 四、Redis 使用（避免内存无限积累）

**共享连接面**：所有应用代码经 `get_redis()`（`rate_limit.py:53-55`）连到同一个 `redis://localhost:6380/0`；Celery broker/backend 也用同一个 URL（`celery_app.py:19`）——业务键和 Celery 队列/结果全部挤在 db0。仓库里没有 `redis.conf`，`infra/docker-compose*.yml` 只设置了 `--appendonly yes`，**没有设置 `maxmemory`/`maxmemory-policy`**。

### 全量 Redis key 清单

| Key 模式 | 位置 | 结构 | TTL | 有界性 |
| --- | --- | --- | --- | --- |
| `rl:{bucket}:{identity}` | `rate_limit.py:68-80` | ZSET | `window+1`s | **窗口内按 RPS 无界（见下）** |
| `PUBLISH job-events:*` / `notifications:*` | `publisher.py:40,48` | pub/sub | n/a | 不落键 |
| `cfg:v1:{section}` | `platform_config/service.py:28-35,184` | string | 30s | 有界（≤9 keys） |
| `slog:{source}:{event}:{dedup}:{epoch}` | `system_log/service.py:67-72` | string | `window+5`s | TTL 有界 |
| `llmfo:conc:{endpoint_id}` | `failover.py:25,107-118` | string | 120s | 有界，但归零时丢 TTL（见下） |
| `llmfo:brk:*` / `llmfo:stats:*` | `failover.py:130-145` | string | 60-3600s | 有界 |
| `admin:llm-validate:{id}` | `validation_jobs.py:18,56-61` | string | ≥180s | 有界 |
| Celery 队列 list | Celery 内部 | LIST | **无** | worker/Beat 停摆时无界 |
| `celery-task-meta-*` | Celery backend | string | `result_expires=86400` | 有界但依赖人工 `purge_stale_celery` 收尾孤儿 |

### P0-4：限流 ZSET 先写后判，攻击流量下无界增长

```68:80:back/app/api/rate_limit.py
# 先 ZADD 再判断是否超限
```

被限流的请求本身也会写入 ZSET 成员——单个 key 的成员数约等于「请求速率 × 窗口长度」而不是 `limit`。例如 `auth_attempt` 窗口 300 秒，攻击者以 1000 RPS 打满 300 秒时单 key 可膨胀到约 30 万个 member，且 member 本身带时间戳+uuid，体积不小。正常流量下流量停止后 `window+1` 秒会过期，但持续的恶意流量是真正无界的。

修复：在 Lua 脚本或 pipeline 内先 `ZCARD` 判断是否已达 `limit`，达到后**只刷新 TTL、不再 `ZADD`**，把 ZSET 大小硬性收敛到 `limit` 量级。

### P0-5：Redis 未配置 maxmemory / eviction policy

生产部署（`infra/docker-compose.yml` / `.prod.yml` / `.release.yml`）都只配置了 `--appendonly yes`，没有 `maxmemory`，Redis 默认策略是 `noeviction`——一旦内存被打满，写命令会直接报错而不是优雅淘汰旧数据，会直接影响限流、Celery 入队等所有写路径。

修复：按机器规格设置 `maxmemory`（例如 512MB 起步）+ `maxmemory-policy volatile-lru`（优先淘汰有 TTL 的键，不误伤 Celery 队列这类无 TTL 但业务关键的数据）。

### P1-7：Celery 与业务缓存共用 db0

Broker 队列本身是无 TTL 的 Redis list；worker/Beat 停摆或数据库被重置后，孤儿消息只能靠人工执行 `make dev-purge-queues` 清理，没有自动化手段。修复：把 broker 换到独立逻辑库（如 `/1`），并监控队列 `LLEN` 设置告警阈值；评估把 `purge_stale_celery`（只清孤儿，不动正常消息）做成周期性 Beat 任务。

### P2-3：小问题

- `llmfo:conc:*` 计数器归零时用裸 `client.set(key, 0)`（`failover.py:117-118`），会丢失原有 TTL，可能残留永久性的 0 值键。修复为 `SET key 0 EX 120` 或计数到 0 时直接 `DELETE`。
- `idempotency_records` 虽然存在 Postgres 而非 Redis，但同样没有 retention（见第一节 P0-1），一并处理。

### 已确认设计合理、无需改动

- Pub/sub 不落任何持久键，SSE 连接结束时正确调用 `pubsub.close()`。
- 平台配置缓存 TTL 30s 且写时主动失效，键数量恒定可控。
- `system_log` 去重键、LLM failover 熔断计数器都设置了合理的 TTL。

---

## 五、API 接口设计合理性

本节内容大多已在第二节覆盖（N+1、分页缺失、input-request 应答同步执行），以下是额外发现：

- **列表响应过取（over-fetch）**：Job/Style-preset 等列表接口的 ORM 查询整行加载了 `routing_trace_json`/`graph_override_json`/大 `request_json`/`params_json` 等只有详情页才需要的字段——即使响应体没有直接回传，数据库和网络层面已经付出了代价。列表场景应做窄列投影（`load_only`/显式选择字段）。
- **无 per-user SSE 并发上限**：全仓库没有对同一用户的并发 SSE 连接数做限制。虽然 SSE 本身不持有 DB 会话，但仍然占用请求处理线程/协程和连接超时窗口，多标签页同时打开多个任务流时有打满 uvicorn worker 的风险。
- **`get_work` 的 `descendant_count` 用 BFS 遍历血缘边计数**（`works.py:150`，`lineage/service.py` 的 `descendants()`），应改成 SQL 层面的 `COUNT`/递归 CTE，而不是应用层遍历。

---

## 六、冗余/无效代码清理

`vulture` 等自动死代码检测工具在当前环境中不可用（`requirements*.txt`/`pyproject.toml` 未声明，且未安装），以下结论全部来自人工 grep/read 核验，均有实际证据。

### 低风险，可直接删除（高置信度）

| 项 | 证据 |
| --- | --- |
| `export_url_for` | `back/app/domain/shortform/service.py:165-177`，全仓零调用 |
| `ms_from_ticks` | `back/app/domain/editor/time.py:31-32`，零调用；`analysis.py:116` 已内联等价公式 |
| 依赖 `opentelemetry-instrumentation-sqlalchemy==0.65b0` | `back/requirements.txt:26`，全仓无 `SQLAlchemyInstrumentor` 或相关 import |

### 中风险，产品面已死但需要前后端联动清理（高置信度）

| 项 | 证据 |
| --- | --- |
| `FeatureFlags.shortform_studio` | `platform_config/schemas.py:172`，无任何产品路径读取该 flag，`/v1/shortform/profiles` 无门控；仅 admin 配置面板展示（`admin/config.py:48`，前端 `runtime-config-panel.tsx:300`） |
| `ShortformProfiles.enable_clarifying_questions` / `enable_preview_picker` / `preview_candidate_count` | `platform_config/schemas.py:142-147`，API `shortform.py:36-38`；短剧编辑器 `drama-editor.tsx` 只取 `profiles.profiles`，不读这三个字段 |
| `LlmProviderPoolView.categories` / `LlmProviderCategoryView` | `admin.py:804-807`；`_pool_view` 恒返回 `categories=[]`（`llm_providers.py:320-323`），schema 自标注 Legacy，前端类型已导出但零组件使用（`admin-types.ts:67`） |

### 高风险，需要数据迁移步骤才能收尾（高置信度，已确认为写死路径）

`Series(kind=cast)` 角色花名册功能的主体 CRUD（`create_series`/`list_series`/`get_series_detail`/`add|remove_character_to_series`/`assign_episode`）早已删除，`characters/service.py` 与 `api/v1/characters.py` 里没有残留函数。但仍有维护性残留：

- `delete_character` 仍在扫描并清理 `SeriesKind.CAST` 行（`characters/service.py:340-350`）；
- `Series.kind` 默认值仍是 `"cast"`（`models/characters.py:42`），但所有生产创建路径都显式传 `DRAMA`；
- `character_ids_json` 对 drama 恒为空数组、从不被业务读取（写入均为 `[]`：`editor/service.py:151`、`script_writing/service.py:227`）；
- `brand_pack_asset_id` 列全仓无任何读写（仅模型定义和迁移）。

收尾顺序（不能跳步）：① 先确认/清理线上遗留的 `kind=cast` 行 → ② 再删 `delete_character` 里的清理循环 → ③ 改 `Series.kind` 默认值为 `drama` → ④ 评估是否随后废弃 `character_ids_json`/`SeriesKind.CAST`/`brand_pack_asset_id`（后两者需要 alembic migration，属于结构性变更，要单独评审）。

### 仅建议巩固、不建议删除

- `characters/service.py` 与 `scenes/service.py` 中的 `_short_description`/`_validate_reference_assets`/`_entries_from_flat_ids` 等近重复 helper：字段和文案有差异，不宜盲目合并成一份。
- `learning/service.py` 与 `skill_library/service.py` 中重复的 `ListPage` cursor 分页 dataclass：可以抽成公共工具，但不是必须。

### 未发现

孤儿 `.py` 文件、孤儿数据表、`_deprecated`/`TODO`/`FIXME`/大段注释掉的死代码块——全仓搜索均为零命中。

---

## 补充优化项

以下几项不在用户原始的五个维度里，但审计过程中发现且有明确代码证据，直接给出结论：

- 数据库连接池未设置 `pool_recycle`，云数据库/负载均衡场景下连接可能被服务端悄悄断开而未被感知，建议设为 1800-3600 秒。
- `AgentRun.input_json` 存储完整 prompt 全文，百万行规模后行宽、TOAST 存储、备份体积都会显著放大，建议摘要化或外置对象存储，只在 DB 里留引用。
- Celery 缺少死信队列（DLQ），失败任务仅靠 `on_failure` 结算积分，没有额外的可观测性；建议为超过重试上限的任务补充结构化日志或指标。
- `reconcile_credits` 路由遗漏（见第三节 P1-6），属于配置疏漏，随 Celery 配置修复批次一并处理。

---

## 实施路线图

按下面的批次顺序推进，**每批独立提交、独立验证，不同风险等级不要混在一次改动里**，允许包含结构性数据库变更（含分区/归档）：

1. **P0 批次**：限流 ZSET 修复、Redis `maxmemory` 配置、异步轮询硬超时（同步更新相关单测）、日志/事件/幂等类表的 retention Beat 任务上线。
2. **P1 批次**：`works`/`jobs`/`collections`/`community` 列表接口的 N+1 批量化改造；补齐统计相关索引，修正 `SystemLog` 索引错配；Celery `task_time_limit`/`visibility_timeout`/`worker --concurrency`/`reconcile_credits` 路由修正；关键词搜索加 `pg_trgm`。
3. **P2 批次**：连接池 `pool_recycle`、大 JSON 列瘦身、冗余索引清理、`llmfo` TTL 修正、SSE 并发配额、`descendant_count` 下推 SQL。
4. **死代码清理批次**（与性能改动分开提交，便于 review）：先删零风险项，再清理已死的 shortform 配置开关（需要同步前端与测试），`Series(kind=cast)` 收尾单独作为一个小批次（涉及数据核对与可能的 migration）。
5. **结构性改动**（需要单独的 migration 评审窗口）：`job_events`/`agent_runs` 等高增长表按月分区或归档策略。

每一批改动都必须：

- 先跑 `make check`（lint + typecheck + trilingual copy + OpenAPI drift + 全量测试）建立基线，改动后复跑确认无回归。
- 涉及索引/迁移的用 `alembic upgrade head` + `alembic check` 验证，`make reset` 做空库回归。
- 涉及 Celery 行为变更（尤其异步轮询超时语义）的必须同步更新 `tests/unit/test_async_provider_tasks.py`、`tests/concurrency/test_idempotency_and_callbacks.py` 等现有测试，而不是绕开或删除断言。
- 涉及限流的必须过 `tests/integration/test_rate_limits.py`。

```bash
make check
cd back && conda run -n zaolang pytest tests/unit/test_async_provider_tasks.py tests/concurrency/test_idempotency_and_callbacks.py -v
cd back && conda run -n zaolang pytest tests/integration/test_rate_limits.py -v
make reset && cd back && conda run -n zaolang alembic upgrade head && conda run -n zaolang alembic check
```
