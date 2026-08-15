"""Demo data.

Produces a corpus that exercises every screen: five roles, a three-level remix
chain with a tombstone in the middle, a ledger containing every entry type, a
review queue with real items, tags, presets, notifications and course content.

Idempotent by design — running it twice does not duplicate anything, so it is
safe to re-run against a database that already has demo data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import logging
import os
import random
import sys
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.agents import safety as safety_agent
from app.config import get_settings
from app.db import session_scope
from app.domain.agent_skills import service as agent_skills_service
from app.domain.credits import service as credits_service
from app.domain.lineage import service as lineage_service
from app.domain.search import service as search_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import (
    AccessGrant,
    AgentNode,
    AgentRun,
    AgentSkill,
    Announcement,
    Asset,
    AsyncProviderTask,
    Bookmark,
    Collection,
    CollectionItem,
    ContentFingerprint,
    CreationSkill,
    CreditAccount,
    CreditLedgerEntry,
    CreditPackage,
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
    Series,
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
    AssetRole,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    DataRequestStatus,
    DataRequestType,
    DistributionChannel,
    JobEventType,
    JobStatus,
    LearnPostLevel,
    LearnPostStatus,
    LedgerEntryType,
    LicenseType,
    LifecycleStatus,
    Locale,
    MediaType,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    Operation,
    PublicationStatus,
    QualityTier,
    Region,
    ReportReason,
    ReportStatus,
    SeriesKind,
    SeriesStatus,
    SystemLogLevel,
    SystemLogSource,
    ThemePreference,
    UserRole,
    UserStatus,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint
from app.security.passwords import hash_password
from app.storage import s3

logger = logging.getLogger(__name__)

SEED_PASSWORD = "Zaolang2026"

CARD_LONG_EDGE = 1280
DEFAULT_ASPECT = "16:9"


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

SEED_TAGS: tuple[tuple[str, str, str, str], ...] = (
    ("cinematic", "电影感", "Cinematic", "シネマティック"),
    ("ocean", "海洋", "Ocean", "海"),
    ("night", "夜色", "Night", "夜"),
    ("portrait", "人像", "Portrait", "ポートレート"),
    ("neon", "霓虹", "Neon", "ネオン"),
    ("slow-motion", "慢动作", "Slow motion", "スローモーション"),
    ("monochrome", "单色", "Monochrome", "モノクロ"),
    ("aerial", "航拍", "Aerial", "空撮"),
)

# Curated style-picker catalogue (studio dialog + create page's inspiration
# section share this one table). Fields: slug, 中/英/日 label, description,
# default aspect ratio, prompt suffix injected on apply, style tag slugs.
SEED_STYLE_GALLERY: tuple[
    tuple[str, str, str, str, str, str, str, tuple[str, ...]], ...
] = (
    (
        "anime-japanese",
        "日漫",
        "Japanese anime",
        "日本アニメ",
        "赛璐璐渲染，锐利线条，鲜艳色块。",
        "9:16",
        "japanese anime style, cel shading, crisp linework, vivid flat colors",
        ("anime",),
    ),
    (
        "imperial-china",
        "国产宫廷",
        "Chinese imperial court",
        "中国宮廷風",
        "华服雕梁，工笔重彩，宫廷光影。",
        "16:9",
        "chinese imperial court drama, ornate hanfu, gongbi fine brushwork, palace lighting",
        ("imperial", "chinese"),
    ),
    (
        "suspense-thriller",
        "悬疑",
        "Suspense thriller",
        "サスペンス",
        "高对比冷调，压迫构图，悬念留白。",
        "21:9",
        "suspense thriller mood, high contrast cold tones, oppressive framing, negative space",
        ("suspense",),
    ),
    (
        "cartoon-3d",
        "3D卡通",
        "3D cartoon",
        "3Dカートゥーン",
        "圆润建模，明快色彩，卡通渲染。",
        "16:9",
        "3d cartoon render, rounded stylized modeling, bright saturated colors, pixar-like shading",
        ("3d", "cartoon"),
    ),
    (
        "ancient-3d",
        "3D古风",
        "3D ancient style",
        "3D古風",
        "水墨质感与三维建模结合，飘逸古装。",
        "9:16",
        "3d ancient chinese style, ink-wash texture blended with 3d modeling, flowing hanfu",
        ("3d", "ancient", "chinese"),
    ),
    (
        "wuxia",
        "武侠",
        "Wuxia",
        "武侠",
        "江湖侠客，御风轻功，山水写意。",
        "21:9",
        "wuxia martial arts style, flowing robes, wire-fu wind effects, ink-wash landscape",
        ("wuxia", "chinese"),
    ),
    (
        "cyberpunk",
        "赛博朋克",
        "Cyberpunk",
        "サイバーパンク",
        "霓虹雨夜，高密度招牌，未来都市。",
        "21:9",
        "cyberpunk city, neon rain at night, dense signage, futuristic megacity",
        ("cyberpunk", "neon"),
    ),
    (
        "ink-wash",
        "水墨",
        "Ink wash painting",
        "水墨画",
        "留白写意，浓淡干湿，山水意境。",
        "16:9",
        "chinese ink wash painting style, expressive negative space, varying ink density",
        ("ink-wash", "chinese"),
    ),
    (
        "steampunk",
        "蒸汽朋克",
        "Steampunk",
        "スチームパンク",
        "黄铜齿轮，蒸汽管道，维多利亚质感。",
        "16:9",
        "steampunk style, brass gears, steam pipes, victorian industrial texture",
        ("steampunk",),
    ),
    (
        "fairy-tale",
        "童话",
        "Fairy tale",
        "童話",
        "柔光色调，梦幻插画，温暖童趣。",
        "4:3",
        "fairy tale illustration style, soft pastel lighting, whimsical dreamlike scenery",
        ("fairy-tale",),
    ),
    (
        "horror",
        "恐怖",
        "Horror",
        "ホラー",
        "阴冷色调，扭曲构图，压抑氛围。",
        "16:9",
        "horror atmosphere, desaturated cold tones, unsettling distorted framing",
        ("horror",),
    ),
    (
        "romantic-comedy",
        "爱情喜剧",
        "Romantic comedy",
        "ラブコメ",
        "明亮暖调，轻盈运镜，都市甜宠。",
        "16:9",
        "romantic comedy style, warm bright lighting, light playful camera movement",
        ("romance", "comedy"),
    ),
    (
        "sci-fi",
        "科幻",
        "Science fiction",
        "SF",
        "冷调金属质感，宏大空间站场景。",
        "21:9",
        "science fiction style, cold metallic texture, grand space station scale",
        ("sci-fi",),
    ),
    (
        "retro-hongkong",
        "复古港片",
        "Retro Hong Kong film",
        "レトロ香港映画",
        "80年代港式霓虹，胶片颗粒，湿润街道。",
        "16:9",
        "retro 1980s hong kong film style, neon signage, heavy film grain, wet streets",
        ("retro", "hongkong"),
    ),
    (
        "healing-slice-of-life",
        "治愈系",
        "Healing slice of life",
        "日常系",
        "柔和自然光，恬静日常，暖色滤镜。",
        "4:3",
        "healing slice-of-life style, soft natural light, tranquil everyday scenery, warm tones",
        ("healing",),
    ),
    (
        "war-epic",
        "战争史诗",
        "War epic",
        "戦争叙事詩",
        "烟尘弥漫，宏大战场，冷峻纪实感。",
        "21:9",
        "war epic style, dust and smoke, sweeping battlefield scale, gritty documentary tone",
        ("war", "epic"),
    ),
    (
        "campus-youth",
        "校园青春",
        "Campus youth",
        "学園青春",
        "清新自然光，校园场景，明快色彩。",
        "4:3",
        "campus youth style, fresh natural lighting, school setting, bright clean colors",
        ("campus", "youth"),
    ),
    (
        "urban-workplace",
        "都市职场",
        "Urban workplace",
        "都会オフィス",
        "写实都市，玻璃幕墙，冷调职场质感。",
        "16:9",
        "urban workplace drama style, realistic city office, glass facades, cool corporate tones",
        ("urban", "workplace"),
    ),
    (
        "xianxia",
        "仙侠",
        "Xianxia fantasy",
        "仙侠ファンタジー",
        "云雾缭绕，法术光效，飘逸仙气。",
        "9:16",
        "xianxia fantasy style, misty clouds, glowing spell effects, ethereal flowing robes",
        ("xianxia", "fantasy"),
    ),
    (
        "western",
        "西部片",
        "Western",
        "西部劇",
        "荒漠黄沙，硬光长影，复古胶片。",
        "21:9",
        "classic western film style, arid desert, hard light long shadows, vintage film grade",
        ("western",),
    ),
    (
        "film-noir",
        "黑色电影",
        "Film noir",
        "フィルム・ノワール",
        "高对比黑白，百叶窗光影，压抑悬疑。",
        "16:9",
        "film noir style, high contrast black and white, venetian blind shadows, moody tension",
        ("noir",),
    ),
    (
        "family-drama",
        "温馨家庭",
        "Family drama",
        "ホームドラマ",
        "暖黄光调，家居场景，柔和写实。",
        "4:3",
        "warm family drama style, soft yellow lighting, cozy domestic setting, gentle realism",
        ("family",),
    ),
    (
        "musical",
        "音乐剧",
        "Musical",
        "ミュージカル",
        "舞台聚光，饱和色彩，戏剧化构图。",
        "16:9",
        "musical stage style, dramatic spotlighting, saturated colors, theatrical framing",
        ("musical",),
    ),
    (
        "documentary-realism",
        "纪录片写实",
        "Documentary realism",
        "ドキュメンタリー",
        "自然光，手持质感，未加修饰的真实。",
        "16:9",
        "documentary realism style, natural available light, handheld texture, unpolished truth",
        ("documentary",),
    ),
    (
        "fantasy-epic",
        "奇幻史诗",
        "Fantasy epic",
        "ファンタジー叙事詩",
        "宏大城堡，魔法光效，史诗级构图。",
        "21:9",
        "fantasy epic style, grand castle scale, magical glow effects, sweeping cinematic framing",
        ("fantasy", "epic"),
    ),
    (
        "future-metropolis",
        "未来都市",
        "Future metropolis",
        "未来都市",
        "垂直城市，飞行载具，冷蓝主调。",
        "21:9",
        "future metropolis style, vertical megacity, flying vehicles, cool blue palette",
        ("future", "urban"),
    ),
    (
        "chinese-watercolor",
        "中式水彩",
        "Chinese watercolor",
        "中国水彩画",
        "淡雅晕染，留白通透，江南意境。",
        "3:4",
        "chinese watercolor style, delicate wash bleeding, airy negative space, jiangnan mood",
        ("watercolor", "chinese"),
    ),
    (
        "pop-art",
        "波普艺术",
        "Pop art",
        "ポップアート",
        "高饱和色块，网点印刷质感，强烈轮廓。",
        "4:3",
        "pop art style, high-saturation flat colors, halftone print texture, bold outlines",
        ("pop-art",),
    ),
)

# The discover feed needs enough material for a masonry wall, so the corpus is
# generated from a small combination table instead of being written out by hand:
# 12 subjects × 8 moments gives 96 unique works, which together with the four
# chain works above makes 100. Every field is derived from the index, so a
# re-seed produces byte-identical rows.
INSPIRATION_TOTAL_WORKS = 100
INSPIRATION_GROUP_SIZE = 4

# (中文题材, 英文提示词片段, 标签)
INSPIRATION_SUBJECTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("潮汐", "tidal flats seen from above", ("ocean", "aerial")),
    ("灯塔", "a lone lighthouse on basalt rocks", ("ocean", "cinematic")),
    ("天台", "a rooftop above a sleeping city", ("night", "cinematic")),
    ("巷口", "a narrow alley crowded with signage", ("neon", "night")),
    ("侧脸", "a close portrait turned three quarters away", ("portrait",)),
    ("雨幕", "rain sheeting across an empty crossing", ("night", "slow-motion")),
    ("盐湖", "a salt lake cracked into hexagons", ("aerial", "monochrome")),
    ("雪线", "the snow line halfway up a ridge", ("aerial", "cinematic")),
    ("站台", "a suburban platform after the last train", ("night", "portrait")),
    ("竹林", "wind moving through a bamboo grove", ("slow-motion", "cinematic")),
    ("渔火", "fishing lamps scattered across black water", ("ocean", "night")),
    ("老街", "a shuttered street of tiled shopfronts", ("monochrome", "cinematic")),
)

# (中文时刻, 英文提示词片段, 追加标签)
INSPIRATION_MOMENTS: tuple[tuple[str, str, str | None], ...] = (
    ("黎明", "before dawn, cold blue light", None),
    ("正午", "high noon, hard shadows", None),
    ("黄昏", "golden hour, long shadows", "cinematic"),
    ("夜色", "deep night, only practical lights", "night"),
    ("雾中", "thick fog flattening every plane", "monochrome"),
    ("雨后", "after rain, wet reflections", "neon"),
    ("逆光", "heavy backlight, rim only", "portrait"),
    ("慢速", "extreme slow motion", "slow-motion"),
)

# (中文镜头, 英文提示词片段)
INSPIRATION_LENSES: tuple[tuple[str, str], ...] = (
    ("长焦压缩，保留胶片颗粒", "long lens, film grain"),
    ("广角，边缘轻微畸变", "wide angle, slight distortion"),
    ("微距，极浅景深", "macro, shallow depth of field"),
    ("变形宽银幕，横向光晕", "anamorphic, horizontal flare"),
)

INSPIRATION_ASPECTS: tuple[str, ...] = ("21:9", "16:9", "9:16", "1:1")

CREDIT_PACKAGES: tuple[dict[str, Any], ...] = (
    {
        "slug": "starter",
        "credits": 500,
        "bonus": 0,
        "price": 2900,
        "currency": "CNY",
        "region": Region.CN,
    },
    {
        "slug": "creator",
        "credits": 2000,
        "bonus": 200,
        "price": 9900,
        "currency": "CNY",
        "region": Region.CN,
    },
    {
        "slug": "studio",
        "credits": 6000,
        "bonus": 900,
        "price": 26900,
        "currency": "CNY",
        "region": Region.CN,
    },
    {
        "slug": "starter-global",
        "credits": 500,
        "bonus": 0,
        "price": 499,
        "currency": "USD",
        "region": Region.GLOBAL,
    },
    {
        "slug": "creator-global",
        "credits": 2000,
        "bonus": 200,
        "price": 1699,
        "currency": "USD",
        "region": Region.GLOBAL,
    },
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
    """Loads (or reloads) the demo corpus. Returns per-entity counts."""
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
        _seed_agent_profiles(session)
        workflow_templates_service.ensure_default_templates(session)
        _seed_llm_providers(session)
        _seed_editor_flags(session)
        _seed_editor_demo(session, users)
        _seed_tags(session)
        _seed_packages(session)
        chain = _seed_creative_chain(session, users)
        _seed_marketplace_samples(session, users)
        _seed_inspiration_feed(session, users)
        _seed_community(session, users, chain)
        _seed_learning_posts(session, users)
        _seed_credits(session, users, chain)
        _seed_moderation(session, users, chain)
        _seed_presets(session, users, chain)
        _seed_style_gallery(session, users)
        _seed_announcements(session, users)
        _seed_ops_material(session, users, chain)

        return {
            "users": len(users),
            # The corpus total, not what this run happened to insert: on a
            # re-run both helpers short-circuit and would report zero.
            "works": session.scalar(select(func.count()).select_from(Work)) or 0,
            "tags": len(SEED_TAGS),
            "packages": len(CREDIT_PACKAGES),
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
    # Cast rosters stay (they are not in RESET_TABLES). Drama rows share
    # `series` but their episodes/cuts were just truncated, so the leftover
    # production shells would reappear on the editor landing as empty ghosts.
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


def _seed_agent_profiles(session: Session) -> None:
    """Adds one non-default agent so the agents console has something to show.

    Video generation is the case that actually motivates agents: the same
    safety wording that suits a still image is too permissive once a subject
    starts moving. Declaring the three video operations is what makes the
    console warn if this ever gets bound to an image workflow.
    """
    if agent_skills_service.find_profile(session, "safety", "video-strict") is not None:
        return
    profile = agent_skills_service.create_profile(
        session,
        role="safety",
        key="video-strict",
        display_name="安全审核 · 视频严格版",
        description="视频生成的安全阈值更严：连续动作会放大静态画面里看不出的风险。",
        operations=[
            Operation.TEXT_TO_VIDEO.value,
            Operation.IMAGE_TO_VIDEO.value,
            Operation.VIDEO_TO_VIDEO.value,
        ],
    )
    agent_skills_service.publish(
        session,
        profile_id=profile.id,
        slot="default",
        prompt_template=(
            f"{safety_agent.SYSTEM_PROMPT}\n\n"
            "补充规则（视频）：连续动作会放大单帧看不出的风险，"
            "涉及真实人物、未成年人特征或暴力动作时一律返回 needs_review，不要放行。"
        ),
        tool_grants=[],
        actor_user_id=None,
        reason="seed: 视频工作流的严格安全智能体",
    )


def _catalog_general_model(session: Session) -> str | None:
    """The first model declared on an enabled general endpoint, if any."""
    config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    for endpoint in config.endpoints.values():
        if endpoint.enabled and endpoint.kind == "general" and endpoint.models:
            return endpoint.models[0]
    return None


def _seed_llm_providers(session: Session) -> None:
    """Bootstraps one general-purpose gateway endpoint from `.env`, if present.

    The gateway reads endpoints from the database only now (see
    `zaolang-agent-gateway`); `.env`'s `LLM_BASE_URL`/`LLM_API_KEY` are read
    here, once, purely to save a local developer from having to open
    `/admin/models` before anything can call out to a real model. Without
    them the pool stays empty and every call degrades to the stub until an
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
        models=[model],
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
        }
    )
    config_service.set_value(
        session,
        "feature_flags",
        value,
        actor_user_id=None,
        note="seed: 本地打开短剧剪辑与 MCP",
    )


def _seed_editor_demo(session: Session, users: dict[str, User]) -> None:
    """One local drama project so `/create/drama` is not an empty first-run."""
    owner = users["linhai"]
    existing = session.scalar(
        select(Series).where(Series.owner_user_id == owner.id, Series.kind == SeriesKind.DRAMA)
    )
    if existing is not None:
        return
    session.add(
        Series(
            owner_user_id=owner.id,
            title="本地短剧项目",
            description="种子数据：桌面剪辑入口用的制作项目，不会出现在角色名册里。",
            character_ids_json=[],
            kind=SeriesKind.DRAMA,
            default_locale=Locale.ZH_CN,
            status=SeriesStatus.ACTIVE,
            allow_external_models=False,
        )
    )
    session.flush()


def _seed_tags(session: Session) -> None:
    for slug, zh, en, ja in SEED_TAGS:
        if session.scalar(select(Tag).where(Tag.slug == slug)) is None:
            session.add(Tag(slug=slug, label_zh=zh, label_en=en, label_ja=ja))
    session.flush()


def _seed_packages(session: Session) -> None:
    for index, spec in enumerate(CREDIT_PACKAGES):
        existing = session.scalar(select(CreditPackage).where(CreditPackage.slug == spec["slug"]))
        if existing is not None:
            continue
        session.add(
            CreditPackage(
                slug=str(spec["slug"]),
                credits=int(spec["credits"]),
                bonus_credits=int(spec["bonus"]),
                price_minor=int(spec["price"]),
                currency=str(spec["currency"]),
                region=str(spec["region"]),
                sort_order=index,
                is_active=True,
            )
        )
    session.flush()


def _seed_creative_chain(session: Session, users: dict[str, User]) -> list[Work]:
    """Builds a four-node chain: root → remix → tombstoned remix → deep remix.

    The tombstone in the middle is deliberate: it is the case where the graph
    must still resolve, and no other fixture exercises it.
    """
    if session.scalar(select(Work).limit(1)) is not None:
        # The four chain works are the oldest rows, and every caller downstream
        # indexes into this list by position, so a re-run must hand back the
        # same four in the same order rather than whatever the feed added later.
        return list(
            session.scalars(select(Work).order_by(Work.created_at.asc(), Work.id.asc()).limit(4))
        )

    root = _publish(
        session,
        owner=users["linhai"],
        title="潮汐之上",
        description="海面在黎明前最安静的那三十秒。",
        visibility=Visibility.PUBLIC_REMIXABLE,
        tags=["cinematic", "ocean", "aerial"],
        params={
            "prompt": "aerial shot of a calm ocean before dawn, long lens, film grain",
            "negative_prompt": "text, watermark",
            "seed": 20260101,
            "style_tags": ["cinematic", "ocean"],
            "aspect_ratio": "21:9",
        },
        operation=Operation.TEXT_TO_IMAGE,
        tier=QualityTier.CINEMATIC,
    )

    second = _publish(
        session,
        owner=users["mizuki"],
        title="潮汐之上 · 夜行",
        description="把黎明换成夜色，把安静换成呼吸。",
        visibility=Visibility.PUBLIC_REMIXABLE,
        tags=["cinematic", "night", "ocean"],
        params={
            "prompt": "aerial shot of a night ocean, moonlight, long lens, film grain",
            "seed": 20260214,
            "style_tags": ["cinematic", "night"],
            "aspect_ratio": "21:9",
        },
        operation=Operation.TEXT_TO_IMAGE,
        tier=QualityTier.STANDARD,
        parent=root,
    )

    removed = _publish(
        session,
        owner=users["ava"],
        title="Night Tide (withdrawn)",
        description="A version its author later withdrew.",
        visibility=Visibility.PUBLIC_REMIXABLE,
        tags=["night", "monochrome"],
        params={"prompt": "monochrome night tide, heavy grain", "seed": 7},
        operation=Operation.TEXT_TO_IMAGE,
        tier=QualityTier.PREVIEW,
        parent=second,
    )
    removed.lifecycle_status = LifecycleStatus.TOMBSTONE
    removed.tombstoned_at = utcnow()
    removed.tombstone_reason = "author_withdrew"
    removed.visibility = Visibility.PRIVATE

    deep = _publish(
        session,
        owner=users["ava"],
        title="Night Tide · Neon",
        description="Third-generation remix. The chain still resolves through a tombstone.",
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        tags=["neon", "night", "slow-motion"],
        params={"prompt": "neon night tide, reflections, slow motion", "seed": 991},
        operation=Operation.TEXT_TO_VIDEO,
        tier=QualityTier.STANDARD,
        parent=removed,
    )

    session.flush()
    return [root, second, removed, deep]


def _seed_marketplace_samples(session: Session, users: dict[str, User]) -> None:
    """A paid remixable work and a paid published skill for marketplace tests."""
    existing = session.scalar(select(Work).where(Work.access_credits > 0).limit(1))
    if existing is None:
        _publish(
            session,
            owner=users["linhai"],
            title="潮汐之上 · 付费样例",
            description="用积分解锁后即可二创的样例作品。",
            visibility=Visibility.PUBLIC_REMIXABLE,
            tags=["cinematic", "ocean"],
            params={
                "prompt": "paid remix sample, aerial ocean, film grain",
                "seed": 20260814,
                "style_tags": ["cinematic"],
                "aspect_ratio": "21:9",
            },
            operation=Operation.TEXT_TO_IMAGE,
            tier=QualityTier.STANDARD,
            access_credits=10,
        )

    paid_skill = session.scalar(
        select(CreationSkill).where(CreationSkill.access_credits > 0).limit(1)
    )
    if paid_skill is None:
        session.add(
            CreationSkill(
                owner_user_id=users["linhai"].id,
                title="黄金时刻镜头",
                description="付费解锁后可套用的镜头技能样例。",
                category=CreationSkillCategory.LENS,
                params_json={"prompt_suffix": "golden hour, anamorphic flare"},
                visibility=CreationSkillVisibility.PUBLIC,
                status=CreationSkillStatus.PUBLISHED,
                access_credits=8,
            )
        )
        session.flush()


def _seed_inspiration_feed(session: Session, users: dict[str, User]) -> list[Work]:
    """Fills the discover feed up to `INSPIRATION_TOTAL_WORKS`.

    The works are grouped into small families rather than published flat: within
    each group of four the second and third are real remixes of their parent and
    the fourth branches off the root. That keeps `remix_count` honest — a card
    claiming two remixes has two lineage edges behind it — and gives the lineage
    graph more than one shape to render.
    """
    existing = session.scalar(select(func.count()).select_from(Work)) or 0
    missing = INSPIRATION_TOTAL_WORKS - existing
    if missing <= 0:
        return []

    creators = [users["linhai"], users["mizuki"], users["ava"]]
    works: list[Work] = []
    group_members: list[Work] = []

    for index in range(missing):
        group, slot = divmod(index, INSPIRATION_GROUP_SIZE)
        if slot == 0:
            group_members = []

        subject = INSPIRATION_SUBJECTS[index % len(INSPIRATION_SUBJECTS)]
        moment = INSPIRATION_MOMENTS[index // len(INSPIRATION_SUBJECTS) % len(INSPIRATION_MOMENTS)]
        lens = INSPIRATION_LENSES[index % len(INSPIRATION_LENSES)]
        subject_zh, subject_en, subject_tags = subject
        moment_zh, moment_en, moment_tag = moment
        lens_zh, lens_en = lens

        tags = list(dict.fromkeys(subject_tags + ((moment_tag,) if moment_tag else ())))
        # Slots 0 and 1 are parents inside their group, so they must stay
        # remixable; only the two leaves are allowed to be view-only.
        if slot in (0, 1):
            remixable = True
        elif slot == 2:
            remixable = group % 3 != 0
        else:
            remixable = group % 5 != 0

        parent: Work | None = None
        if slot == 1:
            parent = group_members[0]
        elif slot == 2:
            parent = group_members[1]
        elif slot == 3:
            parent = group_members[0]

        work = _publish(
            session,
            owner=creators[index % len(creators)],
            title=f"{subject_zh} · {moment_zh}",
            description=f"{subject_zh}在{moment_zh}中的一次记录，{lens_zh}。",
            visibility=(Visibility.PUBLIC_REMIXABLE if remixable else Visibility.PUBLIC_VIEW_ONLY),
            tags=tags,
            params={
                "prompt": f"{subject_en}, {moment_en}, {lens_en}",
                "negative_prompt": "text, watermark, extra limbs",
                "seed": 20_260_000 + index,
                "style_tags": tags,
                "aspect_ratio": INSPIRATION_ASPECTS[index % len(INSPIRATION_ASPECTS)],
            },
            operation=Operation.TEXT_TO_IMAGE,
            tier=(QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC)[index % 3],
            parent=parent,
        )

        # Deterministic spread so `sort=popular` and `sort=recent` both order the
        # feed differently instead of collapsing into the insertion order.
        rng = random.Random(index)
        work.like_count = rng.randint(3, 480)
        work.view_count = work.like_count * rng.randint(9, 40)
        work.published_at = utcnow() - dt.timedelta(hours=(missing - index) * 5)

        group_members.append(work)
        works.append(work)

    session.flush()
    logger.info("seeded %d inspiration works", len(works))
    return works


def _publish(
    session: Session,
    *,
    owner: User,
    title: str,
    description: str,
    visibility: str,
    tags: list[str],
    params: dict[str, Any],
    operation: str,
    tier: str,
    parent: Work | None = None,
    access_credits: int = 0,
) -> Work:
    """Creates a published work directly.

    The API publish path is not reused here: seeding must produce a specific
    chain shape, including a tombstoned middle node that the normal flow would
    never create.
    """
    asset = _prototype_asset(
        session, owner=owner, label=title, aspect=str(params.get("aspect_ratio", DEFAULT_ASPECT))
    )
    job = _completed_job(
        session, owner=owner, operation=operation, tier=tier, params=params, asset=asset
    )

    work = Work(
        owner_user_id=owner.id,
        visibility=visibility,
        lifecycle_status=LifecycleStatus.ACTIVE,
        published_at=utcnow(),
        view_count=120 + len(title) * 7,
        like_count=8 + len(title),
        remix_count=0,
        access_credits=access_credits,
    )
    session.add(work)
    session.flush()

    snapshot_id: str | None = None
    if parent is not None:
        parent_version = session.get(WorkVersion, parent.current_version_id or "")
        assert parent_version is not None
        snapshot = LicenseSnapshot(
            license_type=LicenseType.CC_BY_4_0,
            permissions_json={"remix": True, "commercial": False, "share_alike": False},
            attribution_text=f"基于 {parent_version.title} 创作",
            source_work_version_id=parent_version.id,
            captured_at=utcnow(),
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id

    version = WorkVersion(
        work_id=work.id,
        version_number=1,
        title=title,
        description=description,
        cover_asset_id=asset.id,
        primary_output_asset_id=asset.id,
        ai_generated=True,
        generation_job_id=job.id,
        license_snapshot_id=snapshot_id,
        reusable_params_json=params if Visibility(visibility).allows_remix else {},
        immutable_created_at=utcnow(),
    )
    session.add(version)
    session.flush()
    work.current_version_id = version.id

    if parent is not None and snapshot_id:
        parent_version = session.get(WorkVersion, parent.current_version_id or "")
        parent_owner = session.get(User, parent.owner_user_id)
        parent_profile = session.scalar(
            select(Profile).where(Profile.user_id == parent.owner_user_id)
        )
        assert parent_version is not None and parent_owner is not None
        lineage_service.create_edge(
            session,
            parent_version_id=parent_version.id,
            child_version_id=version.id,
            parent_author_snapshot={
                "user_id": parent_owner.id,
                "display_name": parent_profile.display_name if parent_profile else "",
                "handle": parent_profile.handle if parent_profile else "",
            },
            license_snapshot_id=snapshot_id,
            workflow_version_id=None,
            reused_asset_ids=[],
            created_by_user_id=owner.id,
        )
        parent.remix_count += 1

    for slug in tags:
        tag = session.scalar(select(Tag).where(Tag.slug == slug))
        if tag is None:
            continue
        tag.usage_count += 1
        session.add(WorkTag(work_id=work.id, tag_id=tag.id))

    search_service.index_version(session, work=work, version=version)
    session.flush()
    return work


def _card_size(aspect: str) -> tuple[int, int]:
    """Pixel size for an `w:h` ratio, with the long edge fixed.

    A placeholder whose pixels disagree with the aspect ratio the work declares
    is worse than no placeholder: every client that reserves a box from the
    asset's intrinsic size then reserves the wrong one.
    """
    try:
        w_part, h_part = (int(part) for part in aspect.split(":", 1))
    except ValueError:
        w_part, h_part = 16, 9
    if w_part <= 0 or h_part <= 0:
        w_part, h_part = 16, 9

    if w_part >= h_part:
        return CARD_LONG_EDGE, round(CARD_LONG_EDGE * h_part / w_part)
    return round(CARD_LONG_EDGE * w_part / h_part), CARD_LONG_EDGE


def _prototype_asset(
    session: Session,
    *,
    owner: User,
    label: str,
    aspect: str = DEFAULT_ASPECT,
    role: str = AssetRole.GENERATION_OUTPUT,
) -> Asset:
    """Renders and stores a clearly-marked placeholder image."""
    width, height = _card_size(aspect)
    payload = _render_card(label, width, height)
    # A stable digest, not `hash()`: the built-in string hash is salted per
    # process, so the object key would change on every run and the asset pack
    # importer could never match `replaces_prototype` against it.
    digest = hashlib.sha256(label.encode()).hexdigest()[:12]
    object_key = f"seed/{owner.id}/{digest}.png"
    s3.put_object(object_key, payload, content_type="image/png")

    asset = Asset(
        owner_user_id=owner.id,
        object_key=object_key,
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        role=role,
        width=width,
        height=height,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PUBLIC_VIEW_ONLY,
        is_prototype=True,
    )
    session.add(asset)
    session.flush()
    return asset


def _render_card(label: str, width: int, height: int) -> bytes:
    seed = int.from_bytes(hashlib.sha256(label.encode()).digest()[:8], "big")
    top = ((seed >> 16) % 40 + 8, (seed >> 8) % 30 + 12, seed % 70 + 40)
    bottom = ((seed >> 4) % 70 + 30, (seed >> 12) % 50 + 24, (seed >> 20) % 110 + 90)

    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / (height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * blend) for i in range(3)),
        )
    draw.rectangle([(0, height - 48), (width, height)], fill=(0, 0, 0))
    draw.text((24, height - 32), f"PROTOTYPE · {label}", fill=(235, 235, 235))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _completed_job(
    session: Session,
    *,
    owner: User,
    operation: str,
    tier: str,
    params: dict[str, Any],
    asset: Asset,
) -> GenerationJob:
    """A finished job with a full event trail, so the ops console has material."""
    cost = {"preview": 4, "standard": 12, "cinematic": 40}.get(tier, 12)
    job = GenerationJob(
        user_id=owner.id,
        operation=operation,
        request_json=params,
        quality_tier=tier,
        status=JobStatus.SUCCEEDED,
        quoted_credits=cost,
        reserved_credits=cost,
        actual_credits=cost,
        idempotency_key=f"seed:{asset.id}",
        # Seed data must not invent production media providers. Real routing
        # metadata appears only after an endpoint is configured in Models.
        selected_route_summary_json={},
        routing_trace_json=[],
        output_asset_id=asset.id,
        estimated_seconds=25,
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    session.add(job)
    session.flush()

    credits_service.reserve(session, owner.id, cost, job_id=job.id)
    credits_service.capture(session, owner.id, job_id=job.id, actual_amount=cost)

    steps = [
        (JobEventType.QUEUED, JobStatus.CREATED, 2, "任务已创建，正在排队。"),
        (JobEventType.SAFETY, JobStatus.RUNNING, 12, "安全检查通过。"),
        (JobEventType.PLANNING, JobStatus.RUNNING, 25, "已生成执行计划。"),
        (JobEventType.ROUTING, JobStatus.RUNNING, 35, "已选择生成通道。"),
        (JobEventType.GENERATING, JobStatus.RUNNING, 70, "正在生成画面。"),
        (JobEventType.QUALITY_CHECK, JobStatus.RUNNING, 90, "质量检查通过。"),
        (JobEventType.SUCCEEDED, JobStatus.SUCCEEDED, 100, "生成完成。"),
    ]
    for index, (event_type, status, progress, message) in enumerate(steps, start=1):
        session.add(
            JobEvent(
                job_id=job.id,
                sequence=index,
                event_type=event_type,
                status=status,
                progress=progress,
                public_message=message,
                created_at=utcnow(),
            )
        )

    session.flush()
    return job


def _seed_community(session: Session, users: dict[str, User], works: list[Work]) -> None:
    if session.scalar(select(Follow).limit(1)) is not None:
        return

    session.add(Follow(follower_user_id=users["mizuki"].id, followed_user_id=users["linhai"].id))
    session.add(Follow(follower_user_id=users["ava"].id, followed_user_id=users["linhai"].id))
    session.add(Follow(follower_user_id=users["ava"].id, followed_user_id=users["mizuki"].id))

    session.add(Like(user_id=users["mizuki"].id, work_id=works[0].id))
    session.add(Like(user_id=users["ava"].id, work_id=works[0].id))
    session.add(Bookmark(user_id=users["ava"].id, work_id=works[1].id))

    collection = Collection(
        owner_user_id=users["ava"].id,
        name="Cold water references",
        description="Everything I keep coming back to.",
        is_public=True,
    )
    session.add(collection)
    session.flush()
    for position, work in enumerate(works[:2]):
        session.add(CollectionItem(collection_id=collection.id, work_id=work.id, position=position))

    session.add(
        Notification(
            user_id=users["linhai"].id,
            type=NotificationType.WORK_REMIXED,
            title_key="notification.work_remixed",
            payload_json={"work_id": works[1].id},
            target_type="work",
            target_id=works[1].id,
        )
    )
    session.add(
        Notification(
            user_id=users["mizuki"].id,
            type=NotificationType.ROYALTY_RECEIVED,
            title_key="notification.royalty_received",
            payload_json={"amount": 2, "work_id": works[3].id},
            target_type="work",
            target_id=works[3].id,
        )
    )
    session.flush()


def _seed_learning_posts(session: Session, users: dict[str, User]) -> None:
    """给学习内容审核台准备真实数据：pending / approved / rejected 各至少一条。"""
    if session.scalar(select(LearnPost).limit(1)) is not None:
        return

    linhai, mizuki, ava, reviewer = (
        users["linhai"],
        users["mizuki"],
        users["ava"],
        users["reviewer"],
    )

    approved_cover_1 = _prototype_asset(
        session, owner=linhai, label="长焦压缩入门", aspect="16:9", role=AssetRole.LEARN_MEDIA
    )
    approved_cover_2 = _prototype_asset(
        session, owner=mizuki, label="许可与归因入门", aspect="16:9", role=AssetRole.LEARN_MEDIA
    )
    rejected_cover = _prototype_asset(
        session, owner=ava, label="免费素材来源清单", aspect="16:9", role=AssetRole.LEARN_MEDIA
    )

    posts = (
        LearnPost(
            author_user_id=linhai.id,
            title="用长焦压缩拍出电影感海景",
            summary="三步学会用长焦镜头把平淡的海面拍成有纵深的画面。",
            level=LearnPostLevel.BEGINNER,
            cover_asset_id=approved_cover_1.id,
            body_markdown=(
                "## 为什么长焦更有电影感\n\n"
                "长焦压缩透视，让画面显得更有纵深与厚重感。\n\n"
                "配合三分构图与稳定器，手机长焦也能拍出类似效果。"
            ),
            status=LearnPostStatus.APPROVED,
            reviewed_by_user_id=reviewer.id,
            reviewed_at=utcnow() - dt.timedelta(days=2),
            published_at=utcnow() - dt.timedelta(days=2),
        ),
        LearnPost(
            author_user_id=mizuki.id,
            title="二创前必读：许可与归因入门",
            summary="搞懂 CC 许可类型与署名要求，二创才不会踩坑。",
            level=LearnPostLevel.INTERMEDIATE,
            cover_asset_id=approved_cover_2.id,
            body_markdown=(
                "## 四种常见许可类型\n\n"
                "CC BY 到保留所有权利，授权范围逐级收紧。\n\n"
                "二创发布前，平台会把许可快照冻结在这条二创记录里。"
            ),
            status=LearnPostStatus.APPROVED,
            reviewed_by_user_id=reviewer.id,
            reviewed_at=utcnow() - dt.timedelta(days=1),
            published_at=utcnow() - dt.timedelta(days=1),
        ),
        LearnPost(
            author_user_id=ava.id,
            title="构图与光比：新手到进阶的三个练习",
            summary="从三分法到不对称构图，配合光比练习巩固手感。",
            level=LearnPostLevel.INTERMEDIATE,
            cover_asset_id=None,
            body_markdown=("## 先练三分法\n\n把主体放在网格交点上，是最快建立画面平衡感的方法。"),
            status=LearnPostStatus.PENDING,
        ),
        LearnPost(
            author_user_id=linhai.id,
            title="夜景降噪与后期思路",
            summary="高感光度素材如何在后期里兼顾细节与噪点控制。",
            level=LearnPostLevel.ADVANCED,
            cover_asset_id=None,
            body_markdown=(
                "## 降噪的取舍\n\n"
                "降噪越强细节损失越多，暗部局部降噪比全局降噪划算。\n\n"
                "长曝光叠加也能在拍摄阶段降低后期的降噪压力。"
            ),
            status=LearnPostStatus.PENDING,
        ),
        LearnPost(
            author_user_id=ava.id,
            title="免费素材来源清单（未标注授权）",
            summary="汇总了一批素材站链接，但未说明各自的授权条款。",
            level=LearnPostLevel.BEGINNER,
            cover_asset_id=rejected_cover.id,
            body_markdown=("## 素材站清单\n\n列了几个素材站，但未核实每个站点的商用授权条款。"),
            status=LearnPostStatus.REJECTED,
            reject_reason="未标注素材来源的授权条款，存在侵权风险，请补充后重新提交。",
            reviewed_by_user_id=reviewer.id,
            reviewed_at=utcnow() - dt.timedelta(hours=6),
        ),
    )
    session.add_all(posts)
    session.flush()
    logger.info("seeded %d learn posts", len(posts))


def _seed_credits(session: Session, users: dict[str, User], works: list[Work]) -> None:
    """Adds the ledger entry types the generation flow does not produce."""
    if session.scalar(
        select(CreditLedgerEntry).where(CreditLedgerEntry.type == "royalty_in").limit(1)
    ):
        return

    credits_service.purchase(
        session,
        users["mizuki"].id,
        2_200,
        payment_reference="pi_seed_mizuki_0001",
        metadata={"package_slug": "creator"},
    )
    credits_service.royalty_transfer(
        session,
        from_user_id=users["ava"].id,
        to_user_id=users["linhai"].id,
        amount=4,
        work_version_id=str(works[3].current_version_id),
        idempotency_key=f"seed-royalty:{works[3].id}",
    )
    credits_service.adjust(
        session,
        users["ava"].id,
        50,
        reason="首次充值失败补偿（种子数据）",
        actor_user_id=users["operator"].id,
        idempotency_key=f"seed-adjust:{users['ava'].id}",
    )
    session.flush()


def _seed_moderation(session: Session, users: dict[str, User], works: list[Work]) -> None:
    if session.scalar(select(ModerationQueueItem).limit(1)) is not None:
        return

    session.add(
        ModerationQueueItem(
            subject_type="work",
            subject_id=works[3].id,
            stage=ModerationStage.PRE_PUBLISH,
            priority=5,
            status=ModerationStatus.NEEDS_REVIEW,
            reason_code="agent_uncertain",
        )
    )
    session.add(
        ModerationResult(
            stage=ModerationStage.PRE_PUBLISH,
            subject_type="work",
            subject_id=works[3].id,
            status=ModerationStatus.NEEDS_REVIEW,
            categories_json={"violence": 0.12, "sexual": 0.03},
            reason_code="agent_uncertain",
            public_message="内容需要人工复核。",
            decided_by="agent",
            created_at=utcnow(),
        )
    )
    session.add(
        ReportCase(
            reporter_user_id=users["mizuki"].id,
            subject_type="work",
            subject_id=works[3].id,
            reason=ReportReason.COPYRIGHT,
            detail="疑似使用了未授权的原始素材。",
            status=ReportStatus.OPEN,
        )
    )
    session.flush()


def _seed_presets(session: Session, users: dict[str, User], works: list[Work]) -> None:
    if session.scalar(select(StylePreset).limit(1)) is not None:
        return

    root_version_id = works[0].current_version_id
    session.add(
        StylePreset(
            owner_user_id=users["linhai"].id,
            name="黎明长焦",
            description="低饱和、颗粒感、长焦压缩。",
            params_json={
                "prompt_suffix": "long lens, film grain, low saturation",
                "negative_prompt": "text, watermark, oversaturated",
                "aspect_ratio": "21:9",
            },
            derived_from_work_version_id=root_version_id,
            is_public=True,
            apply_count=12,
        )
    )
    session.add(
        StylePreset(
            owner_user_id=users["ava"].id,
            name="Neon night",
            description="Reflections, cyan and magenta only.",
            params_json={
                "prompt_suffix": "neon reflections, cyan and magenta, wet asphalt",
                "aspect_ratio": "16:9",
            },
            is_public=True,
            apply_count=5,
        )
    )
    session.flush()


def _seed_style_gallery(session: Session, users: dict[str, User]) -> None:
    """Populates the curated style catalogue with placeholder covers.

    Covers are the same `_prototype_asset` renderer used for work thumbnails —
    real generated samples replace them later without touching this table's
    shape (see `zaolang-media-assets`). Owner is the admin account since these
    rows have no user-generated provenance to attribute.
    """
    if session.scalar(select(StyleGalleryEntry).limit(1)) is not None:
        return

    owner = users["admin"]
    for index, (
        slug,
        label_zh,
        label_en,
        label_ja,
        description,
        aspect_ratio,
        prompt_suffix,
        style_tags,
    ) in enumerate(SEED_STYLE_GALLERY):
        cover = _prototype_asset(
            session, owner=owner, label=label_en, aspect=aspect_ratio, role=AssetRole.COVER
        )
        session.add(
            StyleGalleryEntry(
                slug=slug,
                label_zh=label_zh,
                label_en=label_en,
                label_ja=label_ja,
                description=description,
                cover_asset_id=cover.id,
                params_json={
                    "aspect_ratio": aspect_ratio,
                    "prompt_suffix": prompt_suffix,
                    "style_tags": list(style_tags),
                },
                sort_order=index,
                apply_count=index * 3,
            )
        )
    session.flush()
    logger.info("seeded %d style gallery entries", len(SEED_STYLE_GALLERY))


def _seed_announcements(session: Session, users: dict[str, User]) -> None:
    if session.scalar(select(Announcement).limit(1)) is not None:
        return
    session.add(
        Announcement(
            kind="notice",
            title_zh="欢迎来到造浪",
            title_en="Welcome to zaolang",
            body_zh="这是一个可以自由二创、并且每一次二创都能追溯到原作者的地方。",
            body_en="Remix freely. Every remix keeps a resolvable path back to its origin.",
            starts_at=utcnow(),
            is_published=True,
            created_by_user_id=users["admin"].id,
        )
    )
    session.flush()


def _seed_ops_material(session: Session, users: dict[str, User], works: list[Work]) -> None:
    """Fixtures that only the operations console reads.

    A healthy corpus makes every ops screen look empty, which is useless for
    verifying them. These rows deliberately reproduce the three states an
    operator is paid to notice: a job wedged in `running`, a failed job whose
    reservation was correctly released, and a reservation that was never settled
    at all.
    """
    if session.scalar(select(Draft).limit(1)) is not None:
        return

    stale = utcnow() - dt.timedelta(hours=6)
    mizuki, ava, operator = users["mizuki"], users["ava"], users["operator"]

    # Wedged in `running`: shows up under stuck jobs and, because nothing ever
    # captured or released it, under dangling reservations too.
    stuck = GenerationJob(
        user_id=mizuki.id,
        operation=Operation.IMAGE_TO_VIDEO,
        request_json={"prompt": "slow push in on wet asphalt", "seed": 4242},
        quality_tier=QualityTier.STANDARD,
        status=JobStatus.RUNNING,
        quoted_credits=12,
        reserved_credits=12,
        idempotency_key="seed:stuck-job",
        estimated_seconds=40,
        started_at=stale,
        created_at=stale,
    )
    session.add(stuck)
    session.flush()
    credits_service.reserve(session, mizuki.id, 12, job_id=stuck.id)
    _backdate_reserve(session, stuck.id, stale)
    for index, (event_type, progress, message) in enumerate(
        [
            (JobEventType.QUEUED, 2, "任务已创建，正在排队。"),
            (JobEventType.SAFETY, 12, "安全检查通过。"),
            (JobEventType.GENERATING, 55, "正在生成画面。"),
        ],
        start=1,
    ):
        session.add(
            JobEvent(
                job_id=stuck.id,
                sequence=index,
                event_type=event_type,
                status=JobStatus.RUNNING if index > 1 else JobStatus.CREATED,
                progress=progress,
                public_message=message,
                created_at=stale,
            )
        )

    # The reason the job is stuck: an `AsyncProviderTask` whose deadline is
    # long past, but nothing has come along to reap it — exactly what the
    # ops console's "stuck" badge and async-task section exist to surface.
    # `capability_name` deliberately follows the real `f"{endpoint_id}:{cap}"`
    # shape even though no such endpoint exists in this seed's `llm_providers`
    # config, so `provider_label` resolution's "not found, show raw value"
    # fallback is what the console actually renders here.
    session.add(
        AsyncProviderTask(
            job_id=stuck.id,
            node_id="provider_generate",
            capability_name="ep_seed_video:image_to_video",
            external_task_id="seed-ext-task-4242",
            request_json={},
            state_checkpoint_json={},
            next_poll_at=stale,
            deadline_at=stale + dt.timedelta(minutes=10),
            poll_count=37,
        )
    )
    session.add(
        SystemLog(
            source=SystemLogSource.PIPELINE.value,
            event="async_task_deadline_exceeded",
            level=SystemLogLevel.WARNING.value,
            message=f"async task for job {stuck.id} exceeded its deadline; still unresolved.",
            dedup_key=f"job:{stuck.id}",
            window_started_at=stale,
            occurrence_count=1,
            job_id=stuck.id,
            details_json={"async_task_id": "seed-ext-task-4242"},
            created_at=stale,
        )
    )

    # Failed and settled: the contrast case, where the reservation went back.
    failed = GenerationJob(
        user_id=ava.id,
        operation=Operation.TEXT_TO_VIDEO,
        request_json={"prompt": "neon rain, handheld", "seed": 88},
        quality_tier=QualityTier.CINEMATIC,
        status=JobStatus.FAILED,
        quoted_credits=40,
        reserved_credits=40,
        idempotency_key="seed:failed-job",
        failure_code="PROVIDER_EXHAUSTED",
        failure_message="两个供应商都失败了。",
        started_at=stale,
        finished_at=stale + dt.timedelta(minutes=2),
        created_at=stale,
    )
    session.add(failed)
    session.flush()
    credits_service.reserve(session, ava.id, 40, job_id=failed.id)
    credits_service.release(session, ava.id, job_id=failed.id, reason="provider_exhausted")
    session.add(
        JobEvent(
            job_id=failed.id,
            sequence=1,
            event_type=JobEventType.FAILED,
            status=JobStatus.FAILED,
            progress=100,
            public_message="生成失败，预扣积分已退回。",
            created_at=stale,
        )
    )
    # Agent runs for the agent-ops screen, including one degraded call so the
    # "how often are we falling back to the stub" panel is not empty.
    catalog_model = _catalog_general_model(session)
    agent_runs = (
        ("safety", catalog_model, 620, 41, 380, False, None),
        ("planner", catalog_model, 1180, 260, 2450, False, None),
        ("quality", catalog_model, 940, 190, 1870, False, None),
        ("copy", catalog_model, 410, 520, 3120, True, "upstream_timeout"),
    )
    for name, model, prompt_tokens, completion_tokens, latency, degraded, reason in agent_runs:
        session.add(
            AgentRun(
                job_id=failed.id if degraded else stuck.id,
                user_id=ava.id if degraded else mizuki.id,
                agent_name=name,
                mode="stub" if degraded else "openai_compatible",
                model=model,
                status="succeeded",
                degraded=degraded,
                degrade_reason=reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                output_json={"seeded": True},
                created_at=stale,
            )
        )

    # An unpublished draft so /publish and the library's drafts tab have content.
    source_version_id = works[1].current_version_id
    session.add(
        Draft(
            user_id=mizuki.id,
            source_work_version_id=source_version_id,
            title="潮汐之上 · 未完成",
            description="还在调节镜头推进的速度。",
            params_json={"prompt": "slow push in on wet asphalt", "seed": 4242},
            latest_job_id=stuck.id,
        )
    )

    # One short-video export so the distribution history on a work is not empty.
    session.add(
        PublicationIntent(
            work_id=works[3].id,
            user_id=ava.id,
            channel=DistributionChannel.MANUAL_DOWNLOAD,
            status=PublicationStatus.EXPORTED,
            payload_json={
                "title": "Night Tide · Neon",
                "description": "第三代二创，霓虹夜潮。",
                "hashtags": ["neon", "night", "aigc"],
                "cover_asset_id": None,
                "scheduled_at": None,
            },
        )
    )

    # A pending export request for the console's data-request approval flow.
    session.add(
        DataRequest(
            user_id=ava.id,
            type=DataRequestType.EXPORT,
            status=DataRequestStatus.PENDING,
            note="Requested a copy of my works and ledger.",
        )
    )
    # And one already handled, so the list is not all pending.
    session.add(
        DataRequest(
            user_id=mizuki.id,
            type=DataRequestType.EXPORT,
            status=DataRequestStatus.COMPLETED,
            note="上次导出请求。",
            result_object_key=f"exports/{mizuki.id}/seed-export.json",
            handled_by_user_id=operator.id,
            handled_at=stale,
        )
    )
    session.flush()


def _backdate_reserve(session: Session, job_id: str, when: dt.datetime) -> None:
    """Ages a reservation so the dangling-reserve report picks it up.

    The report ignores anything younger than a couple of hours, on the grounds
    that a live job is allowed to hold its reservation.
    """
    entry = session.scalar(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.job_id == job_id,
            CreditLedgerEntry.type == LedgerEntryType.RESERVE,
        )
    )
    if entry is not None:
        entry.created_at = when
    session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="载入造浪演示数据")
    parser.add_argument("--reset", action="store_true", help="先清空业务表再载入")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    counts = run(reset=args.reset)
    print(f"种子数据完成: {counts}")
    print(f"所有演示账号密码: {SEED_PASSWORD}")
    if args.reset:
        print(
            "已清空业务表，但 Celery/Redis 队列未动。"
            "请先停 worker，再执行 make dev-purge-queues"
            "（或 redis-cli -p 6380 -n 0 FLUSHDB），然后重启 worker。",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
