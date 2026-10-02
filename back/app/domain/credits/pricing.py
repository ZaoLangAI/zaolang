"""Quoting.

Prices come from the runtime config centre so operators can change them without
a deploy; the constants here are only the fallback used before any override has
been written.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import Operation, QualityTier

DEFAULT_TIER_PRICING: dict[str, dict[str, int]] = {
    Operation.TEXT_TO_IMAGE: {
        QualityTier.PREVIEW: 4,
        QualityTier.STANDARD: 12,
        QualityTier.CINEMATIC: 40,
    },
    # Priced level with text-to-image: editing a reference image costs the
    # provider about as much as generating one from scratch.
    Operation.IMAGE_TO_IMAGE: {
        QualityTier.PREVIEW: 4,
        QualityTier.STANDARD: 12,
        QualityTier.CINEMATIC: 40,
    },
    Operation.TEXT_TO_VIDEO: {
        QualityTier.PREVIEW: 30,
        QualityTier.STANDARD: 90,
        QualityTier.CINEMATIC: 260,
    },
    Operation.IMAGE_TO_VIDEO: {
        QualityTier.PREVIEW: 26,
        QualityTier.STANDARD: 80,
        QualityTier.CINEMATIC: 240,
    },
    Operation.VIDEO_TO_VIDEO: {
        QualityTier.PREVIEW: 34,
        QualityTier.STANDARD: 100,
        QualityTier.CINEMATIC: 280,
    },
    # Much cheaper than any image/video operation: a TTS call is a single
    # short synchronous request with no per-second video surcharge.
    Operation.AUDIO_GENERATION: {
        QualityTier.PREVIEW: 2,
        QualityTier.STANDARD: 6,
        QualityTier.CINEMATIC: 15,
    },
    # Tiers are analysis depth (summary/per-scene/per-shot), not render
    # quality — see `Operation.VIDEO_ANALYSIS` in `app.models.enums`.
    Operation.VIDEO_ANALYSIS: {
        QualityTier.PREVIEW: 20,
        QualityTier.STANDARD: 50,
        QualityTier.CINEMATIC: 120,
    },
    # Priced above `AUDIO_GENERATION` (a single short TTS call) but below
    # any video operation: a music/SFX render is one synchronous call like
    # TTS, but the upstream vendor call itself costs more (fal's MiniMax
    # Music 2.6 is $0.15/generation vs. TTS's fractions of a cent per
    # 10k characters — see `app.providers.model_catalog`'s fal/DMXAPI
    # music entries) and runs longer (~30-60s per MiniMax's own docs).
    # Same flat per-tier shape as `AUDIO_GENERATION` — no per-second
    # surcharge, since none of the adapted models take an explicit,
    # billable duration control (see `fal_media.py`/`dmxapi_media.py`'s
    # music builders).
    Operation.MUSIC_GENERATION: {
        QualityTier.PREVIEW: 10,
        QualityTier.STANDARD: 25,
        QualityTier.CINEMATIC: 60,
    },
}

DEFAULT_ESTIMATED_SECONDS: dict[str, dict[str, int]] = {
    Operation.TEXT_TO_IMAGE: {
        QualityTier.PREVIEW: 8,
        QualityTier.STANDARD: 20,
        QualityTier.CINEMATIC: 45,
    },
    Operation.IMAGE_TO_IMAGE: {
        QualityTier.PREVIEW: 10,
        QualityTier.STANDARD: 25,
        QualityTier.CINEMATIC: 50,
    },
    Operation.TEXT_TO_VIDEO: {
        QualityTier.PREVIEW: 45,
        QualityTier.STANDARD: 120,
        QualityTier.CINEMATIC: 300,
    },
    Operation.IMAGE_TO_VIDEO: {
        QualityTier.PREVIEW: 40,
        QualityTier.STANDARD: 110,
        QualityTier.CINEMATIC: 280,
    },
    Operation.VIDEO_TO_VIDEO: {
        QualityTier.PREVIEW: 50,
        QualityTier.STANDARD: 130,
        QualityTier.CINEMATIC: 320,
    },
    Operation.AUDIO_GENERATION: {
        QualityTier.PREVIEW: 5,
        QualityTier.STANDARD: 12,
        QualityTier.CINEMATIC: 25,
    },
    Operation.VIDEO_ANALYSIS: {
        QualityTier.PREVIEW: 20,
        QualityTier.STANDARD: 40,
        QualityTier.CINEMATIC: 90,
    },
    Operation.MUSIC_GENERATION: {
        QualityTier.PREVIEW: 20,
        QualityTier.STANDARD: 35,
        QualityTier.CINEMATIC: 60,
    },
}

# Per-second surcharge applied beyond the tier's included duration.
VIDEO_BASE_SECONDS = 4
VIDEO_PER_SECOND_SURCHARGE: dict[str, int] = {
    QualityTier.PREVIEW: 4,
    QualityTier.STANDARD: 12,
    QualityTier.CINEMATIC: 30,
}

VIDEO_OPERATIONS = frozenset(
    {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
)


@dataclass(frozen=True, slots=True)
class Quote:
    credits: int
    estimated_seconds: int
    breakdown: dict[str, int]


def quote(
    *,
    operation: str,
    quality_tier: str,
    duration_seconds: int = 0,
    pricing: dict[str, dict[str, int]] | None = None,
    durations: dict[str, dict[str, int]] | None = None,
    per_second_surcharge: dict[str, int] | None = None,
    base_seconds: int | None = None,
    output_count: int = 1,
) -> Quote:
    """Deterministic price for one job.

    The same inputs must always produce the same number: the quote is shown to
    the user before they commit, and the reservation is made against it.

    `output_count` is only ever greater than 1 for a `character`-asset-kind
    job whose `character_views` names more than one view (a "补全侧面/背面"
    completion request) — see `app.domain.jobs.service.character_output_count`.
    It multiplies the tier's base price directly rather than touching the
    video duration surcharge, since only image jobs ever set it above 1.
    """
    table = pricing or DEFAULT_TIER_PRICING
    seconds_table = durations or DEFAULT_ESTIMATED_SECONDS
    surcharge_table = per_second_surcharge or VIDEO_PER_SECOND_SURCHARGE
    included_seconds = VIDEO_BASE_SECONDS if base_seconds is None else base_seconds

    tiers = table.get(operation)
    if tiers is None or quality_tier not in tiers:
        raise ValueError(f"未定价的组合: {operation}/{quality_tier}")

    unit_base = tiers[quality_tier]
    breakdown = {"base": unit_base}
    total = unit_base
    if output_count > 1:
        additional = unit_base * (output_count - 1)
        breakdown["additional_outputs"] = additional
        total += additional

    billable_seconds = 0
    if operation in VIDEO_OPERATIONS and duration_seconds > included_seconds:
        billable_seconds = duration_seconds - included_seconds
        rate = surcharge_table.get(quality_tier)
        if rate is None:
            raise ValueError(f"缺少每秒加价: {quality_tier}")
        surcharge = billable_seconds * rate
        breakdown["duration_surcharge"] = surcharge
        total += surcharge

    estimated = seconds_table.get(operation, {}).get(quality_tier, 30)
    estimated += billable_seconds * 6
    estimated *= max(output_count, 1)

    return Quote(credits=total, estimated_seconds=estimated, breakdown=breakdown)


def settlement_credits(
    *,
    reserved_credits: int,
    operation: str,
    requested_duration_seconds: int,
    delivered_duration_ms: int | None,
    requested_outputs: int = 1,
    delivered_outputs: int = 1,
) -> int:
    """What the user actually pays once the output is in hand.

    The quote is a price, not an estimate of the platform's cost: a user shown
    "12 credits" pays 12, and what the provider charged us is margin, recorded
    on `ProviderAttempt` rather than passed through.

    The cases that refund are short deliveries, charged pro rata because the
    user did not receive what they paid for:

    - a multi-pass image job (several character views, a scene variant set)
      whose later pass failed after earlier ones delivered — priced per
      image (`jobs.service.requested_output_count`), so it pays for the
      images it got, in integers;
    - a video that came back shorter than ordered.
    """
    if 0 < delivered_outputs < requested_outputs:
        # Never free: the platform still paid a provider for what arrived.
        return max(1, reserved_credits * delivered_outputs // requested_outputs)

    if (
        operation not in VIDEO_OPERATIONS
        or delivered_duration_ms is None
        or requested_duration_seconds <= 0
    ):
        return reserved_credits

    delivered_seconds = delivered_duration_ms / 1000
    if delivered_seconds >= requested_duration_seconds:
        return reserved_credits

    ratio = delivered_seconds / requested_duration_seconds
    # Never free: the platform still paid a provider for the partial output.
    return max(1, min(reserved_credits, round(reserved_credits * ratio)))
