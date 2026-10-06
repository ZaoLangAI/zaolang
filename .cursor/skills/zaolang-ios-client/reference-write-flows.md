# iOS Client — auth & write flows reference

Paths below are relative to `ios/App/Sources/` unless they start with `ios/`.

## Login wall
- `AppEnvironment.requireAuth(actionLabel:action:)` is the only primitive. Signed in → closure runs now; signed out → `Auth/AuthSheet.swift` opens and the closure runs exactly once after login/register; cancel → closure dropped, never run silently.
- `actionLabel` is shown at the top of `AuthSheet`; pass `L10n.t("<existing key>")`, never a literal.
- Login/register capture `Set-Cookie: zl_refresh` through `AuthTransport` (the `APIClient.send` path hides response headers).

## Studio (`Create/StudioView.swift`, `Create/StudioViewModel.swift`)
- Entry is always `CreateRoute.studio(StudioMode)`:
  - `.new(operation:initialPrompt:)` — hub cards text-to-video, image-to-video; and the inspiration preview's "create with this prompt" (`.textToVideo`, prompt only, no source, no lineage).
  - No image creation: since AC-8 the API refuses a `text_to_image` / `image_to_image` job without `asset_kind` character / scene / prop (422 `IMAGE_ASSET_KIND_REQUIRED`, also on quote / retry / promote) and any new `cover`; images are generated only from a card (see Asset libraries). Should an old path still submit one, quote / submit errors show the server message (`ApiError.fallbackMessage`).
  - `.remix(sourceWorkID:)` — work detail "remix". `load()` fetches `WorkDetail` and prefills `reusableParams.prompt`/`negativePrompt`; `rightsSection` (keep-attribution checkbox) must be checked to submit.
- Always switch to the Create tab before pushing (`RootTabView.startRemix`); never push the studio onto another tab's stack.
- The hub's remix card only `selectTab(.discover)`; its learn-publish card switches to Learn and pushes `LearnRoute.publish`. `CreateRoute.publish(draftID:)` is reachable only from a draft.
- `remixOperation(for:)` follows the source medium: video → `.videoToVideo`, image → `.imageToVideo`, audio → `.audioGeneration`, unknown → `.textToVideo`. Remix is not always image-to-video.
- Quote is debounced 400ms.
- `submit()`: derive the draft title (source work title, else first prompt line capped at 200) and seed `params` with `prompt` + `operation` **before** `createDraft` — the draft caption (`DraftResponse.displayTitle`, fallback `createPage.untitledDraft`) is computed from what was stored at create time. Draft and job share one idempotency key (`idempotencyKeys.key(for: draft.id)`). Then `trackJob(id:)`.

## Asset libraries (`AssetLibrary/`)
- Hub cards 角色 / 场景 / 道具创作 → `CreateRoute.assetLibrary(AssetCardKind)` (login wall) → `AssetListView` (full `GET /v1/{characters,scenes,props}`; row = hero, name, description, completeness of the default look / variant) → `CreateRoute.assetDetail(kind:cardID:variantID:)`. New cards are made on the web (toolbar / empty-state button opens `/create/{kind}`).
- `AssetSlots` is the phone copy of `front/src/features/asset-workspace/kind-config.ts`, `camera.ts`, `completeness.ts` and `slot-jobs.ts` — change them together. Slot status: approved > pending (a graph `pending` job on this variant: `orbit` → pose slots, `panorama` → panorama, else the rest) > candidate > missing; the portrait slot shows only on the default look; completeness counts required slots. The turnaround ring reads entry poses (`camera`, else the coarse `view`; a sheet / master is 0°) at eye level.
- `approve(_:)` → `POST /v1/{kind}/{id}/entries/{entry_id}:approve` (`approveAssetEntry`), from the slot sheet's candidates or the graph tab's entry viewer.
- Primary slot only (`Slot.isPrimary`: character `portrait`, scene / prop `master`): `quotePrimary` → `POST /v1/generation-jobs/quote` with `asset_kind`; confirm dialog; `generate` submits a draftless `text_to_image` job with `AssetSlots.primaryJobParams` (prompt = name。description。non-default look description; `asset_kind` + `target_{kind}_id`, `subject_name_hint`; portrait `character_portrait` 3:4; master `target_variant_id`, scene 16:9 + `scene_*` presets, prop 1:1 + `prop_state`), `max_credits` = quote, idempotency key `asset-slot-<card>-<variant>|<slot>` reused until success; then `trackJob`, 3s poll, reload. Every other slot shows 「在网页端继续」 → `/create/{kind}/{id}?look=<variant>`.
- Removed with AC-10: the studio's character / scene target picker (`LibraryPickerSheet`) and 补全侧面/背面 (`characterViews: [.side, .back]`); turnaround views are the web workspace's camera poses.
- Reference-image editing and publishing characters / scenes / props are web-only.

## Character voices & profile (`AssetLibrary/AssetDetailViewModel.swift`, character cards only)
- `makeDefault(_:)` → voice `PATCH {make_default: true}`.
- `previewQuote` sends `dry_run: true`; `generatePreview` reuses one `AppEnvironment.idempotencyKeys` key per voice (`voice-preview-<voice id>`) until the submit succeeds, then polls `fetchGenerationJob` every 3s and reloads the graph (the backend lands the audio as `preview`).
- `saveProfile` PATCHes only name / description / voice_description — never `reference_asset_ids` (that would drop approved images via `set_members`).
- `describe()` returns a draft from linked scripts; the sheet fills the form and saving persists it. The button shows only when `script-links` is non-empty.

## Job detail (`Create/JobDetailViewModel.swift`)
- `start()` = one `refresh()`, then `startPolling()` (every 5s) and `startSSE()` in parallel. A dropped stream needs no handling — polling realigns within 5s. A terminal stage event triggers one `refresh()` for fields the stream omits (output URL, actual credits).
- `applyStreamEvent`: `eventType == "thinking"` frames only append to `liveThinking` (reset when `nodeId` changes) and never touch `lastAppliedSequence`; stage frames apply only when `sequence > lastAppliedSequence`. Undecodable frames are dropped in `jobEvents`, never ending the stream.
- `Create/AwaitingInputSection.swift` renders `awaiting_input` questions: `fetchInputRequest(jobID:)` / `answerJob(jobID:answers:)` in `APIClient+Jobs.swift`.
- `Create/CreateJobBanner.swift` reads `AppEnvironment.activeJobs` (fed by `trackJob`, 5s polling until terminal, independent of SSE); a finished job stays as a result notice for 8s or until dismissed.

## Publish (`Create/PublishView.swift`, `Create/PublishViewModel.swift`)
- Defaults: `visibility = .publicViewOnly`, `rightsConfirmed` and `aiDisclosureConfirmed` both false.
- `POST /v1/drafts/{id}/publish` returns 202 `{status: pending, draft_id}` → pop back. Never navigate to a work that doesn't exist yet.
- `Library/NotificationsViewModel.swift`: `notification.draft_published` / `draft_publish_rejected` with `target_type = draft` route to `payload.work_id` if present, else back to `CreateRoute.publish(draftID:)`.
- A `generation_job` notification / push whose payload names a card (`linked_*_id`, else `target_*_id`, plus `target_variant_id`) opens `CreateRoute.assetDetail` on that look (`AssetLibrary/AssetJobLink.swift`, mirrors web `assetWorkspaceHref`); other jobs open the job page.

## Learn publish
- `Learn/LearnPublishViewModel.swift` → `createLearnPost(_:idempotencyKey:)`. Uploaded images are appended as `![](learn-asset:<assetId>)`; `Learn/LearnAssetImageProvider.swift` swaps them for signed URLs at render time.

## Push
- `PushManager.shared.requestAuthorizationAndRegister()` has one call site: the notifications section of `Library/SettingsView.swift`. Onboarding and cold start never prompt.
- Token → `AppEnvironment.registerPushToken` → `POST /v1/me/devices`. `signOut()` first `DELETE /v1/me/devices/{id}`, then `POST /v1/auth/logout` (see roadmap: no refresh cookie sent).
- Backend send is a logging stub — see `reference-roadmap.md`.

## Money
- `Library/BillingView.swift`: balance, ledger, packages read-only; "buy" opens `<web>/billing` via `UIApplication.shared.open`. Never call `POST /v1/credits/checkout` or embed an `SFSafariViewController` checkout.
- Paid remix (`remixable && !canRemix && accessCredits > 0`) in `WorkDetail/WorkDetailView.swift` opens the web `/work/{id}` to unlock.
- Skill marketplace is not on iOS.
