"""AiHubMix-style HTTP media provider.

The first *real* generation provider — every other one in `app/providers/` is
a fake that never leaves the process. Image and audio calls are synchronous
OpenAI-compatible HTTP requests; video calls are asynchronous: create a task,
poll it, then download the finished file once it completes.

One instance is bound to exactly one (endpoint, capability) pair. That keeps
`ProviderAttempt.provider`/the router's catalog key one-to-one, so per-model
statistics accumulate independently even when two capabilities share the same
credential — see `app/agents/router.py:build_catalog`.
"""

from __future__ import annotations

import base64
import io
import logging
import mimetypes
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from PIL import Image, UnidentifiedImageError

from app.config import get_settings
from app.llm.normalize import extract_json, strip_thinking
from app.models.enums import Operation
from app.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderReference,
    probe_audio_duration_ms,
)
from app.storage import s3

logger = logging.getLogger(__name__)

_VIDEO_OPERATIONS = frozenset(
    {Operation.TEXT_TO_VIDEO.value, Operation.IMAGE_TO_VIDEO.value, Operation.VIDEO_TO_VIDEO.value}
)

MINIMAX_H3_MODEL = "minimax-h3"
WAN_VIDEOEDIT_MODEL = "wan2.7-videoedit"
# AiHubMix's own catalogue lowercases this id (unlike DMXAPI's `MiniMax-H3` /
# `doubao-seedance-2-5-260628` casing, which is preserved verbatim by
# `dmxapi_media.py` — the two providers are looked up independently and never
# share a profile table, so the casing difference cannot collide).
DOUBAO_SEEDANCE_25_MODEL = "doubao-seedance-2-5-260628"
H3_ASPECT_RATIOS = frozenset(
    {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "3:2", "2:3", "9:21", "adaptive"}
)


@dataclass(frozen=True, slots=True)
class NativeVideoModelProfile:
    """One native (`/ai/v1/videos`) model's physical limits.

    Sourced from AiHubMix's own machine-readable schema
    (`https://aihubmix.com/call/schema/models/{model}/endpoints`), not
    guessed — a value missing here that the schema actually allows is a bug,
    not a deliberate restriction.
    """

    min_duration_seconds: int
    max_duration_seconds: int
    aspect_ratios: frozenset[str]
    # What's legal to *send* the provider — used for `router`'s hard filter.
    resolutions: frozenset[str]
    # Sent when the caller doesn't specify one. `None` means "omit the field
    # entirely and let the provider apply its own default" — not every
    # model's schema even has a `resolution` field.
    default_resolution: str | None
    # Whether this model's schema accepts `duration=-1` as "let the model
    # pick a sensible length" instead of a caller-supplied integer.
    supports_auto_duration: bool = False
    # Whether this model's schema accepts a `generate_audio` toggle for a
    # native soundtrack (dialogue/SFX/BGM baked into the output clip).
    supports_generate_audio: bool = False
    # Where the async task lands after `POST /ai/v1/videos`. MiniMax H3 and
    # `wan2.7-videoedit` poll a legacy `/ai/v1/tasks/{id}` (+ `/content`) pair
    # confirmed live (see the `zaolang-agent-gateway` providers reference,
    # AiHubMix native video profiles). `doubao-
    # seedance-2-5-260628`'s own AiHubMix schema
    # (`https://aihubmix.com/call/schema/models/doubao-seedance-2-5-260628/
    # endpoints`, checked 2026-08) instead documents `/ai/v1/videos/{id}` with
    # the output URL inlined in the poll response body — no separate
    # `/content` call. **Unverified against a live credential** — fix
    # `_poll_native_videos_inline` and this comment if a real call disagrees.
    poll_style: Literal["tasks", "videos_inline"] = "tasks"


# Every value here has been confirmed against AiHubMix's schema endpoint —
# widening beyond what's actually documented there is not "supporting more",
# it's fabricating a contract the provider itself never promised.
_NATIVE_VIDEO_PROFILES: dict[str, NativeVideoModelProfile] = {
    MINIMAX_H3_MODEL: NativeVideoModelProfile(
        min_duration_seconds=4,
        max_duration_seconds=15,
        aspect_ratios=H3_ASPECT_RATIOS,
        resolutions=frozenset({"768P", "2K"}),
        default_resolution="2K",
    ),
    WAN_VIDEOEDIT_MODEL: NativeVideoModelProfile(
        min_duration_seconds=2,
        max_duration_seconds=10,
        aspect_ratios=frozenset({"16:9", "9:16", "1:1", "4:3", "3:4"}),
        resolutions=frozenset({"720p", "1080p"}),
        default_resolution=None,
    ),
    DOUBAO_SEEDANCE_25_MODEL: NativeVideoModelProfile(
        min_duration_seconds=4,
        max_duration_seconds=30,
        aspect_ratios=frozenset({"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}),
        resolutions=frozenset({"480p", "720p"}),
        default_resolution="720p",
        supports_auto_duration=True,
        supports_generate_audio=True,
        poll_style="videos_inline",
    ),
}


def native_video_profile(model: str) -> NativeVideoModelProfile | None:
    """The profile for a model's native `/ai/v1/videos` contract, if known.

    `None` for anything not in the table above — callers must treat that as
    "no additional validation, no hard filter", never as "reject it".
    """
    return _NATIVE_VIDEO_PROFILES.get(model.strip().lower())


# AiHubMix accepts at most nine reference images per task and rejects the
# whole request if given more.
_MAX_INPUT_REFERENCES = 9
# Anything else non-terminal is treated as "still working".
_TASK_FAILED_STATUSES = frozenset({"failed", "cancelled", "canceled", "expired"})
# How long a reference image's signed URL must stay valid. Comfortably beyond
# `app.domain.jobs.async_tasks.TASK_TIMEOUT_SECONDS`, the point at which the
# platform gives up on a render — a URL that expired while the render was
# still legitimately running would fail the task for the wrong reason.
_REFERENCE_URL_TTL_SECONDS = 900

# OpenAI-compatible gateways (and AiHubMix's Qwen list) reject sizes below a
# 512px floor. Preview used to emit `512x288` for 16:9, which is not a legal
# generations size.
_IMAGE_SIZE_BY_ASPECT = {
    "16:9": "1024x576",
    "9:16": "576x1024",
    "1:1": "1024x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "21:9": "1024x576",
}

GPT_IMAGE_2_MODEL = "gpt-image-2"
# Documented-safe OpenAI GPT Image sizes. Do not reuse `_IMAGE_SIZE_BY_ASPECT`
# here — values like `1024x576` have been rejected as `size_not_supported`.
# Quality (preview/standard/cinematic) only drives `quality`, not pixels.
_GPT_IMAGE_2_SIZE_BY_ASPECT = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "4:3": "1536x1024",
    "21:9": "1536x1024",
    "3:2": "1536x1024",
    "9:16": "1024x1536",
    "3:4": "1024x1536",
    "2:3": "1024x1536",
}
_GPT_IMAGE_2_QUALITY_BY_TIER = {
    "preview": "low",
    "standard": "medium",
    "cinematic": "high",
}

# `video_analysis`'s prompt to a native video-understanding model. Requests a
# strict JSON object matching `VideoAnalysisResult` (`app.api.schemas.jobs`)
# so the provider layer never has to know that schema — it only has to ask
# for it consistently and let `extract_json` parse whatever comes back.
_VIDEO_ANALYSIS_INSTRUCTIONS = (
    "你是专业的短视频运镜与分镜分析师。请仔细观看这段参考视频，输出严格的 JSON 对象，"
    "不要包含任何 JSON 之外的文字或 Markdown 代码块标记，字段如下：\n"
    "{\n"
    '  "summary": "对整体内容、题材与风格的一段话摘要",\n'
    '  "composed_prompt": "可直接用于视频生成的整合提示词，需具体描述运镜、场景、主体、光线与风格",\n'
    '  "style_tags": ["风格标签", "..."],\n'
    '  "pacing": "整体节奏描述，例如：快节奏剪辑 / 舒缓长镜头",\n'
    '  "shots": [\n'
    "    {\n"
    '      "time_range": "00:00-00:03",\n'
    '      "camera_movement": "运镜方式，例如：推镜 / 摇镜 / 跟随",\n'
    '      "scene": "场景描述",\n'
    '      "subject_action": "主体动作",\n'
    '      "lighting_mood": "光线与氛围",\n'
    '      "transition_in": "该镜头开始处的转场方式"\n'
    "    }\n"
    "  ]\n"
    "}"
)

# AiHubMix has no documented `/v1/images/generations` support for feeding a
# reference image into a Qwen model — the `image` field `_image_reference_
# urls` builds is honoured only loosely there (a 2026-08-19 live check got
# the right gender and nothing else of the reference: wrong clothes, wrong
# face). The real contract for Qwen image editing is this dedicated
# multimodal endpoint (`docs.aihubmix.com/en/api/Image-Gen`, "Qwen-Image-
# Edit"): `input.image` (1-3 images) + `input.text`, and it reliably
# preserves identity/outfit/pose across a view change — verified against
# the same reference photo in that same check. Scoped to Qwen models only:
# every other family keeps going through `_submit_image`'s OpenAI-shaped
# request, unverified against the real API but at least no worse than
# before this fix.
_QWEN_EDIT_MODEL_PATH = "qianfan/qwen-image-edit"
# The documented image-to-image limit for this endpoint.
_QWEN_EDIT_MAX_REFERENCES = 3


def join_media_url(base_url: str, path: str) -> str:
    """Join a rooted media path onto a gateway base without doubling `/v1`.

    Operators often save chat-compatible bases as `https://host/v1`. httpx
    then turns `POST /v1/images/generations` into `/v1/v1/images/generations`
    (404). MiniMax bases are the host root and paths start with `/ai/v1/…`.
    """
    base = httpx.URL(base_url)
    path = "/" + path.lstrip("/")
    base_path = (base.path or "").rstrip("/")
    if path.startswith("/v1/") and base_path.endswith("/v1"):
        merged = base_path + path[3:]
    elif not base_path or base_path == "/":
        merged = path
    else:
        merged = base_path + path
    return str(base.copy_with(path=merged, query=None, fragment=None))


def media_client_base(base_url: str) -> str:
    """Origin only, so rooted paths are joined against the host, not `/v1`."""
    url = httpx.URL(base_url)
    return str(url.copy_with(path="/", query=None, fragment=None)).rstrip("/")


def media_request_path(base_url: str, path: str) -> str:
    return httpx.URL(join_media_url(base_url, path)).path or path


@dataclass(frozen=True, slots=True)
class _EndpointCredentials:
    base_url: str
    api_key: str
    timeout_s: float


class AiHubMixMediaProvider(GenerationProvider):
    """One media capability of one `llm_providers` endpoint."""

    kind = "commercial_api"

    def __init__(
        self,
        *,
        endpoint_id: str,
        capability_tag: str,
        model: str,
        base_url: str,
        api_key: str,
        timeout_ms: int,
        # Defaults to the original (and, until the OpenAI Videos API track,
        # only) native video contract so every existing call site/test that
        # never passed this stays correct without a change.
        protocol: str = "minimax",
    ) -> None:
        self.name = f"{endpoint_id}:{capability_tag}"
        self._capability_tag = capability_tag
        self._model = model
        self._protocol = protocol
        self._creds = _EndpointCredentials(
            base_url=base_url.rstrip("/"), api_key=api_key, timeout_s=timeout_ms / 1000
        )

    def submit(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        try:
            if self._capability_tag == Operation.AUDIO_GENERATION.value:
                return self._submit_audio(request, started)
            if self._capability_tag in {
                Operation.TEXT_TO_IMAGE.value,
                Operation.IMAGE_TO_IMAGE.value,
            }:
                return self._submit_image(request, started)
            if self._capability_tag == Operation.VIDEO_ANALYSIS.value:
                return self._submit_video_analysis(request, started)
            if self._capability_tag in _VIDEO_OPERATIONS and (
                self._protocol == "openai" or _uses_wan_openai_edit(self._model, request)
            ):
                return self._submit_openai_video(request, started)
            return self._submit_video(request, started)
        except httpx.TimeoutException as exc:
            logger.warning(
                "aihubmix %s call timed out for job %s after %.0fs: %s",
                self._capability_tag,
                request.job_id,
                self._creds.timeout_s,
                type(exc).__name__,
            )
            return self._failure(
                started,
                "PROVIDER_TEMPORARY_FAILURE",
                f"{type(exc).__name__} after {int(self._creds.timeout_s)}s",
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "aihubmix %s call failed for job %s: HTTP %s",
                self._capability_tag,
                request.job_id,
                exc.response.status_code,
            )
            status = exc.response.status_code
            code = "PROVIDER_INVALID_RESPONSE" if status < 500 else "PROVIDER_TEMPORARY_FAILURE"
            return self._failure(started, code, _http_error_detail(exc, self._creds.api_key))
        except httpx.HTTPError as exc:
            logger.warning(
                "aihubmix %s call failed for job %s: %s", self._capability_tag, request.job_id, exc
            )
            return self._failure(started, "PROVIDER_TEMPORARY_FAILURE", type(exc).__name__)

    # -- image: text_to_image / image_to_image -----------------------------

    def _submit_image(self, request: GenerationRequest, started: float) -> GenerationResult:
        image_refs = _image_reference_urls(request)
        if image_refs and _is_qwen_model(self._model):
            return self._submit_qwen_image_edit(request, started, image_refs)
        if _image_reference_keys(request) and is_gpt_image_2(self._model):
            return self._submit_gpt_image_2_edit(request, started)

        if is_gpt_image_2(self._model):
            size = _gpt_image_2_size(request.aspect_ratio)
        else:
            size = _size_for(request.aspect_ratio, request.quality_tier)
        body: dict[str, object] = {
            "model": self._model,
            "prompt": request.prompt,
            "size": size,
            "n": 1,
        }
        if is_gpt_image_2(self._model):
            body["quality"] = _gpt_image_2_quality(request.quality_tier)
            body["output_format"] = "png"
        if image_refs:
            body["image"] = image_refs[0] if len(image_refs) == 1 else image_refs

        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/images/generations"), json=body
            )
            response.raise_for_status()
            payload = response.json()
            image_bytes = _image_bytes_from_payload(payload, client)

        return self._store_image_result(request, started, image_bytes)

    def _submit_gpt_image_2_edit(
        self, request: GenerationRequest, started: float
    ) -> GenerationResult:
        """gpt-image-2's documented image-to-image contract.

        `/v1/images/generations` + an ad-hoc `image` field is the same
        unverified path that failed to preserve identity for Qwen. AiHubMix
        documents `POST /v1/images/edits` (multipart) for this model —
        one source image, no `input_fidelity` or other GPT Image 1 fields.
        """
        keys = _image_reference_keys(request)
        if not keys:
            return self._failure(started, "MISSING_REFERENCE", "missing_image")
        source_key = keys[0]
        source_bytes = s3.get_object(source_key)
        if not source_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_image")
        mime = mimetypes.guess_type(source_key)[0] or "image/png"
        filename = source_key.rsplit("/", 1)[-1] or "reference.png"

        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/images/edits"),
                data={
                    "model": self._model,
                    "prompt": request.prompt,
                    "n": "1",
                    "size": _gpt_image_2_size(request.aspect_ratio),
                    "quality": _gpt_image_2_quality(request.quality_tier),
                    "output_format": "png",
                },
                files={"image": (filename, source_bytes, mime)},
            )
            response.raise_for_status()
            payload = response.json()
            image_bytes = _image_bytes_from_payload(payload, client)

        return self._store_image_result(
            request,
            started,
            image_bytes,
            extra_metadata={"endpoint": "gpt-image-2-edits"},
        )

    def _store_image_result(
        self,
        request: GenerationRequest,
        started: float,
        image_bytes: bytes | None,
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> GenerationResult:
        if not image_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_image")

        width, height = _probe_image_size(image_bytes)
        # `attempt_number` (see `GenerationRequest`) keeps a multi-view
        # `CHARACTER` job's side/back passes from colliding with the front
        # pass's already-registered `Asset` row on `uq_assets_object_key` —
        # both share the same `job_id`.
        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.png"
        s3.put_object(object_key, image_bytes, content_type="image/png")

        metadata: dict[str, Any] = {"provider": self.name, "model": self._model}
        if extra_metadata:
            metadata.update(extra_metadata)
        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="image/png",
            width=width,
            height=height,
            latency_ms=self._elapsed_ms(started),
            metadata=metadata,
        )

    def _submit_qwen_image_edit(
        self, request: GenerationRequest, started: float, image_refs: list[str]
    ) -> GenerationResult:
        """Qwen's real image-editing contract — see `_QWEN_EDIT_MODEL_PATH`."""
        images: str | list[str] = (
            image_refs[0] if len(image_refs) == 1 else image_refs[:_QWEN_EDIT_MAX_REFERENCES]
        )
        input_body: dict[str, object] = {
            "prompt": request.prompt,
            "image": images,
            "n": 1,
            "watermark": False,
        }
        if request.seed is not None:
            input_body["seed"] = request.seed
        # No `size`: unlike `qwen-image-3.0`'s plain generations call, this
        # endpoint rejected every `_IMAGE_SIZE_BY_ASPECT` value tried here
        # with `image size is invalid` (2026-08-19 live check) — it takes
        # its output resolution from the input image instead.

        with self._client() as client:
            response = client.post(
                media_request_path(
                    self._creds.base_url, f"/v1/models/{_QWEN_EDIT_MODEL_PATH}/predictions"
                ),
                json={"input": input_body},
            )
            response.raise_for_status()
            payload = response.json()
            output_url = _qwen_edit_output_url(payload)

        if not output_url:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_image")

        # Deliberately a bare, header-less client rather than `self._client()`
        # reused: this endpoint's `output` URL is a pre-signed BCE (Baidu
        # Cloud) object-storage link, not an AiHubMix one, and BCE's edge
        # rejects it with `MissingDateHeader` once *any* `Authorization`
        # header rides along (2026-08-19 live check) — it reads that header's
        # mere presence as "the caller means to authenticate via BCE's own
        # header-signature scheme", which needs a paired `date`/`x-bce-date`
        # we have no reason to send, instead of the query-string signature
        # the presigned URL already carries.
        with httpx.Client(timeout=self._creds.timeout_s) as download_client:
            download = download_client.get(output_url)
            download.raise_for_status()
            image_bytes = download.content or None

        if not image_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_image")

        width, height = _probe_image_size(image_bytes)
        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.png"
        s3.put_object(object_key, image_bytes, content_type="image/png")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="image/png",
            width=width,
            height=height,
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model, "endpoint": "qwen-image-edit"},
        )

    # -- audio: audio_generation ---------------------------------------------

    def _submit_audio(self, request: GenerationRequest, started: float) -> GenerationResult:
        voice = request.extra.get("voice", "alloy")
        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/audio/speech"),
                json={
                    "model": self._model,
                    "input": request.prompt,
                    "voice": voice,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
            audio_bytes = response.content

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp3"
        s3.put_object(object_key, audio_bytes, content_type="audio/mpeg")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="audio/mpeg",
            duration_ms=probe_audio_duration_ms(audio_bytes, "audio/mpeg"),
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model, "voice": voice},
        )

    # -- video understanding: video_analysis ---------------------------------

    def _submit_video_analysis(
        self, request: GenerationRequest, started: float
    ) -> GenerationResult:
        """Native video-understanding call, synchronous like image/audio.

        **Unverified against a live credential** — modelled on DashScope's
        documented OpenAI-compatible contract for Qwen-VL (a `video_url`
        content part inside an otherwise ordinary `/v1/chat/completions`
        multimodal message), the same "verify before trusting the docs"
        situation `_submit_qwen_image_edit` ran into for image editing. If a
        real call disagrees with this shape (wrong path, different content
        part name, a dedicated async task contract like the video-generation
        endpoint instead of a synchronous chat call, ...), fix this method
        and update this comment — do not assume it is still accurate once a
        live check has been made.
        """
        video_url = _video_reference_url(request)
        if video_url is None:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_video_reference")

        user_text = _VIDEO_ANALYSIS_INSTRUCTIONS
        if request.prompt.strip():
            user_text += f"\n\n用户补充说明：{request.prompt.strip()}"

        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": video_url}},
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
            "temperature": 0.2,
        }

        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/chat/completions"), json=body
            )
            response.raise_for_status()
            payload = response.json()

        result_json = _video_analysis_result_json(payload)
        if not result_json:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_analysis_json")

        return GenerationResult(
            succeeded=True,
            output_json=result_json,
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model},
        )

    # -- video: text_to_video / image_to_video / video_to_video -------------

    def _submit_video(self, request: GenerationRequest, started: float) -> GenerationResult:
        """Creates the render task and returns immediately.

        A render runs for minutes. Waiting for it here would pin a worker for
        the whole time and, worse, leave the job's event stream silent until
        the very end — the user would watch one status until it suddenly
        jumped to done. `app.workers.tasks.poll_async_provider_tasks` takes it
        from here, writing a heartbeat on every check.
        """
        references = list(request.references)
        if not references and request.reference_object_keys:
            references = [
                ProviderReference(object_key=key, media_type="image")
                for key in request.reference_object_keys
            ]
        body = build_video_payload(
            model=self._model,
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            resolution=request.resolution,
            seed=request.seed,
            references=references,
            generate_audio=request.extra.get("generate_audio"),
        )

        with self._client() as client:
            create = client.post(
                media_request_path(self._creds.base_url, "/ai/v1/videos"), json=body
            )
            create.raise_for_status()
            task_id = create.json().get("id")

        if not task_id:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_task_id")

        return GenerationResult(
            succeeded=False,
            pending=True,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=task_id,
            metadata={"provider": self.name, "model": self._model},
        )

    # -- video (openai protocol): the OpenAI Videos API track ---------------

    def _submit_openai_video(self, request: GenerationRequest, started: float) -> GenerationResult:
        """`POST /v1/videos` — `videos.create(model, prompt)` in the official
        SDK's shape.

        `wan2.7-videoedit` with a reference is the one documented exception:
        the MiniMax facade cannot carry Wan's media types (see
        `_uses_wan_openai_edit`), so that case also lands here with
        `extra_body.input.media`. Published schema still omits
        `input_reference`; a non-Wan model only attaches that field when
        the caller actually supplied a reference.
        """
        _validate_native_video_request(self._model, request)
        body: dict[str, object] = {"model": self._model, "prompt": request.prompt}
        if request.duration_seconds:
            body["seconds"] = request.duration_seconds
        if _uses_wan_openai_edit(self._model, request):
            # Live 2026-08-29: `/ai/v1/videos` `extra` is ignored by the Wan
            # forwarder, and `input_references[].type=video` is a create-time
            # 400. The shape that create+poll both accept is this track's
            # `extra_body.input.media` with Wan's own enum. Do not merge
            # `request.extra` (product fields like `sound`) into it.
            media = _wan_edit_media(request)
            if media:
                body["extra_body"] = {"input": {"media": media}}
        else:
            reference = _first_reference(request)
            if reference is not None:
                url = s3.presign_get(reference.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
                # Unverified shape — no openai-protocol model in this deployment
                # accepts `input_reference` yet, so this has never been
                # exercised against a live credential. Fix this once one does.
                body["input_reference"] = (
                    {"video_url": url} if reference.media_type == "video" else {"image_url": url}
                )

        with self._client() as client:
            create = client.post(media_request_path(self._creds.base_url, "/v1/videos"), json=body)
            create.raise_for_status()
            task_id = create.json().get("id")

        if not task_id:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_task_id")

        return GenerationResult(
            succeeded=False,
            pending=True,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=task_id,
            metadata={"provider": self.name, "model": self._model},
        )

    def _poll_openai_video(
        self, external_task_id: str, request: GenerationRequest, started: float
    ) -> GenerationResult:
        """`GET /v1/videos/{id}` + `GET /v1/videos/{id}/content`.

        Status judged by exclusion (`!= "completed"` and not a known failure
        status is pending) rather than a `{"queued", "in_progress"}`
        allow-list: a live check against `wan2.7-videoedit`'s openai-shaped
        endpoint found its real vocabulary is `queued`/`processing`/
        `completed`/`failed` — `processing`, not the generic OpenAI docs'
        `in_progress` — so an allow-list would have stuck this model in an
        unknown-status limbo forever.
        """
        try:
            with self._client() as client:
                status_response = client.get(
                    media_request_path(self._creds.base_url, f"/v1/videos/{external_task_id}")
                )
                status_response.raise_for_status()
                payload = status_response.json()
                status = str(payload.get("status") or "").lower()

                if status != "completed" and status not in _TASK_FAILED_STATUSES:
                    metadata: dict[str, object] = {"provider": self.name, "status": status}
                    progress = payload.get("progress")
                    if isinstance(progress, int | float):
                        metadata["progress"] = progress
                    return GenerationResult(
                        succeeded=False,
                        pending=True,
                        external_task_id=external_task_id,
                        latency_ms=self._elapsed_ms(started),
                        metadata=metadata,
                    )

                if status in _TASK_FAILED_STATUSES:
                    error = payload.get("error")
                    message = error.get("message") if isinstance(error, dict) else error
                    return self._failure(started, "PROVIDER_TASK_FAILED", str(message or status))

                content = client.get(
                    media_request_path(
                        self._creds.base_url, f"/v1/videos/{external_task_id}/content"
                    )
                )
                content.raise_for_status()
                video_bytes = content.content
        except httpx.HTTPError as exc:
            logger.warning(
                "aihubmix openai video poll failed for task %s: %s", external_task_id, exc
            )
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not video_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "empty_video_content")

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp4"
        s3.put_object(object_key, video_bytes, content_type="video/mp4")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=external_task_id,
            metadata={"provider": self.name, "model": self._model, "upstream_status": status},
        )

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        """One status check for a video task, plus the download when it is done.

        Deliberately a single round trip with no sleeping: the caller is a
        scheduler tick that must stay short, and how often to come back is
        its decision, not this method's. The caller keeps polling while this
        returns `pending`; it does not invent a timeout on the provider's
        behalf.
        """
        started = time.perf_counter()
        if self._protocol == "openai" or _uses_wan_openai_edit(self._model, request):
            return self._poll_openai_video(external_task_id, request, started)
        profile = native_video_profile(self._model)
        if profile is not None and profile.poll_style == "videos_inline":
            return self._poll_native_videos_inline(external_task_id, request, started)
        try:
            with self._client() as client:
                status_response = client.get(
                    media_request_path(self._creds.base_url, f"/ai/v1/tasks/{external_task_id}")
                )
                status_response.raise_for_status()
                payload = status_response.json()
                status = str(payload.get("status") or "").lower()
                outputs = payload.get("output")

                if status != "completed" and status not in _TASK_FAILED_STATUSES:
                    return GenerationResult(
                        succeeded=False,
                        pending=True,
                        external_task_id=external_task_id,
                        latency_ms=self._elapsed_ms(started),
                        metadata={"provider": self.name, "status": status},
                    )

                if not isinstance(outputs, list) or not outputs:
                    if status in _TASK_FAILED_STATUSES:
                        return self._failure(
                            started, "PROVIDER_TASK_FAILED", str(payload.get("error") or status)
                        )
                    return self._failure(
                        started, "PROVIDER_INVALID_RESPONSE", "completed_without_output"
                    )

                content = client.get(
                    media_request_path(
                        self._creds.base_url, _content_path(external_task_id, payload)
                    )
                )
                content.raise_for_status()
                video_bytes = content.content
        except httpx.HTTPError as exc:
            logger.warning("aihubmix poll failed for task %s: %s", external_task_id, exc)
            # A transient network error must not end the render: report it as
            # still pending so the next tick tries again, and let the caller's
            # deadline be what eventually gives up.
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not video_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "empty_video_content")

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp4"
        s3.put_object(object_key, video_bytes, content_type="video/mp4")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=external_task_id,
            metadata={
                "provider": self.name,
                "model": self._model,
                "partial_output": status != "completed",
                "upstream_status": status,
            },
        )

    def _poll_native_videos_inline(
        self, external_task_id: str, request: GenerationRequest, started: float
    ) -> GenerationResult:
        """`GET /ai/v1/videos/{id}` for a model whose schema inlines the
        output URL in the poll response instead of a separate `/content`
        call (see `NativeVideoModelProfile.poll_style`).

        Status vocabulary per AiHubMix's schema for this track is `pending` /
        `in_progress` / `completed` / `failed` / `cancelled` — folds into the
        same `_TASK_FAILED_STATUSES` set the legacy `/ai/v1/tasks` track uses
        (`cancelled` is already a member; `pending`/`in_progress` both read
        as "still working", same as `queued`/`running` elsewhere).
        **Unverified against a live credential** — the exact field holding
        the output URL is inferred from this provider's other response
        shapes (`_qwen_edit_output_url`'s `output[].url`, DMXAPI's
        `output[].content[].text`) rather than a confirmed sample; fix
        `_extract_inline_video_url` and this comment if a real call
        disagrees.
        """
        try:
            with self._client() as client:
                status_response = client.get(
                    media_request_path(self._creds.base_url, f"/ai/v1/videos/{external_task_id}")
                )
                status_response.raise_for_status()
                payload = status_response.json()
                status = str(payload.get("status") or "").lower()

                if status != "completed" and status not in _TASK_FAILED_STATUSES:
                    return GenerationResult(
                        succeeded=False,
                        pending=True,
                        external_task_id=external_task_id,
                        latency_ms=self._elapsed_ms(started),
                        metadata={"provider": self.name, "status": status},
                    )

                if status in _TASK_FAILED_STATUSES:
                    error = payload.get("error")
                    message = error.get("message") if isinstance(error, dict) else error
                    return self._failure(started, "PROVIDER_TASK_FAILED", str(message or status))

                video_url = _extract_inline_video_url(payload)
                if not video_url:
                    return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_video_url")

            # A bare, header-less client rather than `self._client()` reused:
            # this track's output URL is a pre-signed cloud-storage link, same
            # reasoning as `_submit_qwen_image_edit`'s BCE download — a stray
            # `Authorization` header can make some signed-URL edges reject an
            # otherwise-valid request.
            with httpx.Client(timeout=self._creds.timeout_s) as download_client:
                download = download_client.get(video_url)
                download.raise_for_status()
                video_bytes = download.content or None
        except httpx.HTTPError as exc:
            logger.warning(
                "aihubmix inline-video poll failed for task %s: %s", external_task_id, exc
            )
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not video_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "empty_video_content")

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp4"
        s3.put_object(object_key, video_bytes, content_type="video/mp4")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=external_task_id,
            metadata={"provider": self.name, "model": self._model, "upstream_status": status},
        )

    def cancel(self, external_task_id: str) -> bool:
        # Every documented contract this provider speaks — native H3/
        # wan2.7-videoedit and the OpenAI Videos API alike — only covers
        # create/status/content; every `cancel_path` confirmed against
        # AiHubMix's schema is empty. Do not invent a paid-task cancellation
        # endpoint: a 404 here would give operators false confidence that
        # the render had stopped.
        if self._protocol == "openai" or native_video_profile(self._model) is not None:
            return False
        try:
            with self._client() as client:
                response = client.post(
                    media_request_path(
                        self._creds.base_url, f"/ai/v1/tasks/{external_task_id}/cancel"
                    )
                )
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=media_client_base(self._creds.base_url),
            headers={"Authorization": f"Bearer {self._creds.api_key}"},
            timeout=self._creds.timeout_s,
        )

    def _failure(self, started: float, code: str, detail: str) -> GenerationResult:
        return GenerationResult(
            succeeded=False,
            failure_code=code,
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "detail": detail},
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


def _content_path(task_id: str, payload: dict[str, object]) -> str:
    """The download URL for a finished task.

    A task that produced several outputs rejects the plain path with
    `400 result_id_required`, so the first result's id is appended when the
    status response reports more than one.
    """
    outputs = payload.get("output")
    if isinstance(outputs, list) and len(outputs) > 1:
        first = outputs[0]
        result_id = first.get("result_id") if isinstance(first, dict) else None
        if result_id:
            return f"/ai/v1/tasks/{task_id}/content/{result_id}"
    return f"/ai/v1/tasks/{task_id}/content"


def _extract_inline_video_url(payload: dict[str, object]) -> str | None:
    """Tries every URL-shaped field a `poll_style="videos_inline"` response
    might use, since the exact schema has not been confirmed against a live
    credential (see `NativeVideoModelProfile.poll_style`)."""
    output = payload.get("output")
    if isinstance(output, str) and output:
        return output
    if isinstance(output, dict):
        url = output.get("url")
        if isinstance(url, str) and url:
            return url
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url:
                return url
            content = first.get("content")
            if isinstance(content, list) and content:
                part = content[0]
                if isinstance(part, dict):
                    text = part.get("text") or part.get("output_text")
                    if isinstance(text, str) and text.startswith("http"):
                        return text
    for key in ("video_url", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def build_video_payload(
    *,
    model: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str | None = None,
    seed: int | None = None,
    references: list[ProviderReference] | None = None,
    generate_audio: bool | None = None,
) -> dict[str, object]:
    """Build the one native-video request shape shared by validation and
    production, for whichever model this is.

    Keeping the probe on the production builder prevents the exact regression
    that caused this incident: the button used a request which omitted a
    provider-required field while the worker used another hand-written shape.

    A model with no registered `NativeVideoModelProfile` gets no range
    validation and no `resolution` field — the same "unopinionated passthrough"
    behaviour this function always had before H3 was its only caller, so
    adding a new model here never breaks an unrelated one.
    """

    profile = native_video_profile(model)
    # `-1` is the model's own "pick a sensible length" sentinel on a model
    # whose schema documents it (`doubao-seedance-2-5-260628`) — never a
    # value this platform invents on a model that never advertised it.
    is_auto_duration = (
        duration_seconds == -1 and profile is not None and profile.supports_auto_duration
    )
    if profile is not None and not is_auto_duration:
        if not profile.min_duration_seconds <= duration_seconds <= profile.max_duration_seconds:
            raise ValueError(
                f"{model} duration must be between {profile.min_duration_seconds} and "
                f"{profile.max_duration_seconds} seconds"
            )
        if aspect_ratio not in profile.aspect_ratios:
            raise ValueError(f"{model} aspect ratio is unsupported: {aspect_ratio}")

    body: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "duration": duration_seconds,
        "aspect_ratio": aspect_ratio,
    }
    if profile is not None:
        effective_resolution = resolution or profile.default_resolution
        if effective_resolution is not None:
            if effective_resolution not in profile.resolutions:
                raise ValueError(f"{model} resolution is unsupported: {effective_resolution}")
            body["resolution"] = effective_resolution
        if profile.supports_generate_audio and generate_audio is not None:
            body["generate_audio"] = generate_audio
    if seed is not None:
        body["seed"] = seed

    refs = list(references or [])
    frame_refs = [ref for ref in refs if ref.frame_type]
    input_refs = [ref for ref in refs if not ref.frame_type]
    if frame_refs and input_refs:
        raise ValueError("frame_images and input_references are mutually exclusive")
    if frame_refs:
        body["frame_images"] = [
            {
                "image_url": {
                    "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
                },
                "frame_type": ref.frame_type,
            }
            for ref in frame_refs
        ]
    elif input_refs:
        # No `role` field: confirmed live against a real AiHubMix credential
        # (2026-08-20) that this endpoint's schema is strict, not tolerant of
        # unknown fields — adding `role` (to mirror MiniMax's own native
        # "reference-to-video" contract) got a hard `400 schema_violation:
        # "Unknown request parameter: \`role\`."` on every submission. AiHubMix's
        # own docs don't cover minimax-h3 at all, so this endpoint's contract
        # is only known through what's actually been verified live: `type`+
        # `url` only, nothing else. `wan2.7-videoedit` with a reference
        # does not use this field — see `_uses_wan_openai_edit`.
        body["input_references"] = [
            {
                "type": "video_url" if ref.media_type == "video" else "image_url",
                "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS),
            }
            for ref in input_refs[:_MAX_INPUT_REFERENCES]
        ]
    return body


def _validate_native_video_request(model: str, request: GenerationRequest) -> None:
    """The same physical limits `build_video_payload` enforces, for the
    OpenAI-track Wan-edit branch that never calls that builder."""
    profile = native_video_profile(model)
    if profile is None:
        return
    if not profile.min_duration_seconds <= request.duration_seconds <= profile.max_duration_seconds:
        raise ValueError(
            f"{model} duration must be between {profile.min_duration_seconds} and "
            f"{profile.max_duration_seconds} seconds"
        )
    if request.aspect_ratio not in profile.aspect_ratios:
        raise ValueError(f"{model} aspect ratio is unsupported: {request.aspect_ratio}")
    if request.resolution is not None and request.resolution not in profile.resolutions:
        raise ValueError(f"{model} resolution is unsupported: {request.resolution}")


def _has_video_references(request: GenerationRequest) -> bool:
    if any(ref.object_key for ref in request.references):
        return True
    return bool(request.reference_object_keys)


def _uses_wan_openai_edit(model: str, request: GenerationRequest) -> bool:
    """`wan2.7-videoedit` + a reference must leave the MiniMax facade.

    `/ai/v1/videos` only accepts `input_references[].type` in
    `{image_url, video_url, audio_url}` (live create 400 on `video`,
    `job_01m163ththh5yer79dtmv0q85d`). The gateway then forwards that
    type unchanged into Wan's `input.media[].type`, which only accepts
    `video` / `reference_image` (live poll failure on `video_url`,
    `job_01m1608wr7hm49wzdggkynz6ay`). The published `extra` field is
    ignored for this mapping. The shape that create+completed on a live
    credential (2026-08-29) is `POST /v1/videos` with
    `extra_body.input.media`.
    """
    return model.strip().lower() == WAN_VIDEOEDIT_MODEL and _has_video_references(request)


def _wan_edit_media(request: GenerationRequest) -> list[dict[str, str]]:
    refs = list(request.references)
    if not refs and request.reference_object_keys:
        refs = [
            ProviderReference(object_key=key, media_type="image")
            for key in request.reference_object_keys
        ]
    return [
        {
            "type": "video" if ref.media_type == "video" else "reference_image",
            "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS),
        }
        for ref in refs[:_MAX_INPUT_REFERENCES]
    ]


def _first_reference(request: GenerationRequest) -> ProviderReference | None:
    """The one reference the OpenAI Videos API track's `input_reference`
    (singular — unlike the native track's `input_references` list) could
    carry, if the caller supplied any at all."""
    if request.references:
        return request.references[0]
    if request.reference_object_keys:
        return ProviderReference(object_key=request.reference_object_keys[0], media_type="image")
    return None


def _video_reference_url(request: GenerationRequest) -> str | None:
    """The source clip to analyze, as a signed URL.

    Always URL-based, never inlined as base64 — same reasoning as video
    generation's `frame_images`/`input_references`: a 3-minute reference
    clip is routinely far larger than any sane inline request body.
    """
    for ref in request.references:
        if ref.media_type == "video" and ref.object_key:
            return s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
    for key in request.reference_object_keys:
        return s3.presign_get(key, expires_in=_REFERENCE_URL_TTL_SECONDS)
    return None


def _video_analysis_result_json(payload: object) -> dict[str, Any] | None:
    """Pulls the structured breakdown out of a chat-completions-shaped reply.

    Shares `app.llm.normalize`'s think-block stripping and JSON extraction
    with the general LLM gateway rather than re-implementing them — a
    reasoning-style video model wrapping its answer the same way the text
    gateway's models do is exactly the case those helpers exist for.
    """
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    text = content if isinstance(content, str) else _flatten_content_parts(content)
    if not text:
        return None
    return extract_json(strip_thinking(text))


def _flatten_content_parts(content: object) -> str:
    """Some OpenAI-compatible gateways answer multimodal turns with a list of
    `{"type": "text", "text": ...}` parts instead of a plain string."""
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "\n".join(parts)


def _image_reference_keys(request: GenerationRequest) -> list[str]:
    keys: list[str] = []
    for ref in request.references:
        if ref.media_type == "image" and ref.object_key:
            keys.append(ref.object_key)
    for key in request.reference_object_keys:
        if key not in keys:
            keys.append(key)
    return keys[:_MAX_INPUT_REFERENCES]


def _image_reference_urls(request: GenerationRequest) -> list[str]:
    """Signed URLs (or inline base64 data URIs) for image-to-image references.

    Text-to-image leaves this empty. Image-to-image for non-gpt-image-2
    models sends the same OpenAI `/v1/images/generations` JSON with an extra
    `image` field rather than switching to the multipart `/v1/images/edits`
    path. `gpt-image-2` uses `_submit_gpt_image_2_edit` instead.

    `Settings.embed_reference_images_as_base64` (on for `local`/`test`)
    switches this from a presigned GET URL to an inline `data:` URI —
    aihubmix is a real external HTTP API and can never reach a
    `localhost`-only object store, so a presigned URL there is silently
    unfetchable and the provider quietly falls back to generating from the
    prompt text alone with no actual reference image. A real deployment's
    public bucket domain stays on the cheaper URL path (aihubmix fetches
    once instead of every reference byte round-tripping through our own
    request body). Scoped to this single-image field only — video's
    `frame_images`/`input_references` (`build_video_payload`) stay URL-only,
    since a video reference routinely exceeds any sane inline-body size.
    """
    keys = _image_reference_keys(request)
    if get_settings().embed_reference_images_as_base64:
        return [_data_uri_for(key) for key in keys]
    return [s3.presign_get(key, expires_in=_REFERENCE_URL_TTL_SECONDS) for key in keys]


# aihubmix's documented single-image limit for inline/base64 input
# (`docs.aihubmix.com/en/api/vision`).
_MAX_BASE64_REFERENCE_BYTES = 20 * 1024 * 1024


def _data_uri_for(object_key: str) -> str:
    """Inlines an object-store key's bytes as a `data:` URI.

    A reference this large was never going to fit inside aihubmix's own
    base64 limit either way, so it falls back to the presigned URL — no
    worse than the pre-fix behaviour for that one oversized edge case.
    """
    payload = s3.get_object(object_key)
    if len(payload) > _MAX_BASE64_REFERENCE_BYTES:
        return s3.presign_get(object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
    mime = mimetypes.guess_type(object_key)[0] or "image/png"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _is_qwen_model(model: str) -> bool:
    return "qwen" in model.strip().lower()


def is_gpt_image_2(model: str) -> bool:
    return model.strip().lower() == GPT_IMAGE_2_MODEL


def _gpt_image_2_quality(quality_tier: str) -> str:
    return _GPT_IMAGE_2_QUALITY_BY_TIER.get(quality_tier, "medium")


def _gpt_image_2_size(aspect_ratio: str) -> str:
    return _GPT_IMAGE_2_SIZE_BY_ASPECT.get(aspect_ratio, "1024x1024")


def _qwen_edit_output_url(payload: object) -> str | None:
    """The predictions endpoint answers `{"output": [{"url": ...}]}` — a
    different shape than `/v1/images/generations`'s `{"data": [...]}` (see
    `_image_bytes_from_payload`), and (observed 2026-08-19) always a URL,
    never a `b64_json`."""
    if not isinstance(payload, dict):
        return None
    outputs = payload.get("output")
    if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
        return None
    url = outputs[0].get("url")
    return url if isinstance(url, str) and url else None


def _image_bytes_from_payload(payload: object, client: httpx.Client) -> bytes | None:
    """OpenAI-compatible image responses carry either `b64_json` or a `url`."""
    if not isinstance(payload, dict):
        return None
    entries = payload.get("data") or []
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        return None
    entry = entries[0]
    encoded = entry.get("b64_json")
    if isinstance(encoded, str) and encoded:
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError):
            return None
    url = entry.get("url")
    if isinstance(url, str) and url:
        download = client.get(url)
        download.raise_for_status()
        return download.content or None
    return None


def _http_error_detail(exc: httpx.HTTPStatusError, api_key: str) -> str:
    status = exc.response.status_code
    text = (exc.response.text or "").replace(api_key, "[redacted]")[:300]
    return f"HTTP {status}: {text}" if text else f"HTTP {status}"


def _size_for(aspect_ratio: str, quality_tier: str) -> str:
    """Map aspect ratio onto a gateway-legal OpenAI size.

    `quality_tier` stays in the signature so call sites are unchanged; this
    protocol's allowed grid does not vary by preview/standard/cinematic.
    """
    _ = quality_tier
    return _IMAGE_SIZE_BY_ASPECT.get(aspect_ratio, "1024x1024")


def _probe_image_size(payload: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError):
        return None, None
