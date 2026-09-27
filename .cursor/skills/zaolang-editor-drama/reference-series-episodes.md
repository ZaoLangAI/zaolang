# Drama Editor — series & episodes reference

Series/episode management, content links, co-creation, trash, previews, distribution and the `/create/short` dashboard.

## Key Paths

| Path | What |
|---|---|
| `back/app/domain/editor/service.py` | series CRUD/trash/purge/list, episode CRUD, content links, `set_canonical_work`, preview fill, delete graph |
| `back/app/domain/editor/collaborators.py` | invite/accept/decline/remove, `is_active_member`, `MAX_ACTIVE_COLLABORATORS_PER_SERIES` |
| `back/app/domain/publishing/service.py` | `create_draft` best-effort episode link; `list_unpublished_work_drafts` seat filter |
| `back/app/domain/shortform/service.py` | `PublicationIntent` create/list/`mark_submitted`/`mark_failed` used by distribution |
| `back/app/api/v1/distribution.py` | `/v1/platform-accounts*`, `/v1/works/{id}/publications:fanout`, `/v1/works/{id}/metrics`, `/v1/drama-series/{id}/metrics` |
| `front/src/features/drama-dashboard/dashboard-shell.tsx` | `/create/short`: owned + collaborating series cards, create dialog, trash view, invites entry |
| `front/src/features/drama-dashboard/series-form-dialog.tsx` | the only writer of series-form metadata (title, English title, planned count, genres, platforms, logo) |
| `front/src/features/drama-dashboard/series-detail.tsx` | `/create/short/series/{id}`: season-grouped roster, collaborators, analytics overview, trash dialogs |
| `front/src/features/drama-dashboard/episode-panel.tsx` | `/create/short/episodes/{id}`: metadata, generated videos, 进入剪辑/继续剪辑, 最终成片, publish/analytics |
| `front/src/features/drama-dashboard/episode-delete-gate.ts` | `isEpisodeDeleteBlocked`, `isExportRecordDeletable`, `resumeEditorHref` (vitest) |
| `front/src/features/drama-dashboard/generated-video-href.ts` | `isGeneratedVideoCard`, `generatedVideoDetailHref` (draft studio vs `/work/{id}`) |
| `front/src/features/drama-dashboard/format.ts` | `SERIES_GENRES`, `TARGET_PLATFORMS`, `pascalCase` (i18n keys), `episodeStatusTone` |
| `front/src/features/drama-dashboard/distribution-api.ts` | client for distribution routes; `publish-panel.tsx`, `analytics-panel.tsx` |
| `front/src/features/drama-dashboard/series-analytics-detail.tsx` | `/create/short/series/{id}/analytics` report (+ `episode-ranking.ts`, `export-csv.ts`, `channel-metric-chart.tsx`) |
| `front/src/components/settings/platform-connect.tsx` | per-user platform OAuth (`/profile/settings?section=platforms`); callback page `/create/short/platform-callback/[channel]` |
| `front/src/components/studio/link-episode-dialog.tsx` | 关联到剧集 from a standalone video result (same `createContentLink`) |
| `front/src/components/create/recent-series.tsx` | create-hub 最近短剧 rail from `GET /v1/drama-series` |

## Model

1. `Series` (`back/app/models/characters.py`): `kind` always `drama` on write; form fields `english_title`, `planned_episode_count`, `genre_tags_json` (`SeriesGenre`), `target_platforms_json` (`DistributionChannel`, required non-empty on create), `logo_asset_id` (must be caller-owned). `character_ids_json` holds `CreationSkill` ids.
2. `DramaEpisode`: unique `(series_id, season_number, episode_number)`; `create_episode` auto-numbers within the season, collision → 422. `episode_kind` = `EpisodeKind` (main/trailer/teaser/bts/recap/other). Never build a second episode table.
3. `EpisodeContentLink`: `content_type` draft|work|editor_export, `role` candidate|reference|behind_the_scenes|final, unique `(episode_id, content_type, content_ref_id)` — re-linking updates `role` in place.
4. `content_ref_id` is not an FK: `_content_owner_user_id` walks ownership per type (export → variant → revision → cut → episode → series owner). Missing → 404, someone else's → 403.
5. `set_canonical_work` writes `DramaEpisode.canonical_work_id` (what publishing trusts; work must be caller-owned) and upserts a `role=final` link; `None` clears the column only.

## Co-creation

6. `collaborators.invite` (owner only, rate limit `series_collab_invite`): identifier with `@` not at position 0 = email, else handle (`_find_profile_by_identifier`). Creates `PENDING` + `series_collab_invited` notification; only `ACTIVE` counts in `is_active_member`.
7. Cap 20 counts `pending`+`active`. One row per `(series_id, user_id)`; re-invite resets a declined/removed row. Rows are never hard-deleted.
8. Collaborators get metadata, episode CRUD (incl. delete), content links, canonical work, script writing. Never trash/purge, timeline editor, publish, platform links or analytics. Their generation bills their own credits (`GenerationJob.user_id`).
9. `list_drama_series`: non-trash view = owned ∪ active collaborations; trash view = owner's own only.
10. `list_unpublished_work_drafts` hides drafts bound (param or content link) to series the caller lost access to; `GET /v1/drafts/{id}` stays 200.
11. UI mirrors via `DramaSeriesResponse.viewer_role`: collaborator badge, no trash/purge/analytics, invite/remove owner-only; `episode-panel.tsx` fetches the series to gate `PublishPanel`/`AnalyticsPanel` and export deletion.

## Lifecycle

12. Trash: `DELETE /v1/drama-series/{id}` → `status=TRASHED` + `trashed_at` (`Conflict` if already); `POST …/untrash`; `DELETE …/purge` needs `TRASHED` and no episodes (`series_id` is `RESTRICT`). Dialogs: `trash-series-dialog.tsx`, `purge-series-dialog.tsx`.
13. Episode delete: `purge_unpublished_editor_graph` removes exports → variants → plans → revisions (`revision_no` desc, flush per row — `parent_revision_id` self-`RESTRICT`) → cuts, unbinding drafts. Works, jobs, assets, siblings, the series stay. Sole exception: `delete_script` trashes (never purges) an owner's uncurated `/create/script` shell once its last episode is gone — see `reference-script-writing.md`.
14. UI delete is disabled only when published (`isEpisodeDeleteBlocked`), not merely because a cut exists.

## Previews

15. `resolve_episode_preview_source` order: canonical work video → draft/work content link → succeeded export → cut `source_asset_id` (short clip before a big export).
16. Auto-fill rides `create_content_link`, `set_canonical_work`, `create_cut_from_job`; never overwrites; failures swallowed in `_try_fill_episode_preview`. `PATCH /v1/drama-episodes/{id}` binds/clears by `model_fields_set` presence. `episodes_with_preview_source` batches `has_preview_source`. UI: `episode-preview-thumb.tsx`.

## Dashboard UI rules

17. New episodes come from 文案创作: 新增一集 links to `/create/script?seriesId=` — never an inline episode form.
18. A generated-video card shows only once the draft has an output; poster → clip detail, 进入剪辑 separate; 继续剪辑 appears whenever a cut exists (`resumeEditorHref` uses `cuts[0]`).
19. 添加已有视频 (`attach-generated-video-dialog.tsx`) and 关联到剧集 both call `createContentLink` on an existing draft with output.
20. Dynamic i18n keys and status badges go through `format.ts` helpers.

## Distribution & analytics

21. All distribution is owner-scoped through `app.domain.distribution`. `publish_fanout` creates one `PublicationIntent` per channel via `shortform_service.create_publication_intent` (`EXPORTED`/`READY`), then pushes and calls `mark_submitted`/`mark_failed`.
22. `PublishPanel`/`AnalyticsPanel` mount only on `episode-panel.tsx`, once `canonical_work_id` is set, for owners. Series metrics (`GET /v1/drama-series/{id}/metrics?days=`) feed `series-analytics-overview.tsx` and the detail report.
23. Route contract details: `zaolang-api-contract`.
