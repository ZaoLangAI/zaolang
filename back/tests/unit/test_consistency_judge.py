"""P3-1: the vision consistency judge (`app.domain.image_assets.consistency`).

Runs on the offline fake gateway (`tests/fake_llm_gateway.py`), which gives
every requested dimension `FAKE_CONSISTENCY_SCORE`; the routing tests at the
bottom opt into the real client with a mocked transport instead.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import base as agent_base
from app.agents import quality as quality_agent
from app.agents.slots import CONSISTENCY_SLOT, VISION_CONSISTENCY_AGENT_KEY
from app.domain.agent_skills import service as agent_skills_service
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import NoCapableEndpoint, ProviderTemporaryFailure
from app.domain.image_assets import consistency
from app.domain.image_assets.consistency import ConsistencyContext
from app.domain.props import service as props_service
from app.domain.scenes import service as scenes_service
from app.llm import client as llm_client
from app.models import AgentRun, Asset, CreationSkill, CreditLedgerEntry, User
from app.models.base import new_id
from app.models.enums import AgentName, AssetEntryType, MediaType
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.scripts import ensure_catalog
from app.scripts import seed as seed_script
from app.storage import s3
from tests import fake_llm_gateway

# ---- helpers ----------------------------------------------------------------


def _png(size: tuple[int, int] = (64, 64), mode: str = "RGB") -> bytes:
    color: Any = (200, 40, 40, 0) if mode == "RGBA" else (200, 40, 40)
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _asset(
    db: Session,
    owner: User,
    payload: bytes | None = None,
    *,
    media_type: str = MediaType.IMAGE,
) -> Asset:
    key = f"test/{new_id('obj')}.png"
    s3.put_object(key, payload if payload is not None else _png(), content_type="image/png")
    asset = Asset(
        owner_user_id=owner.id,
        object_key=key,
        media_type=media_type,
        mime_type="image/png" if media_type == MediaType.IMAGE else "video/mp4",
        size_bytes=1024,
        checksum_sha256="c" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _character(db: Session, author: User) -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill


def _scene(db: Session, author: User) -> CreationSkill:
    return scenes_service.create_scene(
        db, user_id=author.id, name="客厅", description=None, reference_asset_ids=[]
    ).skill


def _prop(db: Session, author: User) -> CreationSkill:
    return props_service.create_prop(
        db, user_id=author.id, name="铜镜", description=None, reference_asset_ids=[]
    ).skill


def _anchored(db: Session, author: User, card: CreationSkill, entry_type: str, variant=None):  # type: ignore[no-untyped-def]
    entry = av.file_generated(
        db,
        card,
        variant or av.find_default(card),
        asset_id=_asset(db, author).id,
        entry_type=entry_type,
    )
    av.claim_anchor(db, card, entry)
    db.flush()
    return entry


def _seed_agents(db: Session) -> None:
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    seed_script.ensure_default_vision_agents(db)


def _score(db: Session, author: User, card: CreationSkill, anchor, context=None, output=None):  # type: ignore[no-untyped-def]
    return consistency.score(
        db,
        card=card,
        anchor_entry=anchor,
        output_asset_id=output or _asset(db, author).id,
        context=context
        or ConsistencyContext(
            entry_type=AssetEntryType.CHARACTER_SHEET.value,
            variant=av.find_default(card),
            user_id=author.id,
        ),
    )


def _run(db: Session, run_id: str | None) -> AgentRun:
    run = db.get(AgentRun, run_id)
    assert run is not None
    return run


def _reply(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    """Makes the fake judge answer with `payload` (a dict, or raw text)."""
    original = fake_llm_gateway.fake_complete

    def _fake(**kwargs: Any) -> llm_client.LlmCallResult:
        result = original(**kwargs)
        is_dict = isinstance(payload, dict)
        result.response.data = payload if is_dict else None  # type: ignore[assignment]
        result.response.text = json.dumps(payload) if is_dict else str(payload)
        return result

    monkeypatch.setattr(llm_client, "complete", _fake)


# ---- rubric -----------------------------------------------------------------


def test_every_rubric_weighs_to_one_hundred_percent() -> None:
    assert {
        kind: [(d.key, d.weight) for d in dims] for kind, dims in consistency.RUBRICS.items()
    } == {
        "character": [("face", 35), ("hair", 20), ("body", 15), ("medium", 15), ("outfit", 15)],
        "scene": [("layout", 40), ("furnishings", 30), ("material", 20), ("medium", 10)],
        "prop": [("silhouette", 40), ("material", 25), ("palette", 20), ("details", 15)],
    }
    assert all(sum(d.weight for d in dims) == 100 for dims in consistency.RUBRICS.values())
    assert consistency.RUBRIC_VERSION == 1


def test_the_total_is_a_weighted_integer_rounded_half_up() -> None:
    dims = consistency.RUBRICS["scene"]
    assert (
        consistency.weighted_total(
            {"layout": 50, "furnishings": 100, "material": 100, "medium": 100}, dims
        )
        == 80
    )
    # 0.4*71 + 0.3*70 + 0.2*70 + 0.1*70 = 70.4 → 70; 70.5 rounds up.
    assert (
        consistency.weighted_total(
            {"layout": 71, "furnishings": 70, "material": 70, "medium": 70}, dims
        )
        == 70
    )
    halves = (consistency.Dimension("a", "", 1), consistency.Dimension("b", "", 1))
    assert consistency.weighted_total({"a": 70, "b": 71}, halves) == 71


@pytest.mark.parametrize(
    ("make_card", "entry_type", "keys"),
    [
        (_character, "identity_portrait", ["face", "hair", "body", "medium", "outfit"]),
        (_scene, "master", ["layout", "furnishings", "material", "medium"]),
        (_prop, "master", ["silhouette", "material", "palette", "details"]),
    ],
)
def test_each_card_kind_is_scored_on_its_own_dimensions(
    db: Session, author: User, make_card, entry_type: str, keys: list[str]
) -> None:  # type: ignore[no-untyped-def]
    _seed_agents(db)
    card = make_card(db, author)
    anchor = _anchored(db, author, card, entry_type)
    context = ConsistencyContext(
        entry_type=entry_type, variant=av.find_default(card), job_id=None, user_id=author.id
    )
    ledger_before = db.scalar(select(func.count()).select_from(CreditLedgerEntry))

    result = _score(db, author, card, anchor, context)

    assert result.status == consistency.STATUS_SCORED
    assert list(result.dimensions) == keys
    assert result.score == fake_llm_gateway.FAKE_CONSISTENCY_SCORE
    assert (result.anchor_entry_id, result.anchor_asset_id) == (anchor.id, anchor.asset_id)
    assert result.rubric_version == 1 and not result.degraded
    run = _run(db, result.agent_run_id)
    vision_agent = agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY)
    assert vision_agent is not None
    assert (run.agent_name, run.prompt_slot, run.agent_profile_id) == (
        "quality",
        CONSISTENCY_SLOT,
        vision_agent.id,
    )
    assert run.cost_micro_usd == 0
    # Images are recorded as placeholders, never as inline base64.
    assert run.input_json["user_content"] == [
        {"type": "image_url", "omitted": True},
        {"type": "image_url", "omitted": True},
    ]
    assert "base64" not in json.dumps(run.input_json)
    # Platform cost only: nothing is charged to the user.
    assert db.scalar(select(func.count()).select_from(CreditLedgerEntry)) == ledger_before


def test_the_judge_runs_the_published_prompt_of_the_vision_agent(db: Session, author: User) -> None:
    _seed_agents(db)
    vision_agent = agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY)
    assert vision_agent is not None
    agent_skills_service.publish(
        db,
        profile_id=vision_agent.id,
        slot=CONSISTENCY_SLOT,
        prompt_template="运营改写过的评审提示词",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    card = _character(db, author)
    result = _score(db, author, card, _anchored(db, author, card, "identity_portrait"))
    assert _run(db, result.agent_run_id).input_json["system_prompt"] == "运营改写过的评审提示词"


def test_without_the_vision_agent_the_quality_default_judges(db: Session, author: User) -> None:
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    card = _character(db, author)
    result = _score(db, author, card, _anchored(db, author, card, "identity_portrait"))
    run = _run(db, result.agent_run_id)
    default = agent_skills_service.default_profile(db, "quality")
    assert default is not None
    assert run.agent_profile_id == default.id
    assert run.input_json["system_prompt"] == quality_agent.CONSISTENCY_SYSTEM_PROMPT


def test_an_outfit_change_drops_the_outfit_dimension_and_renormalises(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = _character(db, author)
    anchor = _anchored(db, author, card, "identity_portrait")
    wedding = av.create_variant(db, card, name="婚礼", description="白色婚纱")
    _reply(
        monkeypatch,
        {
            "dimensions": {"face": 50, "hair": 100, "body": 100, "medium": 100, "outfit": 0},
            "issues": [],
        },
    )

    result = _score(
        db,
        author,
        card,
        anchor,
        ConsistencyContext(entry_type="character_sheet", variant=wedding, user_id=author.id),
    )

    assert list(result.dimensions) == ["face", "hair", "body", "medium"]
    # (35*50 + 20*100 + 15*100 + 15*100) / 85 = 79.4
    assert result.score == 79
    prompt = _run(db, result.agent_run_id).input_json["user_prompt"]
    assert "维度键：face,hair,body,medium\n" in prompt
    assert "服装（本次为换装）" in prompt
    assert "表情、姿态、机位、背景" in prompt


def test_the_same_look_keeps_the_outfit_dimension(db: Session, author: User) -> None:
    card = _character(db, author)
    result = _score(db, author, card, _anchored(db, author, card, "identity_portrait"))
    assert "outfit" in result.dimensions
    assert "服装" not in _run(db, result.agent_run_id).input_json["user_prompt"].split("不比较")[1]


def test_a_scene_ignores_the_preset_axes_this_job_changed(db: Session, author: User) -> None:
    scene = _scene(db, author)
    anchor = _anchored(db, author, scene, "master")
    av.update_variant(db, scene, av.find_default(scene), presets={"period": "republic"})
    night = av.create_variant(
        db, scene, name="夜", presets={"period": "republic", "lighting": "night_exterior"}
    )

    result = _score(
        db,
        author,
        scene,
        anchor,
        ConsistencyContext(
            entry_type="master", variant=night, params={"scene_weather": "rain"}, user_id=author.id
        ),
    )

    ignored = _run(db, result.agent_run_id).input_json["user_prompt"].split("不比较：")[1]
    ignored = ignored.splitlines()[0]
    assert ignored == "机位、光照（本次有意改变）、天气（本次有意改变）"


def test_a_prop_ignores_a_changed_state(db: Session, author: User) -> None:
    prop = _prop(db, author)
    anchor = _anchored(db, author, prop, "master")
    worn = av.create_variant(db, prop, name="破损", presets={"prop_state": "broken"})

    changed = _score(
        db, author, prop, anchor, ConsistencyContext(entry_type="master", variant=worn)
    )
    same = _score(
        db,
        author,
        prop,
        anchor,
        ConsistencyContext(entry_type="master", variant=av.find_default(prop)),
    )

    assert "道具状态" in _run(db, changed.agent_run_id).input_json["user_prompt"]
    assert "道具状态" not in _run(db, same.agent_run_id).input_json["user_prompt"]


def test_an_expression_sheet_is_judged_whole_on_identity(db: Session, author: User) -> None:
    card = _character(db, author)
    result = _score(
        db,
        author,
        card,
        _anchored(db, author, card, "identity_portrait"),
        ConsistencyContext(entry_type="expression_sheet", variant=av.find_default(card)),
    )
    prompt = _run(db, result.agent_run_id).input_json["user_prompt"]
    assert "图 2 是表情合集" in prompt
    assert "忽略表情差异和分格布局" in prompt


# ---- anchors and skip rules -------------------------------------------------


def test_a_character_anchors_on_the_identity_portrait(db: Session, author: User) -> None:
    card = _character(db, author)
    sheet = _anchored(db, author, card, "character_sheet")
    assert consistency.resolve_anchor(card) == sheet
    portrait = _anchored(db, author, card, "identity_portrait")
    assert consistency.resolve_anchor(card) == portrait


def test_a_scene_anchors_on_the_target_variants_master(db: Session, author: User) -> None:
    scene = _scene(db, author)
    main = _anchored(db, author, scene, "master")
    dusk = av.create_variant(db, scene, name="黄昏")
    assert consistency.resolve_anchor(scene, dusk) == main
    dusk_master = _anchored(db, author, scene, "master", dusk)
    assert consistency.resolve_anchor(scene, dusk) == dusk_master
    assert consistency.resolve_anchor(scene) == main


def test_a_panorama_is_never_the_anchor(db: Session, author: User) -> None:
    scene = _scene(db, author)
    _anchored(db, author, scene, "panorama")
    assert consistency.resolve_anchor(scene) is None


@pytest.mark.parametrize("case", ["no_anchor", "output_is_anchor", "panorama", "video"])
def test_skip_rules(db: Session, author: User, case: str) -> None:
    card = _scene(db, author)
    anchor = _anchored(db, author, card, "master")
    output = _asset(db, author).id
    context = ConsistencyContext(entry_type="master", variant=av.find_default(card))
    if case == "no_anchor":
        anchor = None  # type: ignore[assignment]
    elif case == "output_is_anchor":
        output = anchor.asset_id
    elif case == "panorama":
        context.entry_type = AssetEntryType.PANORAMA.value
    else:
        output = _asset(db, author, media_type=MediaType.VIDEO).id

    runs_before = db.scalar(select(func.count()).select_from(AgentRun))
    result = _score(db, author, card, anchor, context, output)

    assert (result.status, result.skip_reason) == (consistency.STATUS_SKIPPED, case)
    assert result.score is None
    assert db.scalar(select(func.count()).select_from(AgentRun)) == runs_before


def test_a_video_context_is_skipped_before_anything_is_read(db: Session, author: User) -> None:
    card = _character(db, author)
    anchor = _anchored(db, author, card, "identity_portrait")
    result = _score(db, author, card, anchor, ConsistencyContext(entry_type="other", is_video=True))
    assert result.skip_reason == consistency.SKIP_VIDEO


# ---- degraded replies and failures -------------------------------------------


def test_a_missing_or_non_numeric_dimension_scores_zero_and_degrades(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = _prop(db, author)
    anchor = _anchored(db, author, card, "master")
    _reply(
        monkeypatch,
        {
            "dimensions": {"silhouette": "90", "material": 80.6, "palette": "很像", "extra": 5},
            "issues": ["  轮廓偏圆  ", "", "色" * 100, 3, "a", "b", "c", "d"],
            "score": 99,
        },
    )

    result = _score(db, author, card, anchor, ConsistencyContext(entry_type="master"))

    assert result.status == consistency.STATUS_SCORED
    assert result.degraded is True
    assert result.dimensions == {"silhouette": 90, "material": 81, "palette": 0, "details": 0}
    # The model's own "score" is ignored: (40*90 + 25*81) / 100 = 56.25.
    assert result.score == 56
    assert result.issues == ["轮廓偏圆", "色" * 60, "3", "a", "b"]


def test_scores_are_clamped_to_zero_and_one_hundred(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = _prop(db, author)
    _reply(
        monkeypatch,
        {"dimensions": {"silhouette": 140, "material": -3, "palette": 100, "details": True}},
    )
    result = _score(
        db, author, card, _anchored(db, author, card, "master"), ConsistencyContext("master")
    )
    assert result.dimensions == {"silhouette": 100, "material": 0, "palette": 100, "details": 0}
    assert result.degraded is True


@pytest.mark.parametrize("reply", ["这不是 JSON", {"verdict": "pass"}, {"dimensions": [1, 2]}])
def test_an_unusable_reply_fails_without_raising(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch, reply: object
) -> None:
    card = _character(db, author)
    anchor = _anchored(db, author, card, "identity_portrait")
    _reply(monkeypatch, reply)

    result = _score(db, author, card, anchor)

    assert (result.status, result.error) == (consistency.STATUS_FAILED, consistency.ERROR_PARSE)
    assert result.score is None and result.dimensions == {}
    assert result.agent_run_id is not None
    assert result.anchor_entry_id == anchor.id


def test_a_failed_call_returns_failed(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _down(**_kwargs: Any) -> None:
        raise ProviderTemporaryFailure("上游超时")

    monkeypatch.setattr(llm_client, "complete", _down)
    card = _character(db, author)
    result = _score(db, author, card, _anchored(db, author, card, "identity_portrait"))
    assert (result.status, result.error) == (consistency.STATUS_FAILED, consistency.ERROR_LLM)


def test_no_vision_endpoint_is_a_skip_not_a_failure(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _no_vision(**_kwargs: Any) -> None:
        raise NoCapableEndpoint({"image"})

    monkeypatch.setattr(llm_client, "complete", _no_vision)
    card = _character(db, author)
    anchor = _anchored(db, author, card, "identity_portrait")
    result = _score(db, author, card, anchor)
    assert (result.status, result.skip_reason) == (
        consistency.STATUS_SKIPPED,
        consistency.SKIP_NO_VISION_ENDPOINT,
    )
    assert result.anchor_asset_id == anchor.asset_id


def test_an_unreadable_image_fails_without_calling_the_judge(db: Session, author: User) -> None:
    card = _character(db, author)
    anchor = _anchored(db, author, card, "identity_portrait")
    broken = _asset(db, author, b"not an image")
    runs_before = db.scalar(select(func.count()).select_from(AgentRun))

    result = _score(db, author, card, anchor, output=broken.id)

    assert (result.status, result.error) == (
        consistency.STATUS_FAILED,
        consistency.ERROR_IMAGE_UNREADABLE,
    )
    assert db.scalar(select(func.count()).select_from(AgentRun)) == runs_before


def test_an_unexpected_error_still_returns_a_result(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(consistency, "rubric_for", _boom)
    card = _character(db, author)
    result = _score(db, author, card, _anchored(db, author, card, "identity_portrait"))
    assert (result.status, result.error) == (consistency.STATUS_FAILED, consistency.ERROR_INTERNAL)
    assert result.as_dict()["status"] == "failed"


# ---- image preparation --------------------------------------------------------


def _decode(data_url: str) -> Image.Image:
    prefix = "data:image/jpeg;base64,"
    assert data_url.startswith(prefix)
    return Image.open(io.BytesIO(base64.b64decode(data_url.removeprefix(prefix))))


def test_prepare_image_caps_the_long_edge_and_encodes_jpeg(db: Session, author: User) -> None:
    wide = _asset(db, author, _png((3000, 1500), "RGBA"))
    image = _decode(consistency.prepare_image(db, wide.id))
    assert (image.format, image.mode, image.size) == ("JPEG", "RGB", (1024, 512))
    # Transparency is flattened onto white, not black.
    red, green, blue = image.getpixel((10, 10))  # type: ignore[misc]
    assert min(red, green, blue) > 240

    tall = _asset(db, author, _png((600, 1200)))
    assert _decode(consistency.prepare_image(db, tall.id, max_px=512)).size == (256, 512)


def test_prepare_image_never_upscales(db: Session, author: User) -> None:
    small = _asset(db, author, _png((300, 200)))
    assert _decode(consistency.prepare_image(db, small.id)).size == (300, 200)


def test_prepare_image_refuses_a_video(db: Session, author: User) -> None:
    clip = _asset(db, author, media_type=MediaType.VIDEO)
    with pytest.raises(ValueError):
        consistency.prepare_image(db, clip.id)


# ---- seeding --------------------------------------------------------------------


def test_ensure_default_vision_agents_is_idempotent_and_add_only(db: Session) -> None:
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    quality_default = agent_skills_service.default_profile(db, "quality")

    assert seed_script.ensure_default_vision_agents(db) == 1
    agent = agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY)
    assert agent is not None
    assert not agent.is_default
    assert agent_skills_service.default_profile(db, "quality") == quality_default
    resolved = agent_skills_service.resolve_prompt(
        db, "quality", "", agent_id=agent.id, slot=CONSISTENCY_SLOT
    )
    assert resolved.text == quality_agent.CONSISTENCY_SYSTEM_PROMPT

    # An operator's own wording and binding survive a re-run.
    agent_skills_service.publish(
        db,
        profile_id=agent.id,
        slot=CONSISTENCY_SLOT,
        prompt_template="自定义",
        tool_grants=[],
        actor_user_id=None,
        reason="operator",
    )
    agent_skills_service.update_profile(db, agent.id, display_name="我的评审")
    assert seed_script.ensure_default_vision_agents(db) == 0
    db.refresh(agent)
    assert agent.display_name == "我的评审"
    assert (
        agent_skills_service.resolve_prompt(
            db, "quality", "", agent_id=agent.id, slot=CONSISTENCY_SLOT
        ).text
        == "自定义"
    )


def test_ensure_default_vision_agents_waits_for_a_quality_default(db: Session) -> None:
    assert seed_script.ensure_default_vision_agents(db) == 0
    assert agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY) is None


def test_the_production_backfill_plants_the_vision_agent(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ensure_catalog.s3, "ensure_bucket", lambda: None)
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)

    assert ensure_catalog.run(session=db)["agents"] == 1
    assert agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY)
    assert ensure_catalog.run(session=db)["agents"] == 0


# ---- admin warnings -------------------------------------------------------------


def _vision_endpoints(db: Session, *, vision: bool = True) -> None:
    endpoints: dict[str, Any] = {
        "text-ep": {
            "name": "文本端点",
            "base_url": "https://text.invalid",
            "api_key": "k",
            "kind": "general",
            "model": "text-model",
            "role": "primary",
            "input_modalities": ["text"],
        }
    }
    if vision:
        endpoints["vision-ep"] = {
            "name": "识图端点",
            "base_url": "https://vision.invalid",
            "api_key": "k",
            "kind": "general",
            "model": "vision-model",
            "role": "backup",
            "input_modalities": ["text", "image"],
        }
    config_service.set_value(
        db, "llm_providers", {"endpoints": endpoints}, actor_user_id=None, note="test"
    )


def _consistency_labels(db: Session) -> dict[str, list[str]]:
    return {
        profile_id: labels
        for profile_id, labels in agent_skills_service.image_slot_labels(db).items()
        if "一致性评审" in labels
    }


def test_the_consistency_warning_sits_on_the_agent_that_judges(db: Session) -> None:
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)
    quality_default = agent_skills_service.default_profile(db, "quality")
    assert quality_default is not None
    # Before the vision agent exists the role default would judge.
    assert _consistency_labels(db) == {quality_default.id: ["一致性评审"]}

    seed_script.ensure_default_vision_agents(db)
    agent = agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY)
    assert agent is not None
    # The metadata QC default no longer carries a vision warning.
    assert _consistency_labels(db) == {agent.id: ["一致性评审"]}
    assert quality_default.id not in agent_skills_service.image_slot_labels(db)

    agent_skills_service.update_profile(db, agent.id, enabled=False)
    assert agent_skills_service.resolve_consistency_agent_id(db) is None
    assert _consistency_labels(db) == {quality_default.id: ["一致性评审"]}


def test_a_text_only_vision_agent_is_warned(db: Session) -> None:
    _seed_agents(db)
    _vision_endpoints(db)
    agent = agent_skills_service.find_profile(db, "quality", VISION_CONSISTENCY_AGENT_KEY)
    assert agent is not None
    agent_skills_service.update_profile(db, agent.id, default_endpoint_id="text-ep")
    config = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    labels = agent_skills_service.image_slot_labels(db)[agent.id]

    assert agent_base.image_binding_warnings(db, agent, labels, config) == [
        "「一致性评审」需要图像输入，但绑定的端点都不支持，这类请求会改用共享池中支持图像的端点。"
    ]
    agent_skills_service.update_profile(db, agent.id, default_endpoint_id="vision-ep")
    assert agent_base.image_binding_warnings(db, agent, labels, config) == []


# ---- run_agent with images (real client, mocked transport) ----------------------


def _completion(model: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model,
        "choices": [{"message": {"content": json.dumps(data)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 3},
    }


_IMAGE = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}


@pytest.mark.real_gateway_seams
def test_run_agent_with_images_goes_to_an_image_endpoint(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _vision_endpoints(db)
    served: list[str] = []
    sent: list[Any] = []

    def _call_gateway(**kwargs: Any) -> dict[str, Any]:
        served.append(kwargs["model"])
        sent.append(kwargs["messages"][-1]["content"])
        return _completion(kwargs["model"], {"ok": True})

    monkeypatch.setattr(llm_client, "_call_gateway", _call_gateway)

    text = agent_base.run_agent(
        db, agent_name=AgentName.QUALITY.value, system_prompt="s", user_prompt="u", fallback={}
    )
    vision = agent_base.run_agent(
        db,
        agent_name=AgentName.QUALITY.value,
        system_prompt="s",
        user_prompt="u",
        user_content=[_IMAGE],
        fallback={},
        slot=CONSISTENCY_SLOT,
    )

    assert served == ["text-model", "vision-model"]
    assert sent[1] == [{"type": "text", "text": "u"}, _IMAGE]
    assert (text.endpoint_id, vision.endpoint_id) == ("text-ep", "vision-ep")
    assert _run(db, vision.agent_run_id).prompt_slot == CONSISTENCY_SLOT


@pytest.mark.real_gateway_seams
def test_run_agent_with_images_raises_when_nothing_reads_images(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _vision_endpoints(db, vision=False)

    def _never(**_kwargs: Any) -> None:
        raise AssertionError("a text-only endpoint must not be called with an image")

    monkeypatch.setattr(llm_client, "_call_gateway", _never)
    with pytest.raises(NoCapableEndpoint):
        agent_base.run_agent(
            db,
            agent_name=AgentName.QUALITY.value,
            system_prompt="s",
            user_prompt="u",
            user_content=[_IMAGE],
            fallback={},
        )


@pytest.mark.real_gateway_seams
def test_score_skips_on_the_real_client_without_a_vision_endpoint(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_agents(db)
    _vision_endpoints(db, vision=False)
    monkeypatch.setattr(llm_client, "_call_gateway", lambda **_: pytest.fail("called"))
    card = _character(db, author)
    result = _score(db, author, card, _anchored(db, author, card, "identity_portrait"))
    assert result.skip_reason == consistency.SKIP_NO_VISION_ENDPOINT


def test_the_write_back_can_declare_an_outfit_change_for_a_look_it_will_create(
    db: Session, author: User
) -> None:
    card = _character(db, author)
    anchor = _anchored(db, author, card, "identity_portrait")
    rubric = consistency.rubric_for(
        card, anchor, ConsistencyContext(entry_type="character_sheet", outfit_change=True)
    )
    assert "outfit" not in [d.key for d in rubric.dimensions]
    same = consistency.rubric_for(
        card,
        anchor,
        ConsistencyContext(
            entry_type="character_sheet", variant=av.find_default(card), outfit_change=False
        ),
    )
    assert "outfit" in [d.key for d in same.dimensions]
