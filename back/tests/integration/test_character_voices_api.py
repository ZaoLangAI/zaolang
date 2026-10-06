"""P7: `/v1/characters/{id}/voices…` — CRUD and look binding, voice edges in
the graph, `:preview` (quote, submit, landing) and `voices:match`."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agents import router as routing
from app.domain.credits import service as credits_service
from app.domain.jobs import state_machine as sm
from app.models import CharacterVoice, CreationSkill, GenerationJob, User
from app.models.base import new_id
from app.models.enums import CreationSkillStatus, CreationSkillVisibility, JobStatus
from app.workers import tasks
from tests.conftest import auth_header
from tests.fake_provider_catalog import build_fake_catalog

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(tasks, "dispatch_generation", lambda job: sent.append(job.id))
    return sent


@pytest.fixture
def tts_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake catalogue plus a `tts-pro` route, so preset voices exist."""
    catalog = build_fake_catalog()
    base = catalog["fake_paid_api"]
    catalog["fake_tts"] = dataclasses.replace(base, name="fake_tts", model_or_workflow="tts-pro")
    monkeypatch.setattr(routing, "build_catalog", lambda session: catalog)


def _card(client: TestClient, user: User, name: str = "林夏") -> dict:
    response = client.post(
        "/v1/characters",
        json={"name": name, "voice_description": "温柔的年轻女声"},
        headers=auth_header(user),
    )
    assert response.status_code == 201
    return response.json()


def _voice(client: TestClient, user: User, card_id: str, **body) -> dict:
    response = client.post(
        f"/v1/characters/{card_id}/voices",
        json={"name": "日常", "source": "preset", "model": "tts-pro", "voice": "柔美女友", **body},
        headers=auth_header(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_voices_round_trip_with_look_binding(client: TestClient, db: Session, author: User) -> None:
    card = _card(client, author)
    headers = auth_header(author)
    look_id = card["looks"][0]["id"]
    voice = _voice(
        client,
        author,
        card["id"],
        params={"emotion": "happy"},
        attributes={"age_stage": "youth", "use": "dialogue"},
        look_ids=[look_id],
    )
    assert voice["is_default"] is True
    assert voice["look_ids"] == [look_id]
    assert voice["params"] == {"speed": None, "emotion": "happy"}

    listed = client.get(f"/v1/characters/{card['id']}/voices", headers=headers).json()
    assert [v["id"] for v in listed] == [voice["id"]]
    graph = client.get(f"/v1/characters/{card['id']}/graph", headers=headers).json()
    assert graph["voices"][0]["id"] == voice["id"]
    assert graph["variants"][0]["voice_id"] == voice["id"]
    assert graph["caps"]["max_voices"] == 48

    # Unbind from the look's side.
    client.patch(
        f"/v1/characters/{card['id']}/looks/{look_id}", json={"clear_voice": True}, headers=headers
    )
    patched = client.patch(
        f"/v1/characters/{card['id']}/voices/{voice['id']}",
        json={"name": "日常·开心", "params": {"emotion": "angry"}},
        headers=headers,
    ).json()
    assert patched["look_ids"] == []
    assert patched["name"] == "日常·开心" and patched["params"]["emotion"] == "angry"

    assert (
        client.delete(
            f"/v1/characters/{card['id']}/voices/{voice['id']}", headers=headers
        ).status_code
        == 204
    )
    assert client.get(f"/v1/characters/{card['id']}/voices", headers=headers).json() == []


def test_deriving_a_voice_adds_a_voice_edge(client: TestClient, db: Session, author: User) -> None:
    card = _card(client, author)
    base = _voice(client, author, card["id"])
    derived = client.post(
        f"/v1/characters/{card['id']}/voices",
        json={"name": "老年", "derived_from": base["id"], "attributes": {"age_stage": "elderly"}},
        headers=auth_header(author),
    )
    assert derived.status_code == 201, derived.text
    assert derived.json()["voice"] == "柔美女友"
    graph = client.get(f"/v1/characters/{card['id']}/graph", headers=auth_header(author)).json()
    (edge,) = graph["edges"]
    assert (edge["level"], edge["source_id"], edge["relations"]) == ("voice", base["id"], ["age"])


def test_a_preview_prices_submits_and_lands(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    card = _card(client, author)
    voice = _voice(client, author, card["id"], params={"emotion": "fear"})
    url = f"/v1/characters/{card['id']}/voices/{voice['id']}:preview"
    quote = client.post(url, json={}, headers=auth_header(author)).json()
    assert quote["credits"] > 0 and quote["job_id"] is None

    headers = {**auth_header(author), "Idempotency-Key": "preview-1"}
    submitted = client.post(url, json={"text": "别过来！", "dry_run": False}, headers=headers)
    assert submitted.status_code == 200, submitted.text
    job = db.get(GenerationJob, submitted.json()["job_id"])
    assert job is not None and dispatched == [job.id]
    params = job.request_json
    assert params["forced_model"] == "tts-pro"
    assert params["extra"] == {"voice": "柔美女友", "emotion": "fear"}
    assert params["voice_card_id"] == card["id"]

    graph = client.get(f"/v1/characters/{card['id']}/graph", headers=auth_header(author)).json()
    (pending,) = graph["pending"]
    assert pending["mode"] == "voice_preview" and pending["target_voice_id"] == voice["id"]

    again = client.post(url, json={"text": "别过来！", "dry_run": False}, headers=headers).json()
    assert again["job_id"] == job.id and again["replayed"] is True

    # The job finishes: its audio becomes the preview.
    output = new_id("ast")
    from app.models import Asset
    from app.models.enums import MediaType

    db.add(
        Asset(
            id=output,
            owner_user_id=author.id,
            object_key=f"generated/{output}.mp3",
            media_type=MediaType.AUDIO,
            mime_type="audio/mpeg",
            size_bytes=100,
            checksum_sha256="e" * 64,
            role="generation_output",
        )
    )
    db.flush()
    for status in (JobStatus.QUEUED, JobStatus.RUNNING):
        sm.transition(db, job.id, status)
    sm.transition(db, job.id, JobStatus.SUCCEEDED, output_asset_id=output)
    stored = db.get(CharacterVoice, voice["id"])
    db.refresh(stored)
    assert stored.preview_asset_id == output and stored.preview_text == "别过来！"


def test_match_proposes_an_available_preset(
    client: TestClient, db: Session, author: User, tts_catalog: None
) -> None:
    card = _card(client, author)
    body = client.post(
        f"/v1/characters/{card['id']}/voices:match", json={}, headers=auth_header(author)
    )
    assert body.status_code == 200, body.text
    proposal = body.json()
    assert proposal["model"] == "tts-pro"
    assert proposal["voice"] == "柔美女友"
    assert proposal["params"]["speed"] is None
    # Nothing was saved.
    assert (
        client.get(f"/v1/characters/{card['id']}/voices", headers=auth_header(author)).json() == []
    )


def test_voices_are_owner_only(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    card = _card(client, author)
    voice = _voice(client, author, card["id"])
    theirs = auth_header(remixer)
    assert client.get(f"/v1/characters/{card['id']}/voices", headers=theirs).status_code == 404
    mine = _card(client, remixer, name="周岩")
    assert (
        client.patch(
            f"/v1/characters/{mine['id']}/voices/{voice['id']}", json={"name": "x"}, headers=theirs
        ).status_code
        == 404
    )
    # Someone else's voice cannot be used in a job either.
    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "audio_generation",
            "quality_tier": "standard",
            "params": {"prompt": "你好", "voice_profile_id": voice["id"]},
        },
        headers={**theirs, "Idempotency-Key": "steal-1"},
    )
    assert response.status_code == 404


def test_a_dubbing_job_can_name_only_the_character_voice(
    client: TestClient, db: Session, author: User, dispatched: list[str]
) -> None:
    """What the script batch dub sends per line: `voice_profile_id`, no
    `extra.voice` — the server fills in model, voice and knobs."""
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    card = _card(client, author)
    voice = _voice(client, author, card["id"], params={"emotion": "angry"})
    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "audio_generation",
            "quality_tier": "standard",
            "params": {"prompt": "目标确认。", "voice_profile_id": voice["id"], "extra": {}},
        },
        headers={**auth_header(author), "Idempotency-Key": "dub-1"},
    )
    assert response.status_code == 202, response.text
    job = db.get(GenerationJob, response.json()["id"])
    assert job is not None
    assert job.request_json["forced_model"] == "tts-pro"
    assert job.request_json["extra"] == {"voice": "柔美女友", "emotion": "angry"}
    # A plain audio job still needs a voice or a sample.
    bare = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "audio_generation",
            "quality_tier": "standard",
            "params": {"prompt": "目标确认。", "extra": {}},
        },
        headers={**auth_header(author), "Idempotency-Key": "dub-2"},
    )
    assert bare.status_code == 422


def _clone_sample(db: Session, owner: User) -> str:
    from app.domain.consent import service as consent_service
    from app.models import Asset
    from app.models.enums import MediaType

    sample = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp3",
        media_type=MediaType.AUDIO,
        mime_type="audio/mpeg",
        size_bytes=2048,
        checksum_sha256="b" * 64,
        role="voice_sample",
    )
    db.add(sample)
    db.flush()
    consent_service.declare(
        db, user=owner, asset_id=sample.id, consent_type="voice", subject_reference="配音演员甲"
    )
    db.commit()
    return sample.id


def _sell(db: Session, card_id: str) -> CreationSkill:
    skill = db.get(CreationSkill, card_id)
    assert skill is not None
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    skill.access_credits = 8
    db.commit()
    return skill


def _dub(client: TestClient, headers: dict, voice_id: str, key: str):
    return client.post(
        "/v1/generation-jobs",
        json={
            "operation": "audio_generation",
            "quality_tier": "standard",
            "params": {"prompt": "你好", "voice_profile_id": voice_id, "extra": {}},
        },
        headers={**headers, "Idempotency-Key": key},
    )


def test_unlocking_a_character_unlocks_its_voices(
    client: TestClient, db: Session, author: User, remixer: User, dispatched: list[str]
) -> None:
    """A buyer gets the card's voices with its looks: listed on the unlocked
    detail (no clone sample), usable by `voice_profile_id` — a clone's
    sample included — but never manageable: the voice routes, the graph and
    previews (which write onto the voice) stay the owner's."""
    card = _card(client, author)
    preset = _voice(
        client, author, card["id"], look_ids=[card["looks"][0]["id"]], params={"emotion": "happy"}
    )
    sample_id = _clone_sample(db, author)
    clone = _voice(
        client,
        author,
        card["id"],
        name="克隆",
        source="clone",
        model=None,
        voice=None,
        sample_asset_id=sample_id,
    )
    skill = _sell(db, card["id"])
    buyer = auth_header(remixer)
    credits_service.grant(db, remixer.id, 5_000, idempotency_key=new_id("grant"))
    db.commit()

    locked = client.get(f"/v1/skills/{card['id']}", headers=buyer).json()
    assert locked["voices"] == [] and locked["asset_variants"] == []
    assert _dub(client, buyer, preset["id"], "locked-1").status_code == 404

    unlocked = client.post(
        f"/v1/skills/{card['id']}/unlock", headers={**buyer, "Idempotency-Key": new_id("idk")}
    )
    assert unlocked.status_code == 200, unlocked.text
    for response in (
        client.get(f"/v1/skills/{card['id']}", headers=buyer),
        client.post(f"/v1/skills/{card['id']}/apply", headers=buyer),
    ):
        assert response.status_code == 200, response.text
        body = response.json()
        assert [v["id"] for v in body["voices"]] == [preset["id"], clone["id"]]
        assert body["voices"][0]["voice"] == "柔美女友"
        assert all(v["sample"] is None for v in body["voices"])
        assert body["asset_variants"][0]["voice_id"] == preset["id"]

    dubbed = _dub(client, buyer, preset["id"], "dub-preset")
    assert dubbed.status_code == 202, dubbed.text
    job = db.get(GenerationJob, dubbed.json()["id"])
    assert job is not None and job.user_id == remixer.id
    assert job.request_json["forced_model"] == "tts-pro"
    assert job.request_json["extra"] == {"voice": "柔美女友", "emotion": "happy"}

    cloned = _dub(client, buyer, clone["id"], "dub-clone")
    assert cloned.status_code == 202, cloned.text
    clone_job = db.get(GenerationJob, cloned.json()["id"])
    assert clone_job is not None
    assert clone_job.request_json["reference_asset_ids"] == [sample_id]

    # The buyer's jobs never show up as the owner's pending work.
    graph = client.get(f"/v1/characters/{card['id']}/graph", headers=auth_header(author)).json()
    assert graph["pending"] == []

    # Management stays the owner's.
    assert client.get(f"/v1/characters/{card['id']}/voices", headers=buyer).status_code == 404
    assert client.get(f"/v1/characters/{card['id']}/graph", headers=buyer).status_code == 404
    preview = client.post(
        f"/v1/characters/{card['id']}/voices/{preset['id']}:preview",
        json={"dry_run": False},
        headers={**buyer, "Idempotency-Key": "steal-preview"},
    )
    assert preview.status_code == 404
    targeted = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "audio_generation",
            "quality_tier": "standard",
            "params": {"prompt": "你好", "target_voice_id": preset["id"], "extra": {}},
        },
        headers={**buyer, "Idempotency-Key": "steal-target"},
    )
    assert targeted.status_code == 404

    # Withdrawn from sale: the voices go with it.
    skill.status = CreationSkillStatus.DRAFT
    db.commit()
    assert _dub(client, buyer, preset["id"], "withdrawn-1").status_code == 404
    assert _dub(client, buyer, clone["id"], "withdrawn-2").status_code == 404
