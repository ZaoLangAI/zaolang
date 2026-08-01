"""What a user is actually charged once the output is delivered."""

from __future__ import annotations

import pytest

from app.domain.credits.pricing import quote, settlement_credits
from app.models.enums import Operation, QualityTier


def test_an_image_is_charged_exactly_what_was_quoted() -> None:
    """The quote is a price the user accepted, not an estimate of our cost."""
    priced = quote(operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    charged = settlement_credits(
        reserved_credits=priced.credits,
        operation=Operation.TEXT_TO_IMAGE,
        requested_duration_seconds=0,
        delivered_duration_ms=None,
    )
    assert charged == priced.credits


def test_a_full_length_video_is_charged_in_full() -> None:
    charged = settlement_credits(
        reserved_credits=120,
        operation=Operation.TEXT_TO_VIDEO,
        requested_duration_seconds=8,
        delivered_duration_ms=8_000,
    )
    assert charged == 120


def test_a_longer_than_ordered_delivery_is_not_charged_extra() -> None:
    """The user only agreed to the quoted number."""
    charged = settlement_credits(
        reserved_credits=120,
        operation=Operation.TEXT_TO_VIDEO,
        requested_duration_seconds=8,
        delivered_duration_ms=12_000,
    )
    assert charged == 120


def test_a_short_delivery_is_charged_pro_rata() -> None:
    """The user did not receive what they paid for."""
    charged = settlement_credits(
        reserved_credits=120,
        operation=Operation.TEXT_TO_VIDEO,
        requested_duration_seconds=8,
        delivered_duration_ms=4_000,
    )
    assert charged == 60


def test_a_near_empty_delivery_still_costs_something() -> None:
    """A provider was still paid for the partial output."""
    charged = settlement_credits(
        reserved_credits=120,
        operation=Operation.TEXT_TO_VIDEO,
        requested_duration_seconds=8,
        delivered_duration_ms=1,
    )
    assert charged == 1


def test_settlement_never_exceeds_the_reservation() -> None:
    """Charging above the reservation would mean capturing credits the user
    never authorised."""
    for delivered in (0, 1, 5_000, 8_000, 50_000):
        charged = settlement_credits(
            reserved_credits=30,
            operation=Operation.IMAGE_TO_VIDEO,
            requested_duration_seconds=8,
            delivered_duration_ms=delivered,
        )
        assert 1 <= charged <= 30


@pytest.mark.parametrize("operation", sorted(Operation))
def test_every_operation_settles_to_a_positive_amount(operation: str) -> None:
    charged = settlement_credits(
        reserved_credits=40,
        operation=operation,
        requested_duration_seconds=6,
        delivered_duration_ms=3_000,
    )
    assert charged > 0
