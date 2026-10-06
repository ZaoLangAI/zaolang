"""`copy` slot `asset_breakdown` (AC-9): the model's proposal is bound to
the script, bounded, and filled from the script where it falls short."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.agents import asset_breakdown
from app.agents.base import AgentOutcome
from app.models import AgentRun


def _script(title: str = "雨夜") -> dict[str, Any]:
    return {
        "title": title,
        "logline": "一块碎玉佩引出的旧案",
        "characters": [
            {"name": "林夏", "traits": "真人写实影视短剧造型，年轻女性，齐肩黑发"},
            {"name": "顾沉", "traits": "真人写实影视短剧造型，中年男性，灰色风衣"},
        ],
        "scenes": [
            {
                "heading": "第一场 · 便利店 - 夜",
                "blocks": [
                    {"type": "scene", "character": None, "text": "深夜的便利店，日光灯嗡嗡作响"},
                    {"type": "action", "character": None, "text": "林夏把玉佩塞进口袋"},
                ],
            },
            {
                "heading": "第二场 · 顾家书房 - 日",
                "blocks": [
                    {"type": "scene", "character": None, "text": "红木书架，午后斜光"},
                    {"type": "dialogue", "character": "顾沉", "text": "钥匙在哪？"},
                ],
            },
            {
                "heading": "第三场 · 便利店 - 夜",
                "blocks": [{"type": "action", "character": None, "text": "林夏攥着玉佩发抖"}],
            },
        ],
    }


def test_the_fake_breakdown_groups_places_and_finds_props(db: Session) -> None:
    result = asset_breakdown.breakdown(db, script=_script())

    assert result.degraded is False
    assert [(c.name, c.age_stage) for c in result.characters] == [
        ("林夏", "youth"),
        ("顾沉", "adult"),
    ]
    assert [(s.name, s.headings, s.lighting) for s in result.scenes] == [
        ("便利店", ("第一场 · 便利店 - 夜", "第三场 · 便利店 - 夜"), "night_interior"),
        ("顾家书房", ("第二场 · 顾家书房 - 日",), "day"),
    ]
    assert {p.name: p.headings for p in result.props} == {
        "玉佩": ("第一场 · 便利店 - 夜", "第三场 · 便利店 - 夜"),
        "钥匙": ("第二场 · 顾家书房 - 日",),
    }
    slot = asset_breakdown.ASSET_BREAKDOWN_SLOT
    run = db.query(AgentRun).filter(AgentRun.prompt_slot == slot).one()
    assert run.agent_name == "copy"


def test_sanitize_binds_the_proposal_to_the_script() -> None:
    raw = {
        "characters": [
            {"name": "顾沉", "appearance": "灰色风衣", "age_stage": "middle_aged"},
            {"name": "路人甲", "appearance": "不在角色表", "age_stage": "adult"},
            {"name": "林夏", "appearance": "", "age_stage": "toddler"},
        ],
        "scenes": [
            {
                "name": "便利店",
                "headings": ["第一场 · 便利店 - 夜", "不存在的场次"],
                "description": "货架与收银台",
                "period": "contemporary",
                "lighting": "sunset",
            },
            # Claims a heading already claimed above: dropped from here.
            {"name": "商店", "headings": ["第一场 · 便利店 - 夜"], "description": "x"},
            {"name": "便利店", "headings": ["第三场 · 便利店 - 夜"], "description": "y"},
        ],
        "props": [
            {"name": "玉佩", "description": "碎成两半", "headings": ["第三场 · 便利店 - 夜", "?"]},
            {"name": "玉佩", "description": "重复"},
            {"name": "", "description": "无名"},
        ],
    }
    result = asset_breakdown.sanitize(raw, _script())

    # Script order and names; an unknown character is dropped, a missing
    # appearance falls back to the traits, an unknown preset to None.
    assert [(c.name, c.appearance, c.age_stage) for c in result.characters] == [
        ("林夏", "真人写实影视短剧造型，年轻女性，齐肩黑发", None),
        ("顾沉", "灰色风衣", "middle_aged"),
    ]
    by_name = {scene.name: scene for scene in result.scenes}
    assert set(by_name) == {"便利店", "顾家书房"}
    assert by_name["便利店"].headings == ("第一场 · 便利店 - 夜", "第三场 · 便利店 - 夜")
    assert by_name["便利店"].lighting is None
    assert by_name["便利店"].period == "contemporary"
    # The unclaimed heading becomes its own place, from the script.
    assert by_name["顾家书房"].description == "红木书架，午后斜光"
    assert [(p.name, p.description, p.headings) for p in result.props] == [
        ("玉佩", "碎成两半", ("第三场 · 便利店 - 夜",))
    ]


def test_junk_output_still_lists_every_character_and_heading(db: Session) -> None:
    result = asset_breakdown.breakdown(db, script=_script(title="无从拆解"))

    assert [c.name for c in result.characters] == ["林夏", "顾沉"]
    assert [heading for s in result.scenes for heading in s.headings] == [
        "第一场 · 便利店 - 夜",
        "第三场 · 便利店 - 夜",
        "第二场 · 顾家书房 - 日",
    ]
    assert result.props == []


def test_props_are_capped() -> None:
    raw = {"props": [{"name": f"道具{i}", "headings": []} for i in range(60)]}
    result = asset_breakdown.sanitize(raw, _script())
    assert len(result.props) == asset_breakdown.MAX_PROPS


def test_a_degraded_run_falls_back_to_the_script(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def degraded(*_args: Any, fallback: dict[str, Any], **_kwargs: Any) -> AgentOutcome:
        return AgentOutcome(
            data=fallback, raw_text="", degraded=True, model="none", agent_run_id="run"
        )

    monkeypatch.setattr(asset_breakdown, "run_agent", degraded)
    result = asset_breakdown.breakdown(db, script=_script())

    assert result.degraded is True
    assert [c.name for c in result.characters] == ["林夏", "顾沉"]
    assert [s.name for s in result.scenes] == ["便利店", "顾家书房"]
    assert result.props == []

    registered = {**_script(), "props": [{"name": "钥匙", "description": "", "prop_ref_id": None}]}
    again = asset_breakdown.breakdown(db, script=registered)
    assert [(p.name, p.headings) for p in again.props] == [("钥匙", ("第二场 · 顾家书房 - 日",))]


@pytest.mark.parametrize(
    ("heading", "place"),
    [
        ("第一场 · 便利店 - 夜", "便利店"),
        ("第12场 日 内 顾家书房", "顾家书房"),
        ("INT. 地下车库 - NIGHT", "地下车库"),
        ("夜", "夜"),
    ],
)
def test_place_name_drops_numbers_and_time_marks(heading: str, place: str) -> None:
    assert asset_breakdown.place_name(heading) == place


def test_registered_props_stay_on_the_list_under_their_own_name() -> None:
    script = {
        **_script(),
        "props": [{"name": "碎玉佩", "description": "白玉，断成两半", "prop_ref_id": "sk_jade"}],
    }
    script["scenes"][2]["blocks"][0]["text"] = "林夏攥着碎玉佩发抖"
    # The model renamed it: the registered name is kept alongside.
    result = asset_breakdown.sanitize({"props": [{"name": "玉佩", "headings": []}]}, script)
    assert [(p.name, p.description, p.headings) for p in result.props] == [
        ("玉佩", "", ()),
        ("碎玉佩", "白玉，断成两半", ("第三场 · 便利店 - 夜",)),
    ]
