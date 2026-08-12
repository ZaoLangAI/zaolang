"""Agent pipeline topology and versioned prompts ("Agent Skill", engineering-side).

Distinct from the user-facing skill library (`app/models/skill_library.py`):
a node here is a pipeline stage (safety/planner/quality/copy/...) and a skill
is that stage's prompt, versioned the same way `PlatformConfig` versions
runtime config — append a new version, flip the active flag, keep every
earlier version around for rollback.

Three levels, from coarse to fine:

* `AgentNode` — the *role* (`safety`, `planner`, ...), one row per pipeline
  stage, stable identity that `AgentRun.agent_name` also keys on.
* `AgentProfile` — one *agent*, which has a role. More than one may share a
  role, so one workflow can run a strict video-oriented safety agent while
  another runs a looser one; a workflow node binds whichever it wants by id.
* `AgentSkill` — an append-only prompt version, scoped to a
  `(profile, slot)` pair. A slot exists because one role can own more than
  one system prompt (`intent_router` classifies tiers *and* selects
  providers); see `app/agents/slots.py`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, id_column


class AgentNode(Base):
    """One stage in the agent pipeline.

    `role` is the stable identity both `AgentSkill.node_role` and
    `AgentRun.agent_name` key on — a string, not a foreign key, since roles
    like the four built-in agents are also `AgentName` enum values used
    outside the database.

    Rows are only ever created from `app.domain.agent_skills.presets`, so
    `category` is a copy of the chosen preset's category rather than
    something an operator types. Both `judgment` and `assist` bind one LLM
    model the same way — the split is purely semantic: `assist` marks a role
    that generates/polishes content instead of handing down a pass/fail
    verdict (`copy` is the only one today).
    """

    __tablename__ = "agent_nodes"

    id: Mapped[str] = id_column("anode")
    role: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="judgment", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Display order in the node topology graph, ascending.
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AgentProfile(Base):
    """One agent. `role` is which pipeline stage it is able to run.

    Several agents may share a role, which is how a prompt can differ per
    workflow: a node binds one of them by id, and a node that binds nothing
    gets the role's `is_default` agent.

    `operations_json` is the agent's declared capability: the `Operation`
    values it was written for. An empty list means "general purpose" and
    never warns. The declaration is advisory — publishing a workflow that
    binds an agent outside its declared operations warns but is not
    blocked, because an operator experimenting is a legitimate case and the
    runtime behaviour is identical either way.

    Like `AgentSkill`, `role` is a free string rather than an FK to
    `AgentNode.role`.

    An agent runs an LLM, so it may pin `default_endpoint_id` (plus a
    backup) and its sampling parameters. The binding is optional: an empty
    one keeps the pre-existing behaviour of drawing from the shared
    `kind="general"` pool.
    """

    __tablename__ = "agent_profiles"

    id: Mapped[str] = id_column("aprof")
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    # A stable, operator-chosen handle (`default`, `video-strict`, ...),
    # unique within the role. Graphs bind by `id`, so this is a label for
    # logs and the console rather than a reference; it is still immutable so
    # that audit history keeps lining up with what an operator saw.
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    operations_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    # `llm_providers` endpoint ids. A judgment agent also chooses one model
    # declared by its default and backup endpoints; NULL on a non-default
    # profile means "inherit the role default", then use the compatible pool.
    default_endpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    backup_endpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Model id selected for this agent. It must be declared by every pinned
    # general endpoint, so the provider and model cannot drift independently.
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stored per mille (0-2000) because floats are not used for persisted
    # numbers anywhere in this schema; 200 means temperature 0.2.
    temperature_milli: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_model: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Exactly one per role, enforced in `agent_skills.service` rather than by
    # a partial index so the invariant lives next to the code that can
    # repair it.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("role", "key", name="uq_agent_profiles_role_key"),
        Index("ix_agent_profiles_role_enabled", "role", "enabled"),
        CheckConstraint(
            "temperature_milli IS NULL OR (temperature_milli >= 0 AND temperature_milli <= 2000)",
            name="temperature_milli_range",
        ),
        # A backup with nothing to back up would silently become the primary.
        CheckConstraint(
            "backup_endpoint_id IS NULL OR default_endpoint_id IS NOT NULL",
            name="backup_requires_default",
        ),
    )


class AgentSkill(Base):
    """One append-only prompt version for one `(agent, slot)` pair.

    `node_role` is kept alongside `profile_id` as a denormalised column: it
    is what every reverse lookup ("show me every prompt this role has ever
    run") filters on, and it lets a role's history survive even if the agent
    that ran it is later deleted.
    """

    __tablename__ = "agent_skills"

    id: Mapped[str] = id_column("askill")
    node_role: Mapped[str] = mapped_column(String(40), nullable=False)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("agent_profiles.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String(40), default="default", nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    tool_grants_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "slot", "version", name="uq_agent_skills_profile_slot_version"
        ),
        Index("ix_agent_skills_profile_slot_active", "profile_id", "slot", "is_active"),
        Index("ix_agent_skills_role_active", "node_role", "is_active"),
    )
