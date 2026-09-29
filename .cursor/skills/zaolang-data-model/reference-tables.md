# Data Model — per-module table reference

Class lists drift; `grep -n "^class " back/app/models/<module>.py` is authoritative. Notes below are the non-obvious column rules.

| Module | Tables / notes |
|---|---|
| `back/app/models/identity.py` | `User` (preferences `theme`/`locale`/`region`, `roles` array, `age_gate_confirmed_at`), `Profile` (display fields, `reduce_motion`), `Follow` |
| `back/app/models/works.py` | `Work` (`trashed_at` recycle bin), `WorkVersion`, `LicenseSnapshot`, `LineageEdge`, `Draft`, likes/bookmarks/collections/tags, `StylePreset`, `PublicationIntent` |
| `back/app/models/generation.py` | `Workflow(Version)`, `GenerationWorkflowTemplate`, `GenerationJob`, `JobEvent`, `ProviderAttempt`, `ProviderStat`, `AgentRun` |
| `back/app/models/credits.py` | `CreditAccount`, `CreditLedgerEntry`, `CreditPackage`, `PaymentIntent`, `WebhookEvent`, redemption codes/records |
| `back/app/models/media.py` | `Asset`, `UploadSession`, `AssetConsent`, `ContentFingerprint`, `ProvenanceManifest` |
| `back/app/models/platform.py` | moderation, reports/appeals, `Notification`, `Device`, `PlatformConfig`, `AuditLog`, `IdempotencyRecord`, announcements, data requests, backups, reconciliation |
| `back/app/models/characters.py` | `Series` (`kind`, drama form fields, `trashed_at`), `SeriesCollaborator` |
| `back/app/models/editor.py` | `DramaEpisode`, `EpisodeContentLink`, cuts/revisions/exports, `EpisodeScriptTurn`, `EpisodeBlockingVersion`, `EditPlan`, `DeliveryVariant`, `MediaAnalysis`, `EditorLease`, editor event logs, `McpTokenGrant` |
| `back/app/models/canvas.py` | six canvas tables → `zaolang-canvas` |
| `back/app/models/skill_library.py` | `CreationSkill` (templates, characters, scenes, covers) |
| other modules | `distribution.py` (off-platform accounts + metrics), `search.py` (`WorkEmbedding`, pgvector), `agent_skills.py` (`AgentNode`/`AgentProfile`/`AgentSkill`), `async_tasks.py` (`AsyncProviderTask`), `workflow_input.py`, `style_gallery.py`, `learning.py`, `system_log.py`, `access.py` (`AccessGrant`) |

## Column rules worth knowing

1. `Draft.publish_status` is `pending`/`rejected`/NULL; success is `published_work_id`, not a third status. Don't reuse `PublicationIntent` (post-publish off-platform distribution) for draft publishing.
2. `GenerationJob` nullable pointers without FK: `linked_character_id` / `linked_scene_id` (at most one set), `promoted_from_job_id` (only set by promote; distinct from `retry_of_job_id`), `draft_history_hidden_at` (tombstone timestamp).
3. `AgentRun.thinking_text` / `EpisodeScriptTurn.thinking_text` hold raw reasoning; never stuff it into `output_json`.
4. `WorkflowInputRequest` is unique per `job_id` and deliberately separate from `AsyncProviderTask`.
5. `DramaEpisode`: unique `uq_drama_episodes_series_season_number` over `(series_id, season_number, episode_number)`; `episode_kind` (`EpisodeKind`) is unrelated to `Series.kind`; `preview_asset_id` and `Series.logo_asset_id` FK `assets` with `ondelete=SET NULL`.
6. `Series.genre_tags_json` holds `SeriesGenre` values; `target_platforms_json` holds `DistributionChannel` values.
7. `CreationSkill` character/scene structured content lives under `params_json["character"]` / `params_json["scene"]`, separate from template keys (`prompt`, `prompt_suffix`, …).
8. `canvas_changes` has no `TimestampMixin`; `canvas_edges` has no `revision`.
9. `MediaGenerationKind` (`create`/`edit`) is an enum used in platform-config JSON, not a DB column.
