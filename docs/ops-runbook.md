# 运维手册

面向值班人员。每节的结构是：**怎么发现 → 怎么确认 → 怎么处理 → 处理完检查什么**。所有后台操作都会写审计日志，高危操作强制填理由。

## 0. 值班第一屏

进 `/admin`（系统健康），四类依赖与五个队列都在这一页：

| 看什么 | 正常 | 不正常时看哪一节 |
| --- | --- | --- |
| Postgres / Redis / MinIO / Celery 存活 | 全绿 | [§1 依赖不可用](#deps-down) |
| 五个队列积压与消费速率 | 积压不持续增长 | [§2 队列积压](#queue-backlog) |
| Alembic 版本 | 与部署版本一致 | [§7 迁移与回滚](#migrations) |
| LLM 网关连通性与当前模式 | `openai_compatible` | [§4 LLM 网关降级](#llm-degraded) |

再看两个数字：`/admin/credits` 的**悬挂预扣**与对账报表。它们不为零通常意味着有任务没走完结算。

## 1. 依赖不可用 { #deps-down }

**确认**

```bash
curl -s localhost:8000/health | jq          # 服务自己的探针
docker compose --env-file infra/.env.example -f infra/docker-compose.yml ps
make logs                                    # 跟容器日志
```

**处理**

- 容器挂了：`make up` 重新拉起（`--wait` 会等健康检查通过）。
- Postgres 连接耗尽：先看是否有长事务（`pg_stat_activity` 里 `state = 'idle in transaction'`），杀掉源头进程再重启应用；应用侧连接池配置在 `back/app/db.py`。
- Redis 不可用：**不会导致 500**。配置中心退化为直读数据库，限流放行，SSE 只走数据库补发。功能可用但性能与限流保护下降，尽快恢复。
- MinIO 不可用：上传与媒体读取失败，已发布页面的封面会破图。不要为了「先能看」把桶设成公开读。

**收尾**：健康页四项全绿；`/admin/jobs` 里在故障窗口内卡住的任务按 [§3](#stuck-jobs) 处理。

## 2. 队列积压 { #queue-backlog }

五个队列：`moderation_short`、`image_generation`、`video_generation_long`、`quality_check`、`webhook_reconcile`。

**确认**：健康页的积压数与消费速率。积压高但速率为 0 → worker 没在消费；两者都高 → 容量不足。

**处理**

```bash
make dev-worker      # 本地：确认 -Q 列表包含全部五个队列
```

worker 起来了但某个队列不动，先确认它有没有在 `-Q` 列表里——**新增队列忘了加进 `Makefile` 与部署参数**是最常见的原因。

**收尾**：积压回落；被拖到超时的任务走 [§3](#stuck-jobs)。

## 3. 任务卡死或失败 { #stuck-jobs }

**发现**：用户报「进度条不动」，或 `/admin/credits` 出现悬挂预扣。

**确认**：`/admin/jobs` 按状态与时间筛选，打开任务详情看全链路回放——`JobEvent` 时间线停在哪一步，`ProviderAttempt` 有没有失败码，路由决策选了谁、淘汰了谁。

**处理**（都在任务详情页）

- **卡死可重放** → `requeue`。复用原任务与原预扣，**不会二次扣费**。
- **必须止损** → `terminate`（高危，需二次确认 + 理由）。它走状态机进入终态并释放预扣。
- **供应商侧问题** → 去 `/admin/providers` 关掉该供应商或调低限额，让路由绕开它；这是配置操作，立即生效。

**收尾**：任务处于终态且 `finished_at` 有值；`/admin/credits` 的悬挂预扣少了一条；账本里这个任务恰好有一条 capture **或** 一条 release。

## 4. LLM 网关降级 { #llm-degraded }

**发现**：健康页显示当前模式为 stub，或 `/admin/agents` 的降级次数上升。

**确认**：`/admin/agents` 按智能体看降级原因与延迟；`AgentRun` 记录了模型、token 用量、是否降级。

**处理**

- 网关限流或超时：等待自动恢复。`LLM_MODE=auto` 下降级是**设计好的**保护，不是故障本身。
- 某个模型持续失败：在 `/admin/config` 的 `agents` 段把该智能体切到别的模型（热生效，需理由）。免费模型 `ling-3.0-flash-free` 有配额不确定性，Copy Agent 优先切它。
- 密钥失效：只改 `back/.env` 的 `LLM_API_KEY` 并重启 API。**不要**把密钥写进配置中心或任何会回显的地方。

**收尾**：模式回到 `openai_compatible`；降级计数停止增长。

## 5. 积分对账不平

两个指标不是一回事，处理路径也不同：

| 指标 | 含义 | 性质 |
| --- | --- | --- |
| 对账报表的余额不一致 | 账户余额 ≠ 账本重放结果 | **代码 bug**，需要工程介入 |
| 悬挂预扣 | 预扣长期未结算 | **运维事件**，按 [§3](#stuck-jobs) 处理任务 |

余额不一致时：**不要先调账**。先导出该账户的账本（`/admin/credits/ledger` 可筛选导出），确认差额来源，修完代码再用人工调账把余额对齐——调账是追加 `adjustment` 记录，强制理由与审计，永不修改历史。

## 6. 内容与举报

- **审核队列**：`/admin/moderation`。先 `claim` 再 `decide`，决定人、时间、理由都会记。自动审核结果与人工确认是两条独立记录。
- **举报**：`/admin/reports` 处置并写明结论。
- **下架**：`hide` 可恢复；`tombstone` 是终态。**墓碑保留节点**——下游二创仍能在创作链里看到占位，这是有意的，不要试图「彻底删掉」。
- **指纹重复项**：`/admin/moderation` 的重复分组，按汉明距离聚类，用于洗稿排查。

## 7. 迁移与回滚 { #migrations }

```bash
make migrate                                   # 升到 head
cd back && conda run -n zaolang alembic current # 当前版本
cd back && conda run -n zaolang alembic downgrade -1
```

**先备份再迁移**。降级不总是安全（删列会丢数据），破坏性迁移的回滚路径要在上线前想清楚，写进 PR 描述。

## 8. 备份与恢复

```bash
make backup                       # pg_dump 到 .backups/ 并记录 BackupRecord
make restore f=.backups/xxx.dump  # 需要 --confirm，脚本内已带
```

后台 `/admin/data` 可触发备份并查看历史。**恢复是破坏性操作**：先确认目标库、先停写入、先另存一份当前状态。恢复后立刻核对 `alembic current` 与应用版本是否匹配。

## 9. 用户与合规请求

- **封禁 / 解封**：`/admin/users`，强制理由。被封禁账号登录返回 401（与「密码错误」不可区分，防枚举），管理员被封禁则立即失去后台访问。
- **数据导出**：审批后生成导出物，只通过**短时效签名 URL**交付。不要把该 URL 转贴到工单或邮件里。
- **数据删除**：走匿名化，抹 PII、**保留创作链墓碑**。承诺「彻底物理删除」会破坏其他用户作品的来源链，不要这样答复用户。

## 10. 公告

`/admin/announcements` 下发站内公告与维护公告。维护公告会在 C 端顶部醒目展示——发布前确认时间窗与文案，撤下也要走同一入口。

## 附：本地重建一套干净环境

```bash
make reset       # 销毁数据卷 → 重建 → 迁移 → 种子数据
```

种子账号统一密码 `Zaolang2026`，含一个被封禁账号 `driftwood@zaolang.dev`、一个卡死任务、一条悬挂预扣、一条待审批数据请求与一次降级记录——本手册每一节都能在种子数据上演练一遍。
