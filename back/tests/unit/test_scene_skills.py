"""The per-space packs the scene coach polishes against.

These are data, not behaviour, so the tests guard the two things that break
silently: the table's own shape (a pack the coach cannot read is worse than
no pack) and the resolution order (an author's explicit answer must outrank
a keyword hit, or the follow-up question is decorative).
"""

from __future__ import annotations

import pytest

from app.agents import scene_skills

FICTION_KEYS = {
    "spacecraft_interior",
    "outer_space_void",
    "alien_surface",
    "cyberpunk_city",
    "post_apocalypse",
    "fantasy_realm",
    "underwater",
}


def test_every_pack_is_complete_and_uniquely_keyed() -> None:
    packs = scene_skills.all_skills()
    keys = [pack.key for pack in packs]
    assert len(keys) == len(set(keys))
    for pack in packs:
        assert pack.anchor in ("era_region", "worldbuilding")
        assert pack.label
        for field in ("keywords", "structure", "fixtures", "light", "cues", "pitfalls"):
            value = getattr(pack, field)
            # A one-element field written without its trailing comma is a
            # plain string, and `as_payload`'s `list(...)` would explode it
            # into single characters before the model ever saw it.
            assert isinstance(value, tuple), (pack.key, field)
            assert all(isinstance(item, str) and item for item in value), (pack.key, field)
        assert pack.structure and pack.fixtures and pack.light and pack.cues and pack.pitfalls


def test_the_invented_spaces_are_the_ones_anchored_on_worldbuilding() -> None:
    """An era makes no sense on a vacuum plate, and a spaceship has no
    region — those packs must ask the other follow-up question."""
    by_anchor = {pack.key for pack in scene_skills.all_skills() if pack.anchor == "worldbuilding"}
    assert by_anchor == FICTION_KEYS


def test_only_the_fallback_pack_matches_nothing() -> None:
    for pack in scene_skills.all_skills():
        if pack.key == "generic":
            assert pack.keywords == ()
        else:
            assert pack.keywords


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("夜晚老旧出租屋门口的楼道，紧闭的防盗门与声控灯", "corridor_stairwell"),
        ("空间站舱内的空镜，控制面板亮着", "spacecraft_interior"),
        ("外太空真空中看向行星的弧线边缘", "outer_space_void"),
        ("深海沉船，人造光源照亮悬浮颗粒", "underwater"),
        ("霓虹招牌下的赛博未来都市街区", "cyberpunk_city"),
        ("一段说不清是什么的描述", "generic"),
    ],
)
def test_keyword_resolution(prompt: str, expected: str) -> None:
    assert scene_skills.resolve_scene_skill(prompt).key == expected


def test_an_explicit_answer_beats_the_keyword_hit() -> None:
    prompt = "夜晚老旧出租屋门口的楼道，紧闭的防盗门"
    assert scene_skills.resolve_scene_skill(prompt).key == "corridor_stairwell"
    assert scene_skills.resolve_scene_skill(prompt, "residential_interior").key == (
        "residential_interior"
    )


def test_an_unknown_answer_falls_back_to_the_keyword_hit() -> None:
    """A stale answer from an earlier round must not blank out the pack."""
    prompt = "夜晚老旧出租屋门口的楼道"
    assert scene_skills.resolve_scene_skill(prompt, "no_such_pack").key == "corridor_stairwell"


def test_payload_and_options_are_json_shaped() -> None:
    pack = scene_skills.resolve_scene_skill("空间站舱内")
    payload = scene_skills.as_payload(pack)
    assert payload["key"] == "spacecraft_interior"
    assert payload["anchor"] == "worldbuilding"
    assert isinstance(payload["structure"], list)
    options = scene_skills.skill_options()
    assert len(options) == len(scene_skills.all_skills())
    assert all(set(option) == {"value", "label"} for option in options)


def test_the_vacuum_pack_forbids_the_effects_that_need_an_atmosphere() -> None:
    """The single most common failure on a space plate is god rays in a
    vacuum — if this text drifts, the pack stops earning its place."""
    pack = scene_skills.get_skill("outer_space_void")
    assert pack is not None
    joined = " ".join((*pack.light, *pack.pitfalls))
    assert "散射" in joined
    assert "光柱" in joined
    assert "硬边" in joined
