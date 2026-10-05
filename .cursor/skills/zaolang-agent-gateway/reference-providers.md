# Agent Gateway — providers reference

Single owner for media-provider contracts and quirks. Protocol/pricing schema: see `zaolang-platform-config`.

## Protocol → adapter

`media_endpoints._factory` dispatches purely on `endpoint.protocol` (an HTTP-contract name, not a vendor):

| protocol | Adapter | Contract |
|---|---|---|
| `openai` | `AiHubMixMediaProvider` | `/v1/images/generations`, `/v1/audio/speech`, OpenAI Videos `/v1/videos` |
| `minimax` | `AiHubMixMediaProvider` | AiHubMix `/ai/v1/videos` facade, per-model `NativeVideoModelProfile` |
| `dashscope` | `AiHubMixMediaProvider` | `video_analysis` only: sync `/v1/chat/completions` with a `video_url` part (`_submit_video_analysis`) |
| `dmxapi` | `DmxApiMediaProvider` | `POST /v1/responses` task envelope (DMXAPI's own, body shape per model) |
| `minimax_v2` | `MinimaxV2MediaProvider` | official MiniMax Video V2 (Metaso proxies it at `https://metaso.cn/api/minimax`) |
| `fal` | `FalMediaProvider` | fal queue `queue.fal.run`, `Authorization: Key` (not Bearer) |

- Implemented set: `IMPLEMENTED_MEDIA_PROTOCOLS` in `back/app/platform_config/schemas.py`. Placeholders (`comfyui`/`google`/`ark`/`kling`) never enter `dynamic_capabilities`; never silently fall back to `openai`.
- `infer_media_protocol` (stored endpoints lacking `protocol`) must never infer `minimax_v2` or `fal` — operator opt-in only. Never reuse `minimax` with a Metaso/fal base URL.
- Adapters share no HTTP-shape code; each dispatches internally by `model`/`capability_tag`.

## Cross-provider rules

1. **Download presigned output URLs with a bare, header-less `httpx.Client`**, never `self._client()`. Output often lives on third-party object storage (e.g. BCE/Baidu Cloud for Qwen edit): any `Authorization` header makes BCE answer `400 MissingDateHeader` (it then expects `date`/`x-bce-date` signing). Applies in all four adapter files.
2. **Reference images in `local`/`test` are inlined as base64** (`Settings.embed_reference_images_as_base64` in `back/app/config.py`; `aihubmix_media._image_reference_urls`): MinIO `http://localhost:9000` presigned URLs are unreachable from the vendor, which then silently ignores the reference. >20MB (`_MAX_BASE64_REFERENCE_BYTES`) falls back to URL. Image-to-image `image` only; video references stay URLs.
3. **Never normalise resolution/model casing** — vendors match literals (`768P`/`2K`, `480p`, `480P`). `VIDEO_RESOLUTIONS` in `back/app/platform_config/schemas.py` carries all spellings.
4. **Hard filters key on model name via each adapter's own profile table**, never on `protocol`. Incompatible duration/aspect/reference-mode is filtered in `router.py`, never left for the vendor to 400.
5. **Unverified parsers tolerate several envelopes** and say so in docstrings; when a live call disagrees, fix that one function, not the module.
6. **Poll errors must be classified terminal vs transient explicitly** — defaulting to transient turns a dead task into a 2h timeout. Terminal → `PROVIDER_TASK_FAILED` so `route_score` excludes the provider on retry.
7. **A billable probe must cancel itself**: admin「验证有效」(`back/app/providers/connectivity.py`) sends a 16-token chat ping for `general`, a real render (`probe_video_body` per protocol) for `media`; `_cancel_fal_probe` cancels fal. A model with no safe probe body returns `error_code="no_capability"`. Job status lives in TTL Redis (`validation_jobs.py`), never the api_key.
8. `_QUALITY_PRIOR` is flat for all candidates; each capability key is `f"{endpoint_id}:{tag}"` (opaque — the LLM tells models apart by `model`).

## AiHubMix (`back/app/providers/aihubmix_media.py`)

- Image: default `/v1/images/generations`. With a reference: Qwen models (`_is_qwen_model`) → `_submit_qwen_image_edit` (`POST /v1/models/qianfan/qwen-image-edit/predictions`, 1–3 `input.image`, **no `size`** — rejected as `image size is invalid`; output URL is BCE, see rule 1). `is_gpt_image_2` + reference → multipart `POST /v1/images/edits` (`_submit_gpt_image_2_edit`); its t2i uses `_GPT_IMAGE_2_SIZE_BY_ASPECT`/`_GPT_IMAGE_2_QUALITY_BY_TIER`.
- Native video profiles (`_NATIVE_VIDEO_PROFILES`): H3 4–15s, `768P`/`2K`, ten ratios (`H3_ASPECT_RATIOS`); `wan2.7-videoedit` 2–10s, five ratios, no `resolution` sent; Seedance 2.5 4–30s, `480p`/`720p`, `generate_audio`, `poll_style="videos_inline"` (`/ai/v1/videos/{id}`). H3/Wan poll `/ai/v1/tasks/{id}` (+`/content`). Auto duration (`-1`) exists in profiles but `nodes.py` clamps video duration <4 to 4.
- `frame_images` (H3-only) and `input_references` are mutually exclusive; ≤9 references (`_MAX_INPUT_REFERENCES`).
- `wan2.7-videoedit` + reference (`_uses_wan_openai_edit`) leaves the facade even on a `minimax` endpoint: `POST /v1/videos` with `extra_body.input.media` (Wan enum `video`/`reference_image`), poll `/v1/videos/{id}` (never `/ai/v1/tasks`). Never merge `GenerationRequest.extra` into `extra_body`.

## DMXAPI (`back/app/providers/dmxapi_media.py`)

- Seedream group ("组图"): the adapter can send `sequential_image_generation=auto` + `max_images` when `GenerationRequest.output_count` > 1 and parses every image into `GenerationResult.extra_outputs`, but a live check (2026-10-01) returned one image for `max_images=2`, so `ImageModelProfile.max_group_outputs` is 1 and no workflow requests groups (scene variant sets loop per variant). Re-check with `back/tests/test_seedream_group_live.py` (`make test-llm`, `DMXAPI_API_KEY`) before raising it.
- `/v1/responses` for Seedream 5 image (sync), video families (`MiniMax-H3`, `MiniMax-H3-video_regeneration`, Seedance 2.5, `wan3.0-video`) and `music-3.0` (sync). TTS models use OpenAI-shaped `/v1/audio/speech`.
- Poll = same endpoint with `model` swapped to `"{family}-get"` (`MiniMax-H3-get`, `seedance-2-5-get`, `wan3.0-get`) and the task id as `input`.
- Profiles are independent of AiHubMix: DMXAPI H3 has six ratios (no `adaptive`); Seedance adds `1080p`; `wan3.0-video` uses `480P`/`720P`/`1080P`.
- Seedance 2.5 body: text + references in `input[]` as `image_url`/`video_url`/`audio_url` with `role`; **no top-level `input_references`/`frame_images`** (live `unsupported parameter`). First/last frame forces `ratio="adaptive"`; frame roles vs `reference_*` roles → `ValueError`. `wan3.0-video`: `input.media[]` + `parameters` (`_build_wan3_body`).
- `MiniMax-H3-video_regeneration` only upscales a 768P H3-spec clip to 2K: prompt + one `frame_type="base_video"` reference; no probe body (`no_capability`).
- 502 with `dmxapi_upstream_error` + `_TERMINAL_POLL_ERROR_MARKERS` → `PROVIDER_TASK_FAILED`.

## MiniMax V2 (`back/app/providers/minimax_v2_media.py`)

- `POST /v2/video_generation` with `content[]` (text ≤7000 chars + `image_url`/`video_url`/`audio_url` with `role`); poll `GET /v2/query/video_generation/{id}`; cancel `DELETE` (miss is logged, local CANCELLED proceeds).
- Text-only remaps `adaptive` → `16:9` (V2 400s otherwise); first/last frame forces `adaptive`; reference roles exclusive with frame roles. Caps ≤9 images, ≤3 videos, ≤3 audios, ≤12 files. H3 only; query/cancel/download unverified live.

## fal (`back/app/providers/fal_media.py`)

- Models: `minimax/h3-max` (video), `minimax/voice-clone`, `minimax-music/v2.6`, `elevenlabs/sound-effects/v2`, `fal-ai/qwen-image-edit-2511-multiple-angles` (image_to_image, camera control).
- Multi-angle (`build_multi_angle_body`): first image reference only (`MULTI_ANGLE_MAX_REFERENCES`), pose from `extra.camera_pose` → `horizontal_angle`/`vertical_angle`/`zoom` (`app.domain.image_assets.camera.to_fal`), prompt → `additional_prompt`, ~1MP `image_size` per aspect, output `generated/{job}/output_{attempt}.png`. Flat app path like the audio apps, task route `multi-angle`. Save the endpoint with image-only input (else it also derives `text_to_image`). `supports_camera_control` → `ProviderCapability.camera_control`; the client can never set `extra.camera_pose` (`reference_resolver.resolve` drops it).
- H3 Max routes by reference shape: none → `text-to-video`; only first/last frame → `image-to-video`; any generic ref → `reference-to-video`. Profile 5–15s, `480P`/`768P` (no 2K), t2v `adaptive`→`16:9`, ≤12 files.
- Always `prompt_expansion_mode=balanced`, `enable_safety_checker=true`; never `sync_mode` or the `fal-client` SDK. `external_task_id` = `{route}#{request_id}` (ids are per-app). `COMPLETED` + `error` → `PROVIDER_TASK_FAILED`. Queue paths unverified live.

## Model catalog (`back/app/providers/model_catalog.py`)

`VENDOR_MODEL_CATALOG` (`VendorId`: `aihubmix`/`dmxapi`/`metaso`/`fal`), served by `GET /v1/admin/llm-providers/catalog`: a `/admin/models` pre-fill convenience (protocol, modalities, `suggested_timeout_ms`, `generation_kind`, `price_items`), never enforced at save. Adding a model to an adapter → add its catalog entry too. Per-vendor pricing rules: see `zaolang-platform-config`.
