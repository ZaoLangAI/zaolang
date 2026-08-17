"""`POST /v1/generation/prompts/enhance`: the generation studio's own polish
endpoint — same domain logic as shortform's, no feature flag gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header
from tests.llm_catalog import bind_default_agents_to_catalog


@pytest.fixture
def bound_copy_agent(db: Session) -> None:
    """A catalog the copy agent can actually run on.

    Without it every call degrades, which these tests would rather assert
    explicitly (see `test_enhance_reports_an_outage_instead_of_echoing_back`)
    than accidentally exercise everywhere.
    """
    bind_default_agents_to_catalog(db)
    db.commit()


def test_enhance_diagnoses_each_dimension(
    client: TestClient, author: User, bound_copy_agent: None
) -> None:
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边", "operation": "text_to_video", "duration_seconds": 8},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["detail_level"] in ("sparse", "adequate", "detailed")
    assert body["prompt"]
    assert body["feedback"]
    assert {d["key"] for d in body["dimensions"]} == {
        "subject",
        "scene",
        "action",
        "camera",
        "lighting",
        "mood",
        "pacing",
    }
    assert all(d["status"] in ("missing", "weak", "ok") for d in body["dimensions"])
    assert body["additions"]


def test_enhance_diagnoses_image_prompts_on_image_dimensions(
    client: TestClient, author: User, bound_copy_agent: None
) -> None:
    """No camera or pacing advice on a still image — the operation decides."""
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边", "operation": "text_to_image"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    keys = {d["key"] for d in response.json()["dimensions"]}
    assert "composition" in keys
    assert "camera" not in keys
    assert "pacing" not in keys


@pytest.mark.real_gateway_seams
def test_enhance_reports_an_outage_instead_of_echoing_back(
    client: TestClient, author: User
) -> None:
    """No catalog bound, so the call must fail loudly.

    Echoing the author's own text back as a "polish" is what made this
    feature look broken before; a 503 is the honest answer. Opts out of the
    autouse fake gateway (`@pytest.mark.real_gateway_seams`) since the fake
    stays permissive about unbound models — this needs the real
    `app.llm.client.complete` to observe the actual production rule.
    """
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "PROVIDER_TEMPORARY_FAILURE"


def test_enhance_requires_login(client: TestClient) -> None:
    response = client.post("/v1/generation/prompts/enhance", json={"prompt": "女孩在海边"})
    assert response.status_code == 401


def test_enhance_is_not_gated_by_the_shortform_feature_flag(
    client: TestClient, db: Session, author: User, bound_copy_agent: None
) -> None:
    """Disabling `shortform_studio` must not affect the generation studio."""
    current = config_service.get_typed(db, "feature_flags", FeatureFlags)
    config_service.set_value(
        db,
        "feature_flags",
        {**current.model_dump(mode="json"), "shortform_studio": False},
        actor_user_id=None,
        note="test: disable shortform studio",
    )
    db.commit()

    shortform_response = client.post(
        "/v1/shortform/prompt/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert shortform_response.status_code == 422

    generation_response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert generation_response.status_code == 200, generation_response.text
