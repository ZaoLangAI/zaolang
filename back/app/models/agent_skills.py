"""Agent pipeline topology and versioned prompts ("Agent Skill", engineering-side).

Distinct from the user-facing skill library (`app/models/skill_library.py`):
a node here is a pipeline stage (safety/planner/quality/copy/...) and a skill
is that stage's prompt, versioned the same way `PlatformConfig` versions
runtime config — append a new version, flip the active flag, keep every
earlier version around for rollback.

Three levels, from coarse to fine:

* `AgentNode` — the *role* (`safety`, `planner`, ...), one row per pipeline
  stage, stable identity that `AgentRun.agent_name` also keys on.
* `AgentProfile` — a named *variant* of a role, so one workflow can run a
  strict video-oriented safety agent while another runs a looser one.
* `AgentSkill` — an append-only prompt version, scoped to a
  `(profile, slot)` pair. A slot exists because one role can own more than
  one system prompt (`intent_router` classifies tiers *and* selects
  providers); see `app/agents/slots.py`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, id_column


class AgentNode(Base):
    """One stage in the agent pipeline.

    `role` is the stable identity both `AgentSkill.node_role` and
    `AgentRun.agent_name` key on — a string, not a foreign key, since roles
    like the four built-in agents are also `AgentName` enum values used
    outside the database.
    """

    __tablename__ = "agent_nodes"

    id: Mapped[str] = id_column("anode")
    role: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Display order in the node topology graph, ascending.
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AgentProfile(Base):
    """A named variant of one role, so a prompt can differ per workflow.

    `operations_json` is the variant's declared capability: the `Operation`
    values it was written for. An empty list means "general purpose" and
    never warns. The declaration is advisory — publishing a workflow that
    binds a variant outside its declared operations warns but is not
    blocked, because an operator experimenting is a legitimate case and the
    runtime behaviour is identical either way.

    Like `AgentSkill`, `role` is a free string rather than an FK to
    `AgentNode.role`.
    """

    __tablename__ = "agent_profiles"

    id: Mapped[str] = id_column("aprof")
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    # Stable, operator-chosen handle a workflow node binds to (`default`,
    # `video-strict`, ...). Renaming a profile's display name is safe;
    # changing this key breaks every graph that references it, so the admin
    # API does not allow it.
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    operations_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    # Exactly one per role, enforced in `agent_skills.service` rather than by
    # a partial index so the invariant lives next to the code that can
    # repair it.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("role", "key", name="uq_agent_profiles_role_key"),
        Index("ix_agent_profiles_role_enabled", "role", "enabled"),
    )


class AgentSkill(Base):
    """One append-only prompt version for one `(profile, slot)` pair.

    `node_role` is kept alongside `profile_id` as a denormalised column: it
    is what every reverse lookup ("show me every prompt this role has ever
    run") filters on, and it lets a role's history survive even if a variant
    is later reorganised.
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
