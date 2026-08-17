"""`app.domain.prompts.enhance`: the dimension-by-dimension diagnosis shared by
the shortform studio and the generation studio's own polish button."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.api.schemas.shortform import PromptDimensionKey, PromptEnhanceDirection
from app.domain import prompts
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ValidationFailed
from app.llm import client as llm_client
from app.llm import stub
from app.models import AgentRun, User
from tests.llm_catalog import bind_default_agents_to_catalog


@pytest.fixture(autouse=True)
def _bind_copy_model(db: Session) -> None:
    bind_default_agents_to_catalog(db)


def test_a_sparse_description_is_flagged_and_expanded(db: Session, author: User) -> None:
    result = prompts.enhance(db, user_id=author.id, prompt="女孩在海边")
    assert result.detail_level == "sparse"
    assert result.feedback
    assert result.prompt != "女孩在海边"
    assert result.degraded is False


def test_an_already_detailed_description_is_barely_touched(db: Session, author: User) -> None:
    text = (
        "黄昏时分，一位穿着白色长裙的女孩独自站在海边礁石上，海风吹动她的裙摆，"
        "镜头缓慢从远景推近到她的侧脸特写，逆光剪影，暖橙色调，长焦压缩景深"
    )
    result = prompts.enhance(db, user_id=author.id, prompt=text)
    assert result.detail_level == "detailed"
    assert result.prompt == text
    assert result.additions == []


def test_blank_input_is_rejected_before_calling_the_agent(db: Session, author: User) -> None:
    with pytest.raises(ValidationFailed):
        prompts.enhance(db, user_id=author.id, prompt="   ")


def test_the_diagnosis_explains_every_dimension_of_the_medium(db: Session, author: User) -> None:
    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="text_to_video"),
    )
    assert [d.key for d in result.dimensions] == list(copywriter.VIDEO_DIMENSIONS)
    assert all(d.hint for d in result.dimensions)
    # `sparse` is a consequence of the diagnosis, not a separate verdict.
    assert sum(1 for d in result.dimensions if d.status == "missing") >= 2


def test_an_image_prompt_is_never_diagnosed_on_camera_work(db: Session, author: User) -> None:
    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="text_to_image"),
    )
    assert [d.key for d in result.dimensions] == list(copywriter.IMAGE_DIMENSIONS)


def test_a_direction_round_adjusts_instead_of_re_padding(db: Session, author: User) -> None:
    first = prompts.enhance(db, user_id=author.id, prompt="女孩在海边")
    second = prompts.enhance(
        db,
        user_id=author.id,
        prompt=first.prompt,
        context=prompts.PromptContext(direction="stronger_camera"),
    )
    assert second.additions == ["镜头缓慢推近"]
    assert second.prompt.startswith(first.prompt)


def test_the_polish_slot_asks_for_its_own_budget_and_creativity(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The platform default (2048 / 0.2) exists to keep verdicts repeatable.
    A rewrite needs room for the diagnosis and latitude to vary its wording."""
    captured: dict[str, object] = {}
    real_complete = llm_client.complete

    def capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return real_complete(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(llm_client, "complete", capture)
    prompts.enhance(db, user_id=author.id, prompt="女孩在海边")

    assert captured["max_tokens"] == copywriter.ENHANCE_MAX_TOKENS
    assert captured["temperature"] == copywriter.ENHANCE_TEMPERATURE


def test_enhance_routes_to_the_asset_kinds_dedicated_agent(db: Session, author: User) -> None:
    """A `character`/`scene`/`cover` polish must land on that bucket's agent,
    not the role's ordinary default — the whole point of separate agent
    profiles per asset kind."""
    specific = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character",
        display_name="角色润色",
        default_for_asset_kind="character",
    )
    outcome = copywriter.enhance_prompt(
        db,
        prompt="女孩在海边",
        max_length=600,
        operation="text_to_image",
        asset_kind="character",
        user_id=author.id,
    )
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.agent_profile_id == specific.id


def test_enhance_without_a_matching_bucket_keeps_the_roles_ordinary_default(
    db: Session, author: User
) -> None:
    """`general`/empty `asset_kind`, and any string outside the three buckets,
    must all fall back to `default_profile(role="copy")` exactly as before
    this feature existed — even with a `scene`-specific agent configured."""
    default = agent_skills_service.default_profile(db, "copy")
    assert default is not None
    agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-scene",
        display_name="场景润色",
        default_for_asset_kind="scene",
    )

    for asset_kind in ("", "general", "not_a_real_bucket"):
        outcome = copywriter.enhance_prompt(
            db,
            prompt="女孩在海边",
            max_length=600,
            operation="text_to_image",
            asset_kind=asset_kind,
            user_id=author.id,
        )
        run = db.get(AgentRun, outcome.agent_run_id)
        assert run is not None
        assert run.agent_profile_id == default.id


def test_an_explicit_agent_id_wins_over_asset_kind_routing(db: Session, author: User) -> None:
    """A caller that already pinned an agent must not be second-guessed by
    the asset-kind lookup."""
    specific = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-cover",
        display_name="封面润色",
        default_for_asset_kind="cover",
    )
    other = agent_skills_service.create_profile(
        db, role="copy", key="explicit-choice", display_name="显式指定"
    )

    outcome = copywriter.enhance_prompt(
        db,
        prompt="女孩在海边",
        max_length=600,
        asset_kind="cover",
        agent_id=other.id,
        user_id=author.id,
    )
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.agent_profile_id == other.id
    assert run.agent_profile_id != specific.id


def test_the_prompt_context_asset_kind_reaches_the_copy_agent(db: Session, author: User) -> None:
    """`domain.prompts.enhance` is the layer both studios call through — this
    confirms `PromptContext.asset_kind` actually reaches `enhance_prompt`
    rather than being dropped along the way."""
    specific = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character-2",
        display_name="角色润色 2",
        default_for_asset_kind="character",
    )
    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="text_to_image", asset_kind="character"),
    )
    assert result.degraded is False
    # `AgentOutcome.agent_run_id` is not on `PromptEnhancement`, so the
    # routing itself is asserted via the most recent run instead.
    from sqlalchemy import select

    latest_run_id = db.scalars(
        select(AgentRun.id).order_by(AgentRun.created_at.desc()).limit(1)
    ).first()
    run = db.get(AgentRun, latest_run_id)
    assert run is not None
    assert run.agent_profile_id == specific.id


def test_unknown_dimensions_and_duplicates_are_dropped() -> None:
    """The panel renders these rows verbatim, so anything improvised has to go."""
    cleaned = copywriter._sanitize_dimensions(
        [
            {"key": "subject", "status": "ok", "hint": "很具体"},
            {"key": "subject", "status": "missing", "hint": "重复的"},
            {"key": "vibes", "status": "ok", "hint": "编出来的维度"},
            {"key": "scene", "status": "excellent", "hint": "编出来的状态"},
            "not a dict",
        ]
    )
    assert cleaned == [{"key": "subject", "status": "ok", "hint": "很具体"}]


def test_additions_are_bounded() -> None:
    cleaned = copywriter._sanitize_additions(["  ", "短语", "很长" * 40, *["x"] * 10])
    assert len(cleaned) == copywriter.MAX_ADDITIONS
    assert cleaned[0] == "短语"
    assert all(len(item) <= copywriter.MAX_ADDITION_LENGTH for item in cleaned)


def test_the_published_contract_matches_the_agent_whitelist() -> None:
    """`schemas/shortform.py` spells these out instead of importing them."""
    assert set(PromptDimensionKey.__args__) == set(copywriter.DIMENSION_KEYS)
    assert set(PromptEnhanceDirection.__args__) == set(copywriter.ENHANCE_DIRECTIONS)


def test_the_stub_mirrors_the_agents_dimension_sets() -> None:
    """A stub diagnosing different dimensions would make `make check` green
    on behaviour the real model never produces."""
    assert stub._ENHANCE_VIDEO_DIMENSIONS == copywriter.VIDEO_DIMENSIONS
    assert stub._ENHANCE_IMAGE_DIMENSIONS == copywriter.IMAGE_DIMENSIONS
    assert set(stub._ENHANCE_DIRECTION_PHRASES) == set(copywriter.ENHANCE_DIRECTIONS)
