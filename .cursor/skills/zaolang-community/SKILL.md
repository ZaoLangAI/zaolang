---
name: zaolang-community
description: Community — learning posts (/v1/learn/posts), notifications + SSE stream + APNs device registry, profiles, bookmarks/trash, collections, follows, reports. Use when editing learning/notifications domains, community.py, devices.py, profiles.py, or learn/notifications/profile/collection pages.
---

# Community

**Scope**: non-generation social surfaces — reviewed tutorial posts, notification inbox/stream/push, profiles, collections, follows, reports.
Not here → `zaolang-discovery-search` (style presets in `community.py`), `zaolang-generation-jobs` (job-side publisher), `zaolang-admin-ops` (learn review, report handling), `zaolang-ios-client` (push consumer), `zaolang-frontend-ui` (notification center UI).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/learning/service.py` | submit/update/withdraw/get_visible/list_*/approve/reject, `ensure_catalog_posts` |
| `back/app/domain/learning/catalog.py` | seeded tutorial `CATALOG` (covers in sibling `seed_covers/`) |
| `back/app/api/v1/learning.py` | `/v1/learn/posts` (+ `/mine`, `/{id}`, `/{id}/withdraw`) |
| `back/app/presenters/learn_body.py` | `resolve_body_asset_urls`: `learn-asset:` ids → fresh signed URLs |
| `back/app/domain/notifications/push.py` | `notify`, `sync_*_notification` upserts, `present_notification`, `send_push` stub |
| `back/app/api/v1/community.py` | collections, notifications (list/unread-count/read/stream), follow, `POST /reports` |
| `back/app/api/v1/devices.py` | `POST /v1/me/devices`, `DELETE /v1/me/devices/{id}` |
| `back/app/api/v1/profiles.py` | `/profiles/{handle}` (+ `/works`), `/me/trash`, `/me/bookmarks` |
| `back/app/models/platform.py` | `Notification` (`uq_notifications_user_creation_target`), `Device`, `ReportCase`; also `learning.py` `LearnPost`, `identity.py` `Profile`/`Follow`, `works.py` `Collection*`/`Bookmark` |
| `front/src/app/[locale]/(site)/learn/` | list, `[postId]`, `publish` (`?edit=`) |
| `front/src/components/learn/` | publish form (MDXEditor, dynamic `ssr:false`), `learn-body-view.tsx` |
| `front/src/components/notifications/notification-format.ts` | `GROUPS`, `TITLE_KEYS`, `CREATION_TARGET_TYPES`, `targetHref` |
| `front/src/components/collection/` | `/collection` tabs (`TABS` in `library-tabs.tsx`), collection dialogs |
| `front/src/components/profile/` | `profile-header.tsx` (follow toggle), `activity-feed.tsx` |

## Invariants

1. Learn `submit`/`update` passes the `learning_moderation` gate (hit → no row), then lands `PENDING` with review fields + `published_at` cleared. No queue item; `approve`/`reject` need `PENDING` (409); reject needs a reason.
2. Non-`APPROVED` posts 404 (never 403) for non-authors (`get_visible`). `list_public` sorts `published_at, id` desc; bad cursor → empty page.
3. Body images are `![](learn-asset:{id})`; cover/body assets must be the author's, role `LEARN_MEDIA` (upload `learn_media`); external image URLs 422. Caps 20 images / 20,000 chars. Signed URLs rebuilt per read, never stored.
4. `ensure_catalog_posts` matches `(author, title)`, plants `APPROVED`, never overwrites.
5. `notify()` inserts (social, moderation, sales). `sync_creation_notification` upserts one row per `(user, target_type, target_id)` for `generation_job`/`editor_export`/`episode_script`/`draft`, guarded by the partial unique index (`IntegrityError` → update). Neither commits.
6. Upserts on actionable statuses reset `read_at` and push; others update in place silently. Sandbox jobs never notify. Store `title_key` + payload, never rendered text. `present_notification` overlays live job/export state.
7. `/notifications/stream`: `sse_quota.reserve` before `StreamingResponse`; generator never touches `session`; 15 s heartbeat, 600 s cap, no `Last-Event-ID` backfill (REST list resyncs). `_publish` fires before the caller commits.
8. `send_push` only logs; `_dispatch_push` fans out to all the user's `Device`s. Devices upsert on unique `push_token` (re-register moves it); delete is owner-only (403).
9. Follow: self → 409, target needs a `Profile`; idempotent, only the first follow sends `NEW_FOLLOWER`.
10. Collections: writes owner-only (403); adding a work needs `licensing.assert_viewable` (404), idempotent (`uq_collection_items_pair`). `is_public` is unread — a future non-owner route must gate on it and filter items via `can_view`.
11. Profiles: a non-public profile 404s for others on both routes (`_visible_profile`); visitors see `ACTIVE` + public works only.
12. `POST /reports` writes `ReportCase` (`OPEN`) for `work|asset|user|comment`; `reason` must be a `ReportReason` (422); no dedupe.
13. Every `community.py`/`devices.py` route declares a `rate_limited` bucket: reads `public_read`, owner writes `authenticated_write`, follow + report `social_outreach`. `test_rate_limits.py` fails on a route without one (`profiles.py`/`learning.py` aren't walked).

## Recipes

1. **Notification kind**: `NotificationType` in `back/app/models/enums.py` → `notify()`/sync helper → `GROUPS` + `TITLE_KEYS` + `notificationBody.*` copy → iOS mapping.
2. **Upserted creation target**: `sync_*` helper over `sync_creation_notification` → extend the partial index + dedupe-then-rebuild migration (`zaolang-data-model`) → `test_creation_notifications.py` param → `CREATION_TARGET_TYPES`.
3. **Real APNs**: replace only `send_push`'s body.
4. **Learn-post field**: model + migration → `back/app/api/schemas/learning.py` → `submit`/`update` (keep `PENDING` reset) → `make openapi` → publish form + admin console.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_community.py tests/integration/test_creation_notifications.py tests/integration/test_notification_stream.py tests/integration/test_learn_posts.py tests/integration/test_devices.py tests/integration/test_rate_limits.py tests/unit/test_learning_catalog.py -q
cd front && npm run test -- src/components/notifications/notification-format.test.ts
```
