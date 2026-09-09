"""`app.domain.prompts.enhance`: the dimension-by-dimension diagnosis shared by
the shortform studio and the generation studio's own polish button."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.agents.base import AgentOutcome
from app.api.schemas.shortform import PromptDimensionKey, PromptEnhanceDirection
from app.domain import prompts
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ValidationFailed
from app.llm import client as llm_client
from app.models import AgentRun, User
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
        copywriter._enhance_text_is_usable(
            'If unsure {"answer":"$your_answer"} then ' + usable
        )
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
    cover = copywriter.ENHANCE_SYSTEM_PROMPT_COVER

    assert not character.startswith(generic)
    assert not scene.startswith(generic)
    assert not cover.startswith(generic)
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
    assert "封面海报" in cover
    assert "安全区" in cover
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
        cover,
        action,
        transition,
        cover_video,
        copywriter.SYSTEM_PROMPT,
    ):
        assert "只输出一个 JSON 对象" in prompt


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
