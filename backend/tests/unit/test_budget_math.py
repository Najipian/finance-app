"""Budget thresholds and month arithmetic (BR-09, BR-10)."""

from datetime import date
from decimal import Decimal

import pytest

from finance_app.modules.budgets.schemas import parse_month
from finance_app.modules.budgets.service import (
    budget_status,
    month_start,
    next_month,
    percent_used,
    thresholds_reached,
)

LIMIT = Decimal("300.00")


@pytest.mark.parametrize(
    ("spent", "expected"),
    [
        ("0", (False, False)),
        ("239.99", (False, False)),
        ("240.00", (True, False)),  # US-07: 240 of 300 is the 80 % alert
        ("299.99", (True, False)),
        ("300.00", (True, True)),  # and 300 is the 100 % alert
        ("450.00", (True, True)),
    ],
)
def test_thresholds_at_80_and_100_percent_br10(spent: str, expected: tuple[bool, bool]) -> None:
    assert thresholds_reached(Decimal(spent), LIMIT) == expected


def test_status_and_percent_used() -> None:
    assert budget_status(Decimal("100"), LIMIT) == "ok"
    assert budget_status(Decimal("240"), LIMIT) == "warning"
    assert budget_status(Decimal("301"), LIMIT) == "exceeded"
    assert percent_used(Decimal("240"), LIMIT) == Decimal("80.0")
    assert percent_used(Decimal("1"), Decimal("3")) == Decimal("33.3")
    assert percent_used(Decimal("5"), Decimal("0")) == Decimal("0.0")


def test_zero_limit_alerts_on_any_spend() -> None:
    assert thresholds_reached(Decimal("0.01"), Decimal("0")) == (True, True)
    assert thresholds_reached(Decimal("0"), Decimal("0")) == (False, False)


def test_month_helpers() -> None:
    assert month_start(date(2026, 11, 17)) == date(2026, 11, 1)
    assert next_month(date(2026, 11, 1)) == date(2026, 12, 1)
    assert next_month(date(2026, 12, 1)) == date(2027, 1, 1)
    assert parse_month("2026-02") == date(2026, 2, 1)
