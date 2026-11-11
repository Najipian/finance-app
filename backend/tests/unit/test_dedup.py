"""Transaction deduplication keys (BR-06)."""

import uuid
from datetime import date
from decimal import Decimal

from finance_app.modules.transactions.dedup import dedup_keys
from finance_app.providers.base import ProviderTransaction

ACCOUNT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _tx(
    provider_id: str | None, amount: str = "-3.20", description: str = "PRET"
) -> ProviderTransaction:
    return ProviderTransaction(
        provider_transaction_id=provider_id,
        booking_date=date(2026, 11, 10),
        amount=Decimal(amount),
        currency="GBP",
        description=description,
        status="booked",
    )


def test_provider_id_gives_a_stable_key_br06() -> None:
    assert dedup_keys(ACCOUNT, [_tx("tx-1")]) == dedup_keys(ACCOUNT, [_tx("tx-1")])
    assert dedup_keys(ACCOUNT, [_tx("tx-1")]) != dedup_keys(ACCOUNT, [_tx("tx-2")])


def test_identical_transactions_without_ids_are_both_kept_br06() -> None:
    two_coffees = [_tx(None), _tx(None)]

    keys = dedup_keys(ACCOUNT, two_coffees)

    assert len(set(keys)) == 2  # not collapsed into one
    assert keys == dedup_keys(ACCOUNT, two_coffees)  # and stable across syncs


def test_fallback_key_depends_on_account_amount_and_description() -> None:
    base = dedup_keys(ACCOUNT, [_tx(None)])
    assert base != dedup_keys(uuid.uuid4(), [_tx(None)])
    assert base != dedup_keys(ACCOUNT, [_tx(None, amount="-3.21")])
    assert base != dedup_keys(ACCOUNT, [_tx(None, description="COSTA")])


def test_keys_fit_the_column() -> None:
    assert all(len(k) == 64 for k in dedup_keys(ACCOUNT, [_tx("x" * 300), _tx(None)]))
