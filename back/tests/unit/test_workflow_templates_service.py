"""`workflow_templates.service`: append-only versioning, activation/rollback,
and validation-before-publish — the same shape as `agent_skills.service`,
tested the same way.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.errors import NotFound, ValidationFailed
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import User
from app.models.enums import Operation
from app.workflows.defaults import default_graph


def _minimal_graph() -> dict:
    return {
        "nodes": [
            {"id": "entry", "type": "safety_check", "config": {}},
            {"id": "ok_end", "type": "settle_success", "config": {}},
            {"id": "fail_end", "type": "fail", "config": {}},
        ],
        "edges": [
            {"from": "entry", "from_port": "pass", "to": "ok_end"},
            {"from": "entry", "from_port": "reject", "to": "fail_end"},
        ],
    }


def test_publishing_the_first_version_activates_it(db: Session, author: User) -> None:
    row = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="首次发布",
    )
    assert row.version == 1
    assert row.is_active is True
    assert workflow_templates_service.get_active(db, Operation.TEXT_TO_IMAGE.value).id == row.id


def test_publishing_a_second_version_deactivates_the_first(db: Session, author: User) -> None:
    first = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="首次发布",
    )
    second = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v2",
        graph_json=default_graph(),
        actor_user_id=author.id,
        reason="切换到默认六步流程",
    )
    assert second.version == 2
    db.refresh(first)
    assert first.is_active is False
    assert second.is_active is True

    versions = workflow_templates_service.list_versions(db, Operation.TEXT_TO_IMAGE.value)
    assert [v.version for v in versions] == [2, 1]


def test_publishing_one_operation_never_touches_another_operations_active_version(
    db: Session, author: User
) -> None:
    image_v1 = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="图片流程",
    )
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_VIDEO.value,
        name="v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="视频流程",
    )
    db.refresh(image_v1)
    assert image_v1.is_active is True


def test_publishing_a_structurally_broken_graph_is_refused(db: Session, author: User) -> None:
    broken = {"nodes": [{"id": "a", "type": "safety_check", "config": {}}], "edges": []}
    with pytest.raises(ValidationFailed):
        workflow_templates_service.publish(
            db,
            operation=Operation.TEXT_TO_IMAGE.value,
            name="broken",
            graph_json=broken,
            actor_user_id=author.id,
            reason="不应该发布成功",
        )
    assert workflow_templates_service.get_active(db, Operation.TEXT_TO_IMAGE.value) is None


def test_publishing_an_unknown_operation_is_refused(db: Session, author: User) -> None:
    with pytest.raises(ValidationFailed):
        workflow_templates_service.publish(
            db,
            operation="not_a_real_operation",
            name="v1",
            graph_json=_minimal_graph(),
            actor_user_id=author.id,
            reason="非法 operation",
        )


def test_activating_an_older_version_republishes_it_as_the_newest(
    db: Session, author: User
) -> None:
    v1 = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="v1",
    )
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v2",
        graph_json=default_graph(),
        actor_user_id=author.id,
        reason="v2",
    )

    rolled_back = workflow_templates_service.activate_version(
        db, v1.id, actor_user_id=author.id, reason=None
    )

    assert rolled_back.version == 3
    assert rolled_back.graph_json == v1.graph_json
    assert rolled_back.reason == f"回滚到版本 {v1.version}"
    active = workflow_templates_service.get_active(db, Operation.TEXT_TO_IMAGE.value)
    assert active.id == rolled_back.id


def test_activating_a_nonexistent_template_id_raises_not_found(db: Session, author: User) -> None:
    with pytest.raises(NotFound):
        workflow_templates_service.activate_version(
            db, "gwt_does_not_exist", actor_user_id=author.id, reason=None
        )


def test_ensure_default_templates_seeds_every_operation_exactly_once(db: Session) -> None:
    workflow_templates_service.ensure_default_templates(db)

    for operation in Operation:
        active = workflow_templates_service.get_active(db, operation.value)
        assert active is not None
        assert active.graph_json == default_graph()

    # Idempotent: an operation that already has an active template (hand
    # edited or seeded before) must be left alone, not re-seeded to v2.
    workflow_templates_service.ensure_default_templates(db)
    for operation in Operation:
        versions = workflow_templates_service.list_versions(db, operation.value)
        assert len(versions) == 1


def test_ensure_default_templates_does_not_override_an_already_customized_operation(
    db: Session, author: User
) -> None:
    custom = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="定制流程",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="已经手工配置过",
    )

    workflow_templates_service.ensure_default_templates(db)

    active = workflow_templates_service.get_active(db, Operation.TEXT_TO_IMAGE.value)
    assert active.id == custom.id
    # Every other operation still gets seeded.
    other_active = workflow_templates_service.get_active(db, Operation.AUDIO_GENERATION.value)
    assert other_active is not None
