"""`copy` agent's `script_draft`/`script_revise` slots: stub streaming,
fenced-JSON extraction and structural sanitization."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.llm import client as llm_client
from app.llm.client import StreamChunk
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS
from app.scripts import seed


def _drain(chunks) -> str:
    """Concatenates only the `kind="content"` chunks — the user-facing
    text a script's summary/JSON payload is parsed from. `kind="thinking"`
    chunks are a separate channel (see `stream_complete`'s docstring) and
    must never leak into the text these tests parse."""
    return "".join(chunk.text for chunk in chunks if chunk.kind == "content")


def test_stream_draft_script_produces_a_sanitized_script(db: Session) -> None:
    chunks, finalize = copywriter.stream_draft_script(db, idea="深夜便利店的秘密", title="")
    _drain(chunks)
    outcome = finalize()

    assert outcome.parse_ok is True
    assert outcome.summary
    assert outcome.script["scenes"]
    for scene in outcome.script["scenes"]:
        assert scene["heading"]
        for block in scene["blocks"]:
            assert block["type"] in copywriter.SCRIPT_BLOCK_TYPES


def test_stream_revise_script_changes_the_script_and_keeps_it_on_failure(db: Session) -> None:
    current = {
        "title": "便利店",
        "logline": "",
        "characters": [],
        "scenes": [
            {"heading": "第一场", "blocks": [{"type": "scene", "character": None, "text": "开场"}]}
        ],
    }
    chunks, finalize = copywriter.stream_revise_script(
        db, message="把结局改得更悬疑一点", current_script=current
    )
    _drain(chunks)
    outcome = finalize()

    assert outcome.parse_ok is True
    all_text = " ".join(
        block["text"] for scene in outcome.script["scenes"] for block in scene["blocks"]
    )
    assert "把结局改得更悬疑一点" in all_text
    # The original scene must still be there — a revision is the full
    # document, but the stub only appends, it never drops what existed.
    # `ref_id` is sanitizer-added (absent from the caller's plain dict, so
    # `None` after a round trip) rather than part of the original content.
    assert outcome.script["scenes"][0] == {
        **current["scenes"][0],
        "ref_id": None,
        "variant_id": None,
    }


def test_extract_summary_and_script_splits_on_the_fence() -> None:
    raw = '先改了开场。\n```json\n{"title": "t", "scenes": []}\n```'
    summary, parsed = copywriter._extract_summary_and_script(raw)
    assert summary == "先改了开场。"
    assert parsed == {"title": "t", "scenes": []}


def test_extract_summary_and_script_handles_missing_fence() -> None:
    summary, parsed = copywriter._extract_summary_and_script("纯文本，没有代码块")
    assert summary == "纯文本，没有代码块"
    assert parsed is None


def test_extract_summary_and_script_falls_back_to_bare_json_without_a_fence() -> None:
    """A model that ignores the "always fence it" instruction and just emits
    bare JSON after its summary must still be recognized — via `extract_json`'s
    balanced-brace scan — rather than treated as if it produced no script."""
    raw = '先改了开场。\n{"title": "t", "scenes": []}'
    summary, parsed = copywriter._extract_summary_and_script(raw)
    assert summary == "先改了开场。"
    assert parsed == {"title": "t", "scenes": []}
    assert copywriter._script_text_is_usable(raw) is False  # no scenes survive sanitization


def test_script_text_is_usable_accepts_bare_json_with_real_scenes() -> None:
    raw = (
        "先改了开场。\n"
        '{"title": "t", "scenes": [{"heading": "第一场", '
        '"blocks": [{"type": "scene", "character": null, "text": "开场"}]}]}'
    )
    assert copywriter._script_text_is_usable(raw) is True


def test_sanitize_script_drops_invalid_blocks_and_empty_scenes() -> None:
    raw = {
        "title": "  标题  ",
        "logline": "梗概",
        "characters": [{"name": "小雨", "traits": "冷静"}, {"name": "", "traits": "应被丢弃"}],
        "scenes": [
            {
                "heading": "第一场",
                "blocks": [
                    {"type": "scene", "character": None, "text": "场景描述"},
                    {"type": "not_a_type", "character": None, "text": "应被丢弃"},
                    {"type": "dialogue", "character": "小雨", "text": ""},
                ],
            },
            {"heading": "空场次", "blocks": []},
        ],
    }
    sanitized = copywriter._sanitize_script(raw)
    assert sanitized is not None
    assert sanitized["title"] == "标题"
    assert len(sanitized["characters"]) == 1
    # The empty scene and the invalid/empty blocks must not survive.
    assert len(sanitized["scenes"]) == 1
    assert len(sanitized["scenes"][0]["blocks"]) == 1


def test_sanitize_script_rejects_a_document_with_no_usable_scenes() -> None:
    assert copywriter._sanitize_script({"title": "t", "scenes": []}) is None
    assert copywriter._sanitize_script("not even a dict") is None
    assert copywriter._sanitize_script({"scenes": [{"heading": "h", "blocks": []}]}) is None


def test_sanitize_script_keeps_a_breakpoint_block_with_no_character() -> None:
    raw = {
        "title": "t",
        "scenes": [
            {
                "heading": "第一场",
                "blocks": [
                    {"type": "dialogue", "character": "小雨", "text": "台词"},
                    {"type": "breakpoint", "character": None, "text": "建议在此处切分"},
                ],
            }
        ],
    }
    sanitized = copywriter._sanitize_script(raw)
    assert sanitized is not None
    blocks = sanitized["scenes"][0]["blocks"]
    assert [b["type"] for b in blocks] == ["dialogue", "breakpoint"]
    assert blocks[1]["character"] is None
    assert blocks[1]["text"] == "建议在此处切分"


def test_draft_stub_includes_a_breakpoint_block(db: Session) -> None:
    chunks, finalize = copywriter.stream_draft_script(db, idea="深夜便利店的秘密", title="")
    _drain(chunks)
    outcome = finalize()
    all_types = {block["type"] for scene in outcome.script["scenes"] for block in scene["blocks"]}
    assert "breakpoint" in all_types


def test_sanitize_script_passes_through_existing_links() -> None:
    raw = {
        "title": "t",
        "characters": [{"name": "小雨", "traits": "冷静", "character_ref_id": "chr_1"}],
        "scenes": [
            {
                "heading": "第一场",
                "ref_id": "scn_1",
                "blocks": [{"type": "scene", "character": None, "text": "开场"}],
            }
        ],
    }
    sanitized = copywriter._sanitize_script(raw)
    assert sanitized is not None
    assert sanitized["characters"][0]["character_ref_id"] == "chr_1"
    assert sanitized["scenes"][0]["ref_id"] == "scn_1"


def test_carry_over_links_reattaches_links_the_model_output_omits() -> None:
    previous = {
        "characters": [{"name": "小雨", "traits": "", "character_ref_id": "chr_1"}],
        "scenes": [{"heading": "第一场", "ref_id": "scn_1", "blocks": []}],
    }
    # The model's own output never carries these fields — it isn't told they
    # exist — so a freshly sanitized turn result has them as `None`.
    updated = {
        "characters": [{"name": "小雨", "traits": "更冷静", "character_ref_id": None}],
        "scenes": [{"heading": "第一场", "ref_id": None, "blocks": []}],
    }
    copywriter._carry_over_links(previous, updated)
    assert updated["characters"][0]["character_ref_id"] == "chr_1"
    assert updated["scenes"][0]["ref_id"] == "scn_1"


def test_sanitize_script_bounds_props_and_keeps_their_links() -> None:
    raw = {
        "scenes": [
            {"heading": "第一场", "blocks": [{"type": "scene", "character": None, "text": "开场"}]}
        ],
        "props": [
            {"name": " 玉佩 ", "description": "碎成两半", "prop_ref_id": "sk_1"},
            {"name": "玉佩", "description": "重复"},
            {"name": ""},
            "not a prop",
            *({"name": f"道具{i}"} for i in range(copywriter.MAX_PROPS + 5)),
        ],
    }
    sanitized = copywriter._sanitize_script(raw)
    assert sanitized is not None
    props = sanitized["props"]
    assert len(props) == copywriter.MAX_PROPS
    assert props[0] == {"name": "玉佩", "description": "碎成两半", "prop_ref_id": "sk_1"}
    assert [p["name"] for p in props].count("玉佩") == 1


def test_carry_over_links_keeps_the_breakdown_props_the_model_never_writes() -> None:
    previous = {
        "characters": [],
        "scenes": [],
        "props": [{"name": "玉佩", "description": "", "prop_ref_id": "sk_1"}],
    }
    updated = {"characters": [], "scenes": [], "props": []}
    copywriter._carry_over_links(previous, updated)
    assert updated["props"] == previous["props"]

    echoed = {"characters": [], "scenes": [], "props": [{"name": "玉佩", "prop_ref_id": None}]}
    copywriter._carry_over_links(previous, echoed)
    assert echoed["props"][0]["prop_ref_id"] == "sk_1"


def test_carry_over_links_does_not_match_a_renamed_character() -> None:
    previous = {"characters": [{"name": "小雨", "character_ref_id": "chr_1"}], "scenes": []}
    updated = {"characters": [{"name": "小晴", "character_ref_id": None}], "scenes": []}
    copywriter._carry_over_links(previous, updated)
    assert updated["characters"][0]["character_ref_id"] is None


def test_stream_draft_scales_up_to_the_bound_models_own_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`SCRIPT_MAX_TOKENS` is only a *floor* — a reasoning model whose bound
    endpoint declares a larger `max_output_tokens` gets that larger budget on
    the very first attempt, rather than being artificially capped down to
    the slot's own smaller constant. A fixed, undersized first attempt is
    exactly what let a real reasoning model spend its whole (needlessly
    small) budget thinking and come back with zero completion tokens — see
    `back/app/agents/base.py`'s `run_agent_stream` floor semantics."""
    from tests.llm_catalog import seed_test_llm_catalog

    seed_test_llm_catalog(db, max_output_tokens=16_384)
    seen: dict[str, int] = {}

    def capture_stream(**kwargs):  # type: ignore[no-untyped-def]
        seen["max_tokens"] = kwargs["max_tokens"]
        text = (
            "先写了开场。\n```json\n"
            '{"title": "t", "logline": "", "characters": [], '
            '"scenes": [{"heading": "h", "blocks": '
            '[{"type": "scene", "character": null, "text": "开场"}]}]}\n```'
        )
        kwargs["result"].text = text
        yield StreamChunk(kind="content", text=text)

    monkeypatch.setattr(llm_client, "stream_complete", capture_stream)
    chunks, finalize = copywriter.stream_draft_script(db, idea="深夜便利店的秘密")
    _drain(chunks)
    outcome = finalize()
    assert seen["max_tokens"] == 16_384
    assert outcome.parse_ok is True


def test_stream_draft_still_floors_at_script_max_tokens_when_the_endpoint_declares_no_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the floor semantics: an endpoint that hasn't
    declared its own `max_output_tokens` (0 = undeclared) must not fall back
    to the generic `DEFAULT_MAX_TOKENS` (2048) for a payload this size —
    `SCRIPT_MAX_TOKENS` is still what gets requested."""
    seen: dict[str, int] = {}

    def capture_stream(**kwargs):  # type: ignore[no-untyped-def]
        seen["max_tokens"] = kwargs["max_tokens"]
        text = (
            "先写了开场。\n```json\n"
            '{"title": "t", "logline": "", "characters": [], '
            '"scenes": [{"heading": "h", "blocks": '
            '[{"type": "scene", "character": null, "text": "开场"}]}]}\n```'
        )
        kwargs["result"].text = text
        yield StreamChunk(kind="content", text=text)

    monkeypatch.setattr(llm_client, "stream_complete", capture_stream)
    chunks, finalize = copywriter.stream_draft_script(db, idea="深夜便利店的秘密")
    _drain(chunks)
    outcome = finalize()
    assert seen["max_tokens"] == copywriter.SCRIPT_MAX_TOKENS
    assert outcome.parse_ok is True


def test_stream_revise_scales_up_to_the_bound_models_own_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.llm_catalog import seed_test_llm_catalog

    seed_test_llm_catalog(db, max_output_tokens=16_384)
    seen: dict[str, int] = {}

    def capture_stream(**kwargs):  # type: ignore[no-untyped-def]
        seen["max_tokens"] = kwargs["max_tokens"]
        text = (
            "改了结局。\n```json\n"
            '{"title": "t", "logline": "", "characters": [], '
            '"scenes": [{"heading": "h", "blocks": '
            '[{"type": "scene", "character": null, "text": "悬疑结尾"}]}]}\n```'
        )
        kwargs["result"].text = text
        yield StreamChunk(kind="content", text=text)

    monkeypatch.setattr(llm_client, "stream_complete", capture_stream)
    current = {
        "title": "便利店",
        "logline": "",
        "characters": [],
        "scenes": [
            {"heading": "第一场", "blocks": [{"type": "scene", "character": None, "text": "开场"}]}
        ],
    }
    chunks, finalize = copywriter.stream_revise_script(
        db, message="把结局改得更悬疑一点", current_script=current
    )
    _drain(chunks)
    outcome = finalize()
    assert seen["max_tokens"] == 16_384
    assert outcome.parse_ok is True


def test_stream_revise_still_floors_at_script_max_tokens_when_the_endpoint_declares_no_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, int] = {}

    def capture_stream(**kwargs):  # type: ignore[no-untyped-def]
        seen["max_tokens"] = kwargs["max_tokens"]
        text = (
            "改了结局。\n```json\n"
            '{"title": "t", "logline": "", "characters": [], '
            '"scenes": [{"heading": "h", "blocks": '
            '[{"type": "scene", "character": null, "text": "悬疑结尾"}]}]}\n```'
        )
        kwargs["result"].text = text
        yield StreamChunk(kind="content", text=text)

    monkeypatch.setattr(llm_client, "stream_complete", capture_stream)
    current = {
        "title": "便利店",
        "logline": "",
        "characters": [],
        "scenes": [
            {"heading": "第一场", "blocks": [{"type": "scene", "character": None, "text": "开场"}]}
        ],
    }
    chunks, finalize = copywriter.stream_revise_script(
        db, message="把结局改得更悬疑一点", current_script=current
    )
    _drain(chunks)
    outcome = finalize()
    assert seen["max_tokens"] == copywriter.SCRIPT_MAX_TOKENS
    assert outcome.parse_ok is True


def test_script_prompts_require_a_shared_visual_medium() -> None:
    """`traits` seed the character-sheet jump-out verbatim. Without a
    script-wide medium the image model picks photoreal for one cast member
    and anime for the next."""
    draft = copywriter.SCRIPT_DRAFT_SYSTEM_PROMPT
    revise = copywriter.SCRIPT_REVISE_SYSTEM_PROMPT
    appearance = copywriter._CHARACTER_APPEARANCE_RULE
    assert "唯一视觉媒介" in appearance
    assert "真人写实影视短剧" in appearance
    assert "开头写同一句媒介" in appearance
    assert appearance in draft
    assert appearance in revise
    assert "媒介句必须保持一致且原样保留" in revise
    # `traits` is reused verbatim on every shot this character appears in, so
    # a mood or pose written into it drifts the character between shots.
    assert "稳定的静态特征" in appearance
    assert "完全相同的措辞" in appearance


def test_both_script_prompts_keep_the_factory_opener() -> None:
    """`seed._publish_factory_prompt` only republishes a seeded prompt while
    the stored draft still starts with a `_FACTORY_SCRIPT_OPENERS` prefix.

    Rewording the opening sentence would sync once and then silently stop:
    the next rewrite would look like an operator's hand-edit and be left
    alone forever. This is cheap to assert and expensive to discover."""
    for prompt in (
        copywriter.SCRIPT_DRAFT_SYSTEM_PROMPT,
        copywriter.SCRIPT_REVISE_SYSTEM_PROMPT,
    ):
        assert prompt.startswith(seed._FACTORY_SCRIPT_OPENERS)
        assert seed._looks_like_factory_prompt(prompt, seed._FACTORY_SCRIPT_OPENERS)


def test_block_type_rules_split_framing_from_camera_movement() -> None:
    """A `camera` block's text is what a shot's prompt is built from later, and
    Kling's guide separates 「镜头语言」(framing, angle) from movement control
    for a reason: written as one phrase such as 「特写环绕」the two drift, and
    stacked moves wobble at the switch point.

    The `action` rules carry the other half of the same budget — one beat per
    block, counted where countable, emotion externalised — because five
    vendors document that stacked actions deform the subject."""
    rules = copywriter._BLOCK_TYPE_RULES

    assert "先景别、再运镜" in rules
    assert "一个 camera 色块只给一个运镜动作" in rules
    assert "方式＋方向＋速度" in rules
    assert "特写环绕" in rules

    assert "写清次数与幅度" in rules
    assert "情绪一律外化成看得见的生理信号" in rules

    # `scene` still seeds `sceneImagePrompt` verbatim, so the no-people rule
    # is load-bearing and must survive any rewrite of this block.
    assert "不能出现任何人物" in rules
    assert "只写镜头拍得到的东西" in rules

    for prompt in (
        copywriter.SCRIPT_DRAFT_SYSTEM_PROMPT,
        copywriter.SCRIPT_REVISE_SYSTEM_PROMPT,
    ):
        assert rules in prompt


def test_breakpoint_rules_give_a_duration_baseline_to_estimate_with() -> None:
    """ "Estimate the duration" is unactionable on its own — the baselines turn
    it into arithmetic against the platform's live per-generation ceiling."""
    rules = copywriter._BREAKPOINT_RULES

    assert "每秒 3 到 4 个字" in rules
    assert "远景约 10 秒" in rules
    assert str(MAX_GENERATION_DURATION_SECONDS) in rules
    assert "留出接口" in rules


def test_the_short_drama_craft_rules_reach_both_turns() -> None:
    """Split out of the draft prompt so a revision turn writing a brand-new
    scene is held to the same standard.

    Revise scopes them to newly written content on purpose: its stronger
    promise is "don't touch what the user didn't ask about", and a craft rule
    that overrides that would make every revision a rewrite."""
    rules = copywriter._SHORT_DRAMA_CRAFT_RULES

    assert "直接冲突型" in rules and "强悬念型" in rules and "极致反差型" in rules
    assert "悬念断" in rules and "情感断" in rules
    assert "同一类不要连续用超过两次" in rules
    assert "主要角色控制在 3 人以内" in rules
    assert "双人不要左右并排" in rules
    assert "优先中近景与特写" in rules

    assert rules in copywriter.SCRIPT_DRAFT_SYSTEM_PROMPT
    assert rules in copywriter.SCRIPT_REVISE_SYSTEM_PROMPT
    assert "未被这一轮意见触及的既有内容不要为了符合这些" in copywriter.SCRIPT_REVISE_SYSTEM_PROMPT


def test_empty_stream_is_not_a_successful_draft(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def empty_stream(**kwargs):  # type: ignore[no-untyped-def]
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)
    chunks, finalize = copywriter.stream_draft_script(db, idea="深夜便利店的秘密")
    assert _drain(chunks) == ""
    outcome = finalize()
    assert outcome.parse_ok is False
    assert outcome.script["scenes"] == []


def test_stream_draft_yields_thinking_chunks_live_and_keeps_them_out_of_the_summary(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `kind="thinking"` chunk must reach the caller (so it can be shown
    live) but must never be concatenated into the text `_extract_summary_and_script`
    parses — only `kind="content"` chunks make up the summary/script text."""

    def capture_stream(**kwargs):  # type: ignore[no-untyped-def]
        text = (
            "先写了开场。\n```json\n"
            '{"title": "t", "logline": "", "characters": [], '
            '"scenes": [{"heading": "h", "blocks": '
            '[{"type": "scene", "character": null, "text": "开场"}]}]}\n```'
        )
        kwargs["result"].text = text
        kwargs["result"].thinking = "先构思一下开场画面……"
        yield StreamChunk(kind="thinking", text="先构思一下开场画面……")
        yield StreamChunk(kind="content", text=text)

    monkeypatch.setattr(llm_client, "stream_complete", capture_stream)
    chunks, finalize = copywriter.stream_draft_script(db, idea="深夜便利店的秘密")
    kinds = [chunk.kind for chunk in chunks]
    outcome = finalize()

    assert kinds == ["thinking", "content"]
    assert outcome.parse_ok is True
    assert outcome.thinking == "先构思一下开场画面……"
    assert "先构思" not in outcome.summary
