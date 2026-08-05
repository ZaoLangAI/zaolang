"""SQLAlchemy models.

Everything is re-exported here so that `Base.metadata` is fully populated by a
single import, which is what Alembic autogenerate relies on.
"""

from app.models.agent_skills import AgentNode, AgentSkill
from app.models.base import Base, TimestampMixin, new_id, utcnow
from app.models.characters import Character, Series
from app.models.credits import (
    CreditAccount,
    CreditLedgerEntry,
    CreditPackage,
    PaymentIntent,
    RedemptionCode,
    RedemptionRecord,
    WebhookEvent,
)
from app.models.generation import (
    AgentRun,
    GenerationJob,
    JobEvent,
    ProviderAttempt,
    ProviderStat,
    Workflow,
    WorkflowVersion,
)
from app.models.identity import Follow, Profile, User
from app.models.learning import LearnPost
from app.models.media import (
    Asset,
    AssetConsent,
    ContentFingerprint,
    ProvenanceManifest,
    UploadSession,
)
from app.models.platform import (
    Announcement,
    AuditLog,
    BackupRecord,
    DataRequest,
    Device,
    IdempotencyRecord,
    ModerationQueueItem,
    ModerationResult,
    Notification,
    PlatformConfig,
    ReconciliationReport,
    ReportCase,
)
from app.models.search import EMBEDDING_DIM, WorkEmbedding
from app.models.skill_library import CreationSkill
from app.models.system_log import SystemLog
from app.models.works import (
    Bookmark,
    Collection,
    CollectionItem,
    Draft,
    LicenseSnapshot,
    Like,
    LineageEdge,
    PublicationIntent,
    StylePreset,
    Tag,
    Work,
    WorkTag,
    WorkVersion,
)

__all__ = [
    "EMBEDDING_DIM",
    "AgentNode",
    "AgentRun",
    "AgentSkill",
    "Announcement",
    "Asset",
    "AssetConsent",
    "AuditLog",
    "BackupRecord",
    "Base",
    "Bookmark",
    "Character",
    "Collection",
    "CollectionItem",
    "ContentFingerprint",
    "CreationSkill",
    "CreditAccount",
    "CreditLedgerEntry",
    "CreditPackage",
    "DataRequest",
    "Device",
    "Draft",
    "Follow",
    "GenerationJob",
    "IdempotencyRecord",
    "JobEvent",
    "LearnPost",
    "LicenseSnapshot",
    "Like",
    "LineageEdge",
    "ModerationQueueItem",
    "ModerationResult",
    "Notification",
    "PaymentIntent",
    "PlatformConfig",
    "Profile",
    "ProvenanceManifest",
    "ProviderAttempt",
    "ProviderStat",
    "PublicationIntent",
    "ReconciliationReport",
    "RedemptionCode",
    "RedemptionRecord",
    "ReportCase",
    "Series",
    "StylePreset",
    "SystemLog",
    "Tag",
    "TimestampMixin",
    "UploadSession",
    "User",
    "WebhookEvent",
    "Work",
    "WorkEmbedding",
    "WorkTag",
    "WorkVersion",
    "Workflow",
    "WorkflowVersion",
    "new_id",
    "utcnow",
]
