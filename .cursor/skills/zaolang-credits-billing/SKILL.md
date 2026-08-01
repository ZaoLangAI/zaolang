---
name: zaolang-credits-billing
description: 造浪的积分账本与计费：reserve/capture/release 三段式、乐观锁与唯一键、档位报价与结算、原作者回流分成、对账与悬挂预扣、Mock 支付 webhook 幂等入账、后台人工调账。Use when touching credits, the ledger, pricing quotes, settlement, royalties, payment webhooks, reconciliation, or manual credit adjustments.
disable-model-invocation: true
---

# 积分账本与计费

## 职责

钱的唯一真相。账本是**追加式**的，账户余额只是账本的缓存。任何余额变化都必须经 `app/domain/credits/service.py`，绕过它直接 UPDATE 账户 = 对不上账。

## 关键路径

| 文件 | 内容 |
| --- | --- |
| `back/app/domain/credits/service.py` | `grant` / `purchase` / `reserve` / `capture` / `release` / `adjust` / `royalty_transfer` / `list_ledger`，核心是私有的 `_apply` |
| `back/app/domain/credits/pricing.py` | `quote()` 报价、`settlement_credits()` 实耗折算 |
| `back/app/domain/credits/royalty.py` | `plan_royalties` / `distribute` 回流分成 |
| `back/app/domain/credits/reconciliation.py` | `derive_totals` / `find_mismatches` / `find_dangling_reservations` / `build_report` |
| `back/app/api/v1/credits.py` | 余额、账单、套餐、Mock 支付与 webhook |
| `back/app/api/v1/admin/ledger.py` | 后台账本检索、对账报表、悬挂预扣、人工调账 |
| `back/tests/unit/test_credits_invariants.py` / `test_credits_properties.py` / `back/tests/concurrency/test_credit_races.py` | 例子、属性、竞态三层测试 |

## 不可破坏的不变量

1. **一次 `reserve` 最终必然恰好一次 `capture` 或一次 `release`**，不可两者都有、不可重复。数据库层由 `CreditLedgerEntry` 对 `(account_id, type, job_id)` 的唯一约束保证。
2. **余额永不为负**：`_apply` 把 `version` 与 `available_balance + delta >= 0`、`reserved_balance + delta >= 0` 全写进 UPDATE 的 WHERE。匹配 0 行 → `Conflict("已被并发修改")`，而不是静默透支。**不要把这些条件挪到 Python 里判断**，那样就变回了 check-then-act 的双花漏洞。
3. **乐观锁 `version` 每次 +1**，并发写只有一个赢家。竞态用例断言的正是「恰好一个赢家」。
4. **`capture` 对实耗封顶到预扣值**：供应商报得再多也只收报价，差额立刻回到 available。
5. **支付只入账一次**：`purchase` 靠 `payment_reference` 唯一约束；`grant` / `adjust` 靠 `idempotency_key` 唯一约束（全局唯一，不是按账户）。webhook 重投是常态，不是异常。
6. **人工调账只追加 `adjustment` 记录**，必须带理由与操作者，写 `AuditLog`。永不修改历史记录。
7. **回流分成是尽力而为**：`_pay_royalties` 失败不能让发布回滚，但成功了就必须双向记账（`royalty_out` / `royalty_in`），金额守恒。
8. **`IntegrityError` 会 `session.rollback()`**（见 `_apply`），整个工作单元被丢弃。调用方要么在其之后不再依赖之前 flush 的对象，要么先 commit——测试里这条踩过坑，`tests/conftest.py` 的 `committed_db` fixture 就是为它准备的。

## 报价与结算

`quote()` 读配置中心 `pricing` 段：`tier_pricing[operation][tier]` 为基价，视频按 `video_base_seconds` 之外的秒数加 `video_per_second_surcharge`。改价格改配置，**不要改代码里的数字**（见 `zaolang-platform-config`）。

## 对账语义（两个指标不是一回事）

- `find_mismatches`：账户余额与账本重放不一致——**这是 bug 信号**。
- `find_dangling_reservations`：预扣长期未结算，无论任务状态——**这是运维信号**（卡死任务、worker 挂了）。

后台对账报表只统计终态未结算的任务，`/admin/credits/dangling` 按时间阈值统计。两者数字不同是设计使然，不要「修」成一致。

## 改造切入点

- **加一种账本条目类型**：`LedgerEntryType` 加值 → 在 service 里加一个薄封装调 `_apply`（明确 `available_delta` / `reserved_delta`）→ 补属性测试里的不变量断言 → 前端 `billing/ledger-table.tsx` 与三语文案加显示名。
- **接真实支付**：`PaymentProvider` 适配器接口已在位，Mock 走真实 HMAC 验签、时间窗与防重放；换 Stripe 只替换适配器，**入账仍然走 `purchase`**。
- **改分成规则**：改配置中心 `royalty` 段与 `royalty.py` 的 `plan_royalties`，注意祖先层数上限与总比例上限。

## 验证

```bash
cd back && conda run -n zaolang pytest tests/unit/test_credits_invariants.py tests/unit/test_credits_properties.py tests/concurrency -v
cd back && conda run -n zaolang pytest tests/integration/test_billing_webhook.py -v
```

改完必须跑并发套件：账本的保证全是「两个事务同时来」时才成立的，顺序测试证明不了。
