"""Headline balance choice and per-currency totals (BR-05)."""

from datetime import UTC, datetime
from decimal import Decimal

from finance_app.modules.accounts.models import Balance
from finance_app.modules.accounts.service import headline_balance, totals_by_currency

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def _balance(type_: str, amount: str, currency: str = "GBP") -> Balance:
    return Balance(type=type_, amount=Decimal(amount), currency=currency, as_of=NOW)


def test_available_balance_is_preferred_over_booked_br05() -> None:
    balances = [_balance("CLOSING_BOOKED", "100.00"), _balance("INTERIM_AVAILABLE", "90.00")]

    headline = headline_balance(balances)

    assert headline is not None and headline.amount == Decimal("90.00")


def test_unknown_types_fall_back_deterministically() -> None:
    headline = headline_balance([_balance("OTHER", "5.00"), _balance("INFORMATION", "7.00")])

    assert headline is not None and headline.type == "INFORMATION"
    assert headline_balance([]) is None


def test_totals_are_per_currency_and_never_mixed_br05() -> None:
    totals = totals_by_currency(
        [
            _balance("INTERIM_AVAILABLE", "1523.47"),
            _balance("INTERIM_AVAILABLE", "8200.00"),
            _balance("INTERIM_AVAILABLE", "-245.90"),
            _balance("INTERIM_AVAILABLE", "642.10", "EUR"),
            None,  # account without balances yet
        ]
    )

    assert [(t.currency, t.amount, t.account_count) for t in totals] == [
        ("EUR", Decimal("642.10"), 1),
        ("GBP", Decimal("9477.57"), 3),
    ]
