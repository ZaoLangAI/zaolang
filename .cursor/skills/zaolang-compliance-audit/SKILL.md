---
name: zaolang-compliance-audit
description: 造浪的合规能力：追加式 AuditLog、用户数据导出与删除请求（删除保留创作链墓碑）、MinIO 对象生命周期策略、pg_dump 备份与恢复脚本。Use when changing audit logging, data export or deletion requests, user anonymisation, retention/lifecycle policies, or backup and restore.
disable-model-invocation: true
---

# 合规、审计与数据留存

## 职责

回答「谁在什么时候改了什么、为什么」，以及「用户要求带走或删除自己的数据时怎么办」。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/domain/audit/service.py` | `record()` / `search()`，自动带上操作者、角色、request_id、IP、UA |
| `back/app/domain/system_log/service.py` | `emit()`（窗口聚合）/ `search()`，登录失败、限流、鉴权拒绝等安全信号 |
| `back/app/domain/compliance/service.py` | `export_user_data` / `anonymise_user` / `signed_export_url` / `purge_expired_exports` |
| `back/app/api/v1/privacy.py` | 用户侧导出与删除请求入口 |
| `back/app/api/v1/admin/users.py` | 后台审批 `DataRequest` |
| `back/app/api/v1/admin/data.py` | 备份触发、生命周期策略、seed/reset |
| `infra/scripts/backup.sh` / `restore.sh` | `pg_dump` / `pg_restore`，对应 `make backup` / `make restore` |
| `back/app/models/platform.py` | `AuditLog` / `DataRequest` / `BackupRecord` |
| `back/app/models/system_log.py` | `SystemLog`（安全信号聚合投影，不替代 AuditLog） |

## 不可破坏的不变量

1. **`AuditLog` 只追加**，永不 UPDATE/DELETE。字段包含操作者、角色、目标对象、**前后值摘要**、理由、request_id、IP、UA。
2. **`SystemLog` 是旁路聚合投影**，用于高频安全信号（登录失败、限流、鉴权拒绝），窗口内计数折叠防写爆；**不替代** `AuditLog` 与各业务专表。
3. **`/v1/admin/*` 的所有写操作都必须留痕**，由审计装饰器统一处理。新增后台写接口忘了接装饰器，是这个仓库最容易犯又最难发现的错。
4. **高危操作强制理由**：调账、墓碑、封禁、配置回滚、强制终止任务、切换智能体模型、触发恢复。没有理由要 `ReasonRequired`（而不是存一个空字符串）。
5. **删除用户是匿名化，不是 DELETE**：`anonymise_user` 抹掉 PII、保留 `Work` / `WorkVersion` / `LineageEdge` 的墓碑节点。**下游二创的来源不能凭空消失**，这是创作链的完整性要求，也是 `LineageProtected` 存在的原因。
6. **导出物是有时效的**：`export_user_data` 落对象存储，只通过短时效签名 URL 交付（默认 900 秒），过期由 `purge_expired_exports` 清理。不要把导出 URL 写进邮件或日志。
7. **备份记录进 `BackupRecord`**：谁触发、结果、文件位置。恢复脚本必须显式 `--confirm`，不给「顺手执行」的机会。
8. **审计日志可检索可导出**，但导出本身也是一次审计事件。

## 改造切入点

- **加一个受审计的操作**：领域函数里调 `audit.record(...)`，`before`/`after` 只放摘要而**不放敏感原文**（密钥、密码、完整 PII）。补 `tests/integration/test_admin_security.py` 的审计断言。
- **加一种数据请求类型**：`DataRequestType` 加值 → 审批流程分支 → 后台 `data-requests-panel.tsx` 加处理入口。
- **改留存策略**：MinIO 生命周期规则在 `app/storage/s3.py` 的 `lifecycle_rules` / `put_lifecycle_rules`，后台 `lifecycle-panel.tsx` 可视化。改规则前确认不会误删已发布资产（staging 前缀与发布区必须分开）。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_compliance_audit.py tests/integration/test_admin_security.py -v
make backup          # 生成 .backups/*.dump 并记录 BackupRecord
```

手工路径：后台做一次人工调账 → `/admin/audit`（日志中心）能看到记录且带理由；对种子用户提一次删除请求并审批 → 用户匿名化后，其作品在创作链里仍是墓碑节点而不是消失。
