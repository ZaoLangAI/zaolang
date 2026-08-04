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
import random
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.domain.credits import service as credits_service
from app.domain.lineage import service as lineage_service
from app.domain.search import service as search_service
from app.models import (
    AgentRun,
    Announcement,
    Asset,
    Bookmark,
    Collection,
    CollectionItem,
    ContentFingerprint,
    CreditAccount,
    CreditLedgerEntry,
    CreditPackage,
    DataRequest,
    Draft,
    Follow,
    GenerationJob,
    JobEvent,
    LicenseSnapshot,
    Like,
    LineageEdge,
    ModerationQueueItem,
    ModerationResult,
    Notification,
    Profile,
    ProviderAttempt,
    ProviderStat,
    PublicationIntent,
    ReportCase,
    StylePreset,
    Tag,
    User,
    Work,
    WorkEmbedding,
    WorkTag,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    AssetRole,
    DataRequestStatus,
    DataRequestType,
    DistributionChannel,
    JobEventType,
    JobStatus,
    LedgerEntryType,
    LicenseType,
    LifecycleStatus,
    Locale,
    MediaType,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    Operation,
    ProviderAttemptStatus,
    PublicationStatus,
    QualityTier,
    Region,
    ReportReason,
    ReportStatus,
    ThemePreference,
    UserRole,
    UserStatus,
    Visibility,
)
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
    ModerationQueueItem,
    ModerationResult,
    ReportCase,
    DataRequest,
    StylePreset,
    JobEvent,
    ProviderAttempt,
    GenerationJob,
    Draft,
    PublicationIntent,
    LineageEdge,
    WorkVersion,
    Work,
    LicenseSnapshot,
    Asset,
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
        _seed_tags(session)
        _seed_packages(session)
        chain = _seed_creative_chain(session, users)
        _seed_inspiration_feed(session, users)
        _seed_community(session, users, chain)
        _seed_credits(session, users, chain)
        _seed_moderation(session, users, chain)
        _seed_presets(session, users, chain)
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
    session: Session, *, owner: User, label: str, aspect: str = DEFAULT_ASPECT
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
        role=AssetRole.GENERATION_OUTPUT,
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
        selected_route_summary_json={
            "provider": "fake_open_workflow",
            "provider_kind": "open_workflow",
            "model_or_workflow": "comfy-sdxl-base@1.4.0",
            "score": 0.82,
            "reason": "综合评分最高",
        },
        routing_trace_json=[
            {
                "provider": "fake_open_workflow",
                "eligible": True,
                "quality_score": 0.8,
                "latency_score": 0.7,
                "cost_score": 0.9,
                "reliability_score": 0.85,
                "total_score": 0.82,
                "effective_cost": 2,
            },
            {
                "provider": "fake_paid_api",
                "eligible": True,
                "quality_score": 0.9,
                "latency_score": 0.4,
                "cost_score": 0.3,
                "reliability_score": 0.9,
                "total_score": 0.66,
                "effective_cost": 18,
            },
        ],
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

    session.add(
        ProviderAttempt(
            job_id=job.id,
            provider="fake_open_workflow",
            provider_kind="open_workflow",
            model_or_workflow_version="comfy-sdxl-base@1.4.0",
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            cost_minor=2,
            latency_ms=1180,
            created_at=utcnow(),
        )
    )
    _bump_provider_stat(session, "fake_open_workflow", operation, tier)
    session.flush()
    return job


def _bump_provider_stat(session: Session, provider: str, operation: str, tier: str) -> None:
    stat = session.scalar(
        select(ProviderStat).where(
            ProviderStat.provider == provider,
            ProviderStat.operation == operation,
            ProviderStat.quality_tier == tier,
        )
    )
    if stat is None:
        # The counters have column defaults, which only apply at INSERT; the
        # in-memory object would still hold None when incremented below.
        stat = ProviderStat(
            provider=provider,
            operation=operation,
            quality_tier=tier,
            attempts=0,
            successes=0,
            total_latency_ms=0,
            total_cost_minor=0,
        )
        session.add(stat)
    stat.attempts += 1
    stat.successes += 1
    stat.total_latency_ms += 1180
    stat.total_cost_minor += 2
    session.flush()


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
    for attempt_number, provider in enumerate(("fake_open_workflow", "fake_paid_api"), start=1):
        session.add(
            ProviderAttempt(
                job_id=failed.id,
                provider=provider,
                provider_kind="open_workflow" if attempt_number == 1 else "paid_api",
                model_or_workflow_version=(
                    "comfy-sdxl-base@1.4.0" if attempt_number == 1 else "paid-video@2026-01"
                ),
                attempt_number=attempt_number,
                status=ProviderAttemptStatus.FAILED,
                failure_code="UPSTREAM_TIMEOUT",
                latency_ms=30_000,
                created_at=stale,
            )
        )

    # Agent runs for the agent-ops screen, including one degraded call so the
    # "how often are we falling back to the stub" panel is not empty.
    agent_runs = (
        ("safety", "doubao-seed-2-1-pro", 620, 41, 380, False, None),
        ("planner", "kimi-k3", 1180, 260, 2450, False, None),
        ("quality", "kimi-k3", 940, 190, 1870, False, None),
        ("copy", "ling-3.0-flash-free", 410, 520, 3120, True, "upstream_timeout"),
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


if __name__ == "__main__":
    main()
