---
name: zaolang-domain-licensing-lineage
description: Who may view/remix a work — visibility, remix authorization, paid unlocks (AccessGrant), license snapshots, LineageEdge and tombstones — plus the draft → work publish transaction and trash/purge. Use when changing domain/licensing, access, lineage or publishing, drafts/works routes, or marketplace unlock UI.
---

# Licensing, Access, Lineage & Publish

**Scope**: view/remix rules, unlocks, license snapshots, lineage edges, publish, work lifecycle.
Not here → `zaolang-lineage-graph` (graph UI, diff panel), `zaolang-credits-billing` (`access_transfer`, royalties ledger), `zaolang-discovery-search` (index), `zaolang-data-model` (draft version pointers).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/licensing/service.py` | `can_view`, `can_remix`, `remix_block_reason`, `assert_remixable`, `assert_source_still_remixable`, `resolve_license_type`, `capture_license_snapshot`, `LICENSE_PERMISSIONS` |
| `back/app/domain/access/service.py` | `unlock_work` / `unlock_skill` → `_unlock`; `viewer_unlocked_work` (+ `_batch` for list pages); `normalize_access_credits` (marketplace flag + max price); `quote_unlock` (fee bps) |
| `back/app/domain/lineage/service.py` | `create_edge`, `ancestors`, `descendants`, `descendant_count` (recursive CTE), `build_tree`, `ancestor_author_ids`; `MAX_TRAVERSAL_DEPTH = 24` |
| `back/app/domain/publishing/service.py` | `create_draft`, `request_publish`, `finalize_draft_publish` (worker body), `publish`, `change_visibility`, `tombstone`, `hide`/`restore`, `trash`/`untrash`/`purge`, `list_unpublished_work_drafts` |
| `back/app/api/v1/works.py`, `back/app/api/v1/drafts.py` | Works (detail, lineage, diff, unlock, visibility, trash/purge) and drafts (create, list, publish, versions); skill unlock lives in `back/app/api/v1/skills.py` |
| `front/src/components/marketplace/` | `RemixUnlockGate` (shown on `remix_block_reason === 'needs_unlock'`), `UnlockDialog` (POST unlock with idempotency key), `AccessPriceField` |
| `front/src/components/publish/publish-form.tsx` | Publish form (pre-selects `public_remixable`) |

## Invariants

1. Model default is `PUBLIC_VIEW_ONLY`; only `PUBLIC_REMIXABLE` allows remix (`Visibility.allows_remix`). The web form pre-selects remixable on purpose — check both when changing "default".
2. `can_view`: owner or staff, else not `PRIVATE` and `ACTIVE`. Consumer routes never derive `viewer_is_staff` from a consumer session's roles (`_load_visible`, `version_diff`); staff read via `/v1/admin`.
3. `can_remix`: `ACTIVE` and (owner, or remixable and price 0 or has `AccessGrant`). Every remix entry calls `assert_remixable`: view-only → `LicenseNotRemixable` (409), unpaid → `AccessRequired` (402).
4. `_unlock` charges via `credits_service.access_transfer` with key `access:{buyer}:{subject_type}:{subject_id}`, then inserts the `AccessGrant`; a replayed/raced unlock returns the existing grant. Owner or free → no grant, no ledger row. Prices are ints; non-zero needs `marketplace_enabled`; non-remixable forces price 0 (`publish`, `change_visibility`).
5. `create_draft` asserts remixability and captures a `LicenseSnapshot` once (`zaolang_paid_remix` when priced, with `access_grant_id`). `change_visibility` is forward-only: existing remixes keep their snapshot; snapshots are never backfilled.
6. Publish re-check uses `assert_source_still_remixable` (visibility only) — never re-charges.
7. `LineageEdge` points at a `WorkVersion`, freezes the parent author and license snapshot, materialises `depth`. `child_work_version_id` is unique → one parent per version (a forest, not a general DAG).
8. `tombstone` sets `TOMBSTONE` + `PRIVATE` and keeps the row so lineage survives. `HIDDEN` (admin/moderation) and `TRASHED` (owner) are reversible and distinct. `purge` hard-deletes unless `_is_referenced` (edge, draft, snapshot or job points at a version) → tombstone. `LineageProtected` is defined but never raised.
9. `request_publish` (HTTP 202) runs synchronously: pending/has-output/`rights_confirmed` checks, source re-check, keyword block; then `publish_status=pending` + `publish_params_json` and `run_draft_publish` on `quality_check` (enqueue failure → `revert_publish_request`). `finalize_draft_publish` is idempotent: already published → re-notify only; not pending → no-op; `DomainError` → `rejected` (may resubmit). A draft publishes once.
10. `publish` order (one worker transaction): ① source re-check ② safety review (`REJECTED` aborts, `NEEDS_REVIEW` publishes + enqueues review) ③ `Work` + first `WorkVersion` ④ `publish_asset` + tags ⑤ edge + `remix_count` ⑥ `index_version` ⑦ royalties ⑧ notify ancestors. Best-effort side effects go last.
11. `WorkVersion` is immutable; today only `publish` creates one (v1). Never UPDATE a version — add one.
12. `GET /v1/drafts` (`list_unpublished_work_drafts`) is owner-scoped and drops, in SQL, drafts with another user's thumbnail or bound to a series the caller no longer owns or collaborates on (active seat).

## Recipes

**Add a visibility**: `Visibility` + `allows_remix` + `resolve_license_type` + `_visible_works` + publish form + copy.

**Add a license type**: `LicenseType` + `LICENSE_PERMISSIONS`.

**Add a publish step**: insert in `publish` at the right index; an exception rolls back the whole publish, so tolerant side effects go last.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_licensing_invariants.py tests/unit/test_lineage_invariants.py tests/unit/test_access_marketplace.py tests/integration/test_publish_flow.py tests/integration/test_access_marketplace.py tests/integration/test_drafts.py tests/integration/test_lineage_visibility.py tests/integration/test_consumer_admin_role_visibility.py tests/concurrency/test_access_races.py -v
```
