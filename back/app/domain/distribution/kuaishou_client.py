"""Kuaishou (快手) Open Platform client.

Kuaishou's app registration (AppId + verification info, approved before an
AppId/AppSecret pair is issued) and OAuth authorization
(`code2AccessToken`/`refreshToken`) are documented to follow the same overall
shape as Douyin's: app-level credentials plus a per-creator OAuth grant, then
a content-management flow of create → init-upload → upload → publish, with a
metrics query available afterwards.

Unlike `douyin_client.py`'s `create_post`, none of Kuaishou's exact endpoint
paths were pinned down against the live docs before writing this file — per
the plan this is deliberate: the *architecture* (interface, error handling,
encryption, OAuth flow shape, credential gating) matters more here than the
exact undocumented URL, since none of it can be exercised end-to-end without
a real AppId/AppSecret anyway. Every path constant below is a placeholder in
Kuaishou's plausible `open.kuaishou.com` open-platform shape and should be
confirmed against the real docs the day this org's Kuaishou registration
completes.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.domain.distribution.client_base import (
    AccountStatsSnapshot,
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

AUTHORIZE_URL = "https://open.kuaishou.com/oauth2/authorize"
TOKEN_URL = "https://open.kuaishou.com/oauth2/access_token"
REFRESH_URL = "https://open.kuaishou.com/oauth2/refresh_token"
UPLOAD_INIT_URL = "https://open.kuaishou.com/openapi/photo/init"
UPLOAD_URL = "https://open.kuaishou.com/openapi/photo/upload"
PUBLISH_URL = "https://open.kuaishou.com/openapi/photo/publish"
METRICS_URL = "https://open.kuaishou.com/openapi/photo/stats"
USER_INFO_URL = "https://open.kuaishou.com/openapi/user/info"

PUBLISH_SCOPE = "user_info,photo.publish"
MAX_CAPTION_CHARS = 1000
_TIMEOUT_SECONDS = 15.0


class KuaishouClient(PlatformClient):
    def authorize_url(self, state: str) -> str:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        url = httpx.URL(
            AUTHORIZE_URL,
            params={
                "app_id": settings.kuaishou_app_id,
                "response_type": "code",
                "scope": PUBLISH_SCOPE,
                "redirect_uri": settings.kuaishou_redirect_uri,
                "state": state,
            },
        )
        return str(url)

    def exchange_code(self, code: str) -> TokenBundle:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        payload = {
            "app_id": settings.kuaishou_app_id,
            "app_secret": settings.kuaishou_app_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        data = self._post(TOKEN_URL, payload, error=PlatformOAuthFailed)
        return _token_bundle_from(data)

    def refresh_token(self, refresh_token: str) -> TokenBundle:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        payload = {
            "app_id": settings.kuaishou_app_id,
            "app_secret": settings.kuaishou_app_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        data = self._post(REFRESH_URL, payload, error=PlatformOAuthFailed)
        return _token_bundle_from(data)

    def init_upload(self, access_token: str) -> UploadTicket:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            UPLOAD_INIT_URL,
            {},
            error=PlatformPublishFailed,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return UploadTicket(
            upload_token=str(data.get("upload_token", "")),
            upload_server_uri=str(data.get("upload_url", "")),
        )

    def upload_video(self, ticket: UploadTicket, file_bytes: bytes) -> str:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            UPLOAD_URL,
            {"upload_token": ticket.upload_token},
            error=PlatformPublishFailed,
            files={"photo": ("video.mp4", file_bytes, "video/mp4")},
        )
        video_id = data.get("photo_id") or data.get("video_id")
        if not video_id:
            raise PlatformPublishFailed(platform_error_code=data.get("result"))
        return str(video_id)

    def create_post(
        self, access_token: str, open_id: str, video_id: str, caption: str
    ) -> PublishResult:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        body = {"photo_id": video_id, "caption": caption[:MAX_CAPTION_CHARS], "open_id": open_id}
        data = self._post(
            PUBLISH_URL,
            body,
            error=PlatformPublishFailed,
            headers={"Authorization": f"Bearer {access_token}"},
            json_body=True,
        )
        result_code = int(data.get("result") or 0)
        if result_code != 0 and result_code != 1:
            # Kuaishou's own "1 == success" convention, mirrored consistently
            # with Douyin's "0 == success" in `_post`'s caller-side check.
            raise PlatformPublishFailed(platform_error_code=result_code)
        return PublishResult(
            item_id=data.get("photo_id"),
            video_id=data.get("photo_id"),
            error_code=0 if result_code in (0, 1) else result_code,
        )

    def fetch_metrics(self, access_token: str, open_id: str, item_id: str) -> MetricsSnapshot:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            METRICS_URL,
            {"photo_id": item_id, "open_id": open_id},
            error=PlatformPublishFailed,
            headers={"Authorization": f"Bearer {access_token}"},
            json_body=True,
        )
        return MetricsSnapshot(
            view_count=int(data.get("view_count") or 0),
            like_count=int(data.get("like_count") or 0),
            comment_count=int(data.get("comment_count") or 0),
            share_count=int(data.get("share_count") or 0),
            finish_rate_bp=_finish_rate_bp(data),
            avg_play_duration_ms=_avg_play_duration_ms(data),
        )

    def fetch_account_stats(self, access_token: str, open_id: str) -> AccountStatsSnapshot:
        settings = get_settings()
        if not settings.kuaishou_app_id or not settings.kuaishou_app_secret:
            raise PlatformNotConfigured()
        data = self._post(
            USER_INFO_URL,
            {"open_id": open_id},
            error=PlatformPublishFailed,
            headers={"Authorization": f"Bearer {access_token}"},
            json_body=True,
        )
        return AccountStatsSnapshot(follower_count=_follower_count(data))

    # -- internals ----------------------------------------------------------

    def _post(
        self,
        url: str,
        payload: dict[str, object],
        *,
        error: type[DomainError],
        headers: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        json_body: bool = False,
    ) -> dict[str, object]:
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                if files is not None:
                    response = client.post(url, data=payload, files=files, headers=headers)
                elif json_body:
                    response = client.post(url, json=payload, headers=headers)
                else:
                    response = client.post(url, data=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise error() from exc
        except httpx.HTTPStatusError as exc:
            raise error(platform_error_code=exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise error() from exc

        if not isinstance(body, dict):
            raise error()
        return body


def _token_bundle_from(data: dict[str, object]) -> TokenBundle:
    if not data.get("access_token"):
        raise PlatformOAuthFailed(platform_error_code=data.get("result"))
    return TokenBundle(
        access_token=str(data["access_token"]),
        refresh_token=str(data["refresh_token"]) if data.get("refresh_token") else None,
        expires_in=int(data.get("expires_in") or 0),
        open_id=str(data.get("open_id", "")),
    )


def _finish_rate_bp(data: dict[str, object]) -> int | None:
    """Basis points (0-10000) — neither key name below is confirmed against
    live docs (see the file's own header disclaimer)."""
    raw = data.get("complete_play_rate")
    if raw is None:
        raw = data.get("finish_rate")
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        return round(float(raw) * 10000)
    except (TypeError, ValueError):
        return None


def _avg_play_duration_ms(data: dict[str, object]) -> int | None:
    raw = data.get("play_duration_avg")
    if raw is None:
        raw = data.get("avg_play_duration")
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _follower_count(data: dict[str, object]) -> int | None:
    raw = data.get("follower_count")
    if raw is None:
        raw = data.get("fans_count")
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None
