---
name: zaolang-credits-billing
description: Credit ledger and billing — reserve/capture/release, optimistic-lock balances, pricing, royalties, marketplace transfers, spend cap, mock checkout/webhook, redemption codes, reconciliation. Use when touching back/app/domain/credits, /v1/credits/*, admin ledger/redemption or the billing page.
---

# Credit Ledger & Billing

**Scope**: the only money path. `CreditLedgerEntry` is append-only; `CreditAccount` balances are its cache; every change goes through `_apply`.
Not here → `zaolang-generation-jobs` (when jobs reserve/settle), `zaolang-platform-config` (pricing/royalty/marketplace config), `zaolang-domain-licensing-lineage` (unlock rules).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/credits/service.py` | `grant`/`purchase`/`reserve`/`capture`/`release`/`adjust`/`royalty_transfer`/`access_transfer` → `_apply`; `list_ledger` (raw), `list_billing_history` (projection); `set_monthly_spend_limit`, `remaining_monthly_spend`; `SIGNUP_GRANT_CREDITS` |
| `back/app/domain/credits/pricing.py` | `quote()` (`DEFAULT_TIER_PRICING` = fallback only), `settlement_credits()` |
| `back/app/domain/credits/` | also `royalty.py` (`plan_royalties` pure, `distribute`), `reconciliation.py` (`build_report`), `redemption.py` (`create_code`/`redeem`, `INVITE`/`PROMO`) |
| `back/app/api/v1/credits.py` | balance, `PUT /credits/spend-limit`, ledger, packages, redeem, checkout (`/credits/checkout`, `/checkout/{ref}`, `/checkout/confirm`), HMAC webhook `/webhooks/payments/mock` |
| `back/app/api/v1/admin/ledger.py` | admin ledger, reconciliation (`?refresh=`), `/credits/dangling` (`DANGLING_WARNING_HOURS = 2`), `/users/{id}/credits/adjust` |
| `back/app/api/v1/admin/redemption.py` | `/redemption-codes` list/create/deactivate/records |
| `front/src/app/[locale]/(site)/billing/page.tsx` | billing page; `billing/mock-checkout/page.tsx` confirms an intent via `/checkout/confirm` |
| `front/src/components/billing/` | `ledger-table.tsx`, `spend-limit-form.tsx`, `credit-packages.tsx`, `redeem-code-form.tsx` |
| `front/src/components/admin/credits/` | `ledger-console.tsx`, `dangling-reserves.tsx`, `redemption-codes-panel.tsx` |

## Invariants

1. One `reserve` → exactly one `capture` or `release`: `uq_credit_ledger_job_type` on `(job_id, type)` (no account in key) → `back/app/models/credits.py`.
2. `_apply` puts `version` (+1 per write), `available + delta >= 0`, `reserved + delta >= 0` and the spend cap in the UPDATE's WHERE; 0 rows → `Conflict`, except that `capture` / `release` pass `recheck` and retry up to `STALE_ACCOUNT_ATTEMPTS` against a refreshed row (re-checking the job is still unsettled first — `(job_id, type)` alone would let a capture and a release both land), so sibling jobs of one user settling at once never fail a finished job (`tests/concurrency/test_credit_races.py::test_sibling_jobs_settling_at_once_both_capture`). Never move these into Python only. DB `CheckConstraint`s back them up.
3. `capture` charges `min(actual, reserved)`; the rest returns to available.
4. Post once: unique `payment_reference` (purchase), global unique `idempotency_key` (grant/adjust/transfers). Key formats: `signup:{user}`, `redemption:{record}`, `royalty:{version}:out|in:{to}`, `access:{buyer}:{type}:{id}:out|in`. Webhook: `X-Signature` HMAC over `timestamp.raw_body`, `X-Timestamp` within `WEBHOOK_TOLERANCE_SECONDS`, `WebhookEvent` event-id dedupe. `/checkout/confirm` (mock page; browser never holds the secret) reuses `purchase` + `payment_reference`, so it can't double-credit with the webhook. `checkout` itself grants nothing.
5. `IntegrityError` in `_apply` → `session.rollback()` of the whole unit of work; callers must not reuse earlier flushed objects (hence `committed_db` in `back/tests/conftest.py`).
6. Admin adjust appends an `adjustment` with reason + actor + audit; route needs `Operator` + `AdminDangerous` + `require_confirmation`.
7. Royalties (`publishing.service._pay_royalties`, config `royalty` → `RoyaltyRule`): base = draft's latest job `actual_credits or quoted_credits`; `ancestor_author_ids` dedupes and drops the payer; capped by `total_cap_bps`. Best-effort = a leg the payer can't cover is skipped (`royalty_transfer` → `None`), never blocks publish; each paid leg posts `royalty_out` + `royalty_in`.
8. `access_transfer` must succeed or fail whole: buyer pays `price`, seller gets `seller_net`, fee burned (`price == seller_net + platform_fee`); never reuse `royalty_transfer`.
9. `GET /v1/credits/ledger` = `list_billing_history` projection: stored capture/release hidden, reserve shown as hold / settled amount / zero release. `BillingLedgerRow` is never persisted; admin + reconciliation read raw `list_ledger`.
10. Monthly cap `monthly_spend_limit` (null = none; setting it writes no ledger row) counts generation reserves per UTC month (`spend_period`, `period_spent`; period stamped in the reserve's metadata) inside `_apply`'s WHERE; release/capture refund only within the same month. `jobs.service.submit` pre-checks (skipped for sandbox jobs) → `SpendLimitExceeded` (402), distinct from `InsufficientCredits` (402) and `CreditsExceedBudget` (409).
11. Prices come from config `pricing` (`tier_pricing`, `video_base_seconds`, `video_per_second_surcharge`), never hardcoded. `output_count` multiplies base price only. `settlement_credits` refunds only a short delivery, min 1: a short video pro rata by duration, or a partly delivered multi-pass image job (`requested_outputs`/`delivered_outputs`) as `reserved * delivered // requested`.
12. `quote:batch` (`back/app/api/v1/jobs.py`) sums the same per-line `quote_for` — exact total, never a range — and returns `period_remaining` / `within_spend_limit`.
13. Redemption: `redeem` claims a use with a conditional UPDATE (`used_count < max_uses`), one record per user (`uq_redemption_records_code_user`), then `grant`. Inactive/expired → `Conflict`.
14. Two reconciliation metrics: `find_dangling_reservations` (unsettled reserve on a terminal job = bug) vs `/credits/dangling` (older than 2h, any status = ops signal). They differ by design. `build_report` persists a `ReconciliationReport`; Beat runs `reconcile_credits` hourly on `webhook_reconcile`; admin reads the latest unless `refresh=true`.

## Recipes

**Add a ledger entry type**: `LedgerEntryType` value → thin wrapper calling `_apply` with explicit deltas → decide if it belongs in `reconciliation.EXTERNAL_TYPES` → property-test invariants → label in `ledger-table.tsx` + copy. `REFUND` exists with no wrapper: add `refund()` before first use.

**Wire a real payment provider**: extract webhook verification from `credits.py` into an adapter; posting still via `purchase` with unique `payment_reference`.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_credits_invariants.py tests/unit/test_credits_properties.py tests/unit/test_credit_spend_limit.py tests/unit/test_royalty_and_pricing.py tests/unit/test_settlement_pricing.py tests/unit/test_access_marketplace.py tests/concurrency -v
cd back && conda run -n zaolang pytest tests/integration/test_billing_webhook.py tests/integration/test_credit_spend_limit_api.py tests/integration/test_access_marketplace.py tests/integration/test_redemption.py -v
```
Always run `tests/concurrency` after ledger changes.
