"""P3-0: image requests only reach endpoints that declare `"image"` input.

Covers the two places the rule is visible from outside: script image
extraction (`POST /v1/scripts/extract`) and the binding `warnings` on the
`/admin/agents` profile views.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.llm import client as llm_client
from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import admin_header, auth_header

_TEXT_EP = {
    "name": "文本端点",
    "base_url": "https://text.invalid",
    "api_key": "k",
    "kind": "general",
    "model": "text-model",
    "role": "primary",
    "input_modalities": ["text"],
}
_VISION_EP = {
    "name": "识图端点",
    "base_url": "https://vision.invalid",
    "api_key": "k",
    "kind": "general",
    "model": "vision-model",
    "role": "backup",
    "input_modalities": ["text", "image"],
}


def _seed(db: Session, *, vision: bool) -> str:
    """Pool plus copy's default agent pinned to the text-only endpoint;
    returns that agent's id."""
    endpoints = {"text-ep": _TEXT_EP, **({"vision-ep": _VISION_EP} if vision else {})}
    config_service.set_value(
        db, "llm_providers", {"endpoints": endpoints}, actor_user_id=None, note="test"
    )
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    copy_default = agent_skills_service.default_profile(db, "copy")
    assert copy_default is not None
    agent_skills_service.update_profile(db, copy_default.id, default_endpoint_id="text-ep")
    db.commit()
    return copy_default.id


def _enable_script_studio(db: Session, actor: User) -> None:
    value = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["script_studio_enabled"] = True
    config_service.set_value(db, "feature_flags", value, actor_user_id=actor.id, note="test")


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _post_png(client: TestClient, author: User):  # type: ignore[no-untyped-def]
    return client.post(
        "/v1/scripts/extract",
        files={"file": ("page.png", _png(), "image/png")},
        headers=auth_header(author),
    )


@pytest.mark.real_gateway_seams
def test_script_image_extract_routes_to_the_image_endpoint(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db, vision=True)
    _enable_script_studio(db, author)
    served: list[str] = []

    def _gateway(**kw):  # type: ignore[no-untyped-def]
        served.append(kw["model"])
        return {
            "model": kw["model"],
            "choices": [{"message": {"content": "第一场 便利店"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(llm_client, "_call_gateway", _gateway)

    response = _post_png(client, author)

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "第一场 便利店"
    assert served == ["vision-model"]


@pytest.mark.real_gateway_seams
def test_script_image_extract_without_an_image_endpoint_returns_the_clear_message(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(db, vision=False)
    _enable_script_studio(db, author)

    def _gateway(**_kw):  # type: ignore[no-untyped-def]
        raise AssertionError("a text-only endpoint must not receive the image")

    monkeypatch.setattr(llm_client, "_call_gateway", _gateway)

    response = _post_png(client, author)

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "PROVIDER_TEMPORARY_FAILURE"
    assert error["message"] == "未配置支持图像输入的端点。"


def _profile(client: TestClient, admin: User, profile_id: str) -> dict:
    items = client.get("/v1/admin/agent-profiles?role=copy", headers=admin_header(admin)).json()[
        "items"
    ]
    return next(item for item in items if item["id"] == profile_id)


def test_admin_agent_views_warn_when_the_extract_agent_is_text_only(
    client: TestClient, db: Session, admin: User
) -> None:
    agent_id = _seed(db, vision=True)

    listed = _profile(client, admin, agent_id)
    assert listed["warnings"] == [
        "「剧本识图」需要图像输入，但绑定的端点都不支持，这类请求会改用共享池中支持图像的端点。"
    ]

    patched = client.patch(
        f"/v1/admin/agent-profiles/{agent_id}",
        json={"default_endpoint_id": "vision-ep"},
        headers=admin_header(admin),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["warnings"] == []


def test_admin_warnings_never_block_saving_a_text_only_binding(
    client: TestClient, db: Session, admin: User
) -> None:
    agent_id = _seed(db, vision=False)

    patched = client.patch(
        f"/v1/admin/agent-profiles/{agent_id}",
        json={"default_endpoint_id": "text-ep"},
        headers=admin_header(admin),
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["warnings"] == [
        "「剧本识图」需要图像输入，但没有已启用的端点支持图像，这类请求会直接报错。"
    ]
    # Agents that never send images carry no warning.
    others = client.get("/v1/admin/agent-profiles?role=safety", headers=admin_header(admin))
    assert all(item["warnings"] == [] for item in others.json()["items"])
