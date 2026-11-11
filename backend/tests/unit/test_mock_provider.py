"""Mock provider used for offline demos and tests."""

from urllib.parse import parse_qs, urlsplit

import pytest

from finance_app.providers.base import ConsentRejectedError, ProviderAuthError, ProviderError
from finance_app.providers.mock import MockProvider

provider = MockProvider("http://api.test")


async def test_institutions_are_filtered_by_country() -> None:
    gb = {i.id for i in await provider.list_institutions("gb")}
    ie = {i.id for i in await provider.list_institutions("IE")}

    assert gb == {"mock-bank-uk", "mock-credit-union"}
    assert ie == {"mock-credit-union"}


async def test_create_consent_points_at_the_mock_bank_page() -> None:
    start = await provider.create_consent("user-1", "mock-bank-uk", "http://api.test/cb?state=s")

    url = urlsplit(start.authorisation_url)
    assert url.path == "/api/v1/mock-bank/authorize"
    assert parse_qs(url.query)["callback"] == ["http://api.test/cb?state=s"]


async def test_unknown_institution_is_rejected() -> None:
    with pytest.raises(ProviderError):
        await provider.create_consent("user-1", "nope", "http://api.test/cb")


async def test_consent_round_trip_gives_accounts_and_balances() -> None:
    token = MockProvider.one_time_token("mock-bank-uk")

    consent = await provider.complete_consent({"one-time-token": token})
    accounts = await provider.get_accounts(consent.consent_token.get_secret_value())
    balances = await provider.get_balances(
        consent.consent_token.get_secret_value(), accounts[0].provider_account_id
    )

    assert consent.expires_at is not None
    assert [a.currency for a in accounts] == ["GBP", "GBP"]
    assert accounts[0].account_number_masked == "•••• 5555"
    assert {b.type for b in balances} == {"INTERIM_AVAILABLE", "CLOSING_BOOKED"}


async def test_cancel_raises_consent_rejected() -> None:
    with pytest.raises(ConsentRejectedError) as exc_info:
        await provider.complete_consent({"error": "access_denied", "error-source": "user"})

    assert exc_info.value.reason == "access_denied"


async def test_bad_tokens_are_rejected() -> None:
    with pytest.raises(ProviderError):
        await provider.complete_consent({"one-time-token": "forged"})
    with pytest.raises(ProviderAuthError):
        await provider.get_accounts("mock-consent.unknown-bank.x")
