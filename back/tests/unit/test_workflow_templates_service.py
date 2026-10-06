"""`workflow_templates.service`: append-only versioning, activation/rollback,
and validation-before-publish — the same shape as `agent_skills.service`,
tested the same way.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import User
from app.models.enums import ImageAssetKind, Operation
from app.workflows.defaults import asset_graph, default_graph, video_analysis_graph


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


def _custom_agent_graph(config: dict) -> dict:
    """A publishable graph whose only interesting node is a `custom_agent`.

    That node type is the one whose role, slot and agent are all operator
    input rather than code — everything `_binding_errors` has to check.
    """
    return {
        "nodes": [
            {"id": "entry", "type": "safety_check", "config": {}},
            {"id": "judge", "type": "custom_agent", "config": config},
            {"id": "ok_end", "type": "settle_success", "config": {}},
            {"id": "fail_end", "type": "fail", "config": {}},
        ],
        "edges": [
            {"from": "entry", "from_port": "pass", "to": "judge"},
            {"from": "entry", "from_port": "reject", "to": "fail_end"},
            {"from": "judge", "from_port": "ok", "to": "ok_end"},
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
        graph_json=default_graph(db),
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


def test_a_custom_agent_node_with_a_role_outside_the_presets_is_refused(db: Session) -> None:
    """`custom_agent`'s role is operator input, and a role no preset declares
    can never have an agent created for it — the node would fail every run.
    Before this validation such a graph published cleanly."""
    errors = workflow_templates_service.validate_graph_json(
        _custom_agent_graph({"agent_role": "made_up_role"}), session=db
    )
    assert any("不在角色预设里" in e for e in errors)


def test_a_custom_agent_node_with_an_assist_role_is_accepted(db: Session) -> None:
    """`copy` is `assist`, not `judgment`, but it is still prompt-bound rather
    than creative — `custom_agent` is how its `enhance`/`clarify` slots get
    invoked from anywhere in a graph, so this must keep working."""
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    assert agent_skills_service.presets.category_for("copy") == "assist"
    assert (
        workflow_templates_service.validate_graph_json(
            _custom_agent_graph({"agent_role": "copy", "slot": "enhance"}), session=db
        )
        == []
    )


def test_a_custom_agent_node_with_a_slot_the_role_does_not_own_is_refused(db: Session) -> None:
    """Slots belong to the role (`app.agents.slots`), so `safety` has no
    `select_provider` — publishing one would resolve to no prompt at all."""
    errors = workflow_templates_service.validate_graph_json(
        _custom_agent_graph({"agent_role": "safety", "slot": "select_provider"}), session=db
    )
    assert any("不属于角色 safety" in e for e in errors)


def test_a_custom_agent_node_binding_a_disabled_agent_is_refused(db: Session) -> None:
    """Same rule the static bindings already had — it just never reached
    `custom_agent`, whose binding was not walked at all."""
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    retired = agent_skills_service.create_profile(
        db, role="safety", key="retired", display_name="停用版"
    )
    agent_skills_service.update_profile(db, retired.id, enabled=False)

    errors = workflow_templates_service.validate_graph_json(
        _custom_agent_graph({"agent_role": "safety", "agent_id": retired.id}), session=db
    )
    assert any("已停用" in e for e in errors)


def test_a_custom_agent_node_leaving_the_agent_empty_only_needs_a_valid_role(db: Session) -> None:
    """An empty agent field means the role's default agent, which is always
    a valid choice — but the role itself still has to be one."""
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    assert (
        workflow_templates_service.validate_graph_json(
            _custom_agent_graph({"agent_role": "safety"}), session=db
        )
        == []
    )


def test_agent_usage_counts_a_custom_agent_nodes_binding(db: Session, author: User) -> None:
    """The agents console's "used by" badge reads this; a `custom_agent`
    binding used to be invisible to it."""
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    strict = agent_skills_service.create_profile(
        db, role="safety", key="strict", display_name="严格版"
    )
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="带自定义智能体的流程",
        graph_json=_custom_agent_graph({"agent_role": "safety", "agent_id": strict.id}),
        actor_user_id=author.id,
        reason="绑定严格版安全智能体",
    )

    assert workflow_templates_service.agent_usage(db).get(strict.id) == [
        Operation.TEXT_TO_IMAGE.value
    ]


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
        graph_json=default_graph(db),
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
        expected = (
            video_analysis_graph(db) if operation == Operation.VIDEO_ANALYSIS else default_graph(db)
        )
        assert active.graph_json == expected

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


# --------------------------------------------------------------------------
# `asset_kind` dimension
# --------------------------------------------------------------------------


def test_get_active_falls_back_to_the_generic_template_for_an_unseeded_asset_kind(
    db: Session, author: User
) -> None:
    generic = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用流程",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="通用",
    )
    resolved = workflow_templates_service.get_active(
        db, Operation.TEXT_TO_IMAGE.value, ImageAssetKind.SCENE.value
    )
    assert resolved is not None
    assert resolved.id == generic.id


def test_get_active_prefers_the_specific_asset_kind_template(db: Session, author: User) -> None:
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用流程",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="通用",
    )
    specific = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="角色正面流程",
        graph_json=asset_graph(db, ImageAssetKind.CHARACTER.value),
        actor_user_id=author.id,
        reason="角色正面专用",
        asset_kind=ImageAssetKind.CHARACTER.value,
    )
    resolved = workflow_templates_service.get_active(
        db, Operation.TEXT_TO_IMAGE.value, ImageAssetKind.CHARACTER.value
    )
    assert resolved.id == specific.id
    # A different, unseeded kind still falls back to the generic template.
    other_kind = workflow_templates_service.get_active(
        db, Operation.TEXT_TO_IMAGE.value, ImageAssetKind.SCENE.value
    )
    assert other_kind is not None
    assert other_kind.id != specific.id


def test_general_asset_kind_is_treated_the_same_as_no_asset_kind(db: Session, author: User) -> None:
    generic = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用流程",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="通用",
    )
    assert (
        workflow_templates_service.get_active(
            db, Operation.TEXT_TO_IMAGE.value, ImageAssetKind.GENERAL.value
        ).id
        == generic.id
    )


def test_publishing_an_asset_kind_template_for_a_non_image_operation_is_refused(
    db: Session, author: User
) -> None:
    with pytest.raises(ValidationFailed):
        workflow_templates_service.publish(
            db,
            operation=Operation.TEXT_TO_VIDEO.value,
            name="不支持资产用途",
            graph_json=_minimal_graph(),
            actor_user_id=author.id,
            reason="视频不区分资产用途",
            asset_kind=ImageAssetKind.SCENE.value,
        )


def test_publishing_two_asset_kinds_does_not_deactivate_each_other(
    db: Session, author: User
) -> None:
    front = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="角色正面",
        graph_json=asset_graph(db, ImageAssetKind.CHARACTER.value),
        actor_user_id=author.id,
        reason="正面",
        asset_kind=ImageAssetKind.CHARACTER.value,
    )
    scene = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="场景图",
        graph_json=asset_graph(db, ImageAssetKind.SCENE.value),
        actor_user_id=author.id,
        reason="场景",
        asset_kind=ImageAssetKind.SCENE.value,
    )
    db.refresh(front)
    db.refresh(scene)
    assert front.is_active is True
    assert scene.is_active is True


def test_list_versions_is_scoped_to_one_asset_kind(db: Session, author: User) -> None:
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="通用 v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="通用",
    )
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="角色正面 v1",
        graph_json=asset_graph(db, ImageAssetKind.CHARACTER.value),
        actor_user_id=author.id,
        reason="正面",
        asset_kind=ImageAssetKind.CHARACTER.value,
    )
    generic_versions = workflow_templates_service.list_versions(db, Operation.TEXT_TO_IMAGE.value)
    front_versions = workflow_templates_service.list_versions(
        db, Operation.TEXT_TO_IMAGE.value, asset_kind=ImageAssetKind.CHARACTER.value
    )
    assert [v.name for v in generic_versions] == ["通用 v1"]
    assert [v.name for v in front_versions] == ["角色正面 v1"]


def test_ensure_default_templates_seeds_one_template_per_non_general_asset_kind_for_images(
    db: Session,
) -> None:
    workflow_templates_service.ensure_default_templates(db)

    for operation in (Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE):
        for kind in ImageAssetKind:
            active = workflow_templates_service.get_active(db, operation.value, kind.value)
            assert active is not None
            # A retired cover image (AC-8) gets no template of its own.
            if kind in (ImageAssetKind.GENERAL, ImageAssetKind.COVER):
                assert active.asset_kind is None
                assert active.graph_json == default_graph(db)
            else:
                assert active.asset_kind == kind.value
                assert active.graph_json == asset_graph(db, kind.value)

    # A non-image operation never gets asset-kind-specific templates.
    assert (
        workflow_templates_service.get_active(
            db, Operation.TEXT_TO_VIDEO.value, ImageAssetKind.SCENE.value
        ).asset_kind
        is None
    )


def _planning_node(graph: dict) -> dict:
    return next(node for node in graph["nodes"] if node["id"] == "planning")


def test_asset_graph_disables_the_generic_planning_node_followup_question(db: Session) -> None:
    """An asset-kind graph's `asset_planning` node already runs a dedicated,
    `asset_kind`/`character_view`-aware plan right after this one — the
    generic `planning` node's own clarify slot has neither, so left at its
    default it judges a bare completion-job prompt (just a character's name,
    see `character-library.tsx`'s "补全侧面/背面") as missing scene/action/
    shot info and asks for exactly what a character/scene/cover asset must
    NOT have (see `app.agents.planner._ASSET_KIND_BRIEF`) — a job the image
    studio can never recover from (it never renders `AwaitingInputPanel`).
    """
    for kind in ImageAssetKind:
        if kind == ImageAssetKind.GENERAL:
            continue
        planning = _planning_node(asset_graph(db, kind.value))
        assert planning["config"]["allow_followup_question"] is False

    # The plain graph is unaffected — a `GENERAL` text-to-image job still
    # gets the "ask for free" behaviour `PlanningConfig` documents.
    generic_planning = _planning_node(default_graph(db))
    assert "allow_followup_question" not in generic_planning["config"]


# --------------------------------------------------------------------------
# `text_to_image`/`image_to_image` merge (`canonical_operation`)
# --------------------------------------------------------------------------


def test_image_to_image_resolves_the_same_active_template_as_text_to_image(
    db: Session, author: User
) -> None:
    published = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="共享流程",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="仅在 text_to_image 下发布",
    )
    resolved = workflow_templates_service.get_active(db, Operation.IMAGE_TO_IMAGE.value)
    assert resolved is not None
    assert resolved.id == published.id
    assert resolved.operation == Operation.TEXT_TO_IMAGE.value


def test_publishing_under_image_to_image_lands_on_the_text_to_image_row(
    db: Session, author: User
) -> None:
    """An operator working from the `image_to_image` tab still edits the one
    shared graph, not a second independent history."""
    published = workflow_templates_service.publish(
        db,
        operation=Operation.IMAGE_TO_IMAGE.value,
        name="从图生图发布",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="仅在 image_to_image 下发布",
    )
    assert published.operation == Operation.TEXT_TO_IMAGE.value
    assert (
        workflow_templates_service.get_active(db, Operation.TEXT_TO_IMAGE.value).id == published.id
    )
    assert (
        workflow_templates_service.get_active(db, Operation.IMAGE_TO_IMAGE.value).id == published.id
    )


def test_list_versions_is_shared_between_text_to_image_and_image_to_image(
    db: Session, author: User
) -> None:
    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v1",
        graph_json=_minimal_graph(),
        actor_user_id=author.id,
        reason="v1",
    )
    workflow_templates_service.publish(
        db,
        operation=Operation.IMAGE_TO_IMAGE.value,
        name="v2",
        graph_json=default_graph(db),
        actor_user_id=author.id,
        reason="v2",
    )
    text_to_image_versions = workflow_templates_service.list_versions(
        db, Operation.TEXT_TO_IMAGE.value
    )
    image_to_image_versions = workflow_templates_service.list_versions(
        db, Operation.IMAGE_TO_IMAGE.value
    )
    assert [v.version for v in text_to_image_versions] == [2, 1]
    assert [v.id for v in image_to_image_versions] == [v.id for v in text_to_image_versions]


def test_ensure_default_templates_seeds_the_image_family_exactly_once(db: Session) -> None:
    """Four rows total (one generic + three library kinds), not eight — the old
    per-operation seeding would have created a duplicate set under
    `image_to_image`."""
    workflow_templates_service.ensure_default_templates(db)

    text_to_image_ids = {
        workflow_templates_service.get_active(db, Operation.TEXT_TO_IMAGE.value, kind.value).id
        for kind in ImageAssetKind
    }
    # `cover` (retired, AC-8) resolves to the generic row.
    assert len(text_to_image_ids) == len(list(ImageAssetKind)) - 1

    all_active = [
        t
        for t in workflow_templates_service.list_versions(db, Operation.TEXT_TO_IMAGE.value)
        if t.is_active
    ] + [
        t
        for kind in ImageAssetKind
        if kind not in (ImageAssetKind.GENERAL, ImageAssetKind.COVER)
        for t in workflow_templates_service.list_versions(
            db, Operation.TEXT_TO_IMAGE.value, asset_kind=kind.value
        )
        if t.is_active
    ]
    assert all(row.operation == Operation.TEXT_TO_IMAGE.value for row in all_active)
