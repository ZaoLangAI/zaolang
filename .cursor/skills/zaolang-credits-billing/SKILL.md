---
name: zaolang-credits-billing
description: Credit ledger and billing — reserve/capture/release, optimistic-lock balances, pricing, royalties, marketplace transfers, spend cap, mock checkout/webhook, redemption, reconciliation. Use when touching back/app/domain/credits, /v1/credits/*, admin ledger or the billing page.
---

# Credit Ledger & Billing

**Scope**: the only money path. `CreditLedgerEntry` is append-only; `CreditAccount` balances are its cache; every change goes through `_apply`.
Not here → `zaolang-generation-jobs` (when jobs reserve/settle), `zaolang-platform-config` (pricing/royalty config).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/credits/service.py` | `grant`/`purchase`/`reserve`/`capture`/`release`/`adjust`/`royalty_transfer`/`access_transfer` → `_apply`; `list_ledger` (raw), `list_billing_history` (projection); spend cap helpers |
| `back/app/domain/credits/pricing.py` | `quote()`, `settlement_credits()` |
| `back/app/domain/credits/` | also `royalty.py` (`plan_royalties`), `reconciliation.py` (`build_report`), `redemption.py` (`INVITE`/`PROMO` codes → `grant`) |
| `back/app/api/v1/credits.py` | balance, spend-limit, ledger, packages, redeem, mock checkout, HMAC webhook `/webhooks/payments/mock` |
| `back/app/api/v1/admin/ledger.py` | admin ledger, reconciliation, `/credits/dangling` (`DANGLING_WARNING_HOURS = 2`), adjust |
| `front/src/app/[locale]/(site)/billing/page.tsx` | billing page; `billing/mock-checkout/page.tsx` confirms a checkout intent |
| `front/src/components/billing/` | `ledger-table.tsx`, `spend-limit-form.tsx`, `credit-packages.tsx`, `redeem-code-form.tsx` |

## Invariants

1. One `reserve` → exactly one `capture` or `release`: `uq_credit_ledger_job_type` on `(job_id, type)` (no account in key) → `back/app/models/credits.py`.
2. `_apply` puts `version` (+1 per write), `available + delta >= 0`, `reserved + delta >= 0` and the spend cap in the UPDATE's WHERE; 0 rows → `Conflict`. Never move these into Python only.
3. `capture` charges `min(actual, reserved)`; the rest returns to available.
4. Post once: unique `payment_reference` (purchase), global unique `idempotency_key` (grant/adjust/transfers). Webhook: `X-Signature` HMAC over `timestamp.raw_body`, `X-Timestamp` window, `WebhookEvent` event-id dedupe.
5. `IntegrityError` in `_apply` → `session.rollback()` of the whole unit of work; callers must not reuse earlier flushed objects (hence `committed_db` in `back/tests/conftest.py`).
6. Admin adjust appends an `adjustment` with reason + actor + audit; route needs `Operator` + `AdminDangerous` + `require_confirmation`.
7. Royalties are best-effort (`publishing.service._pay_royalties` failure doesn't roll back publish) but post both `royalty_out`/`royalty_in`; capped by `RoyaltyRule.total_cap_bps`.
8. `access_transfer` must succeed or fail whole: buyer pays `price`, seller gets `seller_net`, fee burned; never reuse `royalty_transfer`.
9. `GET /v1/credits/ledger` = `list_billing_history` projection: stored capture/release hidden, reserve shown as hold / settled amount / zero release. `BillingLedgerRow` is never persisted; admin + reconciliation read raw `list_ledger`.
10. Monthly cap `monthly_spend_limit` (null = none) counts generation reserves per UTC month (`spend_period`, `period_spent`) inside `_apply`'s WHERE; release/capture refund only within the same month. `jobs.service.submit` pre-checks → `SpendLimitExceeded` (402), distinct from `InsufficientCredits` and `CreditsExceedBudget` (409).
11. Prices come from config `pricing` (`tier_pricing`, video surcharge), never hardcoded. `output_count` multiplies base price only. `settlement_credits` refunds only a short video, pro rata, min 1.
12. `quote:batch` (`back/app/api/v1/jobs.py`) sums the same per-line `quote_for` — exact total, never a range.
13. Two reconciliation metrics: `find_dangling_reservations` (unsettled reserve on a terminal job = bug) vs `/credits/dangling` (older than 2h, any status = ops signal). They differ by design.

## Recipes

**Add a ledger entry type**: `LedgerEntryType` value → thin wrapper calling `_apply` with explicit deltas → property-test invariants → label in `ledger-table.tsx` + copy. `REFUND` exists with no wrapper: add `refund()` before first use.

**Wire a real payment provider**: extract webhook verification from `credits.py` into an adapter; posting still via `purchase` with unique `payment_reference`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_credits_invariants.py tests/unit/test_credits_properties.py tests/unit/test_credit_spend_limit.py tests/unit/test_access_marketplace.py tests/concurrency -v
cd back && conda run -n zaolang pytest tests/integration/test_billing_webhook.py tests/integration/test_credit_spend_limit_api.py tests/integration/test_access_marketplace.py -v
```
Always run `tests/concurrency` after ledger changes.
