"""剧本拆解建卡 (AC-9): turn a script into character / scene / prop cards.

`propose` runs the `copy` agent's `asset_breakdown` slot over the episode's
`script_json` and pairs every proposal with the caller's own cards of the
same name — nothing is written. `plan_apply` validates the author's
per-row choice (新建 / 关联已有 / 忽略) against the script and prices the
first images (identity portrait, scene master plate, prop hero plate) with
the same `quote_for` a submit uses; `write_cards` then creates the new
cards (DRAFT / PRIVATE, like every library create), sets their presets on
the default look / variant and writes every link into `script_json`
through `service.update_links`. Submitting the jobs, the balance check and
the idempotent replay live in the route (`api/v1/scripts.py`), the same
split as the scene matrix (`api/v1/scene_matrix.py`).

Cards belong to the caller, not to the series owner: a co-creator's
breakdown matches and creates the co-creator's own cards, the same rule
`update_links` applies to a hand-picked link.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agents import asset_breakdown
from app.domain.asset_variants import service as asset_variants_service
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.props import service as props_service
from app.domain.scenes import service as scenes_service
from app.domain.script_writing import service as script_service
from app.models import CreationSkill, DramaEpisode
from app.models.enums import ImageAssetKind, Operation

CHARACTER = "character"
SCENE = "scene"
PROP = "prop"

# The first image each kind's card starts from, as one image job.
_ASSET_KIND = {
    CHARACTER: ImageAssetKind.CHARACTER.value,
    SCENE: ImageAssetKind.SCENE.value,
    PROP: ImageAssetKind.PROP.value,
}
_ASPECT_RATIO = {CHARACTER: "3:4", SCENE: "16:9", PROP: "1:1"}


@dataclass(frozen=True, slots=True)
class CardRef:
    id: str
    name: str


@dataclass(slots=True)
class ProposedItem:
    kind: str
    name: str
    description: str = ""
    headings: list[str] = field(default_factory=list)
    age_stage: str | None = None
    period: str | None = None
    lighting: str | None = None
    linked_card_id: str | None = None
    matches: list[CardRef] = field(default_factory=list)


@dataclass(slots=True)
class Proposal:
    characters: list[ProposedItem]
    scenes: list[ProposedItem]
    props: list[ProposedItem]
    degraded: bool


def _script_of(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    script_service._require_script_studio(session, user_id=user_id)
    episode = script_service._owned_episode(session, user_id=user_id, episode_id=episode_id)
    if not (episode.script_json or {}).get("scenes"):
        raise ValidationFailed("该剧本还没有初稿，请先生成初稿。")
    return episode


def _owned_cards(session: Session, *, user_id: str) -> dict[str, list[CardRef]]:
    """The caller's cards per kind, newest first."""
    return {
        CHARACTER: [
            CardRef(card.id, card.name)
            for card in characters_service.list_characters(session, user_id=user_id)
        ],
        SCENE: [
            CardRef(card.id, card.name)
            for card in scenes_service.list_scenes(session, user_id=user_id)
        ],
        PROP: [
            CardRef(card.id, card.name)
            for card in props_service.list_props(session, user_id=user_id)
        ],
    }


def _matches(cards: list[CardRef], *names: str) -> list[CardRef]:
    wanted = {name.strip() for name in names if name.strip()}
    return [card for card in cards if card.name.strip() in wanted]


def _owned_or_none(cards: list[CardRef], card_id: Any) -> str | None:
    return card_id if card_id and any(card.id == card_id for card in cards) else None


def propose(session: Session, *, user_id: str, episode_id: str) -> Proposal:
    """The cards the script needs, each with the caller's same-named cards
    and the card the script already links (only when the caller owns it —
    a co-creator cannot link the owner's cards)."""
    episode = _script_of(session, user_id=user_id, episode_id=episode_id)
    script = episode.script_json or {}
    result = asset_breakdown.breakdown(session, script=script, user_id=user_id)
    cards = _owned_cards(session, user_id=user_id)

    character_links = {
        str(item.get("name")): item.get("character_ref_id")
        for item in script.get("characters") or []
        if isinstance(item, dict)
    }
    heading_links = {
        str(scene.get("heading")): scene.get("ref_id")
        for scene in script.get("scenes") or []
        if isinstance(scene, dict)
    }
    prop_links = {
        str(item.get("name")): item.get("prop_ref_id")
        for item in script.get("props") or []
        if isinstance(item, dict)
    }

    characters = [
        ProposedItem(
            kind=CHARACTER,
            name=item.name,
            description=item.appearance,
            age_stage=item.age_stage,
            linked_card_id=_owned_or_none(cards[CHARACTER], character_links.get(item.name)),
            matches=_matches(cards[CHARACTER], item.name),
        )
        for item in result.characters
    ]
    scenes = [
        ProposedItem(
            kind=SCENE,
            name=item.name,
            description=item.description,
            headings=list(item.headings),
            period=item.period,
            lighting=item.lighting,
            linked_card_id=next(
                (
                    linked
                    for heading in item.headings
                    if (linked := _owned_or_none(cards[SCENE], heading_links.get(heading)))
                ),
                None,
            ),
            matches=_matches(
                cards[SCENE],
                item.name,
                *(asset_breakdown.place_name(heading) for heading in item.headings),
            ),
        )
        for item in result.scenes
    ]
    props = [
        ProposedItem(
            kind=PROP,
            name=item.name,
            description=item.description,
            headings=list(item.headings),
            linked_card_id=_owned_or_none(cards[PROP], prop_links.get(item.name)),
            matches=_matches(cards[PROP], item.name),
        )
        for item in result.props
    ]
    return Proposal(characters=characters, scenes=scenes, props=props, degraded=result.degraded)


# ---- apply ------------------------------------------------------------------


@dataclass(slots=True)
class ApplyItem:
    kind: str
    name: str
    action: str
    card_id: str | None = None
    description: str = ""
    headings: list[str] = field(default_factory=list)
    age_stage: str | None = None
    period: str | None = None
    lighting: str | None = None
    # Filled by `plan_apply` / `write_cards` / the route's submit.
    credits: int = 0
    created: bool = False
    job_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ApplyPlan:
    episode: DramaEpisode
    items: list[ApplyItem]
    generate: bool
    quality_tier: str

    @property
    def total_credits(self) -> int:
        return sum(item.credits for item in self.items)

    def first_image_items(self) -> list[ApplyItem]:
        return [item for item in self.items if item.action == "create" and self.generate]


def plan_apply(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    items: list[ApplyItem],
    generate: bool,
    quality_tier: str,
) -> ApplyPlan:
    """Validates every row against the script and the caller's library
    (422 per field, 404 for a card the caller cannot use) and prices the
    first images. Writes nothing."""
    episode = _script_of(session, user_id=user_id, episode_id=episode_id)
    script = episode.script_json or {}
    character_names = {
        str(item.get("name")) for item in script.get("characters") or [] if isinstance(item, dict)
    }
    headings = {
        str(scene.get("heading")) for scene in script.get("scenes") or [] if isinstance(scene, dict)
    }
    seen: set[tuple[str, str]] = set()
    claimed: set[str] = set()
    for index, item in enumerate(items):
        item.name = item.name.strip()
        key = (item.kind, item.name)
        if key in seen:
            raise ValidationFailed(
                f"「{item.name}」重复出现。", fields={f"items.{index}.name": "重复"}
            )
        seen.add(key)
        if item.action == "skip":
            continue
        if item.kind == CHARACTER and item.name not in character_names:
            raise ValidationFailed(
                f"剧本里没有角色「{item.name}」。", fields={f"items.{index}.name": "不在剧本中"}
            )
        if item.kind == SCENE:
            if not item.headings:
                raise ValidationFailed(
                    f"场景「{item.name}」没有对应的场次。",
                    fields={f"items.{index}.headings": "不能为空"},
                )
            for heading in item.headings:
                if heading not in headings or heading in claimed:
                    raise ValidationFailed(
                        f"场次「{heading}」不在剧本中或已归到其他场景。",
                        fields={f"items.{index}.headings": "无效"},
                    )
                claimed.add(heading)
        if item.action == "link":
            _require_card(session, user_id=user_id, item=item, index=index)
        elif item.kind == CHARACTER and characters_service.find_owned_character_by_name(
            session, user_id=user_id, name=item.name
        ):
            raise ValidationFailed(
                f"角色库里已有「{item.name}」，请选择关联已有。",
                fields={f"items.{index}.action": "角色名称已存在"},
            )

    plan = ApplyPlan(episode=episode, items=items, generate=generate, quality_tier=quality_tier)
    for item in plan.first_image_items():
        item.credits = jobs_service.quote_for(
            session,
            operation=Operation.TEXT_TO_IMAGE,
            quality_tier=quality_tier,
            output_count=jobs_service.requested_output_count(
                asset_kind=_ASSET_KIND[item.kind], character_views=None
            ),
        ).credits
    return plan


def _require_card(session: Session, *, user_id: str, item: ApplyItem, index: int) -> None:
    if not item.card_id:
        raise ValidationFailed(
            "请选择要关联的卡片。", fields={f"items.{index}.card_id": "不能为空"}
        )
    if item.kind == CHARACTER:
        characters_service.get_character(session, user_id=user_id, character_id=item.card_id)
    elif item.kind == SCENE:
        scenes_service.get_scene(session, user_id=user_id, scene_id=item.card_id)
    else:
        props_service.get_prop(session, user_id=user_id, prop_id=item.card_id)


def _card_skill(session: Session, *, user_id: str, kind: str, card_id: str) -> CreationSkill:
    if kind == CHARACTER:
        return characters_service.get_character(
            session, user_id=user_id, character_id=card_id
        ).skill
    if kind == SCENE:
        return scenes_service.get_scene(session, user_id=user_id, scene_id=card_id).skill
    return props_service.get_prop(session, user_id=user_id, prop_id=card_id).skill


def _presets(item: ApplyItem) -> dict[str, str]:
    if item.kind == CHARACTER:
        candidates = {"age_stage": item.age_stage}
    elif item.kind == SCENE:
        candidates = {"period": item.period, "lighting": item.lighting}
    else:
        candidates = {"period": item.period}
    return {key: value for key, value in candidates.items() if value}


def _create_card(session: Session, *, user_id: str, item: ApplyItem) -> CreationSkill:
    description = item.description.strip() or None
    skill: CreationSkill
    if item.kind == CHARACTER:
        skill = characters_service.create_character(
            session,
            user_id=user_id,
            name=item.name,
            description=description,
            reference_asset_ids=[],
            voice_description=None,
        ).skill
    elif item.kind == SCENE:
        skill = scenes_service.create_scene(
            session,
            user_id=user_id,
            name=item.name,
            description=description,
            reference_asset_ids=[],
        ).skill
    else:
        skill = props_service.create_prop(
            session,
            user_id=user_id,
            name=item.name,
            description=description,
            reference_asset_ids=[],
        ).skill
    presets = _presets(item)
    default = asset_variants_service.find_default(skill)
    if presets and default is not None:
        asset_variants_service.update_variant(session, skill, default, presets=presets)
    return skill


def write_cards(session: Session, *, user_id: str, plan: ApplyPlan) -> DramaEpisode:
    """Creates the `create` rows' cards and writes every link into the
    script in one `update_links` call. A `skip` row leaves its current link
    as it is."""
    for item in plan.items:
        if item.action == "create":
            item.card_id = _create_card(session, user_id=user_id, item=item).id
            item.created = True
    active = [item for item in plan.items if item.action != "skip"]
    return script_service.update_links(
        session,
        user_id=user_id,
        episode_id=plan.episode.id,
        character_links=[
            (item.name, item.card_id, None) for item in active if item.kind == CHARACTER
        ],
        scene_links=[
            (heading, item.card_id, None)
            for item in active
            if item.kind == SCENE
            for heading in item.headings
        ],
        prop_links=[(item.name, item.card_id) for item in active if item.kind == PROP],
        prop_descriptions={
            item.name: item.description.strip()
            for item in active
            if item.kind == PROP and item.description.strip()
        },
    )


def first_image_params(session: Session, *, user_id: str, item: ApplyItem) -> dict[str, Any]:
    """The raw `GenerationParams` of a created card's first image: the
    identity portrait, the master plate of the scene's default variant, the
    hero plate of the prop's default condition."""
    assert item.card_id is not None
    skill = _card_skill(session, user_id=user_id, kind=item.kind, card_id=item.card_id)
    description = item.description.strip().rstrip("。．.")
    params: dict[str, Any] = {
        "prompt": f"{item.name}。{description}" if description else item.name,
        "aspect_ratio": _ASPECT_RATIO[item.kind],
        "asset_kind": _ASSET_KIND[item.kind],
        "subject_name_hint": item.name[:60],
    }
    default = asset_variants_service.find_default(skill)
    if item.kind == CHARACTER:
        params["target_character_id"] = skill.id
        params["character_portrait"] = True
    elif item.kind == SCENE:
        params["target_scene_id"] = skill.id
        params["target_variant_id"] = default.id if default else None
        if item.lighting:
            params["scene_lighting"] = item.lighting
        if item.period:
            params["scene_period"] = item.period
    else:
        params["target_prop_id"] = skill.id
        params["target_variant_id"] = default.id if default else None
    return params
