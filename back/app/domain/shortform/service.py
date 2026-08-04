"""Short-video specs, pre-publish compliance and distribution intents.

The specs themselves live in the config centre, so nothing here hard-codes a
number that a destination app may change next quarter. What this module owns is
the comparison: an asset and a caption on one side, the selected profile on the
other, reported as one verdict per rule so the UI can show a checklist rather
than a single pass/fail.

Distribution stops at "exported": the platform hands back the file and the
caption, and the creator posts it. `PublicationIntent` still records the attempt
so switching on a direct-publish integration later is a matter of advancing an
existing row rather than inventing history.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.domain.media import service as media_service
from app.models import Asset, Draft, PublicationIntent, Work, WorkVersion
from app.models.enums import (
    LifecycleStatus,
    ModerationStage,
    ModerationStatus,
    PublicationStatus,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import ShortformConfig, ShortformProfile

CheckLevel = Literal["pass", "warn", "block"]

# Any of these in the caption counts as a disclosure that the clip is AI made.
AI_DISCLOSURE_MARKERS = ("aigc", "ai生成", "ai-generated", "ai generated", "#ai", "人工智能")
AI_DISCLOSURE_HASHTAGS = frozenset({"ai", "aigc", "aigenerated", "ai生成"})

# A one-percent deviation is encoder rounding, not the wrong aspect ratio.
ASPECT_TOLERANCE_PERCENT = 1


@dataclass(frozen=True, slots=True)
class ComplianceCheck:
    code: str
    level: CheckLevel
    message: str


@dataclass(slots=True)
class ComplianceReport:
    profile_key: str
    profile: ShortformProfile
    checks: list[ComplianceCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Warnings are advice; a single block is a refusal."""
        return not any(check.level == "block" for check in self.checks)


@dataclass(slots=True)
class PublicationBundle:
    intent: PublicationIntent
    download_url: str | None


def catalog(session: Session) -> ShortformConfig:
    return config_service.get_typed(session, "shortform", ShortformConfig)


def resolve_profile(session: Session, key: str | None) -> tuple[str, ShortformProfile]:
    """Looks a spec up by name, falling back to the configured default."""
    config = catalog(session)
    resolved = key or config.default_profile
    profile = config.profiles.get(resolved)
    if profile is None:
        raise ValidationFailed(
            f"未知的短视频规格: {resolved}",
            fields={"shortform_profile": "规格不存在"},
            available=sorted(config.profiles),
        )
    return resolved, profile


def assert_params_consistent(session: Session, params: Mapping[str, Any]) -> None:
    """Refuses a job whose parameters contradict the spec it claims to follow.

    Without this the studio could submit 16:9 under a vertical profile and the
    mismatch would only surface once the user had already paid for the clip.
    """
    key = params.get("shortform_profile")
    if not key:
        return

    profile_key, profile = resolve_profile(session, str(key))

    aspect_ratio = str(params.get("aspect_ratio") or "未指定")
    if aspect_ratio != profile.aspect_ratio:
        raise ValidationFailed(
            f"{profile_key} 规格要求 {profile.aspect_ratio} 画幅，当前为 {aspect_ratio}。",
            fields={"params.aspect_ratio": f"必须为 {profile.aspect_ratio}"},
        )

    duration = int(params.get("duration_seconds") or 0)
    if not profile.min_duration_seconds <= duration <= profile.max_duration_seconds:
        raise ValidationFailed(
            f"{profile_key} 规格要求时长在 {profile.min_duration_seconds}-"
            f"{profile.max_duration_seconds} 秒之间。",
            fields={
                "params.duration_seconds": (
                    f"必须在 {profile.min_duration_seconds}-{profile.max_duration_seconds} 秒之间"
                )
            },
        )


def check_compliance(
    session: Session,
    *,
    user_id: str,
    draft_id: str | None = None,
    asset_id: str | None = None,
    profile_key: str | None = None,
    title: str = "",
    description: str = "",
    hashtags: Sequence[str] = (),
) -> ComplianceReport:
    """Runs every pre-publish rule and reports each one separately.

    Nothing raises on a failed rule: the caller wants the whole checklist, not
    the first problem, so a creator can fix everything in one pass.
    """
    resolved_key, profile = resolve_profile(session, profile_key)
    subject_type, subject_id, asset = _resolve_subject(
        session, user_id=user_id, draft_id=draft_id, asset_id=asset_id
    )

    report = ComplianceReport(profile_key=resolved_key, profile=profile)
    report.checks.extend(_media_checks(asset, profile))
    report.checks.extend(_caption_checks(profile, title, description, hashtags))
    report.checks.append(
        _safety_check(
            session,
            user_id=user_id,
            subject_type=subject_type,
            subject_id=subject_id,
            text=f"{title}\n{description}\n{' '.join(hashtags)}",
        )
    )
    return report


PROMPT_ENHANCE_MAX_LENGTH = 600  # 与前端 shortform-studio.tsx 的 PROMPT_MAX_LENGTH 对齐


def enhance_prompt(session: Session, *, user_id: str, prompt: str) -> tuple[str, bool]:
    """Hands a scene description to the copy agent and returns the polished text."""
    text = prompt.strip()
    if not text:
        raise ValidationFailed("请先填写画面描述。", fields={"prompt": "不能为空"})

    from app.agents import copywriter

    outcome = copywriter.enhance_prompt(
        session, prompt=text, max_length=PROMPT_ENHANCE_MAX_LENGTH, user_id=user_id
    )
    return str(outcome.data["prompt"]), outcome.degraded


def create_publication_intent(
    session: Session,
    *,
    user_id: str,
    work_id: str,
    channel: str,
    title: str,
    description: str | None,
    hashtags: Sequence[str],
    cover_asset_id: str | None = None,
    scheduled_at: dt.datetime | None = None,
) -> PublicationBundle:
    """Records an export and hands back the material to post with.

    The status reflects what actually happened: `EXPORTED` once a download URL
    exists, `READY` when the work has no deliverable yet. `SUBMITTED` is only
    reachable by a direct-publish integration, which does not exist.
    """
    work, version = _owned_work(session, work_id=work_id, user_id=user_id)

    output_asset_id = version.primary_output_asset_id
    download_url = _download_url(session, asset_id=output_asset_id, user_id=user_id)

    intent = PublicationIntent(
        work_id=work.id,
        user_id=user_id,
        channel=channel,
        status=PublicationStatus.EXPORTED if download_url else PublicationStatus.READY,
        payload_json={
            "title": title,
            "description": description,
            "hashtags": list(hashtags),
            "cover_asset_id": cover_asset_id or version.cover_asset_id,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        },
    )
    session.add(intent)
    session.flush()
    return PublicationBundle(intent=intent, download_url=download_url)


def list_publication_intents(
    session: Session, *, user_id: str, work_id: str, limit: int = 50
) -> list[PublicationIntent]:
    _owned_work(session, work_id=work_id, user_id=user_id)
    return list(
        session.scalars(
            select(PublicationIntent)
            .where(PublicationIntent.work_id == work_id)
            .order_by(PublicationIntent.created_at.desc())
            .limit(limit)
        )
    )


def export_url_for(session: Session, *, work_id: str, user_id: str) -> str | None:
    """Fresh signed URL for a work's deliverable.

    Minted per response rather than stored on the intent: the stored one would
    be expired by the time anyone read the history back.
    """
    work = session.get(Work, work_id)
    if work is None:
        return None
    version = session.get(WorkVersion, work.current_version_id or "")
    if version is None:
        return None
    return _download_url(session, asset_id=version.primary_output_asset_id, user_id=user_id)


# --- internals -----------------------------------------------------------


def _owned_work(session: Session, *, work_id: str, user_id: str) -> tuple[Work, WorkVersion]:
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("只能分发自己的作品。")
    if work.lifecycle_status != LifecycleStatus.ACTIVE:
        raise Conflict("该作品已下架，不能再分发。")

    version = session.get(WorkVersion, work.current_version_id or "")
    if version is None:
        raise Conflict("作品没有可用版本。")
    return work, version


def _download_url(session: Session, *, asset_id: str | None, user_id: str) -> str | None:
    if not asset_id:
        return None
    return media_service.signed_url_for(session, asset_id=asset_id, viewer_user_id=user_id)


def _resolve_subject(
    session: Session, *, user_id: str, draft_id: str | None, asset_id: str | None
) -> tuple[str, str, Asset | None]:
    if draft_id:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise NotFound("草稿不存在。")
        if draft.user_id != user_id:
            raise Forbidden("不能检查他人的草稿。")
        asset = session.get(Asset, draft.output_asset_id) if draft.output_asset_id else None
        return "draft", draft.id, asset

    if asset_id:
        asset = session.get(Asset, asset_id)
        # Same 404 for missing and someone else's: existence is not confirmed.
        if asset is None or asset.owner_user_id != user_id:
            raise NotFound("素材不存在。")
        return "asset", asset.id, asset

    raise ValidationFailed(
        "请提供 draft_id 或 asset_id。", fields={"draft_id": "与 asset_id 至少提供一个"}
    )


def _media_checks(asset: Asset | None, profile: ShortformProfile) -> list[ComplianceCheck]:
    if asset is None:
        # Nothing to measure yet — a warning, because the caption can still be
        # written before the clip finishes generating.
        return [
            ComplianceCheck("ASPECT_RATIO", "warn", "还没有成片，无法校验画幅。"),
            ComplianceCheck("RESOLUTION", "warn", "还没有成片，无法校验分辨率。"),
            ComplianceCheck("DURATION", "warn", "还没有成片，无法校验时长。"),
        ]

    checks: list[ComplianceCheck] = []

    if asset.width and asset.height:
        if _matches_aspect(asset.width, asset.height, profile.aspect_ratio):
            checks.append(
                ComplianceCheck("ASPECT_RATIO", "pass", f"画幅符合 {profile.aspect_ratio}。")
            )
        else:
            checks.append(
                ComplianceCheck(
                    "ASPECT_RATIO",
                    "block",
                    f"画幅需要 {profile.aspect_ratio}，当前为 {asset.width}×{asset.height}。",
                )
            )

        if asset.width >= profile.width and asset.height >= profile.height:
            checks.append(
                ComplianceCheck("RESOLUTION", "pass", f"分辨率 {asset.width}×{asset.height}。")
            )
        else:
            # Lower than recommended still uploads; it just gets recompressed
            # harder, so this is advice rather than a refusal.
            checks.append(
                ComplianceCheck(
                    "RESOLUTION",
                    "warn",
                    f"建议不低于 {profile.width}×{profile.height}，"
                    f"当前为 {asset.width}×{asset.height}。",
                )
            )
    else:
        checks.append(ComplianceCheck("ASPECT_RATIO", "warn", "成片缺少尺寸信息，无法校验画幅。"))
        checks.append(ComplianceCheck("RESOLUTION", "warn", "成片缺少尺寸信息，无法校验分辨率。"))

    checks.append(_duration_check(asset, profile))
    return checks


def _duration_check(asset: Asset, profile: ShortformProfile) -> ComplianceCheck:
    if asset.duration_ms is None:
        return ComplianceCheck("DURATION", "warn", "成片缺少时长信息，无法校验时长。")

    seconds = asset.duration_ms / 1000
    if profile.min_duration_seconds <= seconds <= profile.max_duration_seconds:
        return ComplianceCheck("DURATION", "pass", f"时长 {seconds:.1f} 秒。")
    return ComplianceCheck(
        "DURATION",
        "block",
        f"时长需要在 {profile.min_duration_seconds}-{profile.max_duration_seconds} 秒之间，"
        f"当前为 {seconds:.1f} 秒。",
    )


def _caption_checks(
    profile: ShortformProfile, title: str, description: str, hashtags: Sequence[str]
) -> list[ComplianceCheck]:
    checks: list[ComplianceCheck] = []

    stripped_title = title.strip()
    if not stripped_title:
        checks.append(ComplianceCheck("TITLE_LENGTH", "warn", "还没有填写标题。"))
    elif len(stripped_title) > profile.max_title_length:
        checks.append(
            ComplianceCheck(
                "TITLE_LENGTH",
                "block",
                f"标题不能超过 {profile.max_title_length} 字，当前 {len(stripped_title)} 字。",
            )
        )
    else:
        checks.append(
            ComplianceCheck(
                "TITLE_LENGTH",
                "pass",
                f"标题 {len(stripped_title)}/{profile.max_title_length} 字。",
            )
        )

    if len(hashtags) > profile.max_hashtags:
        checks.append(
            ComplianceCheck(
                "HASHTAG_COUNT",
                "block",
                f"话题不能超过 {profile.max_hashtags} 个，当前 {len(hashtags)} 个。",
            )
        )
    else:
        checks.append(
            ComplianceCheck(
                "HASHTAG_COUNT", "pass", f"话题 {len(hashtags)}/{profile.max_hashtags} 个。"
            )
        )

    checks.append(_disclosure_check(profile, title, description, hashtags))
    return checks


def _disclosure_check(
    profile: ShortformProfile, title: str, description: str, hashtags: Sequence[str]
) -> ComplianceCheck:
    if not profile.require_ai_disclosure:
        return ComplianceCheck("AI_DISCLOSURE", "pass", "该规格不要求 AI 标识。")
    if _has_disclosure(title, description, hashtags):
        return ComplianceCheck("AI_DISCLOSURE", "pass", "文案已包含 AI 标识。")
    return ComplianceCheck(
        "AI_DISCLOSURE", "block", "文案需要包含 AI 生成标识，例如加上 #AIGC 话题。"
    )


def _has_disclosure(title: str, description: str, hashtags: Sequence[str]) -> bool:
    normalised = {tag.strip().lstrip("#").lower() for tag in hashtags}
    if normalised & AI_DISCLOSURE_HASHTAGS:
        return True
    text = f"{title} {description}".lower()
    return any(marker in text for marker in AI_DISCLOSURE_MARKERS)


def _safety_check(
    session: Session, *, user_id: str, subject_type: str, subject_id: str, text: str
) -> ComplianceCheck:
    from app.agents import safety

    verdict = safety.review(
        session,
        text=text,
        stage=ModerationStage.PRE_PUBLISH,
        subject_type=subject_type,
        subject_id=subject_id,
        user_id=user_id,
    )
    if verdict.status == ModerationStatus.REJECTED:
        return ComplianceCheck(
            "CONTENT_SAFETY", "block", verdict.public_message or "文案未通过安全检查。"
        )
    if verdict.status == ModerationStatus.APPROVED:
        return ComplianceCheck("CONTENT_SAFETY", "pass", "文案通过安全检查。")
    return ComplianceCheck("CONTENT_SAFETY", "warn", verdict.public_message or "文案需要人工复核。")


def _matches_aspect(width: int, height: int, ratio: str) -> bool:
    left, _, right = ratio.partition(":")
    try:
        ratio_width, ratio_height = int(left), int(right)
    except ValueError:
        return False
    if ratio_width <= 0 or ratio_height <= 0:
        return False
    # Cross-multiplied so the comparison stays in integers.
    deviation = abs(width * ratio_height - height * ratio_width)
    return deviation * 100 <= height * ratio_width * ASPECT_TOLERANCE_PERCENT
