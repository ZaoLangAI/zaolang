---
name: zaolang-credits-billing
description: Credit ledger and billing — the three-phase reserve/capture/release flow, optimistic locking and unique keys, tier pricing and settlement, royalty payback to ancestor authors, reconciliation and dangling reservations, mock payment webhook idempotency, admin manual adjustments. Use when touching credits, the ledger, pricing quotes, settlement, royalties, payment webhooks, reconciliation, or manual credit adjustments.
disable-model-invocation: true
---

# Credit Ledger & Billing

## Scope

The single source of truth for money. The ledger is **append-only**; account balances are just its cache. Any balance change must go through `app/domain/credits/service.py` — bypassing it with a direct account UPDATE means the books stop reconciling.

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/domain/credits/service.py` | `grant` / `purchase` / `reserve` / `capture` / `release` / `adjust` / `royalty_transfer` / `access_transfer` / `list_ledger`, all funneling through the private `_apply` |
| `back/app/domain/credits/pricing.py` | `quote()` for pricing, `settlement_credits()` for actual-usage conversion |
| `back/app/domain/credits/royalty.py` | `plan_royalties` / `distribute` for payback to ancestors |
| `back/app/domain/credits/reconciliation.py` | `derive_totals` / `find_mismatches` / `find_dangling_reservations` / `build_report` |
| `back/app/domain/credits/redemption.py` | redemption-code generation/redemption (invite/coupon), internally routed through `grant` |
| `back/app/api/v1/credits.py` | balance, billing history, packages, mock payment + webhook, `POST /redeem` |
| `back/app/api/v1/admin/ledger.py` | admin ledger search, reconciliation reports, dangling reservations, manual adjustments |
| `back/tests/unit/test_credits_invariants.py` / `test_credits_properties.py` / `back/tests/concurrency/test_credit_races.py` | example-based, property-based, and race-condition test layers |

## Invariants

1. **Exactly one `reserve` eventually gets exactly one `capture` or one `release`** — never both, never twice. Enforced at the database layer by a unique constraint on `CreditLedgerEntry` for `(account_id, type, job_id)`.
2. **Balances never go negative**: `_apply` puts `version` and `available_balance + delta >= 0`, `reserved_balance + delta >= 0` all into the UPDATE's WHERE clause. Zero rows matched → `Conflict("concurrently modified")`, never a silent overdraft. **Never move these conditions into Python** — that reintroduces the check-then-act double-spend hole.
3. **Optimistic-lock `version` increments by 1 on every write**; concurrent writers have exactly one winner. The race-condition tests assert precisely "exactly one winner."
4. **`capture` caps actual usage at the reserved quote value**: whatever the provider reports costing, only the quoted amount is charged; any difference returns to available immediately.
5. **A payment posts exactly once**: `purchase` relies on a unique `payment_reference`; `grant` / `adjust` rely on a unique `idempotency_key` (globally unique, not per-account). Webhook redelivery is the norm, not an exception.
6. **A manual adjustment only appends an `adjustment` record**, always with a reason and an actor, always written to `AuditLog`. Historical records are never modified.
7. **Royalty payback is best-effort**: a failed `_pay_royalties` must not roll back the publish, but a successful one must post both sides of the entry (`royalty_out` / `royalty_in`) — the amounts must balance.
8. **A marketplace unlock is a forced transfer**: `access_transfer` posts `access_out` / `access_in` — the buyer pays the full price, the seller receives the net amount, and the platform fee is burned; insufficient balance must fail, and it must never reuse `royalty_transfer`. Credits earned this way are spendable on-platform only; there is no cash withdrawal in this version.
9. **`IntegrityError` triggers `session.rollback()`** (inside `_apply`), discarding the entire unit of work. Callers must either stop depending on previously flushed objects afterward, or commit first — a past bug here is why `tests/conftest.py`'s `committed_db` fixture exists.

## Pricing & Settlement

`quote()` reads the `pricing` section of the config center: `tier_pricing[operation][tier]` is the base price, and video adds `video_per_second_surcharge` beyond `video_base_seconds`. Change prices via config, **never via a hardcoded number in code** (see `zaolang-platform-config`).

## Reconciliation (Two Distinct Metrics)

- `find_mismatches`: account balance disagrees with the ledger replay — **this is a bug signal**.
- `find_dangling_reservations`: a reservation that's sat unsettled for too long, regardless of job status — **this is an ops signal** (a stuck job, a dead worker).

The admin reconciliation report only counts unsettled terminal jobs; `/admin/credits/dangling` counts by a time threshold. The two numbers differing is expected — don't "fix" them into agreement.

## Extension Points

- **Add a ledger entry type**: add a value to `LedgerEntryType` → add a thin wrapper in the service calling `_apply` (with explicit `available_delta` / `reserved_delta`) → cover it in the property tests' invariant assertions → add a display name to `billing/ledger-table.tsx` and the trilingual copy.
- **Wire up real payments**: the `PaymentProvider` adapter interface is already in place; mock verifies real HMAC signatures, time windows, and replay protection. Swapping in Stripe means replacing only the adapter — **posting still goes through `purchase`**.
- **Change royalty rules**: edit the config center's `royalty` section and `royalty.py`'s `plan_royalties`, mindful of the ancestor-depth cap and the total-share cap.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_credits_invariants.py tests/unit/test_credits_properties.py tests/unit/test_access_marketplace.py tests/concurrency -v
cd back && conda run -n zaolang pytest tests/integration/test_billing_webhook.py tests/integration/test_access_marketplace.py -v
```

Always run the concurrency suite after a change: the ledger's guarantees only hold when "two transactions arrive at once" — sequential tests can't prove them.
