---
name: zaolang-domain-licensing-lineage
description: Who may view/remix a work — visibility, remix authorization, paid unlocks (AccessGrant), license snapshots, LineageEdge and tombstones — plus the draft → work publish transaction. Use when changing domain/licensing, access, lineage or publishing, drafts/works routes, or marketplace unlock UI.
---

# Licensing, Access, Lineage & Publish

**Scope**: view/remix rules, unlocks, license snapshots, lineage edges, publish, work lifecycle.
Not here → `zaolang-lineage-graph` (graph UI), `zaolang-credits-billing` (`access_transfer` ledger), `zaolang-discovery-search` (index), `zaolang-data-model` (draft version pointers).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/licensing/service.py` | `can_view`, `can_remix`, `remix_block_reason`, `assert_remixable`, `assert_source_still_remixable`, `capture_license_snapshot`, `LICENSE_PERMISSIONS` |
| `back/app/domain/access/service.py` | `unlock_work` / `unlock_skill` → `_unlock`; `normalize_access_credits` (marketplace flag + max price); `quote_unlock` (fee bps) |
| `back/app/domain/lineage/service.py` | `create_edge`, `ancestors`, `descendants`, `build_tree` |
| `back/app/domain/publishing/service.py` | `create_draft`, `request_publish`, `publish`, `change_visibility`, `tombstone`, `hide`/`restore`, `trash`/`untrash`/`purge`, `list_unpublished_work_drafts` |
| `back/app/api/v1/works.py`, `back/app/api/v1/drafts.py` | Works (detail, lineage, diff, unlock, visibility, trash/purge) and drafts (create, list, publish, versions) |
| `front/src/components/marketplace/` | `RemixUnlockGate` (shown on `remix_block_reason === 'needs_unlock'`), `UnlockDialog` (POST unlock with idempotency key), `AccessPriceField` |
| `front/src/components/publish/publish-form.tsx` | Publish form (pre-selects `public_remixable`) |

## Invariants

1. Model default is `PUBLIC_VIEW_ONLY`; only `PUBLIC_REMIXABLE` allows remix (`Visibility.allows_remix`). The web form pre-selects remixable on purpose — check both when changing "default".
2. `can_remix`: `ACTIVE` and (owner, or remixable and price 0 or has `AccessGrant`). Every remix entry calls `assert_remixable`: view-only → `LicenseNotRemixable` (409), unpaid → `AccessRequired` (402).
3. `_unlock` charges via `credits_service.access_transfer` with key `access:{buyer}:{subject_type}:{subject_id}`, then inserts the `AccessGrant`. Prices are ints; non-zero needs `marketplace_enabled`.
4. `create_draft` asserts remixability and captures a `LicenseSnapshot` once (`zaolang_paid_remix` when priced). Later upstream changes don't touch existing remixes; snapshots are never backfilled.
5. Publish re-check uses `assert_source_still_remixable` (visibility only) — never re-charges.
6. `LineageEdge` points at a `WorkVersion` and freezes the parent author and license snapshot.
7. `tombstone` sets `TOMBSTONE` and keeps the row so lineage survives. `HIDDEN` (admin) and `TRASHED` (owner) are reversible and distinct; `purge` of a referenced work tombstones instead. `LineageProtected` is defined but never raised.
8. `request_publish` (HTTP 202) runs synchronously: pending/has-output/`rights_confirmed` checks, source re-check, keyword block; then `publish_status=pending` and `run_draft_publish` on `quality_check`. A draft publishes once; `rejected` may resubmit.
9. `publish` order (one worker transaction): ① source re-check ② safety review (`REJECTED` aborts, `NEEDS_REVIEW` publishes + enqueues review) ③ `Work` + first `WorkVersion` ④ `publish_asset` + tags ⑤ edge + `remix_count` ⑥ `index_version` ⑦ royalties ⑧ notify ancestors. Best-effort side effects go last.
10. `WorkVersion` is immutable — edits add a version.
11. `GET /v1/drafts` (`list_unpublished_work_drafts`) is owner-scoped and drops, in SQL, drafts with another user's thumbnail or bound to a series the caller no longer owns or collaborates on (active seat).

## Recipes

**Add a visibility**: `Visibility` + `allows_remix` + `resolve_license_type` + `_visible_works` + publish form + copy.

**Add a license type**: `LicenseType` + `LICENSE_PERMISSIONS`.

**Add a publish step**: insert in `publish` at the right index; external calls roll back the whole publish, so tolerant side effects go last.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_licensing_invariants.py tests/unit/test_lineage_invariants.py tests/unit/test_access_marketplace.py tests/integration/test_publish_flow.py tests/integration/test_access_marketplace.py -v
```
