"""Generation provider interface.

Both shipped providers are fakes. The interface is what real providers will
implement, so swapping one in requires no change to the worker or the router.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import ProviderKind


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


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """One routable capability: what `app/agents/router.py` scores and picks
    between. Lives here rather than in `router.py` so provider-directory
    modules (e.g. one building capabilities from a database endpoint) can
    construct these without importing the router — the router imports this
    module, never the reverse."""

    name: str
    kind: ProviderKind
    operations: frozenset[str]
    tiers: frozenset[str]
    # 0-1 baseline used before enough real samples exist.
    quality_prior: float
    typical_latency_ms: int
    unit_cost_minor: int
    model_or_workflow: str
    # Deferred so building the catalog never constructs a provider (and
    # therefore never opens a client/connection) for a route that ends up
    # not winning.
    provider_factory: Callable[[], GenerationProvider]
