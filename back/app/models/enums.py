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
    """A work is never hard-deleted while descendants must stay resolvable.

    `TRASHED` is the owner's recycle bin (restorable). `TOMBSTONE` is terminal.
    """

    ACTIVE = "active"
    HIDDEN = "hidden"
    TRASHED = "trashed"
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
    EDITOR_SOURCE = "editor_source"
    EDITOR_EXPORT = "editor_export"
    EDITOR_CAPTION = "editor_caption"
    EDITOR_FONT = "editor_font"


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


class JobOrigin(StrEnum):
    """Who submitted the job. Sandbox runs skip the credit ledger but still
    persist a real `GenerationJob` so ops and moderation can replay them."""

    USER = "user"
    SANDBOX = "sandbox"


class JobStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    # Parked on a `copy_generate` node's follow-up questions — see
    # `app.domain.jobs.input_requests`. Distinct from `RUNNING` so the C-end
    # client knows to render a question form instead of a spinner, and so the
    # stale-job sweeper does not mistake "waiting on the author" for "stuck".
    AWAITING_INPUT = "awaiting_input"
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
        {
            JobStatus.AWAITING_INPUT,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        }
    ),
    # Answering resumes the same walk, so the only way out is back to
    # `RUNNING` — or one of the terminal states an abandoned question times
    # out or gets cancelled into.
    JobStatus.AWAITING_INPUT: frozenset(
        {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.EXPIRED: frozenset(),
}

# Cancelling after submission is a *request*: the provider may still finish and
# bill us, so settlement follows the provider's actual result.
CANCELLABLE_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.CREATED,
        JobStatus.QUEUED,
        JobStatus.SUBMITTED,
        JobStatus.RUNNING,
        JobStatus.AWAITING_INPUT,
    }
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
    # A `copy_generate` node suspended the job on a follow-up question.
    AWAITING_INPUT = "awaiting_input"
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
    JOB_CANCELLED = "job_cancelled"
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


class AppealStatus(StrEnum):
    """A `WorkAppeal` disputes one specific hide decision on a work — distinct
    from `ReportStatus`, whose upheld/dismissed polarity means the opposite
    thing (upholding a report is denying the creator, not granting them)."""

    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"


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
    EDITOR_PLANNER = "editor_planner"


class SeriesKind(StrEnum):
    CAST = "cast"
    DRAMA = "drama"


class SeriesStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class DramaEpisodeStatus(StrEnum):
    DRAFT = "draft"
    PRODUCTION = "production"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EpisodeCutKind(StrEnum):
    FULL = "full"
    CONDENSED = "condensed"
    TRAILER = "trailer"
    HIGHLIGHT = "highlight"
    CUSTOM = "custom"


class EpisodeCutStatus(StrEnum):
    DRAFT = "draft"
    EDITING = "editing"
    READY = "ready"
    ARCHIVED = "archived"


EPISODE_CUT_TRANSITIONS: dict[EpisodeCutStatus, frozenset[EpisodeCutStatus]] = {
    EpisodeCutStatus.DRAFT: frozenset({EpisodeCutStatus.EDITING, EpisodeCutStatus.ARCHIVED}),
    EpisodeCutStatus.EDITING: frozenset(
        {EpisodeCutStatus.READY, EpisodeCutStatus.DRAFT, EpisodeCutStatus.ARCHIVED}
    ),
    EpisodeCutStatus.READY: frozenset({EpisodeCutStatus.EDITING, EpisodeCutStatus.ARCHIVED}),
    EpisodeCutStatus.ARCHIVED: frozenset(),
}


class EditPlanStatus(StrEnum):
    GENERATING = "generating"
    VALIDATED = "validated"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_EDIT_PLAN_STATUSES


TERMINAL_EDIT_PLAN_STATUSES: frozenset[EditPlanStatus] = frozenset(
    {
        EditPlanStatus.APPLIED,
        EditPlanStatus.REJECTED,
        EditPlanStatus.EXPIRED,
        EditPlanStatus.FAILED,
    }
)

EDIT_PLAN_TRANSITIONS: dict[EditPlanStatus, frozenset[EditPlanStatus]] = {
    EditPlanStatus.GENERATING: frozenset(
        {EditPlanStatus.VALIDATED, EditPlanStatus.FAILED, EditPlanStatus.EXPIRED}
    ),
    EditPlanStatus.VALIDATED: frozenset(
        {
            EditPlanStatus.APPLIED,
            EditPlanStatus.REJECTED,
            EditPlanStatus.EXPIRED,
            EditPlanStatus.FAILED,
        }
    ),
    EditPlanStatus.APPLIED: frozenset(),
    EditPlanStatus.REJECTED: frozenset(),
    EditPlanStatus.EXPIRED: frozenset(),
    EditPlanStatus.FAILED: frozenset(),
}


class DeliveryVariantStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    EXPORTING = "exporting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_VARIANT_STATUSES


TERMINAL_VARIANT_STATUSES: frozenset[DeliveryVariantStatus] = frozenset(
    {
        DeliveryVariantStatus.SUCCEEDED,
        DeliveryVariantStatus.FAILED,
        DeliveryVariantStatus.CANCELLED,
    }
)

DELIVERY_VARIANT_TRANSITIONS: dict[DeliveryVariantStatus, frozenset[DeliveryVariantStatus]] = {
    DeliveryVariantStatus.DRAFT: frozenset({DeliveryVariantStatus.READY}),
    DeliveryVariantStatus.READY: frozenset(
        {DeliveryVariantStatus.EXPORTING, DeliveryVariantStatus.CANCELLED}
    ),
    DeliveryVariantStatus.EXPORTING: frozenset(
        {
            DeliveryVariantStatus.SUCCEEDED,
            DeliveryVariantStatus.FAILED,
            DeliveryVariantStatus.CANCELLED,
        }
    ),
    DeliveryVariantStatus.SUCCEEDED: frozenset(),
    DeliveryVariantStatus.FAILED: frozenset(),
    DeliveryVariantStatus.CANCELLED: frozenset(),
}


class EditorExportStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    ENCODING = "encoding"
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_EDITOR_EXPORT_STATUSES


TERMINAL_EDITOR_EXPORT_STATUSES: frozenset[EditorExportStatus] = frozenset(
    {
        EditorExportStatus.SUCCEEDED,
        EditorExportStatus.CANCELLED,
        EditorExportStatus.FAILED,
    }
)

EDITOR_EXPORT_TRANSITIONS: dict[EditorExportStatus, frozenset[EditorExportStatus]] = {
    EditorExportStatus.QUEUED: frozenset(
        {EditorExportStatus.CLAIMED, EditorExportStatus.CANCEL_REQUESTED, EditorExportStatus.FAILED}
    ),
    EditorExportStatus.CLAIMED: frozenset(
        {
            EditorExportStatus.ENCODING,
            EditorExportStatus.CANCEL_REQUESTED,
            EditorExportStatus.FAILED,
        }
    ),
    EditorExportStatus.ENCODING: frozenset(
        {
            EditorExportStatus.UPLOADING,
            EditorExportStatus.CANCEL_REQUESTED,
            EditorExportStatus.FAILED,
        }
    ),
    EditorExportStatus.UPLOADING: frozenset(
        {
            EditorExportStatus.VERIFYING,
            EditorExportStatus.CANCEL_REQUESTED,
            EditorExportStatus.FAILED,
        }
    ),
    EditorExportStatus.VERIFYING: frozenset(
        {
            EditorExportStatus.SUCCEEDED,
            EditorExportStatus.CANCEL_REQUESTED,
            EditorExportStatus.FAILED,
        }
    ),
    EditorExportStatus.CANCEL_REQUESTED: frozenset(
        {EditorExportStatus.CANCELLED, EditorExportStatus.FAILED, EditorExportStatus.SUCCEEDED}
    ),
    EditorExportStatus.SUCCEEDED: frozenset(),
    EditorExportStatus.CANCELLED: frozenset(),
    EditorExportStatus.FAILED: frozenset(),
}


class MediaAnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"

    @property
    def is_terminal(self) -> bool:
        return self in {
            MediaAnalysisStatus.SUCCEEDED,
            MediaAnalysisStatus.FAILED,
            MediaAnalysisStatus.DEGRADED,
        }


class EditorCommandEventStatus(StrEnum):
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


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
    MODERATION = "moderation"
    # Runtime crashes in the generation pipeline/workflow engine/workers —
    # deliberately not "high frequency", but the only durable record of a
    # `job_id`-scoped exception the public `JobEvent` stream must not repeat.
    PIPELINE = "pipeline"


class SystemLogLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
