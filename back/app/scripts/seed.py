"""Local bootstrap data.

Creates the demo login accounts and the system-level defaults every other
feature depends on to actually run: the agent gateway's built-in nodes and
default agent profiles, one default workflow template per operation, an
optional LLM gateway endpoint bootstrapped from `.env`, the desktop editor's
feature flags, a platform-curated short-drama `CreationSkill` catalogue
(`skill_library_service.ensure_catalog_skills`, see
`app/domain/skill_library/catalog.py`), and a platform-curated `LearnPost`
tutorial catalogue (`learning_service.ensure_catalog_posts`, see
`app/domain/learning/catalog.py`). None of these are seeded anywhere else,
so an empty database cannot submit a generation job, resolve an agent
prompt, or offer anything in the skill marketplace or learning page without
this having run at least once.

Otherwise deliberately does not create business content (works, jobs, tags,
credit packages, moderation items, style gallery entries, and so on) — an
operator adds those by hand through the admin console as they become needed.
The `CreationSkill` and `LearnPost` catalogues are the two exceptions: both
are system-default data owned by a dedicated seed account (`zaolang_studio`),
analogous to the workflow templates and agent profiles above them in this
list, not a stand-in for real user-submitted content.

Idempotent by design — running it twice does not duplicate anything, so it is
safe to re-run against a database that already has this bootstrap data.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agents import copywriter as copywriter_agent
from app.config import get_settings
from app.db import session_scope
from app.domain.agent_skills import service as agent_skills_service
from app.domain.credits import service as credits_service
from app.domain.learning import service as learning_service
from app.domain.skill_library import service as skill_library_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import (
    AccessGrant,
    AgentNode,
    AgentProfile,
    AgentRun,
    AgentSkill,
    Announcement,
    Asset,
    Bookmark,
    Collection,
    CollectionItem,
    ContentFingerprint,
    CreationSkill,
    CreditAccount,
    CreditLedgerEntry,
    CutRevision,
    DataRequest,
    DeliveryVariant,
    Draft,
    DramaEpisode,
    EditorCommandEvent,
    EditorExport,
    EditorLease,
    EditorOperationEvent,
    EditPlan,
    EpisodeContentLink,
    EpisodeCut,
    Follow,
    GenerationJob,
    GenerationWorkflowTemplate,
    JobEvent,
    LearnPost,
    LicenseSnapshot,
    Like,
    LineageEdge,
    McpTokenGrant,
    MediaAnalysis,
    ModerationQueueItem,
    ModerationResult,
    Notification,
    Profile,
    ProviderAttempt,
    ProviderStat,
    PublicationIntent,
    ReportCase,
    SeriesCollaborator,
    StyleGalleryEntry,
    StylePreset,
    SystemLog,
    Tag,
    User,
    Work,
    WorkAppeal,
    WorkEmbedding,
    WorkTag,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    Locale,
    Region,
    ThemePreference,
    UserRole,
    UserStatus,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint
from app.security.passwords import hash_password
from app.storage import s3

logger = logging.getLogger(__name__)

SEED_PASSWORD = "Zaolang2026"


@dataclass(frozen=True, slots=True)
class SeedUser:
    handle: str
    email: str
    display_name: str
    roles: tuple[str, ...]
    bio: str
    region: str = Region.CN
    locale: str = Locale.ZH_CN
    status: str = UserStatus.ACTIVE
    suspended_reason: str | None = None


SEED_USERS: tuple[SeedUser, ...] = (
    SeedUser(
        handle="linhai",
        email="linhai@zaolang.dev",
        display_name="林海",
        roles=(UserRole.USER,),
        bio="做海洋与光的影像。原作者，作品开放二创。",
    ),
    SeedUser(
        handle="mizuki",
        email="mizuki@zaolang.dev",
        display_name="Mizuki",
        roles=(UserRole.USER,),
        bio="二创者。喜欢把静止的画面推成一段情绪。",
        region=Region.JP,
        locale=Locale.JA,
    ),
    SeedUser(
        handle="ava",
        email="ava@zaolang.dev",
        display_name="Ava Lindqvist",
        roles=(UserRole.USER,),
        bio="Third-generation remixer. Cold palettes only.",
        region=Region.GLOBAL,
        locale=Locale.EN,
    ),
    SeedUser(
        handle="reviewer",
        email="reviewer@zaolang.dev",
        display_name="审核员 陈",
        roles=(UserRole.USER, UserRole.REVIEWER),
        bio="内容审核。",
    ),
    SeedUser(
        handle="operator",
        email="operator@zaolang.dev",
        display_name="运营 周",
        roles=(UserRole.USER, UserRole.OPERATOR),
        bio="平台运营。",
    ),
    SeedUser(
        handle="admin",
        email="admin@zaolang.dev",
        display_name="管理员",
        roles=(UserRole.USER, UserRole.ADMIN),
        bio="平台管理员。",
    ),
    # The owner of `ensure_catalog_skills`'s platform-curated short-drama
    # `CreationSkill` catalogue — a plain `UserRole.USER` account (it needs no
    # elevated permission, only to own content), kept separate from `linhai`
    # (a demo author with an unrelated persona) so the marketplace's author
    # attribution reads correctly.
    SeedUser(
        handle="zaolang_studio",
        email="studio@zaolang.dev",
        display_name="造浪工作室",
        roles=(UserRole.USER,),
        bio="平台精选技能策展账号：短剧创作配方合集。",
    ),
    # A suspended account so the console's ban/unban path has something real to
    # act on, and so the login rejection can be checked without banning a demo
    # author everyone else's fixtures depend on.
    SeedUser(
        handle="driftwood",
        email="driftwood@zaolang.dev",
        display_name="Driftwood",
        roles=(UserRole.USER,),
        bio="Suspended for repeated reupload of other people's work.",
        region=Region.GLOBAL,
        locale=Locale.EN,
        status=UserStatus.SUSPENDED,
        suspended_reason="重复搬运他人作品（种子数据）",
    ),
)

# Tables cleared by --reset. Order is irrelevant because they are truncated in a
# single statement (see `_reset`), but the list is kept in dependency order so a
# reader can see the shape of the graph.
RESET_TABLES = (
    AgentSkill,
    AgentNode,
    AgentRun,
    WorkEmbedding,
    ContentFingerprint,
    CollectionItem,
    Collection,
    WorkTag,
    Bookmark,
    Like,
    Follow,
    Notification,
    LearnPost,
    ModerationQueueItem,
    ModerationResult,
    ReportCase,
    WorkAppeal,
    DataRequest,
    StyleGalleryEntry,
    StylePreset,
    JobEvent,
    ProviderAttempt,
    # Not FK-linked to `generation_jobs` (matches `AuditLog.target_id`'s
    # cleanup-must-not-cascade design), so `TRUNCATE ... CASCADE` on that
    # table alone would leave these rows behind across re-seeds.
    SystemLog,
    EditorCommandEvent,
    EditorOperationEvent,
    EditorLease,
    EditPlan,
    EditorExport,
    DeliveryVariant,
    MediaAnalysis,
    CutRevision,
    EpisodeCut,
    EpisodeContentLink,
    SeriesCollaborator,
    DramaEpisode,
    McpTokenGrant,
    GenerationJob,
    GenerationWorkflowTemplate,
    Draft,
    PublicationIntent,
    LineageEdge,
    WorkVersion,
    Work,
    LicenseSnapshot,
    Asset,
    AccessGrant,
    CreationSkill,
    CreditLedgerEntry,
    CreditAccount,
    ProviderStat,
    Announcement,
    Tag,
    Profile,
    User,
)


def run(*, reset: bool = False) -> dict[str, int]:
    """Loads (or reloads) the login accounts and system defaults."""
    settings = get_settings()
    if settings.is_production:
        raise RuntimeError("拒绝在生产环境执行种子脚本。")

    s3.ensure_bucket()
    with session_scope() as session:
        if reset:
            _reset(session)

        users = _seed_users(session)
        agent_skills_service.ensure_default_nodes(session)
        agent_skills_service.ensure_default_profiles(session)
        ensure_default_copy_request_agent(session)
        ensure_default_enhance_asset_agents(session)
        workflow_templates_service.ensure_default_templates(session)
        _seed_llm_providers(session)
        _seed_editor_flags(session)
        catalog_skills = skill_library_service.ensure_catalog_skills(
            session, owner_user_id=users["zaolang_studio"].id
        )
        catalog_posts = learning_service.ensure_catalog_posts(
            session, author_user_id=users["zaolang_studio"].id
        )

        return {
            "users": len(users),
            "skills": len(catalog_skills),
            "learn_posts": len(catalog_posts),
        }


def _reset(session: Session) -> None:
    """Empties the business tables in one statement.

    Ordered per-table deletes cannot work here: `work_versions` and
    `license_snapshots` reference each other, so whichever goes first violates
    the other's constraint. A single `TRUNCATE ... CASCADE` sidesteps the cycle
    and is also far faster than 28 delete statements.
    """
    tables = ", ".join(model.__tablename__ for model in RESET_TABLES)
    session.execute(text(f"TRUNCATE TABLE {tables} CASCADE"))
    # `series` is not in RESET_TABLES, but its episodes/cuts were just
    # truncated, so the leftover shells would reappear on the editor landing
    # as empty ghosts. Every series is `kind=drama` (nothing writes
    # `kind=cast` any more).
    session.execute(text("DELETE FROM series WHERE kind = 'drama'"))
    session.flush()
    logger.info("truncated %d tables", len(RESET_TABLES))


def _seed_users(session: Session) -> dict[str, User]:
    users: dict[str, User] = {}
    password_hash = hash_password(SEED_PASSWORD)

    for spec in SEED_USERS:
        user = session.scalar(select(User).where(User.email == spec.email))
        if user is None:
            user = User(
                email=spec.email,
                password_hash=password_hash,
                status=spec.status,
                suspended_reason=spec.suspended_reason,
                age_gate_confirmed_at=utcnow(),
                region=spec.region,
                locale=spec.locale,
                theme=ThemePreference.SYSTEM,
                roles=list(spec.roles),
            )
            session.add(user)
            session.flush()
            session.add(
                Profile(
                    user_id=user.id,
                    display_name=spec.display_name,
                    handle=spec.handle,
                    bio=spec.bio,
                )
            )
            credits_service.grant(session, user.id, 5_000, idempotency_key=f"seed-grant:{user.id}")
        users[spec.handle] = user

    session.flush()
    return users


def ensure_default_copy_request_agent(session: Session) -> None:
    """Marks the copy role's `is_default` agent as the `copy` request bucket.

    Idempotent: an operator who already pointed the bucket at another
    profile is left alone. Does not create a new agent — 「文案生成 · 默认」
    is the role default `ensure_default_profiles` already planted.

    After the bucket is claimed, factory `suggest` text is synced onto the
    seeded copy agents so a re-run of seed picks up a rewritten
    `copywriter.SYSTEM_PROMPT` without asking an operator to fill-from-template.
    """
    if (
        agent_skills_service.default_profile_for_asset_kind(
            session, "copy", agent_skills_service.COPY_REQUEST_BUCKET
        )
        is None
    ):
        default = agent_skills_service.default_profile(session, "copy")
        if default is not None:
            agent_skills_service.update_profile(
                session, default.id, default_for_asset_kind=agent_skills_service.COPY_REQUEST_BUCKET
            )
    sync_seeded_copy_agent_prompts(session)


_ENHANCE_ASSET_AGENT_SPECS: dict[str, tuple[str, str, str, str]] = {
    "character": (
        "enhance-character",
        "文案润色 · 角色",
        "角色设定图教练：把同一个人写成一张多分区设定图（左三视图、右特写与色板），禁止改回单视角。",
        copywriter_agent.ENHANCE_SYSTEM_PROMPT_CHARACTER,
    ),
    "scene": (
        "enhance-scene",
        "文案润色 · 场景",
        "场景空镜教练：单一机位、遮挡成立、锁年代与媒介，"
        "按空间类型挑技能包润色，并在信息不足时追问作者。",
        copywriter_agent.ENHANCE_SYSTEM_PROMPT_SCENE,
    ),
}


def ensure_default_enhance_asset_agents(session: Session) -> None:
    """Gives "AI 润色" a dedicated `copy` agent per image asset kind.

    Idempotent and additive, mirroring `ensure_default_profiles`: a bucket
    that already has a specific default agent — an operator's own, or one
    this function created on an earlier run — is left untouched. Each
    profile publishes its bucket's specialised system prompt
    (`app.agents.copywriter.ENHANCE_SYSTEM_PROMPT_*`) to the `enhance` slot,
    so `agent_skills_service.resolve_prompt` finds a real published version
    rather than falling back to the code-level constant `enhance_prompt`
    also passes as a default.

    A later rewrite of those constants is synced onto the *seeded* keys
    (`enhance-character` / `enhance-scene`) when the
    active draft still looks like a factory prompt. An operator's own
    wording, or a different profile occupying the bucket, is not clobbered.
    """
    for bucket, spec in _ENHANCE_ASSET_AGENT_SPECS.items():
        key, display_name, description, system_prompt = spec
        if agent_skills_service.default_profile_for_asset_kind(session, "copy", bucket) is not None:
            continue
        if agent_skills_service.find_profile(session, "copy", key) is not None:
            continue
        profile = agent_skills_service.create_profile(
            session,
            role="copy",
            key=key,
            display_name=display_name,
            description=description,
            operations=[],
            default_for_asset_kind=bucket,
        )
        agent_skills_service.publish(
            session,
            profile_id=profile.id,
            slot=copywriter_agent.ENHANCE_SLOT,
            prompt_template=system_prompt,
            tool_grants=[],
            actor_user_id=None,
            reason=f"seed: {bucket} 资产的润色专属智能体",
        )
    sync_seeded_copy_agent_prompts(session)


# First sentences of every factory draft we have shipped for these agents.
# A published prompt that still opens with one of these is treated as
# product-owned and is safe to replace when the module constant moves;
# anything else is an operator edit and is left alone.
_FACTORY_SUGGEST_OPENERS = (
    "你是造浪平台的文案助手。",
    "你是造浪平台的作品发布文案助手。",
)
_FACTORY_SCRIPT_OPENERS = ("你是造浪平台的短剧编剧助手",)
_FACTORY_ENHANCE_OPENERS = {
    "character": (
        "你是造浪平台的提示词教练。",
        "你是造浪平台的角色立绘提示词教练。",
        "你是造浪平台的角色设定图提示词教练。",
    ),
    "scene": (
        "你是造浪平台的提示词教练。",
        "你是造浪平台的场景空镜提示词教练。",
    ),
}
_FACTORY_ENHANCE_DESCRIPTIONS = {
    "角色资产的画面描述润色，额外关注人物一致性与表情神态，并要求全身入镜、纯色背景。",
    "场景资产的画面描述润色，额外关注环境细节与氛围。",
    "场景空镜教练：把空间本身写清楚，画面不得出现任何人物痕迹。",
    "场景空镜教练：把空间写成单一机位的连续空镜，遮挡成立，禁止分割构图与人物痕迹。",
}


def _active_skill(session: Session, profile_id: str, slot: str) -> AgentSkill | None:
    return session.scalar(
        select(AgentSkill).where(
            AgentSkill.profile_id == profile_id,
            AgentSkill.slot == slot,
            AgentSkill.is_active.is_(True),
        )
    )


def _looks_like_factory_prompt(text: str, openers: tuple[str, ...]) -> bool:
    stripped = text.strip()
    return not stripped or stripped.startswith(openers)


def _publish_factory_prompt(
    session: Session,
    *,
    profile: AgentProfile,
    slot: str,
    prompt: str,
    openers: tuple[str, ...],
    reason: str,
) -> None:
    skill = _active_skill(session, profile.id, slot)
    current = skill.prompt_template if skill is not None else ""
    if current == prompt:
        return
    if current and not _looks_like_factory_prompt(current, openers):
        return
    agent_skills_service.publish(
        session,
        profile_id=profile.id,
        slot=slot,
        prompt_template=prompt,
        tool_grants=list(skill.tool_grants_json) if skill is not None else [],
        actor_user_id=None,
        reason=reason,
    )


def sync_seeded_copy_agent_prompts(session: Session) -> None:
    """Publishes the current module constants onto the seeded copy agents.

    Runtime `resolve_prompt` prefers the active `AgentSkill` over the
    code-level fallback, so rewriting `copywriter.SYSTEM_PROMPT` /
    `ENHANCE_SYSTEM_PROMPT_*` / `SCRIPT_*_SYSTEM_PROMPT` is invisible until
    those rows move. This keeps the four product-owned agents (`文案生成 · 默认`
    plus the two 文案润色 keys) on the factory draft — including the
    default copy agent's `script_draft` / `script_revise` slots — without
    touching a custom prompt or a different profile an operator pointed
    the bucket at.
    """
    suggest_targets: list[AgentProfile] = []
    role_default = agent_skills_service.default_profile(session, "copy")
    if role_default is not None:
        suggest_targets.append(role_default)
    copy_bucket = agent_skills_service.default_profile_for_asset_kind(
        session, "copy", agent_skills_service.COPY_REQUEST_BUCKET
    )
    if copy_bucket is not None and (role_default is None or copy_bucket.id != role_default.id):
        suggest_targets.append(copy_bucket)
    for profile in suggest_targets:
        _publish_factory_prompt(
            session,
            profile=profile,
            slot=copywriter_agent.SUGGEST_SLOT,
            prompt=copywriter_agent.SYSTEM_PROMPT,
            openers=_FACTORY_SUGGEST_OPENERS,
            reason="seed: 同步文案生成工厂提示词",
        )
        _publish_factory_prompt(
            session,
            profile=profile,
            slot=copywriter_agent.SCRIPT_DRAFT_SLOT,
            prompt=copywriter_agent.SCRIPT_DRAFT_SYSTEM_PROMPT,
            openers=_FACTORY_SCRIPT_OPENERS,
            reason="seed: 同步剧本创作工厂提示词",
        )
        _publish_factory_prompt(
            session,
            profile=profile,
            slot=copywriter_agent.SCRIPT_REVISE_SLOT,
            prompt=copywriter_agent.SCRIPT_REVISE_SYSTEM_PROMPT,
            openers=_FACTORY_SCRIPT_OPENERS,
            reason="seed: 同步剧本修改工厂提示词",
        )

    for bucket, spec in _ENHANCE_ASSET_AGENT_SPECS.items():
        key, _display_name, description, system_prompt = spec
        asset_profile = agent_skills_service.find_profile(session, "copy", key)
        if asset_profile is None:
            continue
        if (
            asset_profile.description in _FACTORY_ENHANCE_DESCRIPTIONS
            or not asset_profile.description
        ):
            agent_skills_service.update_profile(session, asset_profile.id, description=description)
        _publish_factory_prompt(
            session,
            profile=asset_profile,
            slot=copywriter_agent.ENHANCE_SLOT,
            prompt=system_prompt,
            openers=_FACTORY_ENHANCE_OPENERS[bucket],
            reason=f"seed: 同步{bucket}润色工厂提示词",
        )
    session.flush()


def _seed_llm_providers(session: Session) -> None:
    """Bootstraps one general-purpose gateway endpoint from `.env`, if present.

    The gateway reads endpoints from the database only now (see
    `zaolang-agent-gateway`); `.env`'s `LLM_BASE_URL`/`LLM_API_KEY` are read
    here, once, purely to save a local developer from having to open
    `/admin/models` before anything can call out to a real model. Without
    them the pool stays empty and every call fails immediately until an
    operator configures an endpoint by hand.
    """
    config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    if config.endpoints:
        return

    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    if not base_url or not api_key or not model:
        logger.info(
            "未在环境变量中找到 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL，跳过网关端点引导；"
            "请到后台「/admin/models」手动配置。"
        )
        return

    config.endpoints["seed-general"] = LlmProviderEndpoint(
        name="种子默认网关",
        base_url=base_url,
        api_key=api_key,
        kind="general",
        role="primary",
        model=model,
    )
    config_service.set_value(
        session,
        "llm_providers",
        config.model_dump(mode="json"),
        actor_user_id=None,
        note="seed: 从环境变量引导默认网关端点",
    )
    logger.info("已从环境变量引导默认 LLM 网关端点 seed-general。")


def _seed_editor_flags(session: Session) -> None:
    """Opens the desktop editor on local/demo databases only."""
    from app.platform_config.schemas import FeatureFlags

    current = config_service.get_typed(session, "feature_flags", FeatureFlags)
    if (
        current.drama_studio_enabled
        and current.web_editor_enabled
        and current.variant_export_enabled
        and current.editor_ai_enabled
        and current.editor_mcp_enabled
        and current.script_studio_enabled
        and current.video_analysis_enabled
        and current.canvas_studio_enabled
        and current.blocking_studio_enabled
    ):
        return
    value = current.model_dump(mode="json")
    value.update(
        {
            "drama_studio_enabled": True,
            "web_editor_enabled": True,
            "variant_export_enabled": True,
            "editor_ai_enabled": True,
            "editor_mcp_enabled": True,
            "script_studio_enabled": True,
            "video_analysis_enabled": True,
            "canvas_studio_enabled": True,
            "blocking_studio_enabled": True,
        }
    )
    config_service.set_value(
        session,
        "feature_flags",
        value,
        actor_user_id=None,
        note="seed: 本地打开短剧剪辑、MCP 与无限画布",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="载入造浪本地启动数据")
    parser.add_argument("--reset", action="store_true", help="先清空业务表再载入")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    counts = run(reset=args.reset)
    print(f"种子数据完成: {counts}")
    print(f"所有演示账号密码: {SEED_PASSWORD}")
    if args.reset:
        print(
            "已清空业务表，但 Celery/Redis 队列未动。"
            "请执行 make dev-purge-queues，去掉指向已删除 job 的消息"
            "（不要 FLUSHDB，限流键和 LLM 统计会一起没）。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
