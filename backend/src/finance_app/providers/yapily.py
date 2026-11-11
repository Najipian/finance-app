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
from datetime import datetime
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
    mask_account_number,
)

ONE_TIME_TOKEN_PARAM = "one-time-token"  # noqa: S105 - a query parameter name
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MASKABLE_IDENTIFIERS = ("IBAN", "ACCOUNT_NUMBER", "BBAN")


class _RetryableError(ProviderError):
    """Transient failure worth retrying (network error, 429, 5xx)."""


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableError)


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
    ) -> Any:
        headers = {"consent": consent} if consent else None
        try:
            response = await self._client.request(method, path, headers=headers, json=body)
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
            return json.loads(response.content, parse_float=Decimal)["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"yapily {method} {path}: unexpected response") from exc

    async def _get(self, path: str, *, consent: str | None = None) -> Any:
        """GET with retries on transient failures (GETs are idempotent)."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=self._retry_wait, max=8),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._send("GET", path, consent=consent)
        raise ProviderError("unreachable")  # pragma: no cover

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        """POST without retries: creating consents is not idempotent."""
        try:
            return await self._send("POST", path, body=body)
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
        data = await self._post("/consent-one-time-token", {"oneTimeToken": one_time_token})
        status = data.get("status")
        if status in ("REJECTED", "FAILED", "REVOKED", "EXPIRED"):
            raise ConsentRejectedError(str(status).lower())
        token = data.get("consentToken")
        if not token:
            raise ProviderError("consent has no token")
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
