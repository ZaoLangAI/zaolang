# zaolang-frontend-ui — studios reference

Generation studios under `front/src/components/studio/`, the `/jobs/[jobId]` page, and per-draft version history. Script clip studio (`features/script/script-clip-studio.tsx`) reuses these pieces — see zaolang-editor-drama. There is no image studio (AC-8): images are generated in the card workspaces (`front/src/features/asset-workspace/`, zaolang-creation-library).

## Dispatch

| Entry | Picks |
|---|---|
| `front/src/app/[locale]/(site)/create/new/page.tsx` | `?mode=` (`MODES`: video_creation / audio_generation / music_generation) → base operation; unknown mode → `video_creation`; a leftover `image_creation` redirects (draft → `imageDraftHref`, else `/create`) |
| `front/src/components/studio/create-studio.tsx` | `CreateStudio` — one `next/dynamic` per studio so only the mounted studio's chunk loads |
| `front/src/app/[locale]/(site)/remix/[workId]/page.tsx` | `media_type ?? current_version.media_type`: audio → Audio; image → Video with `operation="image_to_video"` (the studio's `sourceMaterialSeededRef` seeds the source image as the reference and first frame); else Video with `operation="video_to_video"` |

## Studios

| File | Notes |
|---|---|
| `front/src/components/studio/video-generation-studio.tsx` | `text_to_video` → `image_to_video` on first frame; reference mode; 视频用途 `OptionGroup` |
| `front/src/components/studio/audio-generation-studio.tsx` | TTS voice (`'voice'` model preset, `'character'` owned/unlocked character card `voice_profile_id` with `VoicePlayButton` preview, `'clone'` reference sample + voice consent); full `useStyleAndSkillPicker` incl. creation-skill Select |
| `front/src/components/studio/music-generation-studio.tsx` | BGM / SFX (`audio_style`, lyrics, instrumental); separate shell because billing + inputs differ from audio |

## Shared pieces

| File | What |
|---|---|
| `front/src/components/studio/generation-studio-shell.tsx` | layout (rail / preview / params, mobile `Sheet`); `previewSlot` = inline result, `promptSlot` = composer. Params `children` mount in exactly one place: the aside yields them while the sheet is open (`panelInAside`), else portalled dialogs (style gallery) open twice |
| `front/src/components/studio/prompt-composer.tsx` | card around `PromptField`: skill chips/unlock dialog, optional `tip` (video/audio fold 写得更像导演 copy here) |
| `front/src/components/studio/prompt-field.tsx` | textarea + counter (`STUDIO_PROMPT_MAX_LENGTH` in `front/src/lib/prompt-limits.ts`); `skillMention` = `@` apply menu (video) |
| `front/src/components/studio/prompt-polish.tsx` | AI 润色 (video + clip studio, `polishContext`): inline `prompt-polish-panel.tsx`, never a drawer; may ask `QuestionField`s |
| `front/src/components/studio/use-applied-skills.tsx` | fetches public `template` + `image_asset` skills, `POST /v1/skills/{id}/apply`; plaza `?skillId=` seeded once |
| `front/src/components/studio/style-and-skill-picker.tsx` | `useStyleAndSkillPicker` — style preset / 画风库; video passes `showCreationSkillSelect: false` |
| `front/src/lib/use-generation-submit.ts` | debounce, login wall, draft create/reuse, idempotency; `onSubmitted` suppresses `router.push('/jobs/{id}')` |
| `front/src/lib/use-generation-models.ts` | 指定模型 picker: `GET /v1/generation-jobs/models?operation=`; `[]` while signed out or outside `FORCED_MODEL_OPERATIONS` |
| `front/src/components/studio/generation-resolution.ts` | `adaptStudioResolution` previews the tier a forced model will get (down first, else lowest supported) |
| `front/src/components/studio/studio-submit-busy.ts` | video + script clip lock 生成 while submitting, polishing, or any draft job non-terminal |
| `front/src/components/studio/inline-video-result.tsx` | video result: 进入剪辑 (flag `web_editor`), 下载, 基于此视频继续创作, 关联到剧集 (`link-episode-dialog.tsx`) |
| `front/src/components/studio/generation-version-history.tsx` | flat chronological draft jobs; 当前 = `appliedJobId`; 设为当前 / 删除 via draft `applied-version` / `versions` APIs |
| `front/src/components/studio/generation-version-select.ts` | clicking a version fills submitted `job.prompt` (not planner text); video also duration + 视频用途 |
| `front/src/components/job/promote-job-dialog.tsx` | 升级为标准/电影档 on a succeeded `preview` job; quotes first, sends `max_credits` |

## Rules

1. Video submits pass `onSubmitted` and stay in the studio; audio/music navigate to `/jobs/{id}`. Result/version UIs live only in `previewSlot`.
2. One draft = one version history: later submits reuse `draftId` (`GenerationSubmitInput.draftId`). Resume picks `?jobId=` > `applied_job_id` > `latest_job_id` (field semantics: `zaolang-data-model`). History writes: `POST /v1/drafts/{id}/applied-version`, `DELETE /v1/drafts/{id}/versions/{jobId}` (tombstone).
3. Links: notification click-through = `draftId`+`jobId`; draft cards / breakpoint chips = `draftId` only (`draftResumeHref` in `front/src/components/collection/library-tabs.tsx`). Never fold `returnTo` into either.
4. Video resume never auto-attaches its output as a reference (that would silently turn a prompt tweak into `video_to_video`); only "Continue creating from this video" ("基于此视频继续创作") does. Image "Use as reference" ("用作参考") replaces `uploads`; video appends.
5. Shot continuity is manual (`frame_images` mode). `continuitySourceAssetId` is accepted for stale links only — don't re-add on-mount frame extraction.
6. Video params stay provider-safe: `DURATIONS` 4–15 s; aspects `LANDSCAPE_ASPECTS` / `PORTRAIT_ASPECTS` / `adaptive`, no `1:1`; tiers `480p/720p/1080p/2K`. A video remix omits `resolution`. Uploads pass platform `Asset.id` only. Vendor mapping: `zaolang-agent-gateway`.
7. **Card workspaces & studio reference pickers**: Scene presets and look extras live on the card workspaces and graph inspectors (`front/src/features/image-assets/`: `vocabulary.ts`, `chip-group.tsx`, `scene-variants.ts:sceneVariantCombos`; `components/library/scene-preset-fields.tsx`). The video studio's reference pickers cover characters, scenes, and props (`prop_ids` + `prop_ref_selection`, default preview `defaultPropReferenceIds`), ≤4 each; `?referenceCharacterIds=` / `referenceSceneIds` / `referencePropIds` preselect the viewer's own cards (plaza asset-card CTA). Its optional reference emotion ("参考情绪") select sends `reference_emotion` once a character is picked; the backend's shot/emotion ranking only reorders defaults, so the picker's default preview (`defaultCharacterReferenceIds`) does not mirror it. The scene library's variants sheet adds batch matrix generation ("批量变体", `front/src/components/scenes/scene-matrix-dialog.tsx`): per-axis chips, a debounced `variants:matrix` dry run whose plan is only shown and submittable for the picks it was made for, then one submit with one idempotency key; past 8 variants the tab row gets a name filter.
8. **Per-card reference image picks**: `front/src/components/studio/reference-image-picker.tsx` (`ReferenceImagePicker` + `useReferencePicks`) mounts under each checked character/scene/prop in the video and clip studios; defaults mirror the backend (`defaultCharacterReferenceIds`/`defaultSceneReferenceIds`/`defaultPropReferenceIds`) and only a modified selection is sent as `character_ref_selection`/`scene_ref_selection`/`prop_ref_selection`.
9. **`@`-mention & plaza skill CTAs**: `@` mention applies only free/owned skills whose `applicable_operations` include the current op (templates: empty = any); image-asset recipes need a declared, matching op list. Plaza CTAs deep-link with `?skillId=` — never POST `/apply` there (double-counts usage): an image-only template links to `/create/{characters,scenes,props}?skillId=` (`CarriedStyleSkill` applies it once; card links carry it; the Creation slot panel preselects it), and everything else links to the video studio (`videoCreationHref`).
10. **Script studio jump-out convention**: Jump-out from script studio to video studio passes `subjectNameHint`, `linkEpisodeId`, `linkBreakpointKey`, and `continuityAssetId`. The retired image studio's `returnTo` / `returnLinkKind` / `returnLinkLabel` trio and link-back are gone; the script link picker creates and links cards directly.
11. **Job page redirects**: `jobs/[jobId]/page.tsx` redirects a video job with `draft_id` to its studio and an asset image job to its card workspace (`assetWorkspaceHref`); `JobProgress` stays for audio/music, draftless jobs, and general / cover images (read-only: no retry / promote, "Go to publish" ("去发布") kept).
12. **Scene heading preset parsing**: `front/src/features/script/scene-heading.ts:parseScenePresets` parses interior/exterior (`内`/`外`), time of day (`日`/`夜`/`晨`/`黄昏`), and weather (`雨`/`雪`/`雾`) from a script scene heading (falling back to its `scene` blocks without rewriting the heading). The in-page batch sends them as `assetPresets` (`scene_lighting`/`scene_weather`).
