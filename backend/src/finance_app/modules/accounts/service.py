"""Accounts overview across banks with per-currency totals (BR-05)."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.modules.accounts.models import Account, Balance
from finance_app.modules.accounts.repository import AccountRepository
from finance_app.modules.accounts.schemas import (
    AccountRead,
    AccountsOverview,
    BalanceRead,
    CurrencyTotal,
)

# Banks report several balance types; the first one present is shown and totalled.
# "Available" reflects what the user can spend now, so it wins over "booked".
HEADLINE_BALANCE_ORDER = (
    "INTERIM_AVAILABLE",
    "CLOSING_AVAILABLE",
    "EXPECTED",
    "FORWARD_AVAILABLE",
    "INTERIM_BOOKED",
    "CLOSING_BOOKED",
    "OPENING_AVAILABLE",
    "OPENING_BOOKED",
)


def headline_balance(balances: Sequence[Balance]) -> Balance | None:
    """Pick the balance to display and total for an account.

    Args:
        balances: All stored balance types of one account.

    Returns:
        The preferred balance, any balance if none is preferred, or None.
    """
    by_type = {b.type: b for b in balances}
    for balance_type in HEADLINE_BALANCE_ORDER:
        if balance_type in by_type:
            return by_type[balance_type]
    return min(balances, key=lambda b: b.type) if balances else None


def totals_by_currency(headlines: Sequence[Balance | None]) -> list[CurrencyTotal]:
    """Sum headline balances per currency, sorted by currency code."""
    sums: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    for balance in headlines:
        if balance is None:
            continue
        sums[balance.currency] += balance.amount
        counts[balance.currency] += 1
    return [
        CurrencyTotal(currency=c, amount=sums[c], account_count=counts[c]) for c in sorted(sums)
    ]


class AccountService:
    """Read models for the user's accounts.

    Args:
        session: Database session for this request.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._accounts = AccountRepository(session)

    async def overview(self, user_id: uuid.UUID) -> AccountsOverview:
        """All of the user's accounts with balances and per-currency totals."""
        accounts: Sequence[Account] = await self._accounts.list_for_user(user_id)
        items: list[AccountRead] = []
        headlines: list[Balance | None] = []
        for account in accounts:
            headline = headline_balance(account.balances)
            headlines.append(headline)
            items.append(
                AccountRead(
                    id=account.id,
                    connection_id=account.connection_id,
                    institution_name=account.connection.institution_name,
                    connection_status=account.connection.status,
                    name=account.name,
                    type=account.type,
                    currency=account.currency,
                    account_number_masked=account.account_number_masked,
                    balance=BalanceRead.model_validate(headline) if headline else None,
                    balances=[
                        BalanceRead.model_validate(b)
                        for b in sorted(account.balances, key=lambda b: b.type)
                    ],
                )
            )
        return AccountsOverview(accounts=items, totals=totals_by_currency(headlines))
