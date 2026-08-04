"""APNs 设备令牌注册。

只做注册表维护，不在这里发推送——发送逻辑在 `app.domain.notifications.push`，
按 `Notification` 行的接收者查这张表拿 token。见该模块顶部注释：本地开发环境
没有真实 APNs 证书，发送动作目前只落日志，接口契约已经就位。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.common import ApiModel, OkResponse
from app.domain.errors import Forbidden, NotFound
from app.models import Device
from app.models.base import utcnow

router = APIRouter(tags=["devices"])


class DeviceRegister(ApiModel):
    push_token: str = Field(min_length=8, max_length=255)
    platform: str = Field(default="ios", max_length=16)
    locale: str = Field(max_length=16)


class DeviceResponse(ApiModel):
    id: str
    platform: str
    locale: str


@router.post("/me/devices", response_model=DeviceResponse, status_code=201)
def register_device(
    payload: DeviceRegister, user: CurrentUser, session: DbSession
) -> DeviceResponse:
    """按 `push_token` upsert：重装 App 换新 token 会插新行，旧 token 静默失效——
    不主动清理旧行，靠 APNs 返回的 Unregistered 反馈去删（该反馈通道本地环境用不上）。
    """
    existing = session.scalar(select(Device).where(Device.push_token == payload.push_token))
    if existing is not None:
        existing.user_id = user.id
        existing.platform = payload.platform
        existing.locale = payload.locale
        existing.last_seen_at = utcnow()
        session.commit()
        return DeviceResponse(id=existing.id, platform=existing.platform, locale=existing.locale)

    device = Device(
        user_id=user.id,
        push_token=payload.push_token,
        platform=payload.platform,
        locale=payload.locale,
    )
    session.add(device)
    session.commit()
    return DeviceResponse(id=device.id, platform=device.platform, locale=device.locale)


@router.delete("/me/devices/{device_id}", response_model=OkResponse)
def unregister_device(device_id: str, user: CurrentUser, session: DbSession) -> OkResponse:
    device = session.get(Device, device_id)
    if device is None:
        raise NotFound("设备不存在。")
    if device.user_id != user.id:
        raise Forbidden("无权移除该设备。")
    session.delete(device)
    session.commit()
    return OkResponse()
