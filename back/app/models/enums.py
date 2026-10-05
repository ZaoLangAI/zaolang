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


class DraftPublishStatus(StrEnum):
    """HTTP accept vs worker finish for a draft's pre-publish review.

    `None` on the column means not submitted. Success is `published_work_id`,
    not a third status here.
    """

    PENDING = "pending"
    REJECTED = "rejected"


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
    # Background music / sound-effect generation. Deliberately a separate
    # operation from `AUDIO_GENERATION` rather than a third `voice`-shaped
    # mode of it: the input shape has no fixed voice at all (`prompt` +
    # optional `lyrics`/`is_instrumental` in `GenerationParams.extra`, see
    # `api.schemas.jobs.validate_generation_params`), and the billing shape
    # is per-clip/per-request (`MusicPricing`), not `AudioPricing`'s
    # per-input-character TTS rate. `extra.audio_style` (`"music"`/`"sfx"`)
    # picks which of the two sub-modes a given job renders — see
    # `zaolang-generation-jobs`.
    MUSIC_GENERATION = "music_generation"
    # Reads an existing video (via `reference_asset_ids[0]`), writes a
    # structured text breakdown (camera movement / scene / style prompts),
    # not a media asset — the first `Operation` whose output modality is
    # `text` rather than image/video/audio. See
    # `zaolang-generation-jobs`/video-analysis feature notes: it is NOT a
    # member of `VIDEO_OPERATIONS` (that set drives the "must specify a
    # duration" video-generation rule, which is meaningless here).
    VIDEO_ANALYSIS = "video_analysis"


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


class MediaGenerationKind(StrEnum):
    """How a `kind="media"` endpoint is allowed to enter video routing.

    `CREATE` can start from text or a still. `EDIT` needs an existing video
    source and is hard-filtered out of text-to-video / image-to-video when
    none is attached — see `app.agents.router._request_constraint_failure`.
    Stored on `LlmProviderEndpoint`, not a SQLAlchemy column.
    """

    CREATE = "create"
    EDIT = "edit"


class AudioGenerationKind(StrEnum):
    """Disambiguates a `kind="media"` endpoint's `text -> audio` shape.

    `AUDIO_GENERATION` (spoken-voice TTS/clone) and `MUSIC_GENERATION`
    (BGM/SFX) are both, at the raw modality level, `text -> audio` — the
    same collision `MediaGenerationKind` above resolves for video's
    create-vs-edit shape. `LlmProviderEndpoint.capabilities` cannot tell
    them apart from `input_modalities`/`output_modalities` alone (that is
    exactly the ambiguity this field exists to break), so an operator
    declares which one this endpoint's one `model` string actually is.
    `VOICE` is the default so every endpoint saved before this field
    existed keeps deriving `AUDIO_GENERATION`, unchanged.
    """

    VOICE = "voice"
    MUSIC = "music"


class LedgerEntryType(StrEnum):
    """Append-only ledger vocabulary.

    `RESERVE` is negative available / positive reserved; `CAPTURE` settles it;
    `RELEASE` returns it. `ROYALTY_OUT` / `ROYALTY_IN` move credits from a
    remixer to ancestor authors (best-effort). `ACCESS_OUT` / `ACCESS_IN` are
    the mandatory marketplace transfer when someone unlocks a paid work or
    skill — they must not be reused for royalties.
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
    ACCESS_OUT = "access_out"
    ACCESS_IN = "access_in"


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
    KUAISHOU = "kuaishou"
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


class PlatformAccountLinkStatus(StrEnum):
    """Lifecycle of one creator's OAuth grant on an external platform."""

    ACTIVE = "active"
    REVOKED = "revoked"


class LicenseType(StrEnum):
    CC_BY_4_0 = "cc_by_4.0"
    CC_BY_SA_4_0 = "cc_by_sa_4.0"
    CC_BY_NC_4_0 = "cc_by_nc_4.0"
    ALL_RIGHTS_RESERVED = "all_rights_reserved"
    # On-platform remix right purchased with credits. Not a Creative Commons
    # licence — charging for remix while labelling CC-BY would be contradictory.
    ZAOLANG_PAID_REMIX = "zaolang_paid_remix"


class NotificationType(StrEnum):
    JOB_PROGRESS = "job_progress"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    WORK_LIKED = "work_liked"
    WORK_REMIXED = "work_remixed"
    DRAFT_PUBLISHED = "draft_published"
    DRAFT_PUBLISH_REJECTED = "draft_publish_rejected"
    ROYALTY_RECEIVED = "royalty_received"
    ACCESS_SOLD = "access_sold"
    NEW_FOLLOWER = "new_follower"
    MODERATION = "moderation"
    SYSTEM = "system"
    SERIES_COLLAB_INVITED = "series_collab_invited"
    SERIES_COLLAB_ACCEPTED = "series_collab_accepted"
    SERIES_COLLAB_REMOVED = "series_collab_removed"


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
    CANVAS_PLANNER = "canvas_planner"


class SeriesKind(StrEnum):
    # No creation path writes this value any more (see
    # `app.domain.characters.service`'s module docstring and migration
    # `ada14f32676f`, which purged the leftover rows). Kept rather than
    # dropped in this batch: removing an enum member read by nothing is a
    # smaller structural change than the two columns above, but still
    # earmarked for its own separate review rather than bundled here.
    CAST = "cast"
    DRAMA = "drama"


class SeriesStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRASHED = "trashed"


class SeriesGenre(StrEnum):
    """The short-drama genre dictionary offered as multi-select tags on a
    `kind=drama` `Series`. Additive only — see `zaolang-data-model` invariant
    on enum values; never rename a value once it may have been persisted."""

    URBAN = "urban"
    ANCIENT_COSTUME = "ancient_costume"
    SWEET_ROMANCE = "sweet_romance"
    SUSPENSE = "suspense"
    COMEDY = "comedy"
    FAMILY_DRAMA = "family_drama"
    WORKPLACE = "workplace"
    FANTASY = "fantasy"
    ERA = "era"
    OTHER = "other"


class SeriesCollaboratorStatus(StrEnum):
    """A `SeriesCollaborator` row's lifecycle. `pending` is an outstanding
    invite the invitee hasn't responded to yet; only `active` counts as an
    actual co-creator (see `app.domain.editor.collaborators.is_active_member`).
    `declined`/`removed` rows are kept (never deleted) so re-inviting the same
    user reuses the row instead of accumulating duplicates — see the unique
    constraint on `(series_id, user_id)`."""

    PENDING = "pending"
    ACTIVE = "active"
    DECLINED = "declined"
    REMOVED = "removed"


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


class EpisodeKind(StrEnum):
    """What an episode *is* within its series — the "剧集类型" the short-drama
    workspace lets a creator pick, independent of `DramaEpisodeStatus`
    (which tracks production lifecycle, not narrative role). Additive only —
    see `zaolang-data-model` invariant on enum values."""

    MAIN = "main"
    TRAILER = "trailer"
    TEASER = "teaser"
    BTS = "bts"
    RECAP = "recap"
    OTHER = "other"


class EpisodeContentType(StrEnum):
    """What `EpisodeContentLink.content_ref_id` points at."""

    DRAFT = "draft"
    WORK = "work"
    EDITOR_EXPORT = "editor_export"


class EpisodeContentRole(StrEnum):
    """Why a piece of content is linked to an episode — orthogonal to
    `DramaEpisode.canonical_work_id`, which names the one output actually
    chosen as the episode's final cut. A `FINAL` link is a record of that
    choice's history; `canonical_work_id` is what every other reader
    (publishing, the public work projection) trusts as current."""

    CANDIDATE = "candidate"
    REFERENCE = "reference"
    BEHIND_THE_SCENES = "behind_the_scenes"
    FINAL = "final"


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
    DeliveryVariantStatus.SUCCEEDED: frozenset({DeliveryVariantStatus.EXPORTING}),
    DeliveryVariantStatus.FAILED: frozenset({DeliveryVariantStatus.EXPORTING}),
    DeliveryVariantStatus.CANCELLED: frozenset({DeliveryVariantStatus.EXPORTING}),
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
    # A shareable generation-parameter *template* — a scene/lens/style
    # "recipe" (prompt/prompt_suffix/aspect_ratio/...) folded into a job by
    # `execute_skill_context`. Not to be confused with `SCENE_ASSET` below,
    # which is an actual reusable reference-image bundle.
    SCENE = "scene"
    LENS = "lens"
    STYLE = "style"
    # Structural *how to write it* constraints rather than a content recipe:
    # every entry is an appendable `prompt_suffix` phrase that stays true no
    # matter what the clip is about (one camera move per clip, counted action
    # beats, positive-only phrasing, ...). Kept separate from `LENS`/`STYLE`
    # so the ~100 seeded `fmt-*` entries stay filterable on their own and
    # don't bury the content recipes — see `docs/video-prompt-formats.md` for
    # the boundary and `skill_library.catalog` for the entries themselves.
    FORMAT = "format"
    # A *content* recipe for one kind of dramatic beat — "how this scene is
    # played and cut", not "how the sentence is written". Every entry names a
    # situation (a hospital-bedside standoff, a wedding reversal) or an
    # emotion (holding it in, snapping) in wording a plot description can
    # actually point at, which is what makes it the one category
    # `app.agents.skill_matcher` searches when it matches a user's story to
    # reference skills — see `docs/video-drama-scenes.md`.
    DRAMA = "drama"
    # The three "image creation" asset kinds (`ImageAssetKind`) each get their
    # own category once shared/sold as a `CreationSkill`, rather than the
    # flat `prompt`/`aspect_ratio`/... template shape every category above
    # uses — see `IMAGE_ASSET_SKILL_CATEGORIES` and `zaolang-overview`'s
    # routing note for why these three alone get special handling in
    # `execute_skill_context`.
    #
    # A reusable cast member (`app.domain.characters.service`); its images
    # live in `skill_asset_variants` / `skill_asset_entries` (looks).
    CHARACTER = "character"
    # A reusable setting (`app.domain.scenes.service`); its images live in
    # the variants tables like a character's. Named `*_ASSET` (not plain
    # `SCENE`) to stay distinct from the prompt-template category above —
    # the two used to be a table (`Scene`) and a `CreationSkillCategory`
    # respectively with no relation to each other; folding the table in
    # required a name of its own.
    SCENE_ASSET = "scene_asset"
    # A single shareable cover image, created directly from an
    # `asset_kind=cover` job's output — see
    # `app.domain.skill_library.service.create` (no dedicated
    # `app.domain.covers` module or CRUD surface: unlike a character/scene, a
    # cover has no roster to maintain, just one `cover_asset_id` and this
    # category on an otherwise ordinary `CreationSkill`).
    COVER_ASSET = "cover_asset"
    OTHER = "other"


class AssetVariantKind(StrEnum):
    """What a `SkillAssetVariant` groups: a character's outfit/look, or a
    scene's lighting/weather/state/period variant."""

    LOOK = "look"
    SCENE_VARIANT = "scene_variant"


class AssetEntryType(StrEnum):
    """What one `SkillAssetEntry` image is for inside its look/variant."""

    # Character entries.
    IDENTITY_PORTRAIT = "identity_portrait"
    CHARACTER_SHEET = "character_sheet"
    VIEW = "view"
    EXPRESSION_SHEET = "expression_sheet"
    POSE = "pose"
    OUTFIT_DETAIL = "outfit_detail"
    PROP = "prop"
    # Scene entries.
    MASTER = "master"
    SHOT = "shot"
    # Either.
    OTHER = "other"


CHARACTER_ENTRY_TYPES: frozenset[str] = frozenset(
    {
        AssetEntryType.IDENTITY_PORTRAIT,
        AssetEntryType.CHARACTER_SHEET,
        AssetEntryType.VIEW,
        AssetEntryType.EXPRESSION_SHEET,
        AssetEntryType.POSE,
        AssetEntryType.OUTFIT_DETAIL,
        AssetEntryType.PROP,
        AssetEntryType.OTHER,
    }
)
SCENE_ENTRY_TYPES: frozenset[str] = frozenset(
    {AssetEntryType.MASTER, AssetEntryType.SHOT, AssetEntryType.OTHER}
)


class AssetGraphLevel(StrEnum):
    """Which nodes a `SkillAssetEdge` joins: looks / variants, or images."""

    VARIANT = "variant"
    ENTRY = "entry"
    # A character's voices (P7).
    VOICE = "voice"


class AssetRelation(StrEnum):
    """What a graph edge says changed from source to target (P4)."""

    AGE = "age"
    OUTFIT = "outfit"
    EMOTION = "emotion"
    SCENE = "scene"
    PERIOD = "period"
    LIGHTING = "lighting"
    WEATHER = "weather"
    STATE = "state"
    # An image adjusted from another (调整修改, P6).
    EDIT = "edit"
    # A voice derived with other TTS parameters (speed, emotion, model).
    PARAMS = "params"
    CUSTOM = "custom"


CHARACTER_RELATIONS: frozenset[str] = frozenset(
    {
        AssetRelation.AGE,
        AssetRelation.OUTFIT,
        AssetRelation.EMOTION,
        AssetRelation.SCENE,
        AssetRelation.PERIOD,
        AssetRelation.EDIT,
        AssetRelation.CUSTOM,
    }
)
SCENE_RELATIONS: frozenset[str] = frozenset(
    {
        AssetRelation.LIGHTING,
        AssetRelation.WEATHER,
        AssetRelation.STATE,
        AssetRelation.PERIOD,
        AssetRelation.EDIT,
        AssetRelation.CUSTOM,
    }
)


VOICE_RELATIONS: frozenset[str] = frozenset(
    {
        AssetRelation.AGE,
        AssetRelation.EMOTION,
        AssetRelation.SCENE,
        AssetRelation.PARAMS,
        AssetRelation.CUSTOM,
    }
)


class VoiceSource(StrEnum):
    """A character voice is a model's preset voice, or a cloned sample."""

    PRESET = "preset"
    CLONE = "clone"


class AssetEdgeOrigin(StrEnum):
    """`auto`: written by a derive / adjust job; `manual`: drawn by the owner."""

    AUTO = "auto"
    MANUAL = "manual"


class AssetEntryStatus(StrEnum):
    """Candidate vs. approved (定稿). P1 writes everything as `approved`."""

    CANDIDATE = "candidate"
    APPROVED = "approved"


class ImageAssetKind(StrEnum):
    """What a `text_to_image`/`image_to_image` job's output is *for*.

    Orthogonal to `Operation`: this is the extra dimension
    `GenerationWorkflowTemplate.asset_kind` and `GenerationParams.asset_kind`
    add on top of it. `GENERAL` is the default and means "a plain, freeform
    image" — today's behaviour, unchanged. `CHARACTER` covers all three of a
    character's turnaround views (front/side/back) — see `CharacterView` for
    which one(s) a given job actually produces
    (`GenerationParams.character_views`) — and `SCENE`/`COVER` each double as
    the `view` tag on a scene's reference-asset entries
    (`reference_assets: [{"asset_id", "view", "label"}]`) the same way
    `CharacterView` does for a character's, so a generated image can be
    traced back to exactly which pose/shot it was made for.
    """

    GENERAL = "general"
    CHARACTER = "character"
    SCENE = "scene"
    COVER = "cover"


class VideoAssetKind(StrEnum):
    """What a `text_to_video`/`image_to_video`/`video_to_video` job's output
    is *for* — the video-side equivalent of `ImageAssetKind`.

    Deliberately its own enum, not a reuse of `ImageAssetKind`: values are
    spelled differently on purpose (`scene_video`/`character_action`/
    `transition_video`/`cover_video`, not `scene`/`character`/`cover`) so a
    video kind can never collide with an image kind wherever the two get
    looked up by bare string key (`copywriter._VIDEO_ENHANCE_SYSTEM_PROMPTS`,
    `GenerationWorkflowTemplate.asset_kind` rows, agent-skill default-profile
    buckets). There is no `CharacterViewAngle` equivalent here — a
    `CHARACTER_ACTION` job always produces exactly one clip per submission,
    never a multi-view loop (see `app.workflows.nodes.execute_asset_output_advance`).

    `TRANSITION`/`COVER` cover short-drama-specific building blocks images
    have no equivalent for: a transition/insert clip and a trailer/cover
    clip respectively. Neither attaches to a character/scene library (same
    as `ImageAssetKind.COVER` today) — see `execute_asset_output_link`.
    """

    GENERAL = "general"
    SCENE = "scene_video"
    CHARACTER_ACTION = "character_action"
    TRANSITION = "transition_video"
    COVER = "cover_video"


# The `CreationSkillCategory` values a generated image asset can end up
# filed under once shared/sold — one per non-`GENERAL` `ImageAssetKind`.
# `execute_skill_context` skips all three when folding `skill_ids` into a
# job (their `params_json` is asset-shaped, not template-shaped); the skill
# marketplace (`skill_library.service.list_public`) excludes all three from
# the unfiltered "browse templates" default and groups them under the
# `content_type="image_asset"` filter instead.
IMAGE_ASSET_SKILL_CATEGORIES: frozenset[CreationSkillCategory] = frozenset(
    {
        CreationSkillCategory.CHARACTER,
        CreationSkillCategory.SCENE_ASSET,
        CreationSkillCategory.COVER_ASSET,
    }
)


class CharacterViewAngle(StrEnum):
    """Which pose/angle one of a character's reference images is for.

    Named `*Angle` (not plain `CharacterView`) to avoid colliding with
    `app.domain.characters.service.CharacterView`, the unrelated
    `CreationSkill` projection type. Independent of `ImageAssetKind`: a
    `CHARACTER`-kind job names which of `FRONT`/`SIDE`/`BACK` it is producing
    via `GenerationParams.character_views` (see
    `app.workflows.nodes.execute_asset_output_advance`), one at a time,
    looping the shared `asset_graph` back to `asset_planning` between
    each. `GENERAL` is reserved for a plain uploaded reference with no fixed
    pose (`characters.service._entries_from_flat_ids`) — a generation job
    never targets it.
    """

    GENERAL = "general"
    FRONT = "front"
    SIDE = "side"
    BACK = "back"


# The views one `asset_kind=character` job may be asked to produce, in the
# canonical front → side → back order `execute_asset_output_advance` walks
# regardless of the order a caller lists them in.
CHARACTER_JOB_VIEWS: tuple[CharacterViewAngle, ...] = (
    CharacterViewAngle.FRONT,
    CharacterViewAngle.SIDE,
    CharacterViewAngle.BACK,
)


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


class AccessSubjectType(StrEnum):
    """What an `AccessGrant` unlocks. Price lives on the subject; the grant is
    the buyer's one-time receipt."""

    WORK = "work"
    SKILL = "skill"


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


# --------------------------------------------------------------------------
# Canvas
# --------------------------------------------------------------------------


class CanvasNodeKind(StrEnum):
    """What a card on the canvas is.

    The first five bind to a real domain object through `binding_json`; the
    rest stand alone. Both sets share one canvas — a drama canvas may hold
    plain notes, and a free canvas gains drama cards once its content is sent
    to an episode.
    """

    SERIES = "series"
    EPISODE = "episode"
    SHOT = "shot"
    SKILL = "skill"
    CLIP = "clip"

    IMAGE = "image"
    VIDEO = "video"
    PROMPT = "prompt"
    NOTE = "note"
    # The card an Agent run hangs off. Its live state lives on
    # `CanvasAgentRun`, never in `data_json` — see `graph_service`'s rule 1.
    AGENT = "agent"


class CanvasNodeOrigin(StrEnum):
    """Who put a card on the canvas.

    Provenance only — it drives a badge and telemetry. It is deliberately not
    an access rule: an agent-produced card must be draggable, editable and
    deletable exactly like one a person added.
    """

    USER = "user"
    AGENT = "agent"


class CanvasChangeEntity(StrEnum):
    NODE = "node"
    EDGE = "edge"
    AGENT_RUN = "agent_run"
    AGENT_TASK = "agent_task"


class CanvasChangeAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


class CanvasAgentRunOrigin(StrEnum):
    """What produced a run's plan.

    A workflow run is a `CanvasAgentRun` whose tasks came from a skill's
    template rather than from the planner, so that landing, cancelling, the
    workbench and the change stream are one mechanism instead of two. This
    column is how the two are told apart — deliberately, rather than probing
    `planner_agent_run_id IS NULL`, which would make a nullable pointer double
    as a type tag and break the moment a workflow run gains a planning step.
    """

    AGENT = "agent"
    WORKFLOW = "workflow"


class CanvasAgentRunStatus(StrEnum):
    """One Agent invocation on a canvas.

    `awaiting_confirm` is the default resting point rather than a formality:
    the plan is priced and shown before a single credit moves, because
    spending a user's balance without a confirming tap is what generates
    refund tickets.
    """

    PLANNING = "planning"
    AWAITING_CONFIRM = "awaiting_confirm"
    SUBMITTING = "submitting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # Some tasks landed and some did not. Distinct from `failed` because the
    # user has results worth keeping and should not be told the run failed.
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_CANVAS_AGENT_RUN_STATUSES


TERMINAL_CANVAS_AGENT_RUN_STATUSES: frozenset[CanvasAgentRunStatus] = frozenset(
    {
        CanvasAgentRunStatus.SUCCEEDED,
        CanvasAgentRunStatus.PARTIAL,
        CanvasAgentRunStatus.FAILED,
        CanvasAgentRunStatus.CANCELLED,
    }
)

CANVAS_AGENT_RUN_TRANSITIONS: dict[CanvasAgentRunStatus, frozenset[CanvasAgentRunStatus]] = {
    CanvasAgentRunStatus.PLANNING: frozenset(
        {
            CanvasAgentRunStatus.AWAITING_CONFIRM,
            # A planner that produced nothing usable ends here rather than
            # presenting an empty plan the user would have to reject.
            CanvasAgentRunStatus.FAILED,
            CanvasAgentRunStatus.CANCELLED,
        }
    ),
    CanvasAgentRunStatus.AWAITING_CONFIRM: frozenset(
        {CanvasAgentRunStatus.SUBMITTING, CanvasAgentRunStatus.CANCELLED}
    ),
    CanvasAgentRunStatus.SUBMITTING: frozenset(
        {
            CanvasAgentRunStatus.RUNNING,
            CanvasAgentRunStatus.FAILED,
            CanvasAgentRunStatus.CANCELLED,
        }
    ),
    CanvasAgentRunStatus.RUNNING: frozenset(
        {
            CanvasAgentRunStatus.SUCCEEDED,
            CanvasAgentRunStatus.PARTIAL,
            CanvasAgentRunStatus.FAILED,
            CanvasAgentRunStatus.CANCELLED,
        }
    ),
    CanvasAgentRunStatus.SUCCEEDED: frozenset(),
    CanvasAgentRunStatus.PARTIAL: frozenset(),
    CanvasAgentRunStatus.FAILED: frozenset(),
    CanvasAgentRunStatus.CANCELLED: frozenset(),
}


class CanvasAgentTaskStatus(StrEnum):
    """One planned generation and the card it will become.

    `landed` is deliberately not the same as the job's `succeeded`: a job can
    finish while its card is still to be inserted, and keeping the two apart is
    what lets the completion hook be idempotent under a redelivered terminal.
    """

    PLANNED = "planned"
    SUBMITTED = "submitted"
    RUNNING = "running"
    LANDED = "landed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Refused before submission — a hallucinated reference, or a plan that
    # would have pushed the canvas past its node cap.
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_CANVAS_AGENT_TASK_STATUSES


TERMINAL_CANVAS_AGENT_TASK_STATUSES: frozenset[CanvasAgentTaskStatus] = frozenset(
    {
        CanvasAgentTaskStatus.LANDED,
        CanvasAgentTaskStatus.FAILED,
        CanvasAgentTaskStatus.CANCELLED,
        CanvasAgentTaskStatus.SKIPPED,
    }
)
