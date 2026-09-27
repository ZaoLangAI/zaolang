---
name: zaolang-community
description: Community — learning posts (/v1/learn/posts), notifications + SSE stream + APNs device registry, profiles, bookmarks/trash, collections, follows, reports. Use when editing learning/notifications domains, community.py, devices.py, profiles.py, or learn/notifications/profile/collection pages.
---

# Community

**Scope**: user-to-user and user-to-platform surfaces that aren't generation — tutorial posts with review, the notification inbox/stream/push, profiles, collections, follows and reports.
Not here → `zaolang-discovery-search` (style presets, also in `community.py`), `zaolang-generation-jobs` (job-side publisher), `zaolang-admin-ops` (learn-post review, report handling), `zaolang-ios-client` (push consumer), `zaolang-frontend-ui` (notification center UI).

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/learning/service.py` | `submit`/`update`/`withdraw`/`get_visible`/`list_public`/`list_mine`/`approve`/`reject`, `ensure_catalog_posts` |
| `back/app/domain/learning/catalog.py` | seeded tutorial `CATALOG`; covers in sibling `seed_covers/` |
| `back/app/api/v1/learning.py` | `/v1/learn/posts` (+ `/mine`, `/{id}`, `/{id}/withdraw`) |
| `back/app/presenters/learn_body.py` | `resolve_body_asset_urls` — `learn-asset:` ids → fresh signed URLs |
| `back/app/domain/notifications/push.py` | `notify`, `sync_*_notification` upserts, `present_notification`, `send_push` stub |
| `back/app/api/v1/community.py` | collections + items, notifications (list/unread-count/read/stream), follow, `POST /reports` |
| `back/app/api/v1/devices.py` | `POST /v1/me/devices`, `DELETE /v1/me/devices/{id}` |
| `back/app/api/v1/profiles.py` | `/profiles/{handle}`, `/profiles/{handle}/works`, `/me/trash`, `/me/bookmarks` |
| `back/app/models/platform.py` | `Notification` (partial unique `uq_notifications_user_creation_target`), `Device`, `ReportCase` |
| `back/app/api/rate_limit.py` | `RULES` — community reads `public_read`, writes `authenticated_write`, follow/report `social_outreach` |
| `front/src/app/[locale]/(site)/learn/` | list, `[postId]` detail, `publish` (`?edit=`) |
| `front/src/components/learn/` | `learn-publish-form.tsx`, MDXEditor (dynamic, `ssr:false`), `learn-body-view.tsx` |
| `front/src/components/notifications/notification-format.ts` | `GROUPS`, `TITLE_KEYS`, `CREATION_TARGET_TYPES`, `targetHref` |
| `front/src/components/collection/` | `/collection` library tabs (`TABS` in `library-tabs.tsx`) and collection dialogs |
| `front/src/components/profile/` | `profile-header.tsx` (follow toggle), `activity-feed.tsx` |

## Invariants

1. Every learn-post `submit`/`update` lands in `PENDING` and clears review fields + `published_at`, after the `learning_moderation` gate (a hit writes no row). No queue item — admin flips status directly; `approve`/`reject` need `PENDING` (409), reject needs a reason.
2. Non-`APPROVED` posts 404 (never 403) for anyone but the author — `get_visible`. `list_public` sorts `published_at, id` desc; an unknown/non-approved cursor returns an empty page.
3. Body images must be `![](learn-asset:{id})`; cover and body assets must be the author's with role `LEARN_MEDIA` (upload `'learn_media'`). Caps: 20 images, 20,000 chars. Signed URLs are rebuilt per read (`asset_urls`), never stored.
4. `ensure_catalog_posts` matches `(author, title)`, plants `APPROVED` rows, never overwrites; seeded covers use role `LEARN_MEDIA` so author edits still pass ownership.
5. Two notification writes: `notify()` inserts (social, moderation, sales); `sync_creation_notification` upserts one row per `(user, target_type, target_id)` for `generation_job`/`editor_export`/`episode_script`/`draft`; the partial unique index covers all four, and a racing insert falls back to update on `IntegrityError`. Neither commits.
6. Upserts reset `read_at` and push only on actionable statuses; sandbox jobs never notify. Lists sort by `updated_at` desc and `present_notification` overlays live job/export state.
7. Store `title_key` + payload values, never rendered text — clients translate.
8. `/notifications/stream`: `sse_quota.reserve` before `StreamingResponse`; the generator never touches `session`; 15 s heartbeat, 600 s cap, no `Last-Event-ID` backfill (REST list is the resync). `_publish` fires before the caller commits.
9. `send_push` only logs; `_dispatch_push` fans out to every `Device` of the user. Devices upsert on unique `push_token`, re-registration moves the token to the caller; delete is owner-only (403).
10. Follow: self → 409, target needs a `Profile`; idempotent, only the first follow sends `NEW_FOLLOWER`.
11. Collection writes are owner-only (403). Adding a work requires `licensing.assert_viewable` for the owner (404 otherwise), is idempotent (`uq_collection_items_pair`); `position` = current item count. Cover previews skip works the owner can no longer view. `Collection.is_public` is stored but unread — no non-owner collection route exists yet; one must gate on it and still filter items via `can_view`.
12. `/profiles/{handle}` and `/profiles/{handle}/works` both 404 a non-public profile for others (`_visible_profile`); visitors' works list is `ACTIVE` + public visibilities only.
13. `POST /reports` writes a `ReportCase` (`OPEN`) for `work|asset|user|comment`; `reason` must be a `ReportReason` (422 otherwise); no dedupe.
14. Every route in `community.py` and `devices.py` declares a `rate_limited` bucket — reads `public_read`, owner writes `authenticated_write`, follow + report `social_outreach` (30 / 5 min: a follow notifies a stranger, reports are undeduped). `test_rate_limits.py` walks both routers and fails on a route without one.

## Recipes

1. **Notification kind**: `NotificationType` in `back/app/models/enums.py` → call `notify()`/sync helper → `GROUPS` + `TITLE_KEYS` in `notification-format.ts` + `notificationBody.*` copy → iOS mapping (`zaolang-ios-client`).
2. **Upserted creation target**: target constant + `sync_*` helper over `sync_creation_notification` → extend the partial unique index in `Notification.__table_args__` + a migration that dedupes then rebuilds it (`zaolang-data-model`) → add the type to the parametrized unique test in `test_creation_notifications.py` → `CREATION_TARGET_TYPES`.
3. **Real APNs**: replace only `send_push`'s body; callers stay as is.
4. **Community route**: add a `rate_limited(...)` dependency (tier per invariant 14) — the router walk test enforces it.
5. **Learn-post field**: model + migration → `back/app/api/schemas/learning.py` → `submit`/`update` (keep the `PENDING` reset) → `npm run gen:api` → `learn-publish-form.tsx` + admin console.

## Verify

```bash
cd back && conda run -n zaolang pytest tests/integration/test_community.py tests/integration/test_creation_notifications.py tests/integration/test_notification_stream.py tests/integration/test_learn_posts.py tests/integration/test_devices.py tests/integration/test_rate_limits.py tests/unit/test_learning_catalog.py tests/unit/test_moderation_domains.py -q
cd front && npm run test -- src/components/notifications/notification-format.test.ts
```

`/learn` is in the Playwright a11y page list (`npm run test:a11y`).
