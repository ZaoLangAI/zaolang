"""Two concurrent opposite edges (A→B, B→A) must not both land — the card
row lock serialises `asset_graph.service.add_edge`'s cycle check."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.asset_graph import service as graph
from app.domain.asset_variants import service as av
from app.domain.characters import service as characters_service
from app.domain.errors import ValidationFailed
from app.models import CreationSkill, SkillAssetEdge
from tests.concurrency.conftest import race, run_in_parallel
from tests.conftest import make_user

SessionFactory = Callable[[], Session]


def test_opposite_edges_cannot_both_land(sessions: SessionFactory) -> None:
    setup = sessions()
    owner = make_user(setup, email="graph@example.com", handle="graph")
    skill_id = characters_service.create_character(
        setup,
        user_id=owner.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    ).id
    skill = setup.get(CreationSkill, skill_id)
    assert skill is not None
    a = av.create_variant(setup, skill, name="甲").id
    b = av.create_variant(setup, skill, name="乙").id
    setup.commit()

    def link(source: str, target: str) -> Callable[[Session], str]:
        def run(session: Session) -> str:
            card = session.get(CreationSkill, skill_id)
            assert card is not None
            return graph.add_edge(
                session,
                card,
                level="variant",
                source_id=source,
                target_id=target,
                relations=["age"],
            ).id

        return run

    outcomes = run_in_parallel([race(link(a, b), sessions), race(link(b, a), sessions)])
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(winners) == 1, outcomes
    assert all(isinstance(o, ValidationFailed | SQLAlchemyError | DBAPIError) for o in losers)

    check = sessions()
    rows = check.scalars(select(SkillAssetEdge).where(SkillAssetEdge.skill_id == skill_id)).all()
    assert len(rows) == 1
