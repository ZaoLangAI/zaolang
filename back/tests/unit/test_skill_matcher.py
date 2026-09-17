"""`app.agents.skill_matcher`: matching a user's story to `drama` skills.

The module's contract is unusually load-bearing for something advisory, so
these tests are organised around its three promises rather than around its
functions: it never blocks the caller, it never charges or counts usage, and
it only ever looks at the seeded 「戏码与情绪」section.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import skill_matcher
from app.domain.errors import ProviderTemporaryFailure
from app.domain.skill_library import service as skill_library_service
from app.models import CreationSkill, User
from app.models.enums import CreationSkillCategory
from tests.llm_catalog import bind_default_agents_to_catalog

_RAIN_FAREWELL = "雨中告别·伞外的那一个"


@pytest.fixture(autouse=True)
def _bind_copy_model(db: Session) -> None:
    bind_default_agents_to_catalog(db)


@pytest.fixture
def seeded(db: Session, author: User) -> None:
    skill_library_service.ensure_catalog_skills(db, owner_user_id=author.id)
    db.commit()


def test_the_shortlist_is_drama_only_and_titles_only(db: Session, seeded: None) -> None:
    """`format` rows outnumber `drama` rows and would be unmatchable — a
    synopsis can point at 「雨中告别」, never at 「一镜一运镜」. Letting them
    into the shortlist would only spend prompt budget and invite a wrong
    pick."""
    candidates = skill_library_service.list_drama_candidates(db)

    assert len(candidates) == 80
    titles = [title for _, title in candidates]
    assert _RAIN_FAREWELL in titles
    assert titles == sorted(titles)

    drama_ids = {
        row.id
        for row in db.scalars(
            select(CreationSkill).where(CreationSkill.category == CreationSkillCategory.DRAMA)
        )
    }
    assert {skill_id for skill_id, _ in candidates} == drama_ids


def test_a_story_matches_the_scenes_it_actually_contains(db: Session, seeded: None) -> None:
    matched = skill_matcher.select_reference_skills(
        db, brief="男主在雨中告别女主，转身走进雨里，女主站在原地"
    )

    assert 1 <= len(matched) <= skill_matcher.MAX_MATCHED_SKILLS
    loaded = skill_library_service.load_reference_skills(db, matched)
    assert _RAIN_FAREWELL in {entry["title"] for entry in loaded}


def test_matching_never_returns_more_than_the_reference_cap(db: Session, seeded: None) -> None:
    """`script_writing.service` only carries five reference entries into the
    drafting prompt, so a sixth pick would be silently dropped downstream."""
    matched = skill_matcher.select_reference_skills(
        db,
        brief="病房床前对峙，雨中告别，婚礼反转，天台谈判，庭审反转，深夜厨房和解，雨夜追逐",
    )
    assert len(matched) <= skill_matcher.MAX_MATCHED_SKILLS


def test_a_story_that_matches_nothing_comes_back_empty(db: Session, seeded: None) -> None:
    """An empty list is a correct answer, not a failure — the callers treat
    it as "carry on with no references", which is also every failure path's
    result."""
    assert skill_matcher.select_reference_skills(db, brief="qqqq zzzz") == []


def test_excluded_ids_never_come_back(db: Session, author: User, seeded: None) -> None:
    """The script path passes the user's own `@` references here so the
    model cannot spend a pick re-choosing one, and the caller never has to
    dedupe two lists afterwards."""
    row = db.scalar(select(CreationSkill).where(CreationSkill.title == _RAIN_FAREWELL))
    assert row is not None

    matched = skill_matcher.select_reference_skills(
        db,
        brief="男主在雨中告别女主，转身走进雨里",
        exclude_ids=(row.id,),
    )
    assert row.id not in matched


def test_an_unreachable_gateway_degrades_to_no_references(
    db: Session, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prompt polish is a live SSE stream. A matcher outage must cost the
    user a polish without references, never a failed polish — so this path
    swallows rather than propagates."""

    def _boom(*args: object, **kwargs: object) -> None:
        raise ProviderTemporaryFailure("gateway down")

    monkeypatch.setattr(skill_matcher, "run_agent", _boom)

    assert skill_matcher.select_reference_skills(db, brief="雨中告别") == []


def test_matching_never_counts_as_usage(db: Session, seeded: None) -> None:
    """`_resolve_referenced_skills` (the user's own `@` picks) charges access
    and bumps `usage_count`. A model choosing on the user's behalf must not,
    or the matcher would rewrite the marketplace's 「热门」ranking one polish
    at a time."""
    before = {
        row.id: row.usage_count
        for row in db.scalars(
            select(CreationSkill).where(CreationSkill.category == CreationSkillCategory.DRAMA)
        )
    }

    matched = skill_matcher.select_reference_skills(db, brief="雨中告别，男主转身走进雨里")
    assert matched
    skill_library_service.load_reference_skills(db, matched)
    db.flush()

    after = {
        row.id: row.usage_count
        for row in db.scalars(
            select(CreationSkill).where(CreationSkill.category == CreationSkillCategory.DRAMA)
        )
    }
    assert after == before


def test_loaded_references_keep_the_requested_order(db: Session, seeded: None) -> None:
    """The order is the model's ranking. `load_reference_skills` issues one
    `IN (...)` query, whose row order is the database's, so it re-sorts."""
    candidates = skill_library_service.list_drama_candidates(db)
    wanted = [skill_id for skill_id, _ in candidates[:3]][::-1]

    loaded = skill_library_service.load_reference_skills(db, wanted)

    assert [entry["id"] for entry in loaded] == wanted
    assert all(entry["title"] and entry["description"] for entry in loaded)


def test_an_unknown_id_is_dropped_rather_than_faked(db: Session, seeded: None) -> None:
    loaded = skill_library_service.load_reference_skills(db, ["does-not-exist"])
    assert loaded == []


def test_an_empty_catalogue_matches_nothing_without_calling_the_model(db: Session) -> None:
    """A fresh database has no `CreationSkill` rows at all. The matcher must
    notice the empty shortlist and skip the call rather than ask a model to
    pick from nothing."""
    assert skill_matcher.select_reference_skills(db, brief="雨中告别") == []
