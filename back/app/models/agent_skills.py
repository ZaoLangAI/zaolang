"""Agent pipeline topology and versioned prompts ("Agent Skill", engineering-side).

Distinct from the user-facing skill library (`app/models/skill_library.py`):
a node here is a pipeline stage (safety/planner/quality/copy/...) and a skill
is that stage's prompt, versioned the same way `PlatformConfig` versions
runtime config — append a new version, flip the active flag, keep every
earlier version around for rollback.
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


class AgentSkill(Base):
    """One append-only prompt version for one node.

    No foreign key to `AgentNode.role`: an operator can publish a skill for a
    role before the node row exists (e.g. while wiring up a brand new node),
    the same way `PlatformConfig.key` is a free string rather than an FK.
    """

    __tablename__ = "agent_skills"

    id: Mapped[str] = id_column("askill")
    node_role: Mapped[str] = mapped_column(String(40), nullable=False)
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
        UniqueConstraint("node_role", "version", name="uq_agent_skills_role_version"),
        Index("ix_agent_skills_role_active", "node_role", "is_active"),
    )
