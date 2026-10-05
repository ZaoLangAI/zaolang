"""What the script studio knows about a library character.

A script character is linked to a library card by `character_ref_id` (and
optionally a look by `look_id`) inside `DramaEpisode.script_json.characters`
(`script_writing.service.update_links`). This module reads those links
back, so the card's description and voice description can be drafted from
the scripts that actually use it (`app.agents.character_profile`).

Read-only and access-checked the same way script writing is: episodes of a
series the user owns or co-creates (`collaborators`), trashed series
excluded, nothing at all while the script studio flag is off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.editor import collaborators
from app.domain.errors import ValidationFailed
from app.domain.script_writing.service import SCRIPT_STUDIO_FLAG
from app.models import DramaEpisode, Series
from app.models.enums import SeriesKind, SeriesStatus
from app.platform_config import service as config_service

if TYPE_CHECKING:
    from app.agents.character_profile import CharacterProfileDraft

MAX_LINKED_SCRIPTS = 20
MAX_DIALOGUE_LINES = 40
MAX_LINE_LEN = 200


@dataclass(frozen=True, slots=True)
class ScriptLink:
    episode_id: str
    episode_title: str
    series_title: str
    character_name: str
    traits: str
    look_id: str | None
    logline: str
    dialogue_lines: tuple[str, ...]


def _linked_character(script: dict[str, Any], character_id: str) -> dict[str, Any] | None:
    for item in script.get("characters") or []:
        if isinstance(item, dict) and item.get("character_ref_id") == character_id:
            return item
    return None


def dialogue_lines(
    script: dict[str, Any], name: str, *, cap: int = MAX_DIALOGUE_LINES
) -> tuple[str, ...]:
    """`name`'s dialogue in script order, each clipped, at most `cap`."""
    lines: list[str] = []
    for scene in script.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for block in scene.get("blocks") or []:
            if not isinstance(block, dict) or block.get("type") != "dialogue":
                continue
            if str(block.get("character") or "").strip() != name:
                continue
            text = str(block.get("text") or "").strip()
            if text:
                lines.append(text[:MAX_LINE_LEN])
            if len(lines) >= cap:
                return tuple(lines)
    return tuple(lines)


def linked_scripts(
    session: Session, *, user_id: str, character_id: str, limit: int = MAX_LINKED_SCRIPTS
) -> list[ScriptLink]:
    """Scripts (newest first) whose cast links `character_id`."""
    if not config_service.is_enabled(session, SCRIPT_STUDIO_FLAG, user_id=user_id):
        return []
    collab_series_ids = collaborators.collaborator_series_ids(session, user_id=user_id)
    accessible = (
        or_(Series.owner_user_id == user_id, Series.id.in_(collab_series_ids))
        if collab_series_ids
        else Series.owner_user_id == user_id
    )
    rows = session.execute(
        select(DramaEpisode, Series.title)
        .join(Series, Series.id == DramaEpisode.series_id)
        .where(
            accessible,
            Series.kind == SeriesKind.DRAMA,
            Series.status != SeriesStatus.TRASHED,
            # JSONB containment: any cast entry carrying this card's id.
            DramaEpisode.script_json.contains({"characters": [{"character_ref_id": character_id}]}),
        )
        .order_by(DramaEpisode.updated_at.desc())
        .limit(limit)
    ).all()
    links: list[ScriptLink] = []
    for episode, series_title in rows:
        script = episode.script_json or {}
        linked = _linked_character(script, character_id)
        if linked is None:
            continue
        name = str(linked.get("name") or "").strip()
        look_id = linked.get("look_id")
        links.append(
            ScriptLink(
                episode_id=episode.id,
                episode_title=str(script.get("title") or episode.title or ""),
                series_title=str(series_title or ""),
                character_name=name,
                traits=str(linked.get("traits") or "").strip(),
                look_id=str(look_id) if look_id else None,
                logline=str(script.get("logline") or "").strip(),
                dialogue_lines=dialogue_lines(script, name) if name else (),
            )
        )
    return links


def draft_profile(
    session: Session,
    *,
    user_id: str,
    character_id: str,
    episode_id: str | None = None,
    fields: tuple[str, ...] = ("description", "voice_description"),
) -> tuple[CharacterProfileDraft, list[ScriptLink]]:
    """Drafts the card's description / voice description from its linked
    scripts (all of them, newest first, or only `episode_id`). Nothing is
    saved — the author reviews the draft first. 422 when no script links
    the card (or `episode_id` is not one of them)."""
    from app.agents import character_profile  # agents sit above domain

    character = characters_service.get_character(
        session, user_id=user_id, character_id=character_id
    )
    links = linked_scripts(session, user_id=user_id, character_id=character_id)
    if episode_id is not None:
        links = [link for link in links if link.episode_id == episode_id]
    if not links:
        raise ValidationFailed(
            "还没有剧本关联这个角色，先在剧本里把角色关联到角色库。",
            fields={"episode_id": "未关联"},
        )
    draft = character_profile.describe(
        session,
        name=character.name,
        description=character.description,
        voice_description=character.voice_description,
        scripts=[
            character_profile.ScriptExcerpt(
                title=link.episode_title,
                logline=link.logline,
                traits=link.traits,
                lines=link.dialogue_lines,
            )
            for link in links
        ],
        fields=fields,
        user_id=user_id,
    )
    return draft, links
