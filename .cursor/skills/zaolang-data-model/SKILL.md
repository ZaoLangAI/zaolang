---
name: zaolang-data-model
description: 造浪的 SQLAlchemy 模型与线性 Alembic 迁移链：前缀 ID、整数金额、枚举与状态迁移表、唯一键与索引，以及 identity/works/generation/credits/media/platform/search/agents/async tasks/characters/learning/skills/system logs 等模型模块的边界。Use when adding or altering database tables, columns, enums, indexes, unique constraints, or when writing an Alembic migration in this repository.
disable-model-invocation: true
---

# 数据模型与迁移

## 职责

一处定义 schema：`back/app/models/` 是唯一真相，Alembic 迁移由它 autogenerate 而来。领域不变量能在数据库层表达的（唯一键、check、外键）就必须在数据库层表达，不要只依赖 Python 校验。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/models/base.py` | `Base`、`TimestampMixin`、`new_id()`、命名约定 |
| `back/app/models/enums.py` | 全部枚举 + `JOB_TRANSITIONS` 状态迁移表 + `JobStatus.is_terminal` + `JobOrigin`（`user` / `sandbox`） |
| `back/app/models/identity.py` | `User` / `Profile`（偏好字段 `theme` / `locale` / `region` 在这里） / `Follow` |
| `back/app/models/works.py` | `Work` / `WorkVersion` / `LicenseSnapshot` / `LineageEdge` / `Draft` / `Like` / `Bookmark` / `Collection` / `Tag` / `StylePreset` |
| `back/app/models/generation.py` | `Workflow(Version)` / `GenerationJob`（`origin`、`graph_override_json`） / `JobEvent` / `ProviderAttempt` / `ProviderStat` / `AgentRun`（`input_json`） |
| `back/app/models/credits.py` | `CreditAccount` / `CreditLedgerEntry` / `CreditPackage` / `PaymentIntent` / `WebhookEvent` |
| `back/app/models/media.py` | `Asset` / `UploadSession` / `AssetConsent` / `ContentFingerprint` / `ProvenanceManifest` |
| `back/app/models/platform.py` | `ModerationResult` / `ReportCase` / `Notification` / `PlatformConfig` / `AuditLog` / `IdempotencyRecord` / `Announcement` / `DataRequest` / `BackupRecord` / `ReconciliationReport` |
| `back/app/models/search.py` | `WorkEmbedding`（pgvector `Vector` 列） |
| `back/app/models/agent_skills.py` / `async_tasks.py` | `AgentNode` / `AgentProfile` / `AgentSkill` 与异步供应商检查点 `AsyncProviderTask` |
| `back/app/models/characters.py` / `learning.py` / `skill_library.py` / `system_log.py` / `editor.py` | 角色资产（`Series.kind`：`cast` 名册 / `drama` 制作项目）、学习内容、技能市场、聚合系统日志、短剧剪辑（episode/cut/revision/lease/export） |
| `back/alembic/versions/` | 从基线持续追加的线性迁移链；以 Alembic 当前 head 为准，不依赖文档里的迁移数量 |

## 不可破坏的不变量

1. **ID 一律 `new_id("<prefix>")`**：48 位毫秒时间戳保证索引局部性，80 位随机保证不可枚举。不要用自增整数或裸 UUID，也不要手写 ID 字面量（测试里除外）。
2. **金额与积分是整数**，单位最小（credits / minor unit）。新增金额列用 `Integer`，禁止 `Numeric`/`Float`。
3. **约束命名走 `NAMING_CONVENTION`**，否则 autogenerate 会反复产生噪音 diff。
4. **账本的三个唯一键不能动**：`CreditLedgerEntry` 对 `(account_id, type, job_id)`、`idempotency_key`、`payment_reference` 各有唯一约束——它们是「一个任务最多 capture 一次」「支付只入账一次」的数据库级保证，Python 层的检查只是提前报错。
5. **`JobEvent.sequence` 对 `(job_id, sequence)` 唯一且从 1 连续递增**：SSE 断线重连按 `sequence > Last-Event-ID` 补发，有洞或重复会让客户端漏事件。
6. **墓碑保留行**：`LifecycleStatus.TOMBSTONED` 只改状态，永不 `DELETE` `Work` / `WorkVersion` / `LineageEdge`，否则创作链断裂。删除用户走匿名化（见 `zaolang-compliance-audit`）。
7. **枚举值持久化的是字符串**，改名等于数据迁移，加值才是安全操作。状态机改动必须同时改 `JOB_TRANSITIONS`。
8. **`Series` 一张表两种 kind，禁止再建剧集表。** `cast` 是角色名册（`/v1/series`）；`drama` 是短剧制作项目（`/v1/drama-series`，MCP `project_id`）。名册查询必须带 `kind=cast`，drama id 对名册 API 404。`Series` 不进 `RESET_TABLES`（名册保留）；`make seed --reset` 额外 `DELETE FROM series WHERE kind = 'drama'`，剪辑子表在 `RESET_TABLES` 里。细节见 `zaolang-editor-drama`。

## 改造切入点

**加一张表**

1. 在对应 `models/*.py` 加类，继承 `Base, TimestampMixin`，`id` 用带前缀的 `new_id`。
2. `back/app/models/__init__.py` 导出它，否则 autogenerate 看不见。
3. `make migration m="add xxx"` → **打开生成的迁移人工过一遍**（autogenerate 不会推断 CHECK、部分索引、`server_default`）。
4. `make migrate` 在空库上验证：`make reset` 是最干净的检验。
5. 如果是业务表，加进 `back/app/scripts/seed.py` 的 `RESET_TABLES`，否则 `make seed --reset` 会留下脏数据。与 `Series` 同表复用、但不能清名册的行，要像 drama 那样单独 `DELETE`，不要把整张 `series` 丢进 `RESET_TABLES`。

**加一列**：可空或带 `server_default` 才能对存量数据安全升级；要求非空就分两步（先加可空并回填，再改非空）。**纯关联/追溯用的列（例如 `JobEvent.node_id`、`AgentRun.node_id`、`AgentRun.input_json`、`GenerationJob.graph_override_json`、`SystemLog.job_id`）可以只加可空列、不回填历史数据、不设外键**——同 `AuditLog.target_id` 一样，允许被引用的那一行先被清理，日志/追溯记录仍要能存在；这类列的目的是让后台能查到"是谁/哪个节点"，不是维护关系完整性。`GenerationJob.origin` 带 `server_default=user`，存量行即 C 端任务。

**加枚举值**：只加不改，并检查所有 `match` 分支与前端 `front/src/lib/api/types.ts` 的联合类型。

## 验证

```bash
make reset                      # 空库一路升到 head + 种子数据
cd back && conda run -n zaolang alembic upgrade head && conda run -n zaolang alembic check
make test-back                  # 唯一键与不变量测试在 tests/unit/
make openapi                    # 模型变化通常会改 schema，别忘了提交前端类型
```
