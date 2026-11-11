"""Yapily adapter (sandbox and production share the API).

Field names follow Yapily's API reference (docs.yapily.com): HTTP Basic auth with
the application UUID/secret, the consent token in a ``consent`` header, response
payloads under ``data``. The consent flow uses ``oneTimeToken: true`` so the real
consent token never appears in a browser URL: the callback carries a short-lived
one-time token that we exchange server-side.

Responses are parsed with ``Decimal`` for JSON numbers (money must not pass
through float). Errors never include response bodies, which hold personal data.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from finance_app.core.config import Settings
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

ONE_TIME_TOKEN_PARAM = "one-time-token"  # noqa: S105 - a query parameter name
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MASKABLE_IDENTIFIERS = ("IBAN", "ACCOUNT_NUMBER", "BBAN")
TRANSACTIONS_PAGE_SIZE = 1000  # Yapily maximum
CLOCK_SKEW_MARGIN = timedelta(minutes=2)
TRANSACTION_WINDOW_DAYS = 31


class _RetryableError(ProviderError):
    """Transient failure worth retrying (network error, 429, 5xx)."""


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableError)


def _fields(document: dict[str, Any]) -> str:
    """Field names of a response, for error messages. Never values: they hold personal data."""
    return ", ".join(sorted(str(k) for k in document)) or "none"


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class YapilyProvider:
    """``BankProvider`` implementation for Yapily.

    Args:
        client: An ``httpx.AsyncClient`` with Yapily's base URL and Basic auth set.
        retry_attempts: Attempts for idempotent GETs (1 disables retries).
        retry_wait_seconds: Initial backoff; doubles each retry.
    """

    name = "yapily"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        retry_attempts: int = 3,
        retry_wait_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._retry_attempts = retry_attempts
        self._retry_wait = retry_wait_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "YapilyProvider":
        """Build a provider with its own HTTP client from settings."""
        if not (settings.yapily_application_uuid and settings.yapily_application_secret):
            raise ProviderError("Yapily credentials are not configured")
        client = httpx.AsyncClient(
            base_url=settings.yapily_base_url,
            auth=httpx.BasicAuth(
                settings.yapily_application_uuid,
                settings.yapily_application_secret.get_secret_value(),
            ),
            timeout=settings.provider_timeout_seconds,
            headers={"Accept": "application/json"},
        )
        return cls(client)

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------ HTTP

    async def _send(
        self,
        method: str,
        path: str,
        *,
        consent: str | None = None,
        body: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        wrapped: bool = True,
    ) -> dict[str, Any]:
        """Send one request and return the whole response document.

        ``wrapped`` requires Yapily's usual ``{"meta", "data"}`` envelope. Errors name
        the fields that were present (keys only, never values).
        """
        headers = {"consent": consent} if consent else None
        try:
            response = await self._client.request(
                method, path, headers=headers, json=body, params=params
            )
        except httpx.TransportError as exc:
            raise _RetryableError(f"yapily {method} {path}: {type(exc).__name__}") from exc
        status = response.status_code
        if consent and status in (401, 403):
            raise ProviderAuthError(f"yapily {method} {path} -> {status}")
        if status in _RETRYABLE_STATUS:
            raise _RetryableError(f"yapily {method} {path} -> {status}")
        if status >= 400:
            raise ProviderError(f"yapily {method} {path} -> {status}")
        try:
            document = json.loads(response.content, parse_float=Decimal)
        except ValueError as exc:
            raise ProviderError(f"yapily {method} {path}: unexpected response") from exc
        if not isinstance(document, dict):
            raise ProviderError(f"yapily {method} {path}: response is not a JSON object")
        if wrapped and "data" not in document:
            raise ProviderError(
                f"yapily {method} {path}: no 'data' in response (fields: {_fields(document)})"
            )
        return document

    async def _with_retries(
        self,
        method: str,
        path: str,
        *,
        consent: str | None = None,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        """Idempotent request (GET, DELETE) with retries on transient failures."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=self._retry_wait, max=8),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._send(method, path, consent=consent, params=params)
        raise ProviderError("unreachable")  # pragma: no cover

    async def _get(self, path: str, *, consent: str | None = None) -> Any:
        """GET with retries; returns the ``data`` member."""
        return (await self._with_retries("GET", path, consent=consent))["data"]

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        """POST without retries (creating consents is not idempotent); returns ``data``."""
        try:
            return (await self._send("POST", path, body=body))["data"]
        except _RetryableError as exc:
            raise ProviderError(str(exc)) from exc

    # ------------------------------------------------------------------ API

    async def list_institutions(self, country: str) -> list[Institution]:
        """Institutions that list ``country`` among their countries."""
        data = await self._get("/institutions")
        country = country.upper()
        result = []
        for item in data:
            codes = tuple(c.get("countryCode2", "") for c in item.get("countries", []))
            if country not in codes:
                continue
            logo = next(
                (m["source"] for m in item.get("media", []) if m.get("type") in ("icon", "logo")),
                None,
            )
            result.append(
                Institution(
                    id=item["id"],
                    name=item.get("fullName") or item.get("name") or item["id"],
                    countries=codes,
                    logo_url=logo,
                )
            )
        return result

    async def create_consent(
        self, user_ref: str, institution_id: str, callback_url: str
    ) -> ConsentStart:
        """Create an account authorisation request with a one-time-token callback."""
        data = await self._post(
            "/account-auth-requests",
            {
                "applicationUserId": user_ref,
                "institutionId": institution_id,
                "callback": callback_url,
                "oneTimeToken": True,
            },
        )
        return ConsentStart(authorisation_url=data["authorisationUrl"])

    async def complete_consent(self, callback_params: Mapping[str, str]) -> ConsentResult:
        """Exchange the callback's one-time token for the consent."""
        if "error" in callback_params:
            raise ConsentRejectedError(callback_params["error"])
        one_time_token = callback_params.get(ONE_TIME_TOKEN_PARAM)
        if not one_time_token:
            raise ProviderError("callback has no one-time token")
        try:
            document = await self._send(
                "POST",
                "/consent-one-time-token",
                body={"oneTimeToken": one_time_token},
                wrapped=False,
            )
        except _RetryableError as exc:
            raise ProviderError(str(exc)) from exc
        # Seen in the sandbox: this endpoint may answer with the Consent object itself
        # rather than inside the usual "data" envelope, so accept both shapes.
        data = document.get("data", document)
        if not isinstance(data, dict):
            raise ProviderError("yapily consent exchange: 'data' is not an object")
        status = data.get("status")
        if status in ("REJECTED", "FAILED", "REVOKED", "EXPIRED"):
            raise ConsentRejectedError(str(status).lower())
        token = data.get("consentToken")
        if not token:
            raise ProviderError(
                f"yapily consent exchange: no consentToken (fields: {_fields(data)})"
            )
        return ConsentResult(
            consent_token=SecretStr(token),
            consent_id=data.get("id"),
            expires_at=_parse_datetime(data.get("expiresAt") or data.get("reconfirmBy")),
        )

    async def get_accounts(self, consent_token: str) -> list[ProviderAccount]:
        """Accounts covered by the consent, with masked account numbers."""
        data = await self._get("/accounts", consent=consent_token)
        accounts = []
        for item in data:
            identifications = {
                i.get("type"): i.get("identification", "")
                for i in item.get("accountIdentifications", [])
            }
            masked = next(
                (
                    mask_account_number(identifications[k])
                    for k in _MASKABLE_IDENTIFIERS
                    if identifications.get(k)
                ),
                None,
            )
            names = item.get("accountNames") or []
            accounts.append(
                ProviderAccount(
                    provider_account_id=item["id"],
                    name=item.get("nickname")
                    or (names[0].get("name") if names else None)
                    or item.get("description")
                    or item.get("type")
                    or "Account",
                    type=item.get("accountType") or item.get("type") or "UNKNOWN",
                    currency=item.get("currency", "XXX"),
                    account_number_masked=masked,
                )
            )
        return accounts

    async def get_balances(self, consent_token: str, account_id: str) -> list[ProviderBalance]:
        """All reported balance types of one account."""
        data = await self._get(
            f"/accounts/{quote(account_id, safe='')}/balances", consent=consent_token
        )
        balances = []
        for item in data.get("balances", []):
            amount = item["balanceAmount"]
            balances.append(
                ProviderBalance(
                    type=item.get("type", "UNKNOWN"),
                    amount=Decimal(amount["amount"]),
                    currency=amount["currency"],
                    as_of=_parse_datetime(item.get("dateTime")) or datetime.now().astimezone(),
                )
            )
        return balances

    async def get_transactions(
        self, consent_token: str, account_id: str, date_from: date, date_to: date
    ) -> list[ProviderTransaction]:
        """Transactions booked or pending between two dates (inclusive), all pages.

        Fetched in windows of ``TRANSACTION_WINDOW_DAYS``: with Modelo Sandbox one
        30-day window answered in 1.4-3.1 s, a 365-day request took 24-28 s per page
        and timed out. Each window is still paged with ``limit`` / ``offset``.
        """
        transactions: list[ProviderTransaction] = []
        start = date_from
        while start <= date_to:
            end = min(start + timedelta(days=TRANSACTION_WINDOW_DAYS - 1), date_to)
            transactions.extend(
                await self._transactions_window(consent_token, account_id, start, end)
            )
            start = end + timedelta(days=1)
        return transactions

    async def _transactions_window(
        self, consent_token: str, account_id: str, date_from: date, date_to: date
    ) -> list[ProviderTransaction]:
        """One window of transactions, all of its pages."""
        path = f"/accounts/{quote(account_id, safe='')}/transactions"
        params: dict[str, str | int] = {
            "from": _yapily_datetime(datetime.combine(date_from, time.min, UTC)),
            "before": _yapily_datetime(_transactions_before(date_to)),
            "limit": TRANSACTIONS_PAGE_SIZE,
            "sort": "date",
        }
        transactions: list[ProviderTransaction] = []
        offset = 0
        while True:
            document = await self._with_retries(
                "GET", path, consent=consent_token, params={**params, "offset": offset}
            )
            page = document["data"]
            transactions.extend(_to_transaction(item) for item in page)
            total = document.get("meta", {}).get("pagination", {}).get("totalCount")
            offset += len(page)
            if (
                not page
                or len(page) < TRANSACTIONS_PAGE_SIZE
                or (total is not None and offset >= total)
            ):
                return transactions

    async def revoke_consent(self, consent_id: str) -> None:
        """Delete the consent at Yapily (and at the bank). Idempotent, so retried."""
        document = await self._with_retries("DELETE", f"/consents/{quote(consent_id, safe='')}")
        if document["data"].get("deleteStatus") not in (None, "SUCCESS"):
            raise ProviderError("yapily consent deletion failed")


def _transactions_before(date_to: date, now: datetime | None = None) -> datetime:
    """End of ``date_to``, but never later than now minus a safety margin.

    Yapily rejects a ``before`` in the future ("The before date cannot be in the
    future", seen with Modelo Sandbox), and our clock can run a few seconds ahead of
    theirs. The next sync's overlap window picks up anything in the margin.
    """
    latest = (now or datetime.now(UTC)) - CLOCK_SKEW_MARGIN
    return min(datetime.combine(date_to, time.max, UTC), latest)


def _yapily_datetime(value: datetime) -> str:
    """Format as Yapily expects: ``yyyy-MM-dd'T'HH:mm:ss.SSSZ`` in UTC."""
    return (
        value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"
    )


def _to_transaction(item: dict[str, Any]) -> ProviderTransaction:
    """Map one Yapily transaction to the provider-neutral DTO."""
    amount = item.get("transactionAmount") or {
        "amount": item.get("amount"),
        "currency": item.get("currency"),
    }
    booked_at = _parse_datetime(item.get("bookingDateTime") or item.get("date"))
    if booked_at is None or amount.get("amount") is None:
        raise ProviderError("transaction without date or amount")
    merchant = (item.get("merchant") or {}).get("merchantName")
    description = (
        item.get("description")
        or " ".join(item.get("transactionInformation") or [])
        or item.get("reference")
        or merchant
        or ""
    )
    return ProviderTransaction(
        provider_transaction_id=item.get("id") or None,
        booking_date=booked_at.date(),
        amount=Decimal(amount["amount"]),
        currency=amount.get("currency") or item.get("currency") or "XXX",
        description=description.strip()[:500],
        merchant=merchant,
        status="pending" if item.get("status") == "PENDING" else "booked",
    )
