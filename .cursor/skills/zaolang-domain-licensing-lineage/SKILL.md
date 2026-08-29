---
name: zaolang-domain-licensing-lineage
description: Visibility and remix authorization, license snapshots, the LineageEdge graph and tombstones, and the eight-step publish transaction. Use when changing visibility rules, remix authorisation, licence snapshots, lineage edges, tombstones, draft publishing, or the royalty/notification side effects of publishing.
disable-model-invocation: true
---

# Licensing, Lineage & the Publish Transaction

## Scope

Answers three questions, and only here: who can view this work, who can remix it, and where a remix sits in the lineage graph. Publishing is the **single transaction** that turns a draft into a work, with eight steps in a strict order.

## Key Paths

| File | Contents |
| --- | --- |
| `back/app/domain/licensing/service.py` | `can_view` / `can_remix` / `assert_viewable` / `assert_remixable` / `assert_source_still_remixable` / `capture_license_snapshot` / `LICENSE_PERMISSIONS` |
| `back/app/domain/access/service.py` | credit unlocks for works/skills, `AccessGrant` buyouts, forced `access_transfer` |
| `back/app/domain/lineage/service.py` | `create_edge` / `ancestors` / `descendants` / `build_tree` / `ancestor_author_ids` / `is_referenced_by_descendants` |
| `back/app/domain/publishing/service.py` | `create_draft` / `request_publish` (HTTP accept) / `publish` (eight steps, worker) / `finalize_draft_publish` / `change_visibility` / `tombstone` |
| `back/app/models/enums.py` | `Visibility` (incl. `allows_remix`), `LifecycleStatus`, `LicenseType` |
| `back/app/api/v1/works.py`, `drafts.py` | public entry points |
| `back/tests/unit/test_licensing_invariants.py`, `test_lineage_invariants.py` | invariant tests |

## Invariants

1. **Default visibility is `PUBLIC_VIEW_ONLY`.** Only `PUBLIC_REMIXABLE` allows others to remix (`Visibility.allows_remix`); an author is never restricted on their own work.
2. **The license snapshot freezes at draft creation.** `LicenseSnapshot` records the terms, original-author attribution, and `snapshot_at` in effect at that moment; if the upstream work's license or visibility later changes, **existing remixes are unaffected** — a visibility change only applies going forward.
3. **Every remix entry point must call `assert_remixable`**, not just hide the button on the frontend. Hitting the API directly against a `public_view_only` work must raise `LicenseNotRemixable` (409). A remixable-but-unpurchased paid work raises `AccessRequired` (402). `can_remix` is true for the author themself, or for `PUBLIC_REMIXABLE` combined with either a zero price or an existing grant. That same `assert_remixable` is also the authorization to treat the source version's `primary_output` as a generation reference (`media_service.licensed_remix_source_output_id`). Re-checking at publish time only calls `assert_source_still_remixable` (visibility), and never re-charges the authorization fee. A snapshot with `access_credits > 0` uses `zaolang_paid_remix`, recording the price and grant id at that time.
4. **Tombstoning keeps the node.** `tombstone` only sets `lifecycle_status` to `TOMBSTONED` — it never deletes the row. A tombstoned work can't be viewed directly, but **remains visible as a placeholder node in the lineage graph** — otherwise a downstream work's provenance would vanish. Deleting a user is anonymisation rather than deletion, for the same reason.
5. **`LineageEdge` points at a version, not a work**, and freezes `parent_author_snapshot` and `license_snapshot_id`. If the author later renames themself, old edges still show the attribution as it was at the time.
6. **The eight publish steps run in a fixed order**: ① re-verify the source is still remixable ② pre-publish safety review ③ create `Work` + the first `WorkVersion` ④ move assets to the readable area + apply tags ⑤ create the `LineageEdge` and increment `remix_count` ⑥ write the search index ⑦ settle royalty payback ⑧ notify ancestor authors. Safety review must precede creating `Work`; the lineage edge must precede notification and royalty settlement. HTTP `POST /v1/drafts/{id}/publish` only accepts the intent (`request_publish`): keyword blocks stay synchronous (422), then the draft is marked `publish_status=pending` and `run_draft_publish` is enqueued on `quality_check`. The eight steps still run in one worker transaction in that same order — never create `Work` first and review later.
7. **A draft can publish exactly once** (`draft.published_work_id` non-null **or** `publish_status=pending` raises `Conflict`; the same `Idempotency-Key` replays 202). A `rejected` draft may be edited and submitted again. Can't publish without a generation result, and can't publish without the rights-confirmation checkbox.
8. **`WorkVersion` is immutable**: changing title/description means opening a new version, never UPDATE-ing an old one — `immutable_created_at` is the marker for this semantic.

## Extension Points

- **Add a visibility value**: add it to `Visibility` + a branch for `allows_remix` + a `resolve_license_type` mapping + the `publish-form.tsx` frontend + trilingual copy. Also update search's `_visible_works()` filter condition.
- **Add a license type**: add it to `LicenseType` + a permission entry in `LICENSE_PERMISSIONS`. **Existing snapshots are never backfilled** — a snapshot is history.
- **Add a step to publish**: insert it into the appropriate point in `publish`, remembering it all runs in one transaction — an external call failure (object storage, notifications) rolls back the whole publish, so "best-effort" side effects (royalties, notifications) go last and must be self-tolerant of failure.
- **Change lineage traversal**: `build_tree` has a `max_depth` (default 6), and `ancestors` / `descendants` both cap depth — don't remove the cap. Cycles shouldn't occur, but a long chain alone can blow up the response body.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/unit/test_licensing_invariants.py tests/unit/test_lineage_invariants.py tests/unit/test_access_marketplace.py tests/integration/test_publish_flow.py tests/integration/test_access_marketplace.py -v
```

Manual path: as `mizuki`, request a remix of `linhai`'s `public_view_only` work — must 409; remix the `public_remixable` work "Tide Above" successfully — the new node should appear in the work's lineage graph. An unpurchased paid example returns 402.
