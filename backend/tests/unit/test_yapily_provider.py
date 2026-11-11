"""Contract tests for the Yapily adapter (respx; no network).

Payloads follow the shapes in Yapily's API reference (docs.yapily.com).
"""

import json
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from finance_app.core.config import Settings
from finance_app.providers.base import ConsentRejectedError, ProviderAuthError, ProviderError
from finance_app.providers.yapily import YapilyProvider

BASE = "https://api.yapily.test"


@pytest.fixture
async def yapily() -> AsyncIterator[YapilyProvider]:
    client = httpx.AsyncClient(base_url=BASE, auth=httpx.BasicAuth("app-uuid", "app-secret"))
    provider = YapilyProvider(client, retry_attempts=3, retry_wait_seconds=0)
    yield provider
    await provider.aclose()


def _json(body: str) -> httpx.Response:
    """Respond with raw JSON text so number formatting is exactly as sent."""
    return httpx.Response(200, content=body.encode(), headers={"content-type": "application/json"})


@respx.mock
async def test_list_institutions_filters_by_country_and_maps_logo(yapily: YapilyProvider) -> None:
    respx.get(f"{BASE}/institutions").respond(
        200,
        json={
            "meta": {"count": 2},
            "data": [
                {
                    "id": "modelo-sandbox",
                    "name": "Modelo Sandbox",
                    "fullName": "Modelo Sandbox Bank",
                    "countries": [{"countryCode2": "IT"}, {"countryCode2": "GB"}],
                    "media": [{"source": "https://img/icon.png", "type": "icon"}],
                },
                {"id": "de-only", "name": "DE Bank", "countries": [{"countryCode2": "DE"}]},
            ],
        },
    )

    institutions = await yapily.list_institutions("gb")

    assert [(i.id, i.name, i.logo_url) for i in institutions] == [
        ("modelo-sandbox", "Modelo Sandbox Bank", "https://img/icon.png")
    ]


@respx.mock
async def test_create_consent_asks_for_one_time_token_br02(yapily: YapilyProvider) -> None:
    route = respx.post(f"{BASE}/account-auth-requests").respond(
        201,
        json={
            "data": {
                "id": "auth-1",
                "status": "AWAITING_AUTHORIZATION",
                "authorisationUrl": "https://bank.example/auth?x=1",
            }
        },
    )

    start = await yapily.create_consent("user-1", "modelo-sandbox", "https://api/cb?state=s")

    assert start.authorisation_url == "https://bank.example/auth?x=1"
    request = route.calls.last.request
    assert json.loads(request.content) == {
        "applicationUserId": "user-1",
        "institutionId": "modelo-sandbox",
        "callback": "https://api/cb?state=s",
        "oneTimeToken": True,
    }
    assert request.headers["authorization"].startswith("Basic ")


@respx.mock
async def test_complete_consent_exchanges_one_time_token(yapily: YapilyProvider) -> None:
    route = respx.post(f"{BASE}/consent-one-time-token").respond(
        201,
        json={
            "data": {
                "id": "consent-1",
                "status": "AUTHORIZED",
                "consentToken": "real-consent-token",
                "expiresAt": "2027-02-09T08:03:20.510Z",
            }
        },
    )

    consent = await yapily.complete_consent({"one-time-token": "ott-123", "institution": "x"})

    assert json.loads(route.calls.last.request.content) == {"oneTimeToken": "ott-123"}
    assert consent.consent_token.get_secret_value() == "real-consent-token"
    assert consent.consent_id == "consent-1"
    assert consent.expires_at is not None and consent.expires_at.year == 2027
    assert "real-consent-token" not in repr(consent)


async def test_complete_consent_reports_user_cancel(yapily: YapilyProvider) -> None:
    with pytest.raises(ConsentRejectedError) as exc_info:
        await yapily.complete_consent(
            {"error": "access_denied", "error-source": "user", "institution": "x"}
        )

    assert exc_info.value.reason == "access_denied"


async def test_complete_consent_without_token_is_an_error(yapily: YapilyProvider) -> None:
    with pytest.raises(ProviderError):
        await yapily.complete_consent({"institution": "x"})


@respx.mock
async def test_rejected_consent_status_is_reported(yapily: YapilyProvider) -> None:
    respx.post(f"{BASE}/consent-one-time-token").respond(
        201, json={"data": {"id": "c", "status": "REJECTED"}}
    )

    with pytest.raises(ConsentRejectedError):
        await yapily.complete_consent({"one-time-token": "ott"})


@respx.mock
async def test_get_accounts_sends_consent_and_masks_identifiers_br05(
    yapily: YapilyProvider,
) -> None:
    route = respx.get(f"{BASE}/accounts").mock(
        return_value=_json(
            """{"data": [
              {"id": "700004000000000000000002", "type": "Personal - Current",
               "currency": "GBP", "accountType": "CURRENT", "nickname": "Joint account",
               "accountNames": [{"name": "Mr. R Rastapopoulos"}],
               "accountIdentifications": [
                 {"type": "SORT_CODE", "identification": "700001"},
                 {"type": "ACCOUNT_NUMBER", "identification": "70000002"}]},
              {"id": "acc-2", "type": "Personal - Savings", "currency": "EUR",
               "accountNames": [{"name": "Savings"}],
               "accountIdentifications": [
                 {"type": "IBAN", "identification": "IE29 AIBK 9311 5212 3456 78"}]}
            ]}"""
        )
    )

    accounts = await yapily.get_accounts("consent-token")

    assert route.calls.last.request.headers["consent"] == "consent-token"
    assert [(a.name, a.type, a.currency, a.account_number_masked) for a in accounts] == [
        ("Joint account", "CURRENT", "GBP", "•••• 0002"),
        ("Savings", "Personal - Savings", "EUR", "•••• 5678"),
    ]
    assert "IE29" not in repr(accounts)  # full IBAN never leaves the adapter


@respx.mock
async def test_balances_keep_exact_decimal_amounts(yapily: YapilyProvider) -> None:
    respx.get(f"{BASE}/accounts/acc%2F1/balances").mock(
        return_value=_json(
            """{"data": {"mainBalanceAmount": {"amount": 1523.47, "currency": "GBP"},
               "balances": [
                 {"type": "INTERIM_AVAILABLE", "dateTime": "2026-11-11T08:51:02.463Z",
                  "balanceAmount": {"amount": 1523.47, "currency": "GBP"}},
                 {"type": "CLOSING_BOOKED", "dateTime": "2026-11-10T23:59:59Z",
                  "balanceAmount": {"amount": -0.10, "currency": "GBP"}}]}}"""
        )
    )

    balances = await yapily.get_balances("consent-token", "acc/1")  # ID is URL-encoded

    assert [(b.type, b.amount) for b in balances] == [
        ("INTERIM_AVAILABLE", Decimal("1523.47")),
        ("CLOSING_BOOKED", Decimal("-0.10")),
    ]
    assert balances[0].as_of.tzinfo is not None


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_consent_on_data_call_means_needs_renewal(
    yapily: YapilyProvider, status: int
) -> None:
    respx.get(f"{BASE}/accounts").respond(status, json={"error": {"code": status}})

    with pytest.raises(ProviderAuthError):
        await yapily.get_accounts("expired")


@respx.mock
async def test_transient_errors_are_retried_on_get(yapily: YapilyProvider) -> None:
    route = respx.get(f"{BASE}/institutions").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"data": []}),
        ]
    )

    assert await yapily.list_institutions("GB") == []
    assert route.call_count == 3


@respx.mock
async def test_gives_up_after_max_attempts(yapily: YapilyProvider) -> None:
    route = respx.get(f"{BASE}/institutions").respond(502)

    with pytest.raises(ProviderError):
        await yapily.list_institutions("GB")
    assert route.call_count == 3


@respx.mock
async def test_consent_creation_is_never_retried(yapily: YapilyProvider) -> None:
    route = respx.post(f"{BASE}/account-auth-requests").respond(503)

    with pytest.raises(ProviderError):
        await yapily.create_consent("u", "i", "https://api/cb")
    assert route.call_count == 1


@respx.mock
async def test_client_errors_and_bad_payloads_are_provider_errors(yapily: YapilyProvider) -> None:
    respx.get(f"{BASE}/institutions").respond(400, json={"error": {}})
    with pytest.raises(ProviderError, match="400"):
        await yapily.list_institutions("GB")

    respx.get(f"{BASE}/accounts").respond(200, json={"unexpected": True})
    with pytest.raises(ProviderError, match="unexpected response"):
        await yapily.get_accounts("t")


def test_yapily_provider_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="YAPILY_APPLICATION_UUID"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            postgres_password=SecretStr("x"),
            jwt_secret=SecretStr("x" * 32),
            bank_provider="yapily",
        )


async def test_from_settings_builds_an_authenticated_client() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_password=SecretStr("x"),
        jwt_secret=SecretStr("x" * 32),
        bank_provider="yapily",
        yapily_application_uuid="app-uuid",
        yapily_application_secret=SecretStr("app-secret"),
    )

    provider = YapilyProvider.from_settings(settings)
    try:
        assert provider.name == "yapily"
    finally:
        await provider.aclose()
