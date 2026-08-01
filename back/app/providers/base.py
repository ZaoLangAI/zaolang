"""Generation provider interface.

Both shipped providers are fakes. The interface is what real providers will
implement, so swapping one in requires no change to the worker or the router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GenerationRequest:
    job_id: str
    operation: str
    quality_tier: str
    prompt: str
    negative_prompt: str | None = None
    seed: int | None = None
    aspect_ratio: str = "16:9"
    duration_seconds: int = 0
    reference_object_keys: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GenerationResult:
    succeeded: bool
    object_key: str | None = None
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    cost_minor: int = 0
    latency_ms: int = 0
    external_task_id: str | None = None
    failure_code: str | None = None
    # Redacted before it reaches ProviderAttempt: no keys, no signed URLs.
    metadata: dict[str, Any] = field(default_factory=dict)


class GenerationProvider(ABC):
    name: str
    kind: str

    @abstractmethod
    def submit(self, request: GenerationRequest) -> GenerationResult:
        """Runs one generation attempt.

        Implementations must be synchronous from the worker's point of view;
        polling an async upstream belongs inside the implementation.
        """

    def cancel(self, external_task_id: str) -> bool:
        """Best-effort cancellation. Returning False is acceptable: the job may
        still complete and bill us, and settlement follows the real outcome."""
        return False
