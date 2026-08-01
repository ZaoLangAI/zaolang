---
name: zaolang-data-model
description: 造浪的 SQLAlchemy 模型与 Alembic 迁移：前缀 ID、整数金额、枚举与状态迁移表、唯一键与索引、六个模型模块的边界。Use when adding or altering database tables, columns, enums, indexes, unique constraints, or when writing an Alembic migration in this repository.
disable-model-invocation: true
---

# 数据模型与迁移

## 职责

一处定义 schema：`back/app/models/` 是唯一真相，Alembic 迁移由它 autogenerate 而来。领域不变量能在数据库层表达的（唯一键、check、外键）就必须在数据库层表达，不要只依赖 Python 校验。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/models/base.py` | `Base`、`TimestampMixin`、`new_id()`、命名约定 |
| `back/app/models/enums.py` | 全部枚举 + `JOB_TRANSITIONS` 状态迁移表 + `JobStatus.is_terminal` |
| `back/app/models/identity.py` | `User` / `Profile`（偏好字段 `theme` / `locale` / `region` 在这里） / `Follow` |
| `back/app/models/works.py` | `Work` / `WorkVersion` / `LicenseSnapshot` / `LineageEdge` / `Draft` / `Like` / `Bookmark` / `Collection` / `Tag` / `StylePreset` |
| `back/app/models/generation.py` | `Workflow(Version)` / `GenerationJob` / `JobEvent` / `ProviderAttempt` / `ProviderStat` / `AgentRun` |
| `back/app/models/credits.py` | `CreditAccount` / `CreditLedgerEntry` / `CreditPackage` / `PaymentIntent` / `WebhookEvent` |
| `back/app/models/media.py` | `Asset` / `UploadSession` / `AssetConsent` / `ContentFingerprint` / `ProvenanceManifest` |
| `back/app/models/platform.py` | `ModerationResult` / `ReportCase` / `Notification` / `PlatformConfig` / `AuditLog` / `IdempotencyRecord` / `Announcement` / `DataRequest` / `BackupRecord` / `ReconciliationReport` |
| `back/app/models/search.py` | `WorkEmbedding`（pgvector `Vector` 列） |
| `back/alembic/versions/` | 迁移链，目前单条基线迁移 |

## 不可破坏的不变量

1. **ID 一律 `new_id("<prefix>")`**：48 位毫秒时间戳保证索引局部性，80 位随机保证不可枚举。不要用自增整数或裸 UUID，也不要手写 ID 字面量（测试里除外）。
2. **金额与积分是整数**，单位最小（credits / minor unit）。新增金额列用 `Integer`，禁止 `Numeric`/`Float`。
3. **约束命名走 `NAMING_CONVENTION`**，否则 autogenerate 会反复产生噪音 diff。
4. **账本的三个唯一键不能动**：`CreditLedgerEntry` 对 `(account_id, type, job_id)`、`idempotency_key`、`payment_reference` 各有唯一约束——它们是「一个任务最多 capture 一次」「支付只入账一次」的数据库级保证，Python 层的检查只是提前报错。
5. **`JobEvent.sequence` 对 `(job_id, sequence)` 唯一且从 1 连续递增**：SSE 断线重连按 `sequence > Last-Event-ID` 补发，有洞或重复会让客户端漏事件。
6. **墓碑保留行**：`LifecycleStatus.TOMBSTONED` 只改状态，永不 `DELETE` `Work` / `WorkVersion` / `LineageEdge`，否则创作链断裂。删除用户走匿名化（见 `zaolang-compliance-audit`）。
7. **枚举值持久化的是字符串**，改名等于数据迁移，加值才是安全操作。状态机改动必须同时改 `JOB_TRANSITIONS`。

## 改造切入点

**加一张表**

1. 在对应 `models/*.py` 加类，继承 `Base, TimestampMixin`，`id` 用带前缀的 `new_id`。
2. `back/app/models/__init__.py` 导出它，否则 autogenerate 看不见。
3. `make migration m="add xxx"` → **打开生成的迁移人工过一遍**（autogenerate 不会推断 CHECK、部分索引、`server_default`）。
4. `make migrate` 在空库上验证：`make reset` 是最干净的检验。
5. 如果是业务表，加进 `back/app/scripts/seed.py` 的 `RESET_TABLES`，否则 `make seed --reset` 会留下脏数据。

**加一列**：可空或带 `server_default` 才能对存量数据安全升级；要求非空就分两步（先加可空并回填，再改非空）。

**加枚举值**：只加不改，并检查所有 `match` 分支与前端 `front/src/lib/api/types.ts` 的联合类型。

## 验证

```bash
make reset                      # 空库一路升到 head + 种子数据
cd back && conda run -n zaolang alembic upgrade head && conda run -n zaolang alembic check
make test-back                  # 唯一键与不变量测试在 tests/unit/
make openapi                    # 模型变化通常会改 schema，别忘了提交前端类型
```
