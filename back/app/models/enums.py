"""Domain enumerations.

These are stored as native strings rather than Postgres enums so that adding a
value never requires a table rewrite. Legal transitions live next to the enum
that governs them.
"""

from __future__ import annotations

from enum import StrEnum


class Visibility(StrEnum):
    """Publication scope. `PUBLIC_VIEW_ONLY` is the mandated default."""

    PUBLIC_REMIXABLE = "public_remixable"
    PUBLIC_VIEW_ONLY = "public_view_only"
    PRIVATE = "private"

    @property
    def allows_remix(self) -> bool:
        return self is Visibility.PUBLIC_REMIXABLE

    @property
    def is_publicly_listed(self) -> bool:
        return self in (Visibility.PUBLIC_REMIXABLE, Visibility.PUBLIC_VIEW_ONLY)


class LifecycleStatus(StrEnum):
    """A work is never hard-deleted; descendants must stay resolvable."""

    ACTIVE = "active"
    HIDDEN = "hidden"
    TOMBSTONE = "tombstone"


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class UserRole(StrEnum):
    """Consumer role plus the four back-office levels."""

    USER = "user"
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    OPERATOR = "operator"
    ADMIN = "admin"


ADMIN_ROLES: frozenset[str] = frozenset(
    {UserRole.VIEWER, UserRole.REVIEWER, UserRole.OPERATOR, UserRole.ADMIN}
)

# Higher rank implies every capability of the ranks below it.
ADMIN_ROLE_RANK: dict[str, int] = {
    UserRole.VIEWER: 1,
    UserRole.REVIEWER: 2,
    UserRole.OPERATOR: 3,
    UserRole.ADMIN: 4,
}


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class AssetRole(StrEnum):
    ORIGINAL = "original"
    PROXY_PREVIEW = "proxy_preview"
    COVER = "cover"
    SUBTITLE = "subtitle"
    GENERATION_OUTPUT = "generation_output"
    GENERATION_REFERENCE = "generation_reference"
    AVATAR = "avatar"
    PROFILE_COVER = "profile_cover"
    CONSENT_EVIDENCE = "consent_evidence"
    # 封面与正文插图共用这一个角色，两者靠是否被 cover_asset_id 引用区分。
    LEARN_MEDIA = "learn_media"


class ModerationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class ModerationStage(StrEnum):
    PRE_GENERATION = "pre_generation"
    POST_GENERATION = "post_generation"
    PRE_PUBLISH = "pre_publish"
    SKILL_REVIEW = "skill_review"


class ConsentType(StrEnum):
    PORTRAIT = "portrait"
    VOICE = "voice"
    TRADEMARK = "trademark"
    THIRD_PARTY_RIGHTS = "third_party_rights"


class ConsentStatus(StrEnum):
    DECLARED = "declared"
    VERIFIED = "verified"
    REVOKED = "revoked"
    EXPIRED = "expired"


class Operation(StrEnum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    AUDIO_GENERATION = "audio_generation"


class QualityTier(StrEnum):
    PREVIEW = "preview"
    STANDARD = "standard"
    CINEMATIC = "cinematic"


class JobStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_JOB_STATUSES


TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}
)

# Terminal statuses have no outgoing edges: a settled job can never go back to running.
JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    # A job that was accepted but never picked up still has to expire, otherwise
    # a broker outage would strand its reservation forever.
    JobStatus.CREATED: frozenset(
        {JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}
    ),
    JobStatus.QUEUED: frozenset(
        {
            JobStatus.SUBMITTED,
            JobStatus.RUNNING,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        }
    ),
    JobStatus.SUBMITTED: frozenset(
        {
            JobStatus.RUNNING,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        }
    ),
    JobStatus.RUNNING: frozenset(
        {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.EXPIRED: frozenset(),
}

# Cancelling after submission is a *request*: the provider may still finish and
# bill us, so settlement follows the provider's actual result.
CANCELLABLE_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.CREATED, JobStatus.QUEUED, JobStatus.SUBMITTED, JobStatus.RUNNING}
)


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in JOB_TRANSITIONS[current]


class JobEventType(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    SAFETY = "safety"
    INTENT_ROUTING = "intent_routing"
    ROUTING = "routing"
    GENERATING = "generating"
    AUDIO = "audio"
    QUALITY_CHECK = "quality_check"
    PROGRESS = "progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderAttemptStatus(StrEnum):
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ProviderKind(StrEnum):
    OPEN_WORKFLOW = "open_workflow"
    COMMERCIAL_API = "commercial_api"


class LedgerEntryType(StrEnum):
    """Append-only ledger vocabulary.

    `RESERVE` is negative available / positive reserved; `CAPTURE` settles it;
    `RELEASE` returns it. `ROYALTY_OUT` / `ROYALTY_IN` move credits from a
    remixer to ancestor authors.
    """

    GRANT = "grant"
    PURCHASE = "purchase"
    RESERVE = "reserve"
    CAPTURE = "capture"
    RELEASE = "release"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    ROYALTY_OUT = "royalty_out"
    ROYALTY_IN = "royalty_in"


class RedemptionCodeKind(StrEnum):
    """`INVITE` is meant for one-to-one referral (small `max_uses`, often 1);
    `PROMO` is an operator-run campaign code shared with many users at once."""

    INVITE = "invite"
    PROMO = "promo"


class DistributionChannel(StrEnum):
    """Where an export is headed.

    `MANUAL_DOWNLOAD` is the only channel that completes today; `DOUYIN` names
    the destination so an intent recorded now stays meaningful once direct
    publishing exists.
    """

    DOUYIN = "douyin"
    MANUAL_DOWNLOAD = "manual_download"


class PublicationStatus(StrEnum):
    """Lifecycle of one distribution intent.

    Nothing reaches `SUBMITTED` yet: it belongs to the OAuth direct-publish path
    that is deliberately left unimplemented, together with `FAILED`.
    """

    DRAFT = "draft"
    READY = "ready"
    EXPORTED = "exported"
    SUBMITTED = "submitted"
    FAILED = "failed"


class LicenseType(StrEnum):
    CC_BY_4_0 = "cc_by_4.0"
    CC_BY_SA_4_0 = "cc_by_sa_4.0"
    CC_BY_NC_4_0 = "cc_by_nc_4.0"
    ALL_RIGHTS_RESERVED = "all_rights_reserved"


class NotificationType(StrEnum):
    JOB_PROGRESS = "job_progress"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_FAILED = "job_failed"
    WORK_LIKED = "work_liked"
    WORK_REMIXED = "work_remixed"
    ROYALTY_RECEIVED = "royalty_received"
    NEW_FOLLOWER = "new_follower"
    MODERATION = "moderation"
    SYSTEM = "system"


class ReportReason(StrEnum):
    COPYRIGHT = "copyright"
    SEXUAL_CONTENT = "sexual_content"
    VIOLENCE = "violence"
    HATE = "hate"
    MINOR_SAFETY = "minor_safety"
    FRAUD = "fraud"
    OTHER = "other"


class ReportStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    UPHELD = "upheld"
    DISMISSED = "dismissed"
    APPEALED = "appealed"


class DataRequestType(StrEnum):
    EXPORT = "export"
    DELETE = "delete"


class DataRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class AgentName(StrEnum):
    SAFETY = "safety"
    PLANNER = "planner"
    QUALITY = "quality"
    COPY = "copy"
    INTENT_ROUTER = "intent_router"


class AgentRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"


class LearnPostLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class LearnPostStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class CreationSkillCategory(StrEnum):
    SCENE = "scene"
    LENS = "lens"
    STYLE = "style"
    OTHER = "other"


class CreationSkillVisibility(StrEnum):
    """Owner's intent, independent of moderation state.

    A `PENDING_REVIEW`/`REJECTED` skill can carry `PUBLIC` here (it is meant
    for sharing) while still being invisible to anyone but its owner — public
    listing always additionally filters on `status == PUBLISHED`.
    """

    PRIVATE = "private"
    PUBLIC = "public"


class CreationSkillStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"


class Region(StrEnum):
    CN = "CN"
    GLOBAL = "GLOBAL"
    JP = "JP"


class Locale(StrEnum):
    ZH_CN = "zh-CN"
    EN = "en"
    JA = "ja"


class ThemePreference(StrEnum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"


class SystemLogSource(StrEnum):
    """Where a `SystemLog` row came from, for the log centre's source filter."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    PERMISSION = "permission"


class SystemLogLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
