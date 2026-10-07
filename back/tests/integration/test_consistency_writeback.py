"""P3-3: consistency scoring in the write-back (`asset_output_link`).

The pipeline runs inline on the fake media catalog (which writes real PNGs)
and the fake LLM gateway, whose consistency judge gives every dimension
`fake_llm_gateway.FAKE_CONSISTENCY_SCORE` — monkeypatched per test.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.asset_variants import service as av
from app.domain.characters import fill
from app.domain.characters import service as characters_service
from app.domain.credits import service as credits_service
from app.domain.errors import NoCapableEndpoint
from app.domain.image_assets.consistency import DIMENSION_KEYS_PREFIX
from app.domain.jobs import service as jobs_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.llm import client as llm_client
from app.models import (
    AgentRun,
    Asset,
    CreationSkill,
    GenerationJob,
    JobEvent,
    SkillAssetEntry,
    User,
)
from app.models.base import new_id
from app.models.enums import (
    AssetEntryStatus,
    JobEventType,
    JobStatus,
    MediaType,
    Operation,
    QualityTier,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import DEFAULT_CONFIGS, AssetConsistencyConfig
from app.storage import s3
from app.workers import deadline, pipeline, tasks
from tests import fake_llm_gateway, fake_providers
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 50_000, idempotency_key=new_id("grant"))
    workflow_templates_service.ensure_default_templates(db)
    db.flush()
    return author


def _configure(db: Session, **overrides: Any) -> None:
    value = {**DEFAULT_CONFIGS["asset_consistency"], **overrides}
    config_service.set_value(db, "asset_consistency", value, actor_user_id=None, note="test")


def _png_asset(db: Session, owner: User) -> Asset:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (90, 120, 200)).save(buffer, format="PNG")
    key = f"test/{owner.id}/{new_id('obj')}.png"
    s3.put_object(key, buffer.getvalue(), content_type="image/png")
    asset = Asset(
        owner_user_id=owner.id,
        object_key=key,
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=len(buffer.getvalue()),
        checksum_sha256="e" * 64,
        role="generation_output",
    )
    db.add(asset)
    db.flush()
    return asset


def _character(db: Session, owner: User, *, portrait: bool = True) -> CreationSkill:
    skill = characters_service.create_character(
        db,
        user_id=owner.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).skill
    if portrait:
        entry = av.file_generated(
            db,
            skill,
            av.find_default(skill),  # type: ignore[arg-type]
            asset_id=_png_asset(db, owner).id,
            entry_type="identity_portrait",
        )
        av.claim_anchor(db, skill, entry)
        db.flush()
    return skill


def _submit(db: Session, owner: User, **params: Any) -> GenerationJob:
    return jobs_service.submit(
        db,
        user_id=owner.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "林夏，短发", "aspect_ratio": "1:1", **params},
        idempotency_key=new_id("idk"),
    ).job


def _run(db: Session, job: GenerationJob) -> GenerationJob:
    assert pipeline.run_generation_pipeline(db, job.id).status == JobStatus.SUCCEEDED
    db.refresh(job)
    return job


def _entries(db: Session, job: GenerationJob) -> list[SkillAssetEntry]:
    rows = db.scalars(
        select(SkillAssetEntry)
        .where(SkillAssetEntry.source_job_id == job.id)
        .order_by(SkillAssetEntry.created_at, SkillAssetEntry.sort_order)
    )
    return list(rows)


def _job_view(client: TestClient, owner: User, job: GenerationJob) -> dict[str, Any]:
    response = client.get(f"/v1/generation-jobs/{job.id}", headers=auth_header(owner))
    assert response.status_code == 200, response.text
    return response.json()


def _succeeded_payload(db: Session, job: GenerationJob) -> dict[str, Any]:
    event = db.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job.id, JobEvent.event_type == JobEventType.SUCCEEDED
        )
    )
    assert event is not None
    return dict(event.payload_json or {})


def _judge_calls(db: Session, job: GenerationJob) -> list[AgentRun]:
    return list(
        db.scalars(
            select(AgentRun).where(AgentRun.job_id == job.id, AgentRun.prompt_slot == "consistency")
        )
    )


@pytest.fixture
def low_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fake_llm_gateway, "FAKE_CONSISTENCY_SCORE", 40)


def _consistency_call_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Only the judge's call fails; planning / safety / QC still answer."""
    original = llm_client.complete

    def _complete(**kwargs: Any) -> Any:
        text = "\n".join(
            fake_llm_gateway._message_text(m.get("content")) for m in kwargs["messages"]
        )
        if DIMENSION_KEYS_PREFIX in text:
            raise exc
        return original(**kwargs)

    monkeypatch.setattr(llm_client, "complete", _complete)


# ---- modes -------------------------------------------------------------------


def test_off_scores_nothing(db: Session, funded: User, client: TestClient) -> None:
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    assert entry.consistency_json is None
    assert entry.status == AssetEntryStatus.APPROVED
    assert _judge_calls(db, job) == []
    assert "consistency" not in _succeeded_payload(db, job)
    assert _job_view(client, funded, job)["flagged_entries"] == 0


def test_shadow_scores_and_stores_without_demoting(
    db: Session, funded: User, client: TestClient, low_score: None
) -> None:
    _configure(db, mode="shadow", thresholds={"character": {"*": 70}})
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    verdict = entry.consistency_json
    assert verdict is not None
    assert verdict["status"] == "scored" and verdict["score"] == 40
    assert (verdict["threshold"], verdict["below"], verdict["mode"], verdict["demoted"]) == (
        70,
        True,
        "shadow",
        False,
    )
    anchor = av.anchor(card)
    assert anchor is not None and verdict["anchor_entry_id"] == anchor.id
    assert verdict["v"] == verdict["rubric_version"] == 1
    assert verdict["scored_at"] and verdict["owner_approved_at"] is None
    assert entry.status == AssetEntryStatus.APPROVED
    assert _succeeded_payload(db, job)["consistency"] == {"scored": 1, "flagged": 0}
    view = _job_view(client, funded, job)
    assert (view["flagged_entries"], view["candidate_entries"]) == (0, 0)
    (call,) = _judge_calls(db, job)
    assert call.agent_name == "quality"


def test_enforce_files_a_low_score_into_an_empty_slot_as_a_candidate(
    db: Session, funded: User, client: TestClient, low_score: None
) -> None:
    _configure(db, mode="enforce", thresholds={"character": {"*": 70}})
    card = _character(db, funded)
    portrait = av.anchor(card)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    assert entry.entry_type == "character_sheet"
    assert entry.status == AssetEntryStatus.CANDIDATE
    assert entry.consistency_json and entry.consistency_json["demoted"] is True
    # The anchor stays with the portrait.
    assert av.anchor(card) == portrait
    assert _succeeded_payload(db, job)["consistency"] == {"scored": 1, "flagged": 1}
    view = _job_view(client, funded, job)
    assert (view["flagged_entries"], view["candidate_entries"]) == (1, 1)

    # It counts as "has a candidate", so 补齐缺失 does not regenerate it.
    character = characters_service.get_character(db, user_id=funded.id, character_id=card.id)
    assert fill.gaps(character, av.find_default(card))["front"] == "candidate"

    # Approving it anyway records the owner's call (calibration signal).
    av.approve_entry(db, card, entry)
    assert entry.consistency_json["owner_approved_at"]


def test_enforce_only_marks_a_low_score_when_the_slot_is_already_filled(
    db: Session, funded: User, client: TestClient, low_score: None
) -> None:
    card = _character(db, funded)
    first = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))
    assert _entries(db, first)[0].status == AssetEntryStatus.APPROVED

    _configure(db, mode="enforce", thresholds={"character": {"character_sheet": 70}})
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    assert entry.status == AssetEntryStatus.CANDIDATE
    verdict = entry.consistency_json
    assert verdict and (verdict["below"], verdict["demoted"]) == (True, False)
    assert _job_view(client, funded, job)["flagged_entries"] == 1


def test_a_high_score_is_approved_as_usual(db: Session, funded: User, client: TestClient) -> None:
    _configure(db, mode="enforce", thresholds={"character": {"*": 70}})
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    assert entry.status == AssetEntryStatus.APPROVED
    verdict = entry.consistency_json
    assert verdict and verdict["score"] == fake_llm_gateway.FAKE_CONSISTENCY_SCORE
    assert verdict["below"] is False
    assert _job_view(client, funded, job)["flagged_entries"] == 0


def test_a_kind_without_a_threshold_is_never_below(
    db: Session, funded: User, low_score: None
) -> None:
    _configure(db, mode="enforce", thresholds={"scene": {"*": 90}})
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))
    (entry,) = _entries(db, job)
    assert entry.status == AssetEntryStatus.APPROVED
    assert entry.consistency_json and entry.consistency_json["threshold"] is None
    assert entry.consistency_json["below"] is False


def test_an_unscored_kind_is_left_alone(db: Session, funded: User) -> None:
    _configure(db, mode="enforce", kinds=["scene"])
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))
    assert _entries(db, job)[0].consistency_json is None


# ---- failures never fail the job -----------------------------------------------


def test_no_vision_endpoint_is_a_skip_and_the_write_back_goes_on(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(db, mode="enforce", thresholds={"character": {"*": 70}})
    _consistency_call_raises(monkeypatch, NoCapableEndpoint({"image"}))
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    assert entry.status == AssetEntryStatus.APPROVED
    verdict = entry.consistency_json
    assert verdict and (verdict["status"], verdict["skip_reason"]) == (
        "skipped",
        "no_vision_endpoint",
    )
    assert verdict["below"] is False
    assert _succeeded_payload(db, job)["consistency"] == {"scored": 0, "flagged": 0}


def test_a_failed_judge_call_is_recorded_and_the_write_back_goes_on(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(db, mode="enforce", thresholds={"character": {"*": 70}})
    _consistency_call_raises(monkeypatch, RuntimeError("upstream exploded"))
    card = _character(db, funded)
    job = _run(db, _submit(db, funded, asset_kind="character", target_character_id=card.id))

    (entry,) = _entries(db, job)
    assert entry.status == AssetEntryStatus.APPROVED
    assert entry.consistency_json and entry.consistency_json["status"] == "failed"


# ---- anchors -----------------------------------------------------------------------


def test_an_auto_created_card_has_nothing_to_compare_with(db: Session, funded: User) -> None:
    _configure(db, mode="enforce", thresholds={"character": {"*": 70}})
    job = _run(db, _submit(db, funded, asset_kind="character", subject_name_hint="新面孔"))

    (entry,) = _entries(db, job)
    assert entry.status == AssetEntryStatus.APPROVED
    assert entry.consistency_json and entry.consistency_json["skip_reason"] == "no_anchor"
    assert _judge_calls(db, job) == []


def test_an_anchor_set_by_this_job_is_not_used_for_its_later_outputs(
    db: Session, funded: User
) -> None:
    """A card with no anchor: the front sheet this job files becomes the
    anchor, but the side/back views of the same job are not compared to it."""
    _configure(db, mode="shadow")
    card = _character(db, funded, portrait=False)
    job = _run(
        db,
        _submit(
            db,
            funded,
            asset_kind="character",
            target_character_id=card.id,
            character_views=["front", "side", "back"],
        ),
    )

    entries = _entries(db, job)
    assert len(entries) == 3
    assert av.anchor(card) is not None
    assert {e.consistency_json["skip_reason"] for e in entries if e.consistency_json} == {
        "no_anchor"
    }
    assert _judge_calls(db, job) == []


def test_outputs_past_the_per_job_budget_are_skipped(db: Session, funded: User) -> None:
    _configure(db, mode="shadow", max_outputs_per_job=1)
    card = _character(db, funded)
    job = _run(
        db,
        _submit(
            db,
            funded,
            asset_kind="character",
            target_character_id=card.id,
            character_views=["front", "side", "back"],
        ),
    )

    verdicts = [e.consistency_json for e in _entries(db, job)]
    assert [v["status"] if v else None for v in verdicts].count("scored") == 1
    assert [v["skip_reason"] for v in verdicts if v and v["status"] == "skipped"] == [
        "budget",
        "budget",
    ]
    assert len(_judge_calls(db, job)) == 1


def test_too_little_task_time_left_skips_scoring(db: Session, funded: User) -> None:
    _configure(db, mode="shadow")
    card = _character(db, funded)
    job = _submit(db, funded, asset_kind="character", target_character_id=card.id)
    with deadline.task_deadline(30):
        _run(db, job)

    (entry,) = _entries(db, job)
    assert entry.consistency_json and entry.consistency_json["skip_reason"] == "budget"
    assert entry.status == AssetEntryStatus.APPROVED


# ---- other entry points --------------------------------------------------------------


def test_a_scene_variant_set_scores_each_pass_against_the_master(db: Session, funded: User) -> None:
    from app.domain.scenes import service as scenes_service

    _configure(db, mode="shadow")
    scene = scenes_service.create_scene(
        db, user_id=funded.id, name="客厅", description=None, reference_asset_ids=[]
    )
    master = av.file_generated(
        db,
        scene.skill,
        av.find_default(scene.skill),  # type: ignore[arg-type]
        asset_id=_png_asset(db, funded).id,
        entry_type="master",
    )
    av.claim_anchor(db, scene.skill, master)
    job = _run(
        db,
        _submit(
            db,
            funded,
            asset_kind="scene",
            target_scene_id=scene.id,
            scene_variants=[{"lighting": "dusk"}, {"weather": "rain"}],
        ),
    )

    entries = _entries(db, job)
    assert len(entries) == 2
    assert all(e.consistency_json and e.consistency_json["status"] == "scored" for e in entries)
    prompts = [run.input_json["user_prompt"] for run in _judge_calls(db, job)]
    assert "光照（本次有意改变）" in prompts[0] and "天气" not in prompts[0].split("不比较")[1]
    assert "天气（本次有意改变）" in prompts[1]


def test_a_partial_delivery_scores_what_it_delivered(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def failing_after_one(original):  # type: ignore[no-untyped-def]
        def submit(self, request):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] > 1:
                return fake_providers.GenerationResult(
                    succeeded=False,
                    failure_code="PROVIDER_TEMPORARY_FAILURE",
                    metadata={"provider": self.name, "simulated": True},
                )
            return original(self, request)

        return submit

    for cls in (fake_providers.FakeOpenWorkflowProvider, fake_providers.FakePaidApiProvider):
        monkeypatch.setattr(cls, "submit", failing_after_one(cls.submit))
    _configure(db, mode="shadow")
    card = _character(db, funded)
    job = _run(
        db,
        _submit(
            db,
            funded,
            asset_kind="character",
            target_character_id=card.id,
            character_views=["front", "side", "back"],
        ),
    )

    (entry,) = _entries(db, job)
    assert entry.consistency_json and entry.consistency_json["status"] == "scored"
    payload = _succeeded_payload(db, job)
    assert payload["delivered_outputs"] == 1
    assert payload["consistency"] == {"scored": 1, "flagged": 0}


# ---- time budget ---------------------------------------------------------------------


def _limits_job(**params: Any) -> GenerationJob:
    return GenerationJob(request_json=params)


def test_scoring_adds_time_per_scored_output_under_the_cap() -> None:
    off = AssetConsistencyConfig()
    shadow = AssetConsistencyConfig(mode="shadow")
    single = _limits_job(asset_kind="character")
    assert tasks.image_generation_time_limits(single, off) == tasks.image_generation_time_limits(
        single
    )
    assert tasks.image_generation_time_limits(single, shadow) == {
        "soft_time_limit": 660 + 45,
        "time_limit": 720 + 60,
    }
    # A cover / general image is never scored.
    assert tasks.image_generation_time_limits(
        _limits_job(asset_kind="general"), shadow
    ) == tasks.image_generation_time_limits(_limits_job(asset_kind="general"))
    # A kind outside `kinds` is not either.
    assert tasks.image_generation_time_limits(
        single, AssetConsistencyConfig(mode="shadow", kinds=["scene"])
    ) == tasks.image_generation_time_limits(single)
    # Three views would want 3 × 45 s more, but the cap still holds.
    three = _limits_job(asset_kind="character", character_views=["front", "side", "back"])
    assert tasks.image_generation_time_limits(three, shadow) == {
        "soft_time_limit": 780,
        "time_limit": 960,
    }


def test_the_task_deadline_follows_this_invocations_soft_limit() -> None:
    from types import SimpleNamespace

    override = SimpleNamespace(request=SimpleNamespace(timelimit=(960, 780)), soft_time_limit=660)
    default = SimpleNamespace(request=SimpleNamespace(timelimit=(None, None)), soft_time_limit=660)
    assert tasks._soft_time_limit(override) == 780  # type: ignore[arg-type]
    assert tasks._soft_time_limit(default) == 660  # type: ignore[arg-type]
    assert tasks._soft_time_limit(SimpleNamespace()) is None  # type: ignore[arg-type]

    assert deadline.seconds_left() is None
    with deadline.task_deadline(120):
        left = deadline.seconds_left()
        assert left is not None and 110 < left <= 120
    assert deadline.seconds_left() is None
