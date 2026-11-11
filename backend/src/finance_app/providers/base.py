"""Provider-neutral interface to an Open Banking aggregator (AIS only).

Everything outside ``providers/`` talks to banks only through ``BankProvider`` and
these DTOs, so Yapily can be swapped for TrueLayer (or the mock) without touching
services. Amounts are ``Decimal``; account numbers arrive already masked.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, SecretStr


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Institution(_Frozen):
    """A bank the user can connect to."""

    id: str
    name: str
    countries: tuple[str, ...]
    logo_url: str | None = None


class ConsentStart(_Frozen):
    """Where to send the user to approve access at their bank."""

    authorisation_url: str


class ConsentResult(_Frozen):
    """An approved consent. The token is secret and must be encrypted before storage."""

    consent_token: SecretStr
    consent_id: str | None = None
    expires_at: datetime | None = None


class ProviderAccount(_Frozen):
    """A bank account as reported by the provider."""

    provider_account_id: str
    name: str
    type: str
    currency: str
    account_number_masked: str | None = None


class ProviderBalance(_Frozen):
    """One balance of an account (banks report several types)."""

    type: str
    amount: Decimal
    currency: str
    as_of: datetime


class ProviderTransaction(_Frozen):
    """A transaction as reported by the provider. Debits are negative.

    ``provider_transaction_id`` is optional because some banks omit it, and a pending
    transaction often gets a new ID when it books.
    """

    provider_transaction_id: str | None
    booking_date: date
    amount: Decimal
    currency: str
    description: str
    merchant: str | None = None
    status: Literal["booked", "pending"]


class ProviderError(Exception):
    """The provider failed or returned something we can't use (retryable later)."""


class ProviderAuthError(ProviderError):
    """The consent is no longer valid (expired or revoked at the bank): needs renewal."""


class ConsentRejectedError(ProviderError):
    """The user cancelled or the bank rejected the consent request."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BankProvider(Protocol):
    """Read-only access to bank data through an aggregator."""

    name: str

    async def list_institutions(self, country: str) -> list[Institution]:
        """Banks available in a country (ISO 3166-1 alpha-2, e.g. ``GB``)."""
        ...

    async def create_consent(
        self, user_ref: str, institution_id: str, callback_url: str
    ) -> ConsentStart:
        """Start a consent request; the bank will redirect to ``callback_url``."""
        ...

    async def complete_consent(self, callback_params: Mapping[str, str]) -> ConsentResult:
        """Finish a consent from the callback's query parameters.

        Raises:
            ConsentRejectedError: The user cancelled or the bank refused.
            ProviderError: The provider failed.
        """
        ...

    async def get_accounts(self, consent_token: str) -> list[ProviderAccount]:
        """Accounts covered by the consent."""
        ...

    async def get_balances(self, consent_token: str, account_id: str) -> list[ProviderBalance]:
        """Current balances of one account."""
        ...

    async def get_transactions(
        self, consent_token: str, account_id: str, date_from: date, date_to: date
    ) -> list[ProviderTransaction]:
        """Booked and pending transactions between two dates (inclusive)."""
        ...

    async def revoke_consent(self, consent_id: str) -> None:
        """Revoke the consent at the provider (and the bank). Idempotent."""
        ...


def mask_account_number(identification: str) -> str:
    """Keep only the last four characters of an IBAN or account number."""
    tail = identification.replace(" ", "")[-4:]
    return f"•••• {tail}"
