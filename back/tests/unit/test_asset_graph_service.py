"""P4: a card's relation graph — same-card, same-level edges that keep each
level acyclic, validate relations per card kind, cascade with their ends
and survive an image moving to another look."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.asset_graph import service as graph
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.scenes import service as scenes_service
from app.models import Asset, CreationSkill, SkillAssetEdge, SkillAssetEntry, User
from app.models.base import new_id
from app.models.enums import AssetEdgeOrigin, MediaType


def _character(db: Session, owner: User, name: str = "林夏") -> CreationSkill:
    return characters_service.create_character(
        db,
        user_id=owner.id,
        name=name,
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill


def _entry(db: Session, skill: CreationSkill, variant=None) -> SkillAssetEntry:
    asset = Asset(
        owner_user_id=skill.owner_user_id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    target = variant or av.find_default(skill)
    return av.add_entry(db, skill, target, asset_id=asset.id, entry_type="other")


def _looks(db: Session, skill: CreationSkill, *names: str) -> list[str]:
    return [av.create_variant(db, skill, name=name).id for name in names]


def test_edges_form_a_dag_per_level(db: Session, author: User) -> None:
    skill = _character(db, author)
    a, b, c = _looks(db, skill, "少年", "青年", "老年")
    graph.add_edge(db, skill, level="variant", source_id=a, target_id=b, relations=["age"])
    graph.add_edge(db, skill, level="variant", source_id=b, target_id=c, relations=["age"])
    with pytest.raises(ValidationFailed, match="形成环"):
        graph.add_edge(db, skill, level="variant", source_id=b, target_id=a, relations=["age"])
    with pytest.raises(ValidationFailed, match="形成环"):
        graph.add_edge(db, skill, level="variant", source_id=c, target_id=a, relations=["age"])
    # A shortcut that keeps it acyclic is fine.
    graph.add_edge(db, skill, level="variant", source_id=a, target_id=c, relations=["age"])
    assert len(graph.edges(db, skill, "variant")) == 3


def test_self_loops_duplicates_and_foreign_nodes_are_rejected(db: Session, author: User) -> None:
    skill = _character(db, author)
    other = _character(db, author, name="周岩")
    a, b = _looks(db, skill, "日常", "婚礼")
    (foreign,) = _looks(db, other, "战甲")
    with pytest.raises(ValidationFailed):
        graph.add_edge(db, skill, level="variant", source_id=a, target_id=a, relations=["outfit"])
    graph.add_edge(db, skill, level="variant", source_id=a, target_id=b, relations=["outfit"])
    with pytest.raises(ValidationFailed, match="已有关系"):
        graph.add_edge(db, skill, level="variant", source_id=a, target_id=b, relations=["age"])
    with pytest.raises(ValidationFailed, match="不在这张卡片"):
        graph.add_edge(
            db, skill, level="variant", source_id=a, target_id=foreign, relations=["outfit"]
        )
    # A look id is not an image id: levels never mix.
    with pytest.raises(ValidationFailed):
        graph.add_edge(db, skill, level="entry", source_id=a, target_id=b, relations=["edit"])


def test_the_database_refuses_a_cross_card_edge(db: Session, author: User) -> None:
    skill = _character(db, author)
    other = _character(db, author, name="周岩")
    (mine,) = _looks(db, skill, "日常")
    (theirs,) = _looks(db, other, "战甲")
    db.add(
        SkillAssetEdge(
            skill_id=skill.id,
            level="variant",
            source_variant_id=mine,
            target_variant_id=theirs,
            relations_json=["outfit"],
            origin=AssetEdgeOrigin.MANUAL,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


@pytest.mark.parametrize(
    ("relations", "label"),
    [([], None), (["lighting"], None), (["custom"], None), (["custom"], "  ")],
)
def test_relations_must_fit_the_card(
    db: Session, author: User, relations: list[str], label: str | None
) -> None:
    skill = _character(db, author)
    a, b = _looks(db, skill, "日常", "婚礼")
    with pytest.raises(ValidationFailed):
        graph.add_edge(
            db, skill, level="variant", source_id=a, target_id=b, relations=relations, label=label
        )


def test_scene_cards_take_scene_relations(db: Session, author: User) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="码头", description=None, reference_asset_ids=[]
    ).skill
    a, b = _looks(db, scene, "白天", "雨夜")
    with pytest.raises(ValidationFailed):
        graph.add_edge(db, scene, level="variant", source_id=a, target_id=b, relations=["age"])
    edge = graph.add_edge(
        db, scene, level="variant", source_id=a, target_id=b, relations=["lighting", "weather"]
    )
    assert edge.relations_json == ["lighting", "weather"]


def test_edges_cascade_with_their_ends(db: Session, author: User) -> None:
    skill = _character(db, author)
    a, b = _looks(db, skill, "日常", "婚礼")
    first, second = _entry(db, skill), _entry(db, skill)
    graph.add_edge(db, skill, level="variant", source_id=a, target_id=b, relations=["outfit"])
    graph.add_edge(
        db, skill, level="entry", source_id=first.id, target_id=second.id, relations=["edit"]
    )
    av.delete_variant(db, skill, av.find_variant(skill, b))
    av.remove_entry(db, skill, second)
    db.flush()
    db.expire_all()
    assert db.scalars(select(SkillAssetEdge).where(SkillAssetEdge.skill_id == skill.id)).all() == []


def test_moving_an_image_keeps_its_id_and_edges(db: Session, author: User) -> None:
    skill = _character(db, author)
    (wedding_id,) = _looks(db, skill, "婚礼")
    wedding = av.find_variant(skill, wedding_id)
    first, second = _entry(db, skill), _entry(db, skill)
    graph.add_edge(
        db, skill, level="entry", source_id=first.id, target_id=second.id, relations=["edit"]
    )
    moved = av.update_entry(db, skill, second, variant=wedding)
    db.flush()
    assert moved.id == second.id
    assert moved.variant_id == wedding_id
    assert len(graph.edges(db, skill, "entry")) == 1


def test_an_auto_edge_skips_instead_of_raising(db: Session, author: User) -> None:
    skill = _character(db, author)
    a, b = _looks(db, skill, "青年", "老年")
    assert graph.add_auto_edge(
        db, skill, level="variant", source_id=a, target_id=b, relations=["age"]
    )
    assert (
        graph.add_auto_edge(db, skill, level="variant", source_id=b, target_id=a, relations=["age"])
        is None
    )
    # Unknown relations fall back to a labelled custom edge.
    (c,) = _looks(db, skill, "战损")
    edge = graph.add_auto_edge(
        db, skill, level="variant", source_id=b, target_id=c, relations=["lighting"]
    )
    assert edge is not None
    assert edge.relations_json == ["custom"]
    assert edge.label == "派生"
    assert edge.origin == "auto"


def test_relations_between_names_what_differs(db: Session, author: User) -> None:
    skill = _character(db, author)
    young = av.create_variant(db, skill, name="青年", presets={"age_stage": "youth"})
    old = av.create_variant(
        db,
        skill,
        name="老年战损",
        presets={"age_stage": "elderly"},
        attributes={"state": "负伤"},
    )
    assert graph.relations_between(young, old) == ["age", "emotion"]
    assert graph.relations_between(young, young) == []


def test_update_edge_validates_like_create(db: Session, author: User) -> None:
    skill = _character(db, author)
    a, b = _looks(db, skill, "日常", "婚礼")
    edge = graph.add_edge(
        db, skill, level="variant", source_id=a, target_id=b, relations=["outfit"]
    )
    graph.update_edge(db, skill, edge, relations=["custom"], label="第二幕")
    assert edge.relations_json == ["custom"]
    with pytest.raises(ValidationFailed):
        graph.update_edge(db, skill, edge, clear_label=True)
