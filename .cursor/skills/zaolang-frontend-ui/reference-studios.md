# zaolang-frontend-ui — studios reference

Generation studios under `front/src/components/studio/`, the `/jobs/[jobId]` page, and per-draft version history. Script clip studio (`features/script/script-clip-studio.tsx`) reuses these pieces — see zaolang-editor-drama.

## Dispatch

| Entry | Picks |
|---|---|
| `front/src/app/[locale]/(site)/create/new/page.tsx` | `?mode=` (`MODES`: image_creation / video_creation / audio_generation / music_generation) → base operation; unknown mode → `video_creation` |
| `front/src/components/studio/create-studio.tsx` | `CreateStudio` — one `next/dynamic` per studio so only the mounted studio's chunk loads |
| `front/src/app/[locale]/(site)/remix/[workId]/page.tsx` | `media_type ?? current_version.media_type`: image → Image, audio → Audio, else Video with `operation="video_to_video"` |

## Studios

| File | Notes |
|---|---|
| `front/src/components/studio/image-generation-studio.tsx` | `text_to_image` → `image_to_image` once a reference is attached; asset kind (`ASSET_KINDS`) + target + auto-attach |
| `front/src/components/studio/video-generation-studio.tsx` | `text_to_video` → `image_to_video` on first frame; reference mode; 视频用途 `OptionGroup` |
| `front/src/components/studio/audio-generation-studio.tsx` | TTS voice; full `useStyleAndSkillPicker` incl. creation-skill Select |
| `front/src/components/studio/music-generation-studio.tsx` | BGM / SFX (`audio_style`, lyrics, instrumental); separate shell because billing + inputs differ from audio |

## Shared pieces

| File | What |
|---|---|
| `front/src/components/studio/generation-studio-shell.tsx` | layout (rail / preview / params, mobile `Sheet`); `previewSlot` = inline result, `promptSlot` = composer. Params `children` mount in exactly one place: the aside yields them while the sheet is open (`panelInAside`), else portalled dialogs (style gallery) open twice |
| `front/src/components/studio/prompt-composer.tsx` | card around `PromptField`: skill chips/unlock dialog, optional `tip` (video/audio fold 写得更像导演 copy here) |
| `front/src/components/studio/prompt-field.tsx` | textarea + counter (`STUDIO_PROMPT_MAX_LENGTH` in `front/src/lib/prompt-limits.ts`); `skillMention` = `@` apply menu (image/video) |
| `front/src/components/studio/prompt-polish.tsx` | AI 润色 (image/video, `polishContext`): inline `prompt-polish-panel.tsx`, never a drawer; may ask `QuestionField`s |
| `front/src/components/studio/use-applied-skills.tsx` | fetches public `template` + `image_asset` skills, `POST /v1/skills/{id}/apply`; plaza `?skillId=` seeded once |
| `front/src/components/studio/style-and-skill-picker.tsx` | `useStyleAndSkillPicker` — style preset / 画风库; video passes `showCreationSkillSelect: false` |
| `front/src/lib/use-generation-submit.ts` | debounce, login wall, draft create/reuse, idempotency; `onSubmitted` suppresses `router.push('/jobs/{id}')` |
| `front/src/lib/use-generation-models.ts` | 指定模型 picker: `GET /v1/generation-jobs/models?operation=`; `[]` while signed out or outside `FORCED_MODEL_OPERATIONS` |
| `front/src/components/studio/generation-resolution.ts` | `adaptStudioResolution` previews the tier a forced model will get (down first, else lowest supported) |
| `front/src/components/studio/studio-submit-busy.ts` | video + script clip lock 生成 while submitting, polishing, or any draft job non-terminal |
| `front/src/components/studio/inline-image-result.tsx` | image result in `previewSlot`: `OutputGallery`, cancel/retry/promote, awaiting-input panel, 用作参考, return button |
| `front/src/components/studio/inline-video-result.tsx` | video result: 进入剪辑 (flag `web_editor`), 下载, 基于此视频继续创作, 关联到剧集 (`link-episode-dialog.tsx`) |
| `front/src/components/studio/generation-version-history.tsx` | flat chronological draft jobs; 当前 = `appliedJobId`; 设为当前 / 删除 via draft `applied-version` / `versions` APIs |
| `front/src/components/studio/generation-version-select.ts` | clicking a version fills submitted `job.prompt` (not planner text); video also duration + 视频用途 |
| `front/src/components/studio/save-cover-as-skill-dialog.tsx` | 另存为可分享技能 for succeeded `asset_kind=cover` / `video_asset_kind=cover_video` |
| `front/src/components/job/promote-job-dialog.tsx` | 升级为标准/电影档 on a succeeded `preview` job; quotes first, sends `max_credits` |

## Rules

1. Image/video submits pass `onSubmitted` and stay in the studio; audio/music navigate to `/jobs/{id}`. Result/version UIs live only in `previewSlot`.
2. One draft = one version history: later submits reuse `draftId` (`GenerationSubmitInput.draftId`). Resume picks `?jobId=` > `applied_job_id` > `latest_job_id` (field semantics: zaolang-data-model). History writes: `POST /v1/drafts/{id}/applied-version`, `DELETE /v1/drafts/{id}/versions/{jobId}` (tombstone).
3. Links: notification click-through = `draftId`+`jobId`; draft cards / breakpoint chips = `draftId` only (`draftResumeHref` in `front/src/components/collection/library-tabs.tsx`). Never fold `returnTo` into either.
4. Video resume never auto-attaches its output as a reference (that would silently turn a prompt tweak into `video_to_video`); only 基于此视频继续创作 does. Image 用作参考 replaces `uploads`; video appends.
5. Shot continuity is manual (`frame_images` mode). `continuitySourceAssetId` is accepted for stale links only — don't re-add on-mount frame extraction.
6. Video params stay provider-safe: `DURATIONS` 4–15 s; aspects `LANDSCAPE_ASPECTS` / `PORTRAIT_ASPECTS` / `adaptive`, no `1:1`; tiers `480p/720p/1080p/2K`. A video remix omits `resolution`. Uploads pass platform `Asset.id` only. Vendor mapping: zaolang-agent-gateway.
7. Image studio has no style-preset picker; `character` produces one multi-panel sheet (no per-view picker) unless expressions are picked. Don't add separate text/image-to-image/edit cards — asset kind is the axis. Kind-specific extras live in `front/src/components/studio/asset-preset-fields.tsx`: `CharacterPresetFields` (expression multi-select → one composite image, auto-attach defaults off; outfit name, disabled while expressions are picked) and `ScenePresetFields` (lighting/weather/state/period, plus a variant set varying one axis 2–4 values (one image per variant, generated in sequence); `sceneVariantCombos` builds `scene_variants`, quoted via `GenerationQuoteInput.sceneVariants`). A scene preset on a picked target attaches its master plate (`sceneHeroAsset`) as reference 1. Presets ride `GenerationSubmitInput.assetPresets` and `PromptPolishContext.assetPresets`. The video studio's optional 参考情绪 select sends `reference_emotion` once a character is picked; the backend's shot/emotion ranking only reorders defaults, so the picker's default preview (`defaultCharacterReferenceIds`) does not mirror it.
7a. Reference picks: `front/src/components/studio/reference-image-picker.tsx` (`ReferenceImagePicker` + `useReferencePicks`) under each checked character/scene in the video and clip studios; defaults mirror the backend (`defaultCharacterReferenceIds`/`defaultSceneReferenceIds`) and only a changed pick is sent as `character_ref_selection`/`scene_ref_selection`.
8. Scene polish gate: while `assetKind === 'scene'`, an unanswered required polish question (`onPolishBlockedChange`) blocks submit and shows `remixPage.scenePolishBlockedHint`.
9. `@` mention applies only free/owned skills whose `applicable_operations` include the current op (templates: empty = any); image-asset recipes need a declared, matching op list. Plaza CTAs deep-link with `?skillId=` — never POST `/apply` there (double-counts usage).
10. Jump-out convention (character/scene library, script studio → image studio → back): `returnTo` / `returnLinkKind` / `returnLinkLabel` / `subjectNameHint` / `linkRefId`. Trio persisted on `Draft.params` via `draftReturnParams`, restored with `readDraftReturnContext` (`front/src/lib/studio-session.ts`). Reuse these names.
11. `jobs/[jobId]/page.tsx` redirects an image/video job with `draft_id` to its studio; `JobProgress` stays for audio/music and draftless jobs.
12. Scene heading presets: `front/src/features/script/scene-heading.ts:parseScenePresets` reads 内/外 + 日/夜/晨/黄昏 (+雨/雪/雾) off a script scene heading (falling back to its `scene` blocks; never rewrites the heading). The script jump-out adds `sceneLighting`/`sceneWeather` URL params (validated on `/create/new`, part of `studioSessionKey`) and the in-page batch sends them as `assetPresets` (`scene_lighting`/`scene_weather`).
