"""Renewal warning arithmetic (BR-03, US-02: warn at 7 days or less)."""

from datetime import UTC, datetime, timedelta

import pytest

from finance_app.modules.connections.lifecycle import days_until, renewal_due

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("expires_in", "due"),
    [
        (timedelta(days=8), False),
        (timedelta(days=7, seconds=1), False),
        (timedelta(days=7), True),
        (timedelta(hours=1), True),
        (timedelta(days=-1), True),  # already expired
    ],
)
def test_renewal_is_due_within_seven_days_br03(expires_in: timedelta, due: bool) -> None:
    assert renewal_due(NOW + expires_in, NOW) is due


def test_unknown_expiry_is_never_due() -> None:
    assert renewal_due(None, NOW) is False
    assert days_until(None, NOW) is None


def test_days_until_counts_whole_days() -> None:
    assert days_until(NOW + timedelta(days=5, hours=3), NOW) == 5
    assert days_until(NOW - timedelta(hours=1), NOW) == -1
