"""`app.domain.prompts.enhance`: the dimension-by-dimension diagnosis behind
the studios' "AI 润色" button."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.agents.base import AgentOutcome
from app.api.schemas.shortform import PromptDimensionKey, PromptEnhanceDirection
from app.domain import prompts
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ValidationFailed
from app.domain.skill_library import service as skill_library_service
from app.llm import client as llm_client
from app.models import AgentRun, CreationSkill, User
from tests import fake_llm_gateway
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


def test_a_sparse_video_polish_auto_attaches_format_skills_once_the_catalog_is_seeded(
    db: Session, author: User, catalog_owner: User
) -> None:
    """The coach has no tool access to the skill library — see
    `app.domain.skill_library.service.apply_matching_format_skills`'s own
    docstring — so this is the end-to-end path: `enhance()` runs the coach,
    then attaches library rows itself off the diagnosis it just got back."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="text_to_video"),
    )

    max_applied = skill_library_service.MAX_AUTO_APPLIED_FORMAT_SKILLS
    assert 1 <= len(result.applied_format_skills) <= max_applied
    for skill in result.applied_format_skills:
        assert skill.id
        assert skill.title

    # At least one attached rule's own text actually landed on the wire.
    applied_ids = {skill.id for skill in result.applied_format_skills}
    rows = db.scalars(
        select(CreationSkill).where(CreationSkill.owner_user_id == catalog_owner.id)
    ).all()
    assert any(
        row.params_json["prompt_suffix"] in result.prompt for row in rows if row.id in applied_ids
    )


def test_a_video_polish_attaches_nothing_when_the_catalog_is_not_seeded(
    db: Session, author: User
) -> None:
    """No `CreationSkill` rows exist in a fresh test database unless a test
    seeds them — `apply_matching_format_skills` must degrade to a no-op
    rather than error."""
    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="text_to_video"),
    )
    assert result.applied_format_skills == []


def test_an_image_polish_never_attaches_a_format_skill_even_when_seeded(
    db: Session, author: User, catalog_owner: User
) -> None:
    """Every seeded `format` row is video-only — an image polish must come
    back empty regardless of what the catalog contains."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="text_to_image"),
    )
    assert result.applied_format_skills == []


def test_a_video_edit_polish_never_attaches_new_clip_format_skills(
    db: Session, author: User, catalog_owner: User
) -> None:
    """The edit coach redefines the dimensions (action = add/remove/replace,
    camera = keep the source's), so a weak `camera` there is not a missing
    camera move. Auto-attaching the dimension's format rule appended "one
    continuous camera move" to an instruction that keeps the source camera
    (seen in a live polish). An author-picked video kind keeps the rules."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    edit = prompts.enhance(
        db,
        user_id=author.id,
        prompt="把裙子换成衬衫",
        context=prompts.PromptContext(operation="video_to_video"),
    )
    assert edit.applied_format_skills == []

    action = prompts.enhance(
        db,
        user_id=author.id,
        prompt="女孩在海边",
        context=prompts.PromptContext(operation="video_to_video", asset_kind="character_action"),
    )
    assert action.applied_format_skills


def test_a_video_polish_shows_the_coach_the_scenes_its_story_contains(
    db: Session, author: User, catalog_owner: User
) -> None:
    """The second half of the same "the coach has no tool access" story as
    the format-skill test above: `enhance()` matches `drama` rows itself and
    hands them over as reference material."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="男主在雨中告别女主，转身走进雨里，女主站在原地淋着雨",
        context=prompts.PromptContext(operation="text_to_video"),
    )

    titles = {skill.title for skill in result.referenced_skills}
    assert "雨中告别·伞外的那一个" in titles
    # Reference material, never text: unlike `applied_format_skills`, none of
    # this is allowed to land in the rewritten prompt by Python.
    rows = {
        row.title: row
        for row in db.scalars(select(CreationSkill).where(CreationSkill.title.in_(titles)))
    }
    for title in titles:
        assert rows[title].params_json["prompt_suffix"] not in result.prompt


def test_an_image_polish_is_never_shown_drama_references(
    db: Session, author: User, catalog_owner: User
) -> None:
    """Every `drama` row is about how a beat plays out over time. Matching
    them for a still would spend a matcher call and several hundred prompt
    tokens on advice a single frame cannot act on."""
    skill_library_service.ensure_catalog_skills(db, owner_user_id=catalog_owner.id)
    db.commit()

    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="男主在雨中告别女主，转身走进雨里，女主站在原地淋着雨",
        context=prompts.PromptContext(operation="text_to_image"),
    )
    assert result.referenced_skills == []


def test_a_video_polish_without_a_seeded_catalog_references_nothing(
    db: Session, author: User
) -> None:
    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="男主在雨中告别女主，转身走进雨里",
        context=prompts.PromptContext(operation="text_to_video"),
    )
    assert result.referenced_skills == []


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


def test_the_polish_slot_scales_up_to_the_bound_models_own_ceiling(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ENHANCE_MAX_TOKENS` is only a floor, same as `SCRIPT_MAX_TOKENS`
    (see `test_script_writing_agent.py`) — a bound endpoint that declares a
    larger `max_output_tokens` gets that larger budget, not the slot's own
    smaller constant (`back/app/agents/base.py`'s `run_agent` floor
    semantics apply to every slot that passes an explicit `max_tokens`,
    not just script writing)."""
    from tests.llm_catalog import seed_test_llm_catalog

    seed_test_llm_catalog(db, max_output_tokens=16_384)
    captured: dict[str, object] = {}
    real_complete = llm_client.complete

    def capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return real_complete(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(llm_client, "complete", capture)
    prompts.enhance(db, user_id=author.id, prompt="女孩在海边")

    assert captured["max_tokens"] == 16_384


def test_the_stream_polish_slot_asks_for_its_own_budget_and_creativity(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The HTTP path is `stream_enhance_prompt`, not `enhance_prompt` —
    losing the slot overrides here is what sent live polishes out at the
    binding default (0.2 / no JSON mode) and left thinking-only replies
    unparseable."""
    captured: dict[str, object] = {}
    real_stream = llm_client.stream_complete

    def capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return real_stream(**kwargs)

    monkeypatch.setattr(llm_client, "stream_complete", capture)
    chunks, finish = copywriter.stream_enhance_prompt(
        db, prompt="女孩在海边", max_length=600, user_id=author.id
    )
    list(chunks)
    finish(db)

    assert captured["max_tokens"] == copywriter.ENHANCE_MAX_TOKENS
    assert captured["temperature"] == copywriter.ENHANCE_TEMPERATURE
    assert captured["expect_json"] is True
    assert captured["is_usable"] is copywriter._enhance_text_is_usable
    assert captured["retry_nudge"] == copywriter.ENHANCE_RETRY_NUDGE


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
    """`general`/empty `asset_kind`, and any string outside the image/video
    buckets, resolve through the `copy` request bucket and then the role
    default — so with no `copy` bucket claimed they still land on
    `default_profile(role="copy")`, even with a `scene`-specific agent."""
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
        key="enhance-scene",
        display_name="场景润色",
        default_for_asset_kind="scene",
    )
    other = agent_skills_service.create_profile(
        db, role="copy", key="explicit-choice", display_name="显式指定"
    )

    outcome = copywriter.enhance_prompt(
        db,
        prompt="女孩在海边",
        max_length=600,
        asset_kind="scene",
        agent_id=other.id,
        user_id=author.id,
    )
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.agent_profile_id == other.id
    assert run.agent_profile_id != specific.id


def test_general_enhance_and_suggest_route_to_the_copy_request_bucket(
    db: Session, author: User
) -> None:
    """A dedicated `copy` bucket, not `is_default`, is what generic polish
    and work-copy generation resolve to once that bucket is claimed."""
    default = agent_skills_service.default_profile(db, "copy")
    assert default is not None
    catch_all = agent_skills_service.create_profile(
        db,
        role="copy",
        key="copy-catch-all",
        display_name="文案生成",
        default_for_asset_kind="copy",
    )
    assert catch_all.id != default.id

    polish = copywriter.enhance_prompt(
        db,
        prompt="女孩在海边",
        max_length=600,
        operation="text_to_image",
        asset_kind="general",
        user_id=author.id,
    )
    polish_run = db.get(AgentRun, polish.agent_run_id)
    assert polish_run is not None
    assert polish_run.agent_profile_id == catch_all.id

    suggestion = copywriter.suggest(db, prompt="女孩在海边", user_id=author.id)
    suggest_run = db.get(AgentRun, suggestion.agent_run_id)
    assert suggest_run is not None
    assert suggest_run.agent_profile_id == catch_all.id

    followup = copywriter.clarify(db, prompt="女孩在海边", user_id=author.id)
    followup_run = db.get(AgentRun, followup.agent_run_id)
    assert followup_run is not None
    assert followup_run.agent_profile_id == catch_all.id

    pinned = copywriter.suggest(db, prompt="女孩在海边", user_id=author.id, agent_id=default.id)
    pinned_run = db.get(AgentRun, pinned.agent_run_id)
    assert pinned_run is not None
    assert pinned_run.agent_profile_id == default.id


def test_the_prompt_context_asset_kind_reaches_the_copy_agent(db: Session, author: User) -> None:
    """`domain.prompts.enhance` is the domain-level polish contract — this
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


def test_stream_enhance_routes_to_the_asset_kinds_dedicated_agent(
    db: Session, author: User
) -> None:
    """The live button is the SSE path — routing through `enhance_prompt`
    alone would miss a regression that only hits `stream_enhance_prompt`."""
    specific = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character-stream",
        display_name="角色润色 · 流式",
        default_for_asset_kind="character",
    )
    chunks, finish = copywriter.stream_enhance_prompt(
        db,
        prompt="女孩在海边",
        max_length=600,
        operation="text_to_image",
        asset_kind="character",
        user_id=author.id,
    )
    list(chunks)
    outcome = finish(db)
    assert outcome.degraded is False
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.agent_profile_id == specific.id
    assert run.degraded is False


def test_enhance_text_is_usable_requires_enhance_shaped_json() -> None:
    usable = '{"prompt": "黄昏海边的女孩", "detail_level": "sparse"}'
    assert copywriter._enhance_text_is_usable(usable) is True
    assert copywriter._enhance_text_is_usable(f"<think>先构思</think>{usable}") is True
    assert copywriter._enhance_text_is_usable('{"prompt": "黄昏海边的女孩"}') is False
    assert (
        copywriter._enhance_text_is_usable(
            'If unsure use {"answer":"$your_answer"} then keep thinking'
        )
        is False
    )
    assert (
        copywriter._enhance_text_is_usable('If unsure {"answer":"$your_answer"} then ' + usable)
        is True
    )
    assert copywriter._enhance_text_is_usable("先分析这段描述缺什么") is False
    assert copywriter._enhance_text_is_usable("") is False


def test_parse_enhance_json_skips_a_harness_decoy_in_thinking() -> None:
    thinking = (
        'If unsure default to {"answer":"$your_answer"}. '
        'Then emit {"prompt": "黄昏海边的女孩", "detail_level": "sparse"}.'
    )
    assert copywriter._parse_enhance_json("", thinking) == {
        "prompt": "黄昏海边的女孩",
        "detail_level": "sparse",
    }
    assert copywriter._parse_enhance_json('{"answer":"$your_answer"}', thinking) == {
        "prompt": "黄昏海边的女孩",
        "detail_level": "sparse",
    }


@pytest.mark.real_gateway_seams
def test_stream_enhance_retries_when_recovered_thinking_is_not_json(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The glm-5.3-flash / reasoning-model shape: first pass thinks out loud
    with no content, recovered prose is not JSON, one budget expansion then
    yields the polish object."""
    calls = 0
    payload = (
        '{"detail_level": "sparse", "feedback": "补主体与光线", '
        '"prompt": "黄昏海边的女孩，逆光剪影", "dimensions": [], "additions": ["逆光剪影"]}'
    )

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            yield llm_client.StreamDelta(reasoning="先分析这段描述缺什么", finish_reason="length")
        else:
            yield llm_client.StreamDelta(content=payload, finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    chunks, finish = copywriter.stream_enhance_prompt(
        db, prompt="女孩在海边", max_length=600, user_id=author.id
    )
    drained = list(chunks)
    outcome = finish(db)

    assert calls == 2
    assert any(chunk.kind == "thinking" for chunk in drained)
    assert outcome.degraded is False
    assert "女孩" in str(outcome.data["prompt"])
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.degraded is False


@pytest.mark.real_gateway_seams
def test_stream_enhance_retries_when_thinking_only_has_a_decoy_object(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live glm-5.3-flash shape: thinking embeds `{"answer":...}` and
    never writes content. A bare `extract_json` used to treat that decoy as
    success and echo the author's prompt back. The second attempt, nudged,
    must emit a real enhance object."""
    calls: list[list[dict[str, str]]] = []
    payload = (
        '{"detail_level": "sparse", "feedback": "补主体与光线", '
        '"prompt": "黄昏海边的女孩，逆光剪影", "dimensions": [], "additions": ["逆光剪影"]}'
    )

    def _stream_gateway(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(kwargs["messages"]))
        if len(calls) == 1:
            yield llm_client.StreamDelta(
                reasoning='If unsure default to {"answer":"$your_answer"} and keep analysing.',
                finish_reason="length",
            )
        else:
            yield llm_client.StreamDelta(content=payload, finish_reason="stop")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    chunks, finish = copywriter.stream_enhance_prompt(
        db, prompt="女孩在海边", max_length=600, user_id=author.id
    )
    list(chunks)
    outcome = finish(db)

    assert len(calls) == 2
    assert calls[1][-1]["content"] == copywriter.ENHANCE_RETRY_NUDGE
    assert outcome.degraded is False
    assert "逆光" in str(outcome.data["prompt"])
    assert outcome.data["detail_level"] == "sparse"


@pytest.mark.real_gateway_seams
def test_stream_enhance_marks_the_run_degraded_when_thinking_never_becomes_json(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both attempts stay reasoning-only prose — `is_usable` spends the one
    retry, then `finish` must flip the already-written `AgentRun` so the
    ops console matches the user's "暂时不可用"."""

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(reasoning="先分析这段描述缺什么", finish_reason="length")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    chunks, finish = copywriter.stream_enhance_prompt(
        db, prompt="女孩在海边", max_length=600, user_id=author.id
    )
    list(chunks)
    outcome = finish(db)

    assert outcome.degraded is True
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.degraded is True
    assert run.degrade_reason == "json_parse_failed"
    assert run.status == "failed"


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


def test_the_fake_gateway_mirrors_the_agents_dimension_sets() -> None:
    """A test fake diagnosing different dimensions would make `make check`
    green on behaviour the real model never produces."""
    assert fake_llm_gateway._ENHANCE_VIDEO_DIMENSIONS == copywriter.VIDEO_DIMENSIONS
    assert fake_llm_gateway._ENHANCE_IMAGE_DIMENSIONS == copywriter.IMAGE_DIMENSIONS
    assert set(fake_llm_gateway._ENHANCE_DIRECTION_PHRASES) == set(copywriter.ENHANCE_DIRECTIONS)


def test_kind_enhance_prompts_are_purpose_built_not_generic_suffixes() -> None:
    """Dedicated polish agents must read as their own coach, not the generic
    enhance prompt plus a footnote — that is what made every fill-from-template
    look the same in `/admin/agents`."""
    generic = copywriter.ENHANCE_SYSTEM_PROMPT
    character = copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER
    scene = copywriter.ENHANCE_SYSTEM_PROMPT_SCENE

    assert not character.startswith(generic)
    assert not scene.startswith(generic)
    # Cover images are retired (AC-8): no cover coach any more.
    assert not hasattr(copywriter, "ENHANCE_SYSTEM_PROMPT_COVER")
    assert "角色设定图" in character
    assert "三视图" in character and "色板" in character
    assert "禁止改回单视角" in character
    assert "不加特写与色板" in character
    assert "全身" in character and "纯色" in character
    assert "性别" in character and "肤色" in character
    assert "真人写实影视短剧" in character
    assert "不得把写实改成动漫" in character
    assert "场景空镜" in scene
    assert "人物痕迹" in scene
    assert "单一机位" in scene
    assert "分割构图" in scene
    assert "遮挡" in scene
    assert "或侧视" in scene
    # The three-step construction method, the two anchors, and the medium
    # lock — the parts that stop a physically impossible plate rather than
    # just deleting the phrases that gave it away.
    assert "相机站在" in scene
    assert "scene_skill" in scene
    assert "era_region" in scene and "worldbuilding" in scene
    assert "真人写实影视短剧实拍质感" in scene
    assert "questions" in scene and "space_type_options" in scene
    assert "作品发布文案" in copywriter.SYSTEM_PROMPT
    assert "lineage" in copywriter.SYSTEM_PROMPT
    action = copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION
    transition = copywriter.ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO
    cover_video = copywriter.ENHANCE_SYSTEM_PROMPT_COVER_VIDEO
    assert not action.startswith(generic)
    assert "角色动作" in action and "起幅" in action
    assert "转场" in transition
    assert "前 1 到 2 秒" in cover_video
    for prompt in (
        generic,
        character,
        scene,
        action,
        transition,
        cover_video,
        copywriter.SYSTEM_PROMPT,
    ):
        assert "只输出一个 JSON 对象" in prompt


def test_every_enhance_coach_carries_the_shared_rewrite_self_checks() -> None:
    """The five self-checks in `_ENHANCE_CONTRACT` are the cross-vendor
    consensus rules from `docs/video-prompt-formats.md` — the ones with four
    or more vendors stating them officially and none disagreeing.

    They live in the shared contract rather than in each coach precisely
    because they hold for a character sheet and a transition plate alike, so
    this asserts all six coaches actually inherited them. The positive-only
    rule is the load-bearing one: `restore_character_sheet_prompt`'s collapse
    markers (「不拼接侧面背面」and friends) are exactly what a coach produces
    when it writes negations into the prompt it hands downstream."""
    for prompt in (
        copywriter.ENHANCE_SYSTEM_PROMPT,
        copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER,
        copywriter.ENHANCE_SYSTEM_PROMPT_SCENE,
        copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION,
        copywriter.ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO,
        copywriter.ENHANCE_SYSTEM_PROMPT_COVER_VIDEO,
        copywriter.ENHANCE_SYSTEM_PROMPT_VIDEO_EDIT,
    ):
        assert "全部改成正向陈述" in prompt
        assert "互斥指令只留一个" in prompt
        assert "可测量的锚点" in prompt
        assert "容器参数不写进正文" in prompt


def test_a_video_to_video_polish_gets_the_edit_coach() -> None:
    """A remix or clip-studio `video_to_video` arrives as `general`; it needs
    an A-to-B edit against existing footage, not a fresh beat-by-beat clip.
    An author-picked video kind still wins, and the edit coach deliberately
    skips `_ENHANCE_VIDEO_DETAIL_RULES`: its 600-1200-character target would
    have the coach re-narrate footage the model can already see."""
    edit = copywriter.ENHANCE_SYSTEM_PROMPT_VIDEO_EDIT
    assert not edit.startswith(copywriter.ENHANCE_SYSTEM_PROMPT)
    assert "把 A 改成 B" in edit
    assert "生效区间" in edit
    assert "保持与原片一致" in edit
    assert "透视、光线和遮挡关系" in edit
    assert copywriter._ENHANCE_VIDEO_DETAIL_RULES not in edit

    select = copywriter._enhance_system_prompt
    assert select("", "video_to_video") == edit
    assert select("general", "video_to_video") == edit
    assert select("character_action", "video_to_video") == (
        copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION
    )
    assert select("general", "text_to_video") == copywriter.ENHANCE_SYSTEM_PROMPT
    assert select("", "") == copywriter.ENHANCE_SYSTEM_PROMPT


def test_the_video_coaches_carry_the_one_move_per_clip_rules() -> None:
    """`pacing`/`camera` are where the per-clip budget rules had to land,
    since the dimension set itself is unchanged (`DIMENSION_KEYS`).

    Five vendors state the single-action, single-move budget officially, and
    PixVerse documents the failure mode for stacking moves (a wobble at the
    switch point), so a video coach that omits it is the one most likely to
    hand back an unusable clip."""
    generic = copywriter.ENHANCE_SYSTEM_PROMPT
    action = copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION
    transition = copywriter.ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO
    cover_video = copywriter.ENHANCE_SYSTEM_PROMPT_COVER_VIDEO

    # One move per *beat* — the budget is what a model can hold in one
    # continuous stretch, and a beat is now that stretch, so a clip built from
    # several beats gets several moves without any of them stacking.
    assert "每个节拍内部只给一个连续动作" in generic
    assert "只给一个运镜动作" in generic
    assert "方式、方向、速度" in generic
    assert "景别与运镜分开写" in generic
    # A reference image means "skip the appearance", not "skip the subject" —
    # Kling documents that dropping the subject is what turns a photo into a
    # panning shot of a painting.
    assert "必须点名主体再写动作" in generic

    assert "一段只写一个动作节拍" in action
    assert "节拍配额" in action
    assert "敲三下桌面" in action

    assert "只沿一个运动轴" in transition
    assert "出幅方向和入幅方向" in transition

    assert "三个信号" in cover_video
    assert "干净带" in cover_video


def test_every_video_coach_carries_the_same_detail_and_continuity_budget() -> None:
    """`_ENHANCE_VIDEO_DETAIL_RULES` is shared for the same reason
    `_ENHANCE_CONTRACT` is: two polishes of the same footage must not disagree
    about how much detail a clip may carry, or the clips they produce cannot
    be cut together.

    The verbatim-carryover rule is the one that actually buys continuity.
    Paraphrasing a locked item reads as the same thing to a person and as a
    fresh set of conditions to the model, which is the main reason split
    clips stop matching."""
    for prompt in (
        copywriter.ENHANCE_SYSTEM_PROMPT,
        copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION,
        copywriter.ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO,
        copywriter.ENHANCE_SYSTEM_PROMPT_COVER_VIDEO,
    ):
        assert str(copywriter.ENHANCE_VIDEO_TARGET_MIN_CHARS) in prompt
        assert str(copywriter.ENHANCE_VIDEO_TARGET_MAX_CHARS) in prompt
        assert "预估秒数区间开头" in prompt
        assert "跨段逐字复用" in prompt
        assert "话音未落" in prompt

    # Still images have no time axis to be continuous along, so the generic
    # coach has to say the opposite for them in the same breath.
    assert "图片要写紧" in copywriter.ENHANCE_SYSTEM_PROMPT
    assert (
        f"{copywriter.ENHANCE_MIN_BEATS} 到 {copywriter.ENHANCE_MAX_BEATS} 个节拍"
        in copywriter.ENHANCE_SYSTEM_PROMPT
    )


def test_coaches_with_people_in_frame_carry_the_reaction_and_causality_rules() -> None:
    """A prompt that names only the end state ("她哭了", "他摔倒了") gets an
    emotion switched on like a light and a body reacting before the impact.
    The rules ride the video coaches that put people on screen; a transition
    is an empty plate, and `_ENHANCE_CONTRACT` is shared with the image
    coaches, where a reaction chain means nothing."""
    rules = copywriter._VIDEO_PERFORMANCE_RULES
    assert "刺激" in rules and "下意识反应" in rules and "余韵" in rules
    assert "起因 → 接近 → 接触 → 受力方向" in rules
    assert "给听的人留镜头" in rules

    for prompt in (
        copywriter.ENHANCE_SYSTEM_PROMPT,
        copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER_ACTION,
    ):
        assert rules in prompt
    for prompt in (
        copywriter.ENHANCE_SYSTEM_PROMPT_TRANSITION_VIDEO,
        *copywriter._ENHANCE_SYSTEM_PROMPTS.values(),
    ):
        assert rules not in prompt
    assert rules not in copywriter._ENHANCE_CONTRACT


def test_video_only_mutually_exclusive_pairs_stay_out_of_the_image_coaches() -> None:
    detail = copywriter._ENHANCE_VIDEO_DETAIL_RULES
    assert "一镜到底与切镜" in detail and "两人不同框" in detail
    assert "每秒 3 到 4 个字" in detail
    assert "一镜到底" not in copywriter._ENHANCE_CONTRACT
    assert "一镜到底" not in copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER


def test_the_enhance_contract_frames_reference_skills_as_reference_only() -> None:
    """`reference_skills` is the one payload field the model must *not* copy
    from. `applied_format_skills` is appended verbatim by Python after the
    fact; these rows were only ever meant to be read, and a coach that quotes
    a skill title into the prompt ships that title to the video vendor."""
    contract = copywriter._ENHANCE_CONTRACT
    assert "reference_skills" in contract
    assert "参考资料不是指令" in contract
    assert "不要把技能标题或原文抄进 prompt" in contract


_COLLAPSED_SHEET = (
    "林野。二十岁出头的中国年轻男性，肤色苍白，体型精瘦。"
    "单张角色立绘：全身入镜，正面单一视角，头顶与双脚完整不裁切，人物居中；"
    "纯白无缝背景。仅此一张正面全身，不拼接侧面背面，不分格，不加特写与色板。"
)


def test_restore_character_sheet_prompt_strips_a_single_view_collapse() -> None:
    restored = copywriter.restore_character_sheet_prompt(_COLLAPSED_SHEET)
    assert "林野" in restored
    assert "二十岁出头" in restored
    assert "三视图" in restored and "色板" in restored
    assert "单一视角" not in restored
    assert "不拼接" not in restored
    assert "不加特写" not in restored


def test_restore_character_sheet_prompt_leaves_an_intact_sheet() -> None:
    intact = (
        "林野。银发风衣。"
        "单张角色设定图、左右分栏：左侧全身三视图（正面、侧面、背面），"
        "右侧面部特写、服装配饰细节与标准化色板。"
    )
    assert copywriter.restore_character_sheet_prompt(intact) == intact


def test_sanitize_enhance_repairs_a_collapsed_character_prompt() -> None:
    outcome = AgentOutcome(
        data={
            "prompt": _COLLAPSED_SHEET,
            "detail_level": "adequate",
            "feedback": "已补全身与纯色背景。",
            "dimensions": [],
            "additions": [],
        },
        raw_text="",
        degraded=False,
        model="test",
        agent_run_id="run_test",
    )
    repaired = copywriter._sanitize_enhance_outcome(
        outcome, prompt="林野", max_length=2000, asset_kind="character"
    )
    assert "三视图" in repaired.data["prompt"]
    assert "色板" in repaired.data["prompt"]
    assert "单一视角" not in repaired.data["prompt"]
    assert "已补回左三视图" in repaired.data["feedback"]


_SPLIT_SCENE_PLATE = (
    "16:9横构图，夜晚老旧出租屋门口与内部走廊的静谧空镜。"
    "画面前景为紧闭的旧式铁框防盗门，金属门板占据画面边缘。"
    "透过门缝或侧视角度，可见室内走廊昏暗无光。"
    "门外楼道视角（或分割构图），声控灯昏黄将熄。"
    "无任何人物出现，强调空间的压抑感与静止感。"
)


def test_restore_scene_plate_prompt_strips_split_and_or_cameras() -> None:
    restored = copywriter.restore_scene_plate_prompt(_SPLIT_SCENE_PLATE)
    assert "紧闭" in restored
    assert "无任何人物" in restored
    assert "分割构图" not in restored
    assert "或侧视" not in restored
    assert "或分割" not in restored
    assert "单一机位" in restored
    assert "遮挡" in restored


def test_restore_scene_plate_prompt_leaves_an_intact_plate() -> None:
    intact = (
        "夜晚老旧出租屋门外楼道。相机站在楼道看向一扇紧闭的铁框防盗门，"
        "门缝只漏出远处电视的冷蓝光，声控灯昏黄将熄，无任何人物。"
    )
    assert copywriter.restore_scene_plate_prompt(intact) == intact


def test_sanitize_enhance_repairs_a_split_scene_prompt() -> None:
    outcome = AgentOutcome(
        data={
            "prompt": _SPLIT_SCENE_PLATE,
            "detail_level": "adequate",
            "feedback": "已去除人物描写，仅保留纯场景。",
            "dimensions": [],
            "additions": [],
        },
        raw_text="",
        degraded=False,
        model="test",
        agent_run_id="run_test",
    )
    repaired = copywriter._sanitize_enhance_outcome(
        outcome, prompt="老旧出租屋门口", max_length=2000, asset_kind="scene"
    )
    assert "分割构图" not in repaired.data["prompt"]
    assert "或侧视" not in repaired.data["prompt"]
    assert "紧闭" in repaired.data["prompt"]
    assert "无任何人物" in repaired.data["prompt"]
    assert "已收成单一机位" in repaired.data["feedback"]


def test_enhance_rewrites_script_segment_blocks_in_place(db: Session, author: User) -> None:
    segment = {
        "heading": "雨巷",
        "blocks": [
            {"type": "action", "character": None, "text": "苏晴撑伞停下"},
            {"type": "dialogue", "character": "苏晴", "text": "你终于来了。"},
        ],
    }
    result = prompts.enhance(
        db,
        user_id=author.id,
        prompt="雨巷\n苏晴撑伞停下\n苏晴：你终于来了。",
        context=prompts.PromptContext(operation="text_to_video", script_segment=segment),
    )
    assert result.script_segment is not None
    assert result.script_segment["heading"] == "雨巷"
    assert [block["type"] for block in result.script_segment["blocks"]] == ["action", "dialogue"]
    assert result.script_segment["blocks"][1]["character"] == "苏晴"
    assert result.script_segment["blocks"][0]["text"] != "苏晴撑伞停下"
    assert "苏晴撑伞停下" in result.script_segment["blocks"][0]["text"]


def test_sanitize_drops_a_script_segment_that_changes_shape() -> None:
    original = {
        "heading": "雨巷",
        "blocks": [{"type": "dialogue", "character": "林夏", "text": "别走。"}],
    }
    outcome = AgentOutcome(
        data={
            "prompt": "别走啊。",
            "detail_level": "adequate",
            "feedback": "",
            "script_segment": {
                "heading": "雨巷",
                "blocks": [
                    {"type": "action", "character": None, "text": "错"},
                    {"type": "breakpoint", "character": None, "text": "切"},
                ],
            },
        },
        raw_text="",
        degraded=False,
        model="test",
        agent_run_id="run_test",
    )
    repaired = copywriter._sanitize_enhance_outcome(
        outcome, prompt="别走。", max_length=2000, script_segment=original
    )
    assert repaired.data["script_segment"]["blocks"] == original["blocks"]


def test_sanitize_enhance_does_not_rewrite_a_non_character_prompt() -> None:
    outcome = AgentOutcome(
        data={"prompt": _COLLAPSED_SHEET, "detail_level": "adequate", "feedback": ""},
        raw_text="",
        degraded=False,
        model="test",
        agent_run_id="run_test",
    )
    left = copywriter._sanitize_enhance_outcome(
        outcome, prompt="林野", max_length=2000, asset_kind="scene"
    )
    # The scene branch appends its own medium lock (this text names no
    # medium), but none of the character-sheet layout repair may fire.
    assert left.data["prompt"].startswith(_COLLAPSED_SHEET)
    assert copywriter.CHARACTER_SHEET_LAYOUT_SENTENCE not in left.data["prompt"]
    assert "三视图" not in left.data["prompt"]


# The live failure this whole pass exists for: a closed security door with a
# corridor, a kitchen and its dishes described behind it. Stripping the "或"
# branches leaves the impossible part intact, which is why the seatbelt now
# also pins the occlusion rule back on.
_OCCLUDED_SCENE_PLATE = (
    "16:9横构图，夜晚老旧出租屋门口。画面前景为紧闭的旧式铁框防盗门。"
    "透过门缝，可见室内走廊昏暗无光，背景深处厨房区域水槽上方堆叠着待洗的碗碟。"
)


def test_enforce_scene_plate_occlusion_pins_the_rule_back_on() -> None:
    enforced = copywriter.enforce_scene_plate_occlusion(_OCCLUDED_SCENE_PLATE)
    assert copywriter.SCENE_PLATE_OCCLUSION_SENTENCE in enforced
    assert enforced.startswith(_OCCLUDED_SCENE_PLATE)


def test_enforce_scene_plate_occlusion_leaves_a_plate_with_nothing_behind_it() -> None:
    intact = "夜晚楼道，相机站在楼道看向一扇紧闭的铁框防盗门，门缝下漏出一线冷蓝光。"
    assert copywriter.enforce_scene_plate_occlusion(intact) == intact


def test_enforce_scene_plate_medium_only_fires_when_no_medium_is_named() -> None:
    bare = "夜晚楼道，声控灯昏黄将熄。"
    assert copywriter.SCENE_PLATE_MEDIUM_SENTENCE in copywriter.enforce_scene_plate_medium(bare)
    named = "夜晚楼道，真人写实影视短剧实拍质感。"
    assert copywriter.enforce_scene_plate_medium(named) == named
    anime = "夜晚楼道，二次元动漫赛璐璐质感。"
    assert copywriter.enforce_scene_plate_medium(anime) == anime


def test_sanitize_enhance_repairs_an_occluded_scene_prompt() -> None:
    outcome = AgentOutcome(
        data={
            "prompt": _OCCLUDED_SCENE_PLATE,
            "detail_level": "adequate",
            "feedback": "",
            "dimensions": [],
            "additions": [],
        },
        raw_text="",
        degraded=False,
        model="test",
        agent_run_id="run_test",
    )
    repaired = copywriter._sanitize_enhance_outcome(
        outcome, prompt="老旧出租屋门口", max_length=2000, asset_kind="scene"
    )
    assert copywriter.SCENE_PLATE_OCCLUSION_SENTENCE in repaired.data["prompt"]
    assert copywriter.SCENE_PLATE_MEDIUM_SENTENCE in repaired.data["prompt"]
    assert "已锁死遮挡" in repaired.data["feedback"]


def test_scene_enhance_payload_carries_the_space_skill_pack() -> None:
    """The pack rides the user message, so an operator's own published system
    prompt cannot drop it (see `app.agents.scene_skills`)."""
    payload = json.loads(
        copywriter._enhance_user_prompt(
            prompt="夜晚老旧出租屋门口的楼道，紧闭的防盗门",
            operation="text_to_image",
            aspect_ratio="16:9",
            duration_seconds=None,
            quality_tier="",
            style_hint="",
            has_reference=False,
            direction="",
            instruction="",
            max_length=2000,
            asset_kind="scene",
        )
    )
    assert payload["scene_skill"]["key"] == "corridor_stairwell"
    assert payload["scene_skill"]["anchor"] == "era_region"
    assert payload["scene_skill"]["pitfalls"]
    assert any(o["value"] == "corridor_stairwell" for o in payload["space_type_options"])


def test_scene_enhance_payload_honours_an_answered_space_type() -> None:
    """A keyword match must not silently override the author's own answer."""
    payload = json.loads(
        copywriter._enhance_user_prompt(
            prompt="夜晚老旧出租屋门口的楼道，紧闭的防盗门",
            operation="text_to_image",
            aspect_ratio="16:9",
            duration_seconds=None,
            quality_tier="",
            style_hint="",
            has_reference=False,
            direction="",
            instruction="",
            max_length=2000,
            asset_kind="scene",
            question_answers={"space_type": "residential_interior"},
        )
    )
    assert payload["scene_skill"]["key"] == "residential_interior"
    assert payload["question_answers"] == {"space_type": "residential_interior"}


def test_non_scene_enhance_payload_carries_no_space_skill() -> None:
    payload = json.loads(
        copywriter._enhance_user_prompt(
            prompt="林野的角色设定图",
            operation="text_to_image",
            aspect_ratio="16:9",
            duration_seconds=None,
            quality_tier="",
            style_hint="",
            has_reference=False,
            direction="",
            instruction="",
            max_length=2000,
            asset_kind="character",
        )
    )
    assert "scene_skill" not in payload
    assert "space_type_options" not in payload


# ---- expression / scene presets ---------------------------------------------


def test_restore_expression_prompt_drops_sheet_layout_clauses() -> None:
    restored = copywriter.restore_expression_prompt(
        "林夏，短发，白衬衫。左侧全身三视图，右侧色板。神情克制", count=4
    )
    assert "三视图" not in restored and "色板" not in restored
    assert "林夏" in restored and "神情克制" in restored
    assert restored.endswith(copywriter.EXPRESSION_SHEET_SENTENCE)


def test_restore_expression_prompt_uses_a_close_up_for_one_expression() -> None:
    restored = copywriter.restore_expression_prompt("林夏，短发", count=1)
    assert restored.endswith(copywriter.EXPRESSION_SINGLE_SENTENCE)


def test_enhance_user_prompt_carries_preset_labels() -> None:
    payload = json.loads(
        copywriter._enhance_user_prompt(
            prompt="老式客厅",
            operation="text_to_image",
            aspect_ratio="16:9",
            duration_seconds=None,
            quality_tier="",
            style_hint="",
            has_reference=False,
            direction="",
            instruction="",
            max_length=2000,
            asset_kind="scene",
            asset_presets={"scene_lighting": "dusk", "scene_period": "1980s"},
        )
    )
    assert payload["asset_presets"] == {"光照": "黄昏", "时期": "八十年代"}
    assert "asset_presets_rule" in payload


def test_character_polish_with_expressions_keeps_the_grid() -> None:
    outcome = AgentOutcome(
        data={"prompt": "林夏。单张角色设定图、左右分栏：左侧全身三视图，右侧色板。"},
        raw_text="",
        degraded=False,
        model="fake",
        agent_run_id=None,
    )
    sanitized = copywriter._sanitize_enhance_outcome(
        outcome,
        prompt="林夏",
        max_length=2000,
        asset_kind="character",
        asset_presets={"character_expressions": ["smile", "anger"]},
    )
    assert "三视图" not in sanitized.data["prompt"]
    assert "表情合集" in sanitized.data["prompt"]


def test_context_from_collects_the_studio_presets() -> None:
    from app.api.schemas.shortform import PromptEnhanceRequest
    from app.api.v1.prompt_enhance import context_from

    ctx = context_from(
        PromptEnhanceRequest(
            prompt="老式客厅",
            asset_kind="scene",
            scene_lighting="neon",
            scene_state="searched",
        )
    )
    assert ctx.asset_presets == {"scene_lighting": "neon", "scene_state": "searched"}
    assert context_from(PromptEnhanceRequest(prompt="林夏")).asset_presets is None
