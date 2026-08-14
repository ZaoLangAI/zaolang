"""Domain errors mapped 1:1 onto the published error-code table.

Raising these from a service is what produces the documented HTTP status and
machine-readable `error.code` at the API boundary. Nothing else in the codebase
should construct an HTTPException for a domain rule.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    default_message: str = "服务暂时不可用。"

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class AuthRequired(DomainError):
    code = "AUTH_REQUIRED"
    http_status = 401
    default_message = "请先登录。"


class Forbidden(DomainError):
    code = "FORBIDDEN"
    http_status = 403
    default_message = "没有权限执行该操作。"


class NotFound(DomainError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "资源不存在。"


class WorkPrivate(DomainError):
    """Private works are indistinguishable from missing ones to outsiders.

    Returning 404 rather than 403 avoids confirming that the ID exists.
    """

    code = "WORK_PRIVATE"
    http_status = 404
    default_message = "作品不存在或不可访问。"


class LicenseNotRemixable(DomainError):
    code = "LICENSE_NOT_REMIXABLE"
    http_status = 409
    default_message = "该作品仅用于展示，不能创建二创。"


class AssetRightsRequired(DomainError):
    code = "ASSET_RIGHTS_REQUIRED"
    http_status = 422
    default_message = "请先确认你拥有新增素材的使用权。"


class ModerationRejected(DomainError):
    code = "MODERATION_REJECTED"
    http_status = 422
    default_message = "内容未通过安全检查。"


class InsufficientCredits(DomainError):
    code = "INSUFFICIENT_CREDITS"
    http_status = 402
    default_message = "积分不足，请先充值。"


class AccessRequired(DomainError):
    """The subject is remixable/usable, but this viewer has not unlocked it."""

    code = "ACCESS_REQUIRED"
    http_status = 402
    default_message = "需要先用积分解锁。"


class CreditsExceedBudget(DomainError):
    code = "CREDITS_EXCEED_BUDGET"
    http_status = 409
    default_message = "预计消耗超过你设置的积分上限。"


class JobNotCancellable(DomainError):
    code = "JOB_NOT_CANCELLABLE"
    http_status = 409
    default_message = "当前任务状态不允许取消。"


class InvalidJobTransition(DomainError):
    code = "INVALID_JOB_TRANSITION"
    http_status = 409
    default_message = "任务状态变更不合法。"


class IdempotencyConflict(DomainError):
    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    default_message = "相同幂等键对应了不同的请求内容。"


class ProviderTemporaryFailure(DomainError):
    code = "PROVIDER_TEMPORARY_FAILURE"
    http_status = 503
    default_message = "生成服务暂时不可用，请稍后重试。"


class ValidationFailed(DomainError):
    code = "VALIDATION_FAILED"
    http_status = 422
    default_message = "请求参数不合法。"


class Conflict(DomainError):
    code = "CONFLICT"
    http_status = 409
    default_message = "操作与当前状态冲突。"


class RateLimited(DomainError):
    code = "RATE_LIMITED"
    http_status = 429
    default_message = "请求过于频繁，请稍后再试。"

    def __init__(
        self, message: str | None = None, *, retry_after_seconds: int = 60, **details: Any
    ) -> None:
        # Promoted to an attribute so the API layer can turn it into the
        # `Retry-After` header a client is entitled to act on.
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, retry_after_seconds=retry_after_seconds, **details)


class ReasonRequired(DomainError):
    """High-risk back-office actions must carry a written justification."""

    code = "REASON_REQUIRED"
    http_status = 422
    default_message = "该操作必须填写理由。"


class LineageProtected(DomainError):
    code = "LINEAGE_PROTECTED"
    http_status = 409
    default_message = "该记录已被后代作品引用，不能删除。"


class AgeGateRequired(DomainError):
    code = "AGE_GATE_REQUIRED"
    http_status = 403
    default_message = "需要确认已满 18 周岁。"


class RevisionConflict(DomainError):
    code = "REVISION_CONFLICT"
    http_status = 409
    default_message = "时间线已被其他人更新，请基于最新修订重试。"


class LeaseHeld(DomainError):
    code = "LEASE_HELD"
    http_status = 409
    default_message = "该剪辑正在被其他会话编辑。"


class BatchRolledBack(DomainError):
    code = "BATCH_ROLLED_BACK"
    http_status = 409
    default_message = "命令批次已回滚，未改动时间线。"


class OperationTerminal(DomainError):
    code = "OPERATION_TERMINAL"
    http_status = 409
    default_message = "该操作已结束，不能再更新。"


class BrowserRequired(DomainError):
    code = "BROWSER_REQUIRED"
    http_status = 409
    default_message = "该导出必须由桌面 Chrome 或 Edge 认领执行。"


class ScopeRequired(DomainError):
    code = "SCOPE_REQUIRED"
    http_status = 403
    default_message = "缺少所需的 MCP 权限范围。"


class ProjectForbidden(DomainError):
    code = "PROJECT_FORBIDDEN"
    http_status = 403
    default_message = "没有该剧集的访问权限。"
