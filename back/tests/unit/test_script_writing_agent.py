"""`copy` agent's `script_draft`/`script_revise` slots: stub streaming,
fenced-JSON extraction and structural sanitization."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents import copywriter


def _drain(chunks) -> str:
    return "".join(chunks)


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
    assert outcome.script["scenes"][0] == {**current["scenes"][0], "ref_id": None}


def test_extract_summary_and_script_splits_on_the_fence() -> None:
    raw = '先改了开场。\n```json\n{"title": "t", "scenes": []}\n```'
    summary, parsed = copywriter._extract_summary_and_script(raw)
    assert summary == "先改了开场。"
    assert parsed == {"title": "t", "scenes": []}


def test_extract_summary_and_script_handles_missing_fence() -> None:
    summary, parsed = copywriter._extract_summary_and_script("纯文本，没有代码块")
    assert summary == "纯文本，没有代码块"
    assert parsed is None


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


def test_carry_over_links_does_not_match_a_renamed_character() -> None:
    previous = {"characters": [{"name": "小雨", "character_ref_id": "chr_1"}], "scenes": []}
    updated = {"characters": [{"name": "小晴", "character_ref_id": None}], "scenes": []}
    copywriter._carry_over_links(previous, updated)
    assert updated["characters"][0]["character_ref_id"] is None
