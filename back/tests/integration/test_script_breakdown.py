"""剧本拆解建卡 (AC-9): `POST /v1/scripts/{id}:breakdown` proposes cards,
`…:breakdown-apply` creates / links them and queues their first images."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.scenes import service as scenes_service
from app.domain.script_writing import service as script_writing_service
from app.models import (
    CreationSkill,
    DramaEpisode,
    GenerationJob,
    SeriesCollaborator,
    User,
)
from app.models.base import new_id
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    Operation,
    SeriesCollaboratorStatus,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from app.workers import tasks
from tests.conftest import auth_header, make_user

pytestmark = pytest.mark.usefixtures("fake_media_catalog")

STORE_NIGHT = "第一场 · 便利店 - 夜"
STUDY_DAY = "第二场 · 顾家书房 - 日"
STORE_AGAIN = "第三场 · 便利店 - 夜"

SCRIPT: dict[str, Any] = {
    "title": "雨夜",
    "logline": "一块碎玉佩引出的旧案",
    "characters": [
        {
            "name": "林夏",
            "traits": "真人写实影视短剧造型，年轻女性，齐肩黑发",
            "character_ref_id": None,
            "look_id": None,
        },
        {
            "name": "顾沉",
            "traits": "真人写实影视短剧造型，中年男性，灰色风衣",
            "character_ref_id": None,
            "look_id": None,
        },
    ],
    "scenes": [
        {
            "heading": STORE_NIGHT,
            "ref_id": None,
            "variant_id": None,
            "blocks": [
                {"type": "scene", "character": None, "text": "深夜的便利店，日光灯嗡嗡作响"},
                {"type": "action", "character": None, "text": "林夏把玉佩塞进口袋"},
            ],
        },
        {
            "heading": STUDY_DAY,
            "ref_id": None,
            "variant_id": None,
            "blocks": [
                {"type": "scene", "character": None, "text": "红木书架，午后斜光"},
                {"type": "dialogue", "character": "顾沉", "text": "钥匙在哪？"},
            ],
        },
        {
            "heading": STORE_AGAIN,
            "ref_id": None,
            "variant_id": None,
            "blocks": [{"type": "action", "character": None, "text": "林夏攥着玉佩发抖"}],
        },
    ],
    "props": [],
}


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: sent.append(job.id))
    return sent


def _enable(session: Session, actor: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["script_studio_enabled"] = True
    config_service.set_value(session, "feature_flags", value, actor_user_id=actor.id, note="test")


def _episode(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> DramaEpisode:
    """A script through the real first-draft route, then this module's
    richer document written over it."""

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(script_writing_service, "session_scope", fake_session_scope)
    _enable(db, author)
    response = client.post(
        "/v1/scripts", json={"title": "", "idea": "雨夜旧案"}, headers=auth_header(author)
    )
    assert response.status_code == 202
    episode = db.scalars(select(DramaEpisode).order_by(DramaEpisode.created_at.desc())).first()
    assert episode is not None
    episode.script_json = SCRIPT
    db.flush()
    return episode


def _card_count(db: Session, owner: User) -> int:
    return db.scalar(
        select(func.count(CreationSkill.id)).where(CreationSkill.owner_user_id == owner.id)
    )


def _apply(
    client: TestClient,
    user: User,
    episode_id: str,
    items: list[dict[str, Any]],
    *,
    generate: bool = False,
    dry_run: bool = False,
    key: str | None = None,
):
    headers = auth_header(user)
    if key:
        headers["Idempotency-Key"] = key
    return client.post(
        f"/v1/scripts/{episode_id}:breakdown-apply",
        json={
            "items": items,
            "generate": {"enabled": generate, "quality_tier": "standard"},
            "dry_run": dry_run,
        },
        headers=headers,
    )


CREATE_ALL = [
    {
        "kind": "character",
        "name": "林夏",
        "action": "create",
        "description": "齐肩黑发",
        "age_stage": "youth",
    },
    {"kind": "character", "name": "顾沉", "action": "skip"},
    {
        "kind": "scene",
        "name": "便利店",
        "action": "create",
        "description": "货架与收银台",
        "headings": [STORE_NIGHT, STORE_AGAIN],
        "period": "contemporary",
        "lighting": "night_interior",
    },
    {"kind": "scene", "name": "顾家书房", "action": "skip", "headings": [STUDY_DAY]},
    {
        "kind": "prop",
        "name": "玉佩",
        "action": "create",
        "description": "碎成两半的白玉",
        "headings": [STORE_NIGHT, STORE_AGAIN],
    },
]


def test_breakdown_needs_the_script_studio_flag(
    client: TestClient, db: Session, author: User
) -> None:
    response = client.post("/v1/scripts/ep_missing:breakdown", headers=auth_header(author))
    assert response.status_code == 404


def test_breakdown_proposes_cards_with_the_callers_matches_and_writes_nothing(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    lin = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    store = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    episode.script_json = {
        **SCRIPT,
        "characters": [
            {**SCRIPT["characters"][0], "character_ref_id": lin.id},
            SCRIPT["characters"][1],
        ],
    }
    db.flush()
    cards_before = _card_count(db, author)

    response = client.post(f"/v1/scripts/{episode.id}:breakdown", headers=auth_header(author))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is False
    lin_row, gu_row = body["characters"]
    assert lin_row["linked_card_id"] == lin.id
    assert lin_row["matches"] == [{"id": lin.id, "name": "林夏"}]
    assert lin_row["age_stage"] == "youth"
    assert gu_row["matches"] == [] and gu_row["linked_card_id"] is None
    store_row = next(row for row in body["scenes"] if row["name"] == "便利店")
    assert store_row["headings"] == [STORE_NIGHT, STORE_AGAIN]
    assert store_row["matches"] == [{"id": store.id, "name": "便利店"}]
    assert store_row["lighting"] == "night_interior"
    assert {row["name"]: row["headings"] for row in body["props"]} == {
        "玉佩": [STORE_NIGHT, STORE_AGAIN],
        "钥匙": [STUDY_DAY],
    }
    assert _card_count(db, author) == cards_before
    db.refresh(episode)
    assert episode.script_json["props"] == []


def test_a_dry_run_prices_the_first_images_and_writes_nothing(
    client: TestClient,
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[str],
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    cards_before = _card_count(db, author)

    response = _apply(client, author, episode.id, CREATE_ALL, generate=True, dry_run=True)

    assert response.status_code == 200, response.text
    body = response.json()
    unit = jobs_service.quote_for(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier="standard"
    ).credits
    assert body["total_credits"] == unit * 3
    assert [item["credits"] for item in body["items"]] == [unit, 0, unit, 0, unit]
    assert body["sufficient"] is True and body["dry_run"] is True
    assert body["submitted"] == 0 and dispatched == []
    assert _card_count(db, author) == cards_before
    assert body["script"]["characters"][0]["character_ref_id"] is None


def test_apply_creates_cards_links_them_and_queues_first_images_then_replays(
    client: TestClient,
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[str],
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))

    first = _apply(client, author, episode.id, CREATE_ALL, generate=True, key="breakdown-1")

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["submitted"] == 3 and len(dispatched) == 3
    by_name = {item["name"]: item for item in body["items"]}
    assert by_name["顾沉"]["card_id"] is None and by_name["顾沉"]["job_id"] is None
    lin_id, store_id, jade_id = (by_name[name]["card_id"] for name in ("林夏", "便利店", "玉佩"))
    for card_id in (lin_id, store_id, jade_id):
        skill = db.get(CreationSkill, card_id)
        assert skill is not None and skill.owner_user_id == author.id
        assert skill.status == CreationSkillStatus.DRAFT
        assert skill.visibility == Visibility.PRIVATE
    lin_skill = db.get(CreationSkill, lin_id)
    store_skill = db.get(CreationSkill, store_id)
    assert av.find_default(lin_skill).presets_json == {"age_stage": "youth"}  # type: ignore[arg-type, union-attr]
    assert av.find_default(store_skill).presets_json == {  # type: ignore[arg-type, union-attr]
        "period": "contemporary",
        "lighting": "night_interior",
    }
    assert db.get(CreationSkill, jade_id).category == CreationSkillCategory.PROP_ASSET  # type: ignore[union-attr]

    script = body["script"]
    assert script["characters"][0]["character_ref_id"] == lin_id
    assert script["characters"][1]["character_ref_id"] is None
    assert [scene["ref_id"] for scene in script["scenes"]] == [store_id, None, store_id]
    assert script["props"] == [
        {"name": "玉佩", "description": "碎成两半的白玉", "prop_ref_id": jade_id}
    ]

    jobs = {
        item["name"]: db.get(GenerationJob, item["job_id"])
        for item in body["items"]
        if item["job_id"]
    }
    portrait = jobs["林夏"].request_json  # type: ignore[union-attr]
    assert portrait["character_portrait"] is True
    assert portrait["target_character_id"] == lin_id
    plate = jobs["便利店"].request_json  # type: ignore[union-attr]
    assert plate["target_scene_id"] == store_id
    assert plate["target_variant_id"] == av.find_default(store_skill).id  # type: ignore[arg-type, union-attr]
    assert plate["scene_lighting"] == "night_interior"
    hero = jobs["玉佩"].request_json  # type: ignore[union-attr]
    assert hero["asset_kind"] == "prop" and hero["target_prop_id"] == jade_id
    assert hero["prompt"] == "玉佩。碎成两半的白玉"

    cards_after = _card_count(db, author)
    again = _apply(client, author, episode.id, CREATE_ALL, generate=True, key="breakdown-1")
    assert again.status_code == 200
    assert again.json() == body
    assert _card_count(db, author) == cards_after
    assert len(dispatched) == 3

    changed = _apply(client, author, episode.id, CREATE_ALL[:1], generate=True, key="breakdown-1")
    assert changed.status_code == 409


def test_apply_links_existing_cards_and_skip_leaves_a_link_alone(
    client: TestClient,
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[str],
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    gu = characters_service.create_character(
        db,
        user_id=author.id,
        name="顾沉",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    study = scenes_service.create_scene(
        db, user_id=author.id, name="书房", description=None, reference_asset_ids=[]
    )
    episode.script_json = {
        **SCRIPT,
        "scenes": [
            SCRIPT["scenes"][0],
            {**SCRIPT["scenes"][1], "ref_id": study.id},
            SCRIPT["scenes"][2],
        ],
    }
    db.flush()
    cards_before = _card_count(db, author)

    response = _apply(
        client,
        author,
        episode.id,
        [
            {"kind": "character", "name": "顾沉", "action": "link", "card_id": gu.id},
            {"kind": "scene", "name": "顾家书房", "action": "skip", "headings": [STUDY_DAY]},
        ],
        generate=True,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_credits"] == 0 and body["submitted"] == 0 and dispatched == []
    assert body["script"]["characters"][1]["character_ref_id"] == gu.id
    assert body["script"]["scenes"][1]["ref_id"] == study.id
    assert _card_count(db, author) == cards_before


def test_apply_refuses_up_front_when_the_first_images_do_not_fit(
    client: TestClient,
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[str],
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    cards_before = _card_count(db, author)

    response = _apply(client, author, episode.id, CREATE_ALL, generate=True)

    assert response.status_code == 402
    assert response.json()["error"]["code"] == "INSUFFICIENT_CREDITS"
    assert _card_count(db, author) == cards_before
    assert dispatched == []
    db.refresh(episode)
    assert episode.script_json["characters"][0]["character_ref_id"] is None

    # Without first images nothing is charged, so the same cards go through.
    free = _apply(client, author, episode.id, CREATE_ALL)
    assert free.status_code == 200, free.text
    assert free.json()["total_credits"] == 0
    assert _card_count(db, author) == cards_before + 3


def test_a_co_creator_breaks_down_the_owners_script_into_their_own_cards(
    client: TestClient,
    db: Session,
    author: User,
    remixer: User,
    monkeypatch: pytest.MonkeyPatch,
    dispatched: list[str],
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    _enable(db, remixer)
    owners_card = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    stranger = make_user(db, email="breakdown@example.com", handle="breaker", display_name="路人")
    db.add(
        SeriesCollaborator(
            series_id=episode.series_id,
            user_id=remixer.id,
            invited_by_user_id=author.id,
            status=SeriesCollaboratorStatus.ACTIVE,
        )
    )
    db.flush()

    proposal = client.post(f"/v1/scripts/{episode.id}:breakdown", headers=auth_header(remixer))
    assert proposal.status_code == 200, proposal.text
    # The owner's same-named card is not the co-creator's to link.
    assert proposal.json()["characters"][0]["matches"] == []

    foreign = _apply(
        client,
        remixer,
        episode.id,
        [{"kind": "character", "name": "林夏", "action": "link", "card_id": owners_card.id}],
    )
    assert foreign.status_code == 404

    applied = _apply(client, remixer, episode.id, CREATE_ALL)
    assert applied.status_code == 200, applied.text
    lin_id = next(item["card_id"] for item in applied.json()["items"] if item["name"] == "林夏")
    assert db.get(CreationSkill, lin_id).owner_user_id == remixer.id  # type: ignore[union-attr]
    db.refresh(episode)
    assert episode.script_json["characters"][0]["character_ref_id"] == lin_id

    for path in (":breakdown", ":breakdown-apply"):
        _enable(db, stranger)
        response = client.post(
            f"/v1/scripts/{episode.id}{path}",
            json={"items": [], "dry_run": True},
            headers=auth_header(stranger),
        )
        assert response.status_code == 404


@pytest.mark.parametrize(
    ("items", "field"),
    [
        ([{"kind": "character", "name": "路人甲", "action": "create"}], "items.0.name"),
        ([{"kind": "scene", "name": "便利店", "action": "create"}], "items.0.headings"),
        (
            [{"kind": "scene", "name": "便利店", "action": "create", "headings": ["第九场"]}],
            "items.0.headings",
        ),
        (
            [
                {"kind": "scene", "name": "便利店", "action": "create", "headings": [STORE_NIGHT]},
                {"kind": "scene", "name": "商店", "action": "create", "headings": [STORE_NIGHT]},
            ],
            "items.1.headings",
        ),
        ([{"kind": "prop", "name": "玉佩", "action": "link"}], "items.0.card_id"),
        (
            [
                {"kind": "prop", "name": "玉佩", "action": "create"},
                {"kind": "prop", "name": "玉佩", "action": "skip"},
            ],
            "items.1.name",
        ),
    ],
)
def test_apply_rejects_rows_that_do_not_fit_the_script(
    client: TestClient,
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    items: list[dict[str, Any]],
    field: str,
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    response = _apply(client, author, episode.id, items, dry_run=True)
    assert response.status_code == 422, response.text
    assert field in response.json()["error"]["details"]["fields"]


def test_creating_a_character_whose_name_is_taken_asks_for_a_link(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    episode = _episode(client, db, author, monkeypatch)
    characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    response = _apply(
        client, author, episode.id, [{"kind": "character", "name": "林夏", "action": "create"}]
    )
    assert response.status_code == 422
    assert "items.0.action" in response.json()["error"]["details"]["fields"]
