"""Offline mock provider with a demo "bank" page, for tests and demos.

The consent flow mirrors a real provider: ``create_consent`` returns a URL to the
mock bank page (served by this API, see ``api/v1/mock_bank.py``), which redirects
back to the callback with a one-time token, or with an error on cancel.
Accounts and balances are deterministic per institution.
"""

import random
import secrets
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from urllib.parse import urlencode

from pydantic import SecretStr

from finance_app.providers.base import (
    ConsentRejectedError,
    ConsentResult,
    ConsentStart,
    Institution,
    ProviderAccount,
    ProviderAuthError,
    ProviderBalance,
    ProviderError,
    ProviderTransaction,
    mask_account_number,
)

MOCK_CONSENT_DAYS = 90
_ONE_TIME_PREFIX = "mock-ott"
_CONSENT_PREFIX = "mock-consent"

INSTITUTIONS: tuple[Institution, ...] = (
    Institution(id="mock-bank-uk", name="Mock Bank (UK)", countries=("GB",)),
    Institution(id="mock-credit-union", name="Mock Credit Union", countries=("GB", "IE")),
)

# provider_account_id -> (name, type, currency, identification, balances)
_ACCOUNTS: dict[str, list[tuple[str, str, str, str, str, dict[str, str]]]] = {
    "mock-bank-uk": [
        (
            "acc-uk-current",
            "Everyday Current",
            "CURRENT",
            "GBP",
            "GB33BUKB20201555555555",
            {"INTERIM_AVAILABLE": "1523.47", "CLOSING_BOOKED": "1610.02"},
        ),
        (
            "acc-uk-savings",
            "Rainy Day Saver",
            "SAVINGS",
            "GBP",
            "GB94BARC10201530093459",
            {"INTERIM_AVAILABLE": "8200.00"},
        ),
    ],
    "mock-credit-union": [
        (
            "acc-cu-current",
            "Euro Current",
            "CURRENT",
            "EUR",
            "IE29AIBK93115212345678",
            {"INTERIM_AVAILABLE": "642.10"},
        ),
        (
            "acc-cu-card",
            "Credit Card",
            "CREDIT_CARD",
            "GBP",
            "00004321",
            {"INTERIM_AVAILABLE": "-245.90"},
        ),
    ],
}


def _institution_from_token(token: str, prefix: str) -> str:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != prefix or parts[1] not in _ACCOUNTS:
        raise ProviderAuthError("unknown mock token")
    return parts[1]


class MockProvider:
    """``BankProvider`` implementation backed by fixed demo data.

    Args:
        public_api_url: Base URL browsers use to reach this API (for the bank page).
    """

    name = "mock"

    def __init__(self, public_api_url: str) -> None:
        self._public_api_url = public_api_url.rstrip("/")

    async def list_institutions(self, country: str) -> list[Institution]:
        """Mock banks available in ``country``."""
        return [i for i in INSTITUTIONS if country.upper() in i.countries]

    async def create_consent(
        self, user_ref: str, institution_id: str, callback_url: str
    ) -> ConsentStart:
        """Send the user to the mock bank's approval page."""
        if institution_id not in _ACCOUNTS:
            raise ProviderError(f"unknown institution {institution_id}")
        query = urlencode({"institution": institution_id, "callback": callback_url})
        return ConsentStart(
            authorisation_url=f"{self._public_api_url}/api/v1/mock-bank/authorize?{query}"
        )

    @staticmethod
    def one_time_token(institution_id: str) -> str:
        """Token the mock bank page appends to the callback on approval."""
        return f"{_ONE_TIME_PREFIX}.{institution_id}.{secrets.token_urlsafe(8)}"

    async def complete_consent(self, callback_params: Mapping[str, str]) -> ConsentResult:
        """Exchange the mock one-time token, or raise if the user cancelled."""
        if "error" in callback_params:
            raise ConsentRejectedError(callback_params["error"])
        token = callback_params.get("one-time-token", "")
        try:
            institution = _institution_from_token(token, _ONE_TIME_PREFIX)
        except ProviderAuthError as exc:
            raise ProviderError("invalid one-time token") from exc
        return ConsentResult(
            consent_token=SecretStr(f"{_CONSENT_PREFIX}.{institution}.{secrets.token_urlsafe(16)}"),
            consent_id=f"mock-consent-{secrets.token_hex(8)}",
            expires_at=datetime.now(UTC) + timedelta(days=MOCK_CONSENT_DAYS),
        )

    async def get_accounts(self, consent_token: str) -> list[ProviderAccount]:
        """The fixed accounts of the consent's institution."""
        institution = _institution_from_token(consent_token, _CONSENT_PREFIX)
        return [
            ProviderAccount(
                provider_account_id=account_id,
                name=name,
                type=account_type,
                currency=currency,
                account_number_masked=mask_account_number(identification),
            )
            for account_id, name, account_type, currency, identification, _ in _ACCOUNTS[
                institution
            ]
        ]

    async def get_balances(self, consent_token: str, account_id: str) -> list[ProviderBalance]:
        """The fixed balances of one account."""
        institution = _institution_from_token(consent_token, _CONSENT_PREFIX)
        for acc_id, _, _, currency, _, balances in _ACCOUNTS[institution]:
            if acc_id == account_id:
                now = datetime.now(UTC)
                return [
                    ProviderBalance(type=t, amount=Decimal(a), currency=currency, as_of=now)
                    for t, a in balances.items()
                ]
        raise ProviderError(f"unknown account {account_id}")

    async def get_transactions(
        self, consent_token: str, account_id: str, date_from: date, date_to: date
    ) -> list[ProviderTransaction]:
        """Deterministic demo transactions; the last two days are pending.

        A pending transaction gets a new ID (``p-`` → ``b-``) once it books, as with
        many real banks, which exercises the sync's pending-cleanup logic.
        """
        institution = _institution_from_token(consent_token, _CONSENT_PREFIX)
        account = next((a for a in _ACCOUNTS[institution] if a[0] == account_id), None)
        if account is None:
            raise ProviderError(f"unknown account {account_id}")
        currency, account_type = account[3], account[2]
        today = datetime.now(UTC).date()
        result: list[ProviderTransaction] = []
        day = max(date_from, today - timedelta(days=MOCK_HISTORY_DAYS))
        while day <= min(date_to, today):
            result.extend(_mock_day(account_id, account_type, currency, day, today))
            day += timedelta(days=1)
        return result

    async def revoke_consent(self, consent_id: str) -> None:
        """Nothing to revoke for demo consents."""
        if not consent_id:
            raise ProviderError("missing consent id")


MOCK_HISTORY_DAYS = 400
PENDING_DAYS = 2
_MERCHANTS: tuple[tuple[str, str, int, int], ...] = (
    # (merchant, description, min pence, max pence)
    ("Tesco", "TESCO STORES 2041", 450, 8900),
    ("Pret A Manger", "PRET A MANGER LONDON", 280, 1450),
    ("TfL", "TFL TRAVEL CHARGE", 175, 1260),
    ("Netflix", "NETFLIX.COM", 1099, 1099),
    ("Deliveroo", "DELIVEROO", 1500, 4200),
    ("Amazon", "AMAZON MKTPLACE", 699, 6499),
    ("Shell", "SHELL KINGS CROSS", 3000, 7500),
    ("Boots", "BOOTS 1123", 350, 2800),
)


def _mock_day(
    account_id: str, account_type: str, currency: str, day: date, today: date
) -> list[ProviderTransaction]:
    """Transactions for one account on one day, the same on every call."""
    rng = random.Random(f"{account_id}:{day.isoformat()}")  # noqa: S311 - demo data, not security
    pending = day > today - timedelta(days=PENDING_DAYS)
    prefix = "p" if pending else "b"
    status: Literal["booked", "pending"] = "pending" if pending else "booked"
    rows: list[ProviderTransaction] = []
    if account_type == "SAVINGS":
        if day.day == 1:
            rows.append(
                ProviderTransaction(
                    provider_transaction_id=f"{prefix}-{account_id}-{day}-0",
                    booking_date=day,
                    amount=Decimal("250.00"),
                    currency=currency,
                    description="TRANSFER FROM CURRENT",
                    merchant=None,
                    status=status,
                )
            )
        return rows
    if day.day == 25 and account_type == "CURRENT":
        rows.append(
            ProviderTransaction(
                provider_transaction_id=f"{prefix}-{account_id}-{day}-salary",
                booking_date=day,
                amount=Decimal("2850.00"),
                currency=currency,
                description="ACME LTD SALARY",
                merchant="Acme Ltd",
                status=status,
            )
        )
    for index in range(rng.randint(0, 3)):
        merchant, description, low, high = rng.choice(_MERCHANTS)
        pence = rng.randint(low, high)
        rows.append(
            ProviderTransaction(
                provider_transaction_id=f"{prefix}-{account_id}-{day}-{index}",
                booking_date=day,
                amount=-(Decimal(pence) / 100),
                currency=currency,
                description=description,
                merchant=merchant,
                status=status,
            )
        )
    return rows
