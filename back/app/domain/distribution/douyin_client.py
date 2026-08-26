"""Douyin (抖音) Open Platform client.

Endpoint shapes below are grounded in the official docs
(`open.douyin.com`), verified prior to writing this file:

* OAuth authorize: `https://open.douyin.com/platform/oauth/connect/` —
  standard `client_key`/`response_type=code`/`scope`/`redirect_uri`/`state`.
  The publish scope, `video.create.bind`, is a sensitive permission that
  needs its own application + 1-3 business day manual review on top of basic
  app registration — nothing here can make that review happen faster.
* Token exchange/refresh: `https://open.douyin.com/oauth/access_token/` and
  `https://open.douyin.com/oauth/refresh_token/`, both form-encoded POSTs
  returning `{"data": {...}}`.
* Publish: `POST https://open.douyin.com/api/douyin/v1/video/create_video/`
  — header `access-token`, query `open_id`, JSON body
  `{"video_id", "text"}` (caption capped at 1000 chars). This exact path and
  shape is the one fact in this file confirmed against the live docs, not
  inferred by analogy.
* Upload is the two-step ticket pattern the video/create flow depends on
  (init → get `upload_token`/`upload_server_uri` → upload the binary →
  receive an encrypted `video_id`); the precise init/part endpoint names
  below are a reasonable, internally consistent guess at that flow's shape,
  not independently doc-verified the way `create_video` is — expect to
  adjust them once real AppKey/AppSecret exist and the flow can be run
  end-to-end.

Every method's first statement is the "is this app even registered" guard:
if `settings.douyin_app_key`/`douyin_app_secret` is empty, raise
`PlatformNotConfigured` before touching `httpx` at all.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.domain.distribution.client_base import (
    MetricsSnapshot,
    PlatformClient,
    PublishResult,
    TokenBundle,
    UploadTicket,
)
from app.domain.errors import (
    DomainError,
    PlatformNotConfigured,
    PlatformOAuthFailed,
    PlatformPublishFailed,
)

AUTHORIZE_URL = "https://open.douyin.com/platform/oauth/connect/"
TOKEN_URL = "https://open.douyin.com/oauth/access_token/"
REFRESH_URL = "https://open.douyin.com/oauth/refresh_token/"
UPLOAD_INIT_URL = "https://open.douyin.com/api/douyin/v1/video/init/"
UPLOAD_PART_URL = "https://open.douyin.com/api/douyin/v1/video/upload/"
CREATE_VIDEO_URL = "https://open.douyin.com/api/douyin/v1/video/create_video/"
VIDEO_DATA_URL = "https://open.douyin.com/api/douyin/v1/video/data/"

# The publish scope — sensitive, requires separate manual review.
PUBLISH_SCOPE = "video.create.bind"

MAX_CAPTION_CHARS = 1000
_TIMEOUT_SECONDS = 15.0


class DouyinClient(PlatformClient):
    def authorize_url(self, state: str) -> str:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        url = httpx.URL(
            AUTHORIZE_URL,
            params={
                "client_key": settings.douyin_app_key,
                "response_type": "code",
                "scope": PUBLISH_SCOPE,
                "redirect_uri": settings.douyin_redirect_uri,
                "state": state,
            },
        )
        return str(url)

    def exchange_code(self, code: str) -> TokenBundle:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        payload = {
            "client_key": settings.douyin_app_key,
            "client_secret": settings.douyin_app_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        data = self._post(TOKEN_URL, payload, error=PlatformOAuthFailed)
        return _token_bundle_from(data)

    def refresh_token(self, refresh_token: str) -> TokenBundle:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        payload = {
            "client_key": settings.douyin_app_key,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        data = self._post(REFRESH_URL, payload, error=PlatformOAuthFailed)
        return _token_bundle_from(data)

    def init_upload(self, access_token: str) -> UploadTicket:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            UPLOAD_INIT_URL,
            {},
            error=PlatformPublishFailed,
            headers={"access-token": access_token},
        )
        return UploadTicket(
            upload_token=str(data.get("upload_token", "")),
            upload_server_uri=str(data.get("upload_server_uri", "")),
        )

    def upload_video(self, ticket: UploadTicket, file_bytes: bytes) -> str:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            UPLOAD_PART_URL,
            {"upload_token": ticket.upload_token},
            error=PlatformPublishFailed,
            files={"video": ("video.mp4", file_bytes, "video/mp4")},
        )
        video_id = data.get("video_id")
        if not video_id:
            raise PlatformPublishFailed(platform_error_code=data.get("error_code"))
        return str(video_id)

    def create_post(
        self, access_token: str, open_id: str, video_id: str, caption: str
    ) -> PublishResult:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        body = {"video_id": video_id, "text": caption[:MAX_CAPTION_CHARS]}
        data = self._post(
            CREATE_VIDEO_URL,
            body,
            error=PlatformPublishFailed,
            headers={"access-token": access_token},
            params={"open_id": open_id},
            json_body=True,
        )
        error_code = int(data.get("error_code") or 0)
        if error_code != 0:
            raise PlatformPublishFailed(platform_error_code=error_code)
        return PublishResult(
            item_id=data.get("item_id"),
            video_id=data.get("video_id"),
            error_code=error_code,
        )

    def fetch_metrics(self, access_token: str, open_id: str, item_id: str) -> MetricsSnapshot:
        settings = get_settings()
        if not settings.douyin_app_key or not settings.douyin_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            VIDEO_DATA_URL,
            {"item_ids": [item_id]},
            error=PlatformPublishFailed,
            headers={"access-token": access_token},
            params={"open_id": open_id},
            json_body=True,
        )
        stats = (data.get("list") or [{}])[0]
        return MetricsSnapshot(
            view_count=int(stats.get("play_count") or 0),
            like_count=int(stats.get("digg_count") or 0),
            comment_count=int(stats.get("comment_count") or 0),
            share_count=int(stats.get("share_count") or 0),
        )

    # -- internals ----------------------------------------------------------

    def _post(
        self,
        url: str,
        payload: dict[str, object],
        *,
        error: type[DomainError],
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        json_body: bool = False,
    ) -> dict[str, object]:
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                if files is not None:
                    response = client.post(
                        url, data=payload, files=files, headers=headers, params=params
                    )
                elif json_body:
                    response = client.post(url, json=payload, headers=headers, params=params)
                else:
                    response = client.post(url, data=payload, headers=headers, params=params)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise error() from exc
        except httpx.HTTPStatusError as exc:
            raise error(platform_error_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise error() from exc

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise error()
        return data


def _token_bundle_from(data: dict[str, object]) -> TokenBundle:
    error_code = int(data.get("error_code") or 0)
    if error_code != 0 or not data.get("access_token"):
        raise PlatformOAuthFailed(platform_error_code=error_code)
    return TokenBundle(
        access_token=str(data["access_token"]),
        refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
        expires_in=int(data.get("expires_in") or 0),
        open_id=str(data.get("open_id", "")),
    )
