"""Direct, side-effect-minimised connectivity checks for configured endpoints.

These checks deliberately target exactly one saved endpoint.  They do not use
the LLM failover pool, provider routing, circuit breakers, or platform job
records, so an operator can tell whether that endpoint itself is usable.
"""

from __future__ import annotations

import base64
import io
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAIError
from PIL import Image

from app.llm import client as llm_client
from app.models.enums import Operation
from app.platform_config.schemas import LlmProviderEndpoint
from app.providers import dmxapi_media, fal_media, minimax_v2_media
from app.providers.aihubmix_media import (
    build_video_payload,
    is_gpt_image_2,
    media_client_base,
    media_request_path,
)

_MEDIA_PROBE_PRIORITY = (
    Operation.AUDIO_GENERATION.value,
    Operation.MUSIC_GENERATION.value,
    Operation.TEXT_TO_IMAGE.value,
    Operation.IMAGE_TO_IMAGE.value,
    Operation.TEXT_TO_VIDEO.value,
    Operation.IMAGE_TO_VIDEO.value,
    Operation.VIDEO_TO_VIDEO.value,
    Operation.VIDEO_ANALYSIS.value,
)
_VIDEO_PROBES = frozenset(
    {
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }
)


@dataclass(frozen=True, slots=True)
class ConnectivityResult:
    target_model: str | None
    probe_type: str
    reachable: bool
    usable: bool
    latency_ms: int
    provider_status_code: int | None = None
    error_code: str | None = None
    warning_code: str | None = None
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    external_task_id: str | None = None


def validate_endpoint(endpoint: LlmProviderEndpoint) -> ConnectivityResult:
    if endpoint.kind == "general":
        return _validate_general(endpoint)
    return _validate_media(endpoint)


def _validate_general(endpoint: LlmProviderEndpoint) -> ConnectivityResult:
    started = time.perf_counter()
    client = llm_client.client_for_endpoint(endpoint)
    target_model = endpoint.model or None

    try:
        if target_model is None:
            models = client.models.list()
            entries = list(getattr(models, "data", []) or [])
            target_model = str(getattr(entries[0], "id", "") or "") if entries else None
            if not target_model:
                return _result(
                    started,
                    target_model=None,
                    probe_type="chat_completion",
                    reachable=True,
                    usable=False,
                    provider_status_code=200,
                    error_code="no_model",
                )

        raw = llm_client.call_gateway_once(
            client=client,
            model=target_model,
            messages=[
                {"role": "system", "content": "Reply briefly."},
                {"role": "user", "content": "Connectivity check. Reply OK."},
            ],
            max_tokens=16,
            temperature=0.0,
            expect_json=False,
        )
        usable = bool(getattr(raw, "choices", None))
        return _result(
            started,
            target_model=target_model,
            probe_type="chat_completion",
            reachable=True,
            usable=usable,
            provider_status_code=200,
            error_code=None if usable else "invalid_response",
        )
    except (OpenAIError, TimeoutError, ConnectionError) as exc:
        status_code = _status_code(exc)
        provider_code, provider_message = _exception_provider_error(exc, endpoint.api_key)
        return _result(
            started,
            target_model=target_model,
            probe_type="chat_completion",
            reachable=status_code is not None,
            usable=False,
            provider_status_code=status_code,
            error_code=_error_code(exc, status_code),
            provider_error_code=provider_code,
            provider_error_message=provider_message,
        )


def _validate_media(endpoint: LlmProviderEndpoint) -> ConnectivityResult:
    started = time.perf_counter()
    probe_type = next((tag for tag in _MEDIA_PROBE_PRIORITY if tag in endpoint.capabilities), None)
    if probe_type is None:
        return _result(
            started,
            target_model=endpoint.model or None,
            probe_type="media_generation",
            reachable=False,
            usable=False,
            error_code="no_capability",
        )

    try:
        auth_header = (
            f"Key {endpoint.api_key}"
            if endpoint.protocol == "fal"
            else f"Bearer {endpoint.api_key}"
        )
        with httpx.Client(
            base_url=media_client_base(endpoint.base_url),
            headers={"Authorization": auth_header},
            timeout=endpoint.timeout_ms / 1000,
        ) as client:
            if probe_type == Operation.AUDIO_GENERATION.value:
                if endpoint.protocol == "fal":
                    # fal's `minimax/voice-clone` has no OpenAI-shaped
                    # `/v1/audio/speech` endpoint at all — it is a queue
                    # submit, same skeleton as the video routes below, just
                    # against the audio app path.
                    return _probe_fal_audio(client, endpoint, started, probe_type)
                response = client.post(
                    media_request_path(endpoint.base_url, "/v1/audio/speech"),
                    json={
                        "model": endpoint.model,
                        "input": "Connectivity check.",
                        "voice": "alloy",
                        "response_format": "mp3",
                    },
                )
                return _media_response(
                    started,
                    endpoint.model,
                    probe_type,
                    response,
                    usable=bool(response.content),
                    api_key=endpoint.api_key,
                )

            if probe_type == Operation.MUSIC_GENERATION.value:
                if endpoint.protocol == "fal":
                    return _probe_fal_audio(client, endpoint, started, probe_type)
                if endpoint.protocol == "dmxapi":
                    response = client.post(
                        media_request_path(endpoint.base_url, "/v1/responses"),
                        json=dmxapi_media.probe_music_body(),
                    )
                    if response.status_code >= 400:
                        return _media_response(
                            started,
                            endpoint.model,
                            probe_type,
                            response,
                            usable=False,
                            api_key=endpoint.api_key,
                        )
                    url, _ = dmxapi_media.extract_music_result(_json_dict(response))
                    return _media_response(
                        started,
                        endpoint.model,
                        probe_type,
                        response,
                        usable=bool(url),
                        api_key=endpoint.api_key,
                    )
                return _result(
                    started,
                    target_model=endpoint.model,
                    probe_type=probe_type,
                    reachable=False,
                    usable=False,
                    error_code="no_capability",
                )

            if probe_type in {
                Operation.TEXT_TO_IMAGE.value,
                Operation.IMAGE_TO_IMAGE.value,
            }:
                if endpoint.protocol == "dmxapi":
                    dmx_body: dict[str, object] = {
                        "model": endpoint.model,
                        "input": "A plain blue square, connectivity test.",
                        "size": "1K",
                        "output_format": "png",
                    }
                    if probe_type == Operation.IMAGE_TO_IMAGE.value:
                        dmx_body["input"] = "Return this simple connectivity test image."
                        dmx_body["image"] = _probe_png_data_uri()
                    response = client.post(
                        media_request_path(endpoint.base_url, "/v1/responses"), json=dmx_body
                    )
                    return _media_response(
                        started,
                        endpoint.model,
                        probe_type,
                        response,
                        usable=_has_dmxapi_image_result(response),
                        api_key=endpoint.api_key,
                    )

                body: dict[str, object] = {
                    "model": endpoint.model,
                    "prompt": "A plain blue square, connectivity test.",
                    "size": "1024x1024",
                    "n": 1,
                }
                if is_gpt_image_2(endpoint.model):
                    body["quality"] = "low"
                    body["output_format"] = "png"
                if probe_type == Operation.IMAGE_TO_IMAGE.value:
                    body["prompt"] = "Return this simple connectivity test image."
                    body["image"] = _probe_png_data_uri()
                response = client.post(
                    media_request_path(endpoint.base_url, "/v1/images/generations"), json=body
                )
                return _media_response(
                    started,
                    endpoint.model,
                    probe_type,
                    response,
                    usable=_has_data_entry(response),
                    api_key=endpoint.api_key,
                )

            if probe_type == Operation.VIDEO_ANALYSIS.value:
                # No sample clip to safely attach from the admin panel, so
                # this only checks that the endpoint/model answers a plain
                # chat turn — it proves reachability and auth, not that the
                # model can actually watch a video. `_submit_video_analysis`
                # is where the real `video_url` contract gets exercised.
                response = client.post(
                    media_request_path(endpoint.base_url, "/v1/chat/completions"),
                    json={
                        "model": endpoint.model,
                        "messages": [{"role": "user", "content": "Connectivity check. Reply OK."}],
                        "max_tokens": 16,
                        "temperature": 0.0,
                    },
                )
                return _media_response(
                    started,
                    endpoint.model,
                    probe_type,
                    response,
                    usable=_has_choice_entry(response),
                    api_key=endpoint.api_key,
                )

            if endpoint.protocol == "openai":
                response = client.post(
                    media_request_path(endpoint.base_url, "/v1/videos"),
                    json={
                        "model": endpoint.model,
                        "prompt": "A static blue square, connectivity test.",
                        "seconds": 5,
                    },
                )
            elif endpoint.protocol == "dmxapi":
                try:
                    dmx_video_body = dmxapi_media.probe_video_body(endpoint.model)
                except ValueError:
                    # `MiniMax-H3-video_regeneration` always needs a real
                    # 768P source clip meeting an exact physical spec — no
                    # minimal body can validate it safely.
                    return _result(
                        started,
                        target_model=endpoint.model,
                        probe_type=probe_type,
                        reachable=False,
                        usable=False,
                        error_code="no_capability",
                    )
                response = client.post(
                    media_request_path(endpoint.base_url, "/v1/responses"), json=dmx_video_body
                )
            elif endpoint.protocol == "minimax_v2":
                response = client.post(
                    media_request_path(endpoint.base_url, "/v2/video_generation"),
                    json=minimax_v2_media.probe_video_body(endpoint.model),
                )
            elif endpoint.protocol == "fal":
                response = client.post(
                    media_request_path(
                        endpoint.base_url, fal_media.probe_submit_path(endpoint.model)
                    ),
                    json=fal_media.probe_video_body(endpoint.model),
                )
            else:
                response = client.post(
                    media_request_path(endpoint.base_url, "/ai/v1/videos"),
                    json=build_video_payload(
                        model=endpoint.model,
                        prompt="A static blue square, connectivity test.",
                        duration_seconds=5,
                        aspect_ratio="16:9",
                    ),
                )
            if response.status_code >= 400:
                return _media_response(
                    started,
                    endpoint.model,
                    probe_type,
                    response,
                    usable=False,
                    api_key=endpoint.api_key,
                )
            payload = _json_dict(response)
            if endpoint.protocol == "dmxapi":
                task_id = dmxapi_media.extract_task_id(endpoint.model, payload)
            elif endpoint.protocol == "minimax_v2":
                task_id = minimax_v2_media.extract_task_id(payload)
            elif endpoint.protocol == "fal":
                request_id = fal_media.extract_request_id(payload)
                task_id = (
                    fal_media.encode_task_id(fal_media.ROUTE_TEXT_TO_VIDEO, request_id)
                    if request_id
                    else None
                )
                if request_id:
                    _cancel_fal_probe(client, endpoint, request_id)
            else:
                task_id = payload.get("id")
            if not task_id:
                return _result(
                    started,
                    target_model=endpoint.model,
                    probe_type=probe_type,
                    reachable=True,
                    usable=False,
                    provider_status_code=response.status_code,
                    error_code="invalid_response",
                )
            return _result(
                started,
                target_model=endpoint.model,
                probe_type=probe_type,
                reachable=True,
                usable=True,
                provider_status_code=response.status_code,
                external_task_id=str(task_id),
            )
    except httpx.TimeoutException:
        return _result(
            started,
            target_model=endpoint.model,
            probe_type=probe_type,
            reachable=False,
            usable=False,
            error_code="timeout",
        )
    except httpx.TransportError:
        return _result(
            started,
            target_model=endpoint.model,
            probe_type=probe_type,
            reachable=False,
            usable=False,
            error_code="connection_failed",
        )


def _media_response(
    started: float,
    model: str,
    probe_type: str,
    response: httpx.Response,
    *,
    usable: bool,
    api_key: str,
) -> ConnectivityResult:
    if response.status_code >= 400:
        provider_code, provider_message = _provider_error(response, api_key)
        return _result(
            started,
            target_model=model,
            probe_type=probe_type,
            reachable=True,
            usable=False,
            provider_status_code=response.status_code,
            error_code=_http_error_code(response.status_code),
            provider_error_code=provider_code,
            provider_error_message=provider_message,
        )
    return _result(
        started,
        target_model=model,
        probe_type=probe_type,
        reachable=True,
        usable=usable,
        provider_status_code=response.status_code,
        error_code=None if usable else "invalid_response",
    )


def _has_data_entry(response: httpx.Response) -> bool:
    if response.status_code >= 400:
        return False
    data = _json_dict(response).get("data")
    return isinstance(data, list) and bool(data)


def _has_choice_entry(response: httpx.Response) -> bool:
    if response.status_code >= 400:
        return False
    choices = _json_dict(response).get("choices")
    return isinstance(choices, list) and bool(choices)


def _has_dmxapi_image_result(response: httpx.Response) -> bool:
    if response.status_code >= 400:
        return False
    url, b64 = dmxapi_media.extract_seedream_result(_json_dict(response))
    return bool(url or b64)


def _cancel_fal_probe(client: httpx.Client, endpoint: LlmProviderEndpoint, request_id: str) -> None:
    """Best-effort cancel so an admin connectivity ping does not leave a
    billable H3 Max render sitting in fal's queue."""
    try:
        client.put(
            media_request_path(
                endpoint.base_url,
                fal_media.probe_cancel_path(endpoint.model, request_id),
            )
        )
    except httpx.HTTPError:
        return


def _cancel_fal_audio_probe(
    client: httpx.Client, endpoint: LlmProviderEndpoint, request_id: str
) -> None:
    """Best-effort cancel for a voice-clone/music/SFX connectivity probe —
    same reasoning as `_cancel_fal_probe`'s video counterpart."""
    try:
        client.put(
            media_request_path(
                endpoint.base_url,
                fal_media.probe_audio_cancel_path(endpoint.model, request_id),
            )
        )
    except httpx.HTTPError:
        return


def _probe_fal_audio(
    client: httpx.Client, endpoint: LlmProviderEndpoint, started: float, probe_type: str
) -> ConnectivityResult:
    """Shared fal queue probe for every audio-shaped capability this
    protocol serves (`AUDIO_GENERATION`'s voice-clone, `MUSIC_GENERATION`'s
    music/SFX): one submit against `fal_media.probe_audio_path`, then a
    best-effort cancel — this only needs proof the queue accepted the call,
    not the finished clip, so it never waits for `COMPLETED` the way the
    video branch below does.
    """
    response = client.post(
        media_request_path(endpoint.base_url, fal_media.probe_audio_path(endpoint.model)),
        json=fal_media.probe_audio_body(endpoint.model),
    )
    if response.status_code >= 400:
        return _media_response(
            started, endpoint.model, probe_type, response, usable=False, api_key=endpoint.api_key
        )
    payload = _json_dict(response)
    request_id = fal_media.extract_request_id(payload)
    if not request_id:
        return _result(
            started,
            target_model=endpoint.model,
            probe_type=probe_type,
            reachable=True,
            usable=False,
            provider_status_code=response.status_code,
            error_code="invalid_response",
        )
    _cancel_fal_audio_probe(client, endpoint, request_id)
    return _result(
        started,
        target_model=endpoint.model,
        probe_type=probe_type,
        reachable=True,
        usable=True,
        provider_status_code=response.status_code,
        external_task_id=str(request_id),
    )


def _json_dict(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _probe_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), (20, 80, 180)).save(buffer, format="PNG")
    return buffer.getvalue()


def _probe_png_data_uri() -> str:
    """A connectivity probe has no user asset to presign, so the reference
    travels inline. Production image-to-image uses a signed object URL."""
    return f"data:image/png;base64,{base64.b64encode(_probe_png()).decode()}"


def _status_code(exc: BaseException) -> int | None:
    value = getattr(exc, "status_code", None)
    return int(value) if isinstance(value, int) else None


def _error_code(exc: BaseException, status_code: int | None) -> str:
    if status_code is not None:
        return _http_error_code(status_code)
    return "timeout" if "timeout" in type(exc).__name__.lower() else "connection_failed"


def _http_error_code(status_code: int) -> str:
    if status_code == 401:
        return "auth_failed"
    if status_code == 403:
        return "access_forbidden"
    if status_code == 404:
        return "endpoint_not_found"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "provider_error"
    return "request_rejected"


def _result(
    started: float,
    *,
    target_model: str | None,
    probe_type: str,
    reachable: bool,
    usable: bool,
    provider_status_code: int | None = None,
    error_code: str | None = None,
    warning_code: str | None = None,
    provider_error_code: str | None = None,
    provider_error_message: str | None = None,
    external_task_id: str | None = None,
) -> ConnectivityResult:
    return ConnectivityResult(
        target_model=target_model,
        probe_type=probe_type,
        reachable=reachable,
        usable=usable,
        latency_ms=int((time.perf_counter() - started) * 1000),
        provider_status_code=provider_status_code,
        error_code=error_code,
        warning_code=warning_code,
        provider_error_code=provider_error_code,
        provider_error_message=provider_error_message,
        external_task_id=external_task_id,
    )


def _exception_provider_error(exc: BaseException, api_key: str) -> tuple[str | None, str | None]:
    response = getattr(exc, "response", None)
    if isinstance(response, httpx.Response):
        return _provider_error(response, api_key)
    body = getattr(response, "json", None)
    if callable(body):
        try:
            payload = body()
        except Exception:  # pragma: no cover - third-party SDK response shape
            payload = None
        return _provider_error_payload(payload, api_key)
    return None, None


def _provider_error(response: httpx.Response, api_key: str) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    return _provider_error_payload(payload, api_key)


def _provider_error_payload(payload: object, api_key: str) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    nested = payload.get("error")
    source = nested if isinstance(nested, dict) else payload
    code = source.get("code") or source.get("type")
    message = source.get("message") or source.get("detail")
    safe_code = _redact(str(code), api_key, limit=100) if code is not None else None
    safe_message = _redact(str(message), api_key, limit=300) if message is not None else None
    return safe_code, safe_message


def _redact(value: str, api_key: str, *, limit: int) -> str:
    safe = value.replace(api_key, "[redacted]") if api_key else value
    safe = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+\-/=]+", "Bearer [redacted]", safe)
    safe = re.sub(r"https?://\S+", "[redacted-url]", safe)
    return safe[:limit]
