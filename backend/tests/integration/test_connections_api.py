"""BR-02 (connect a bank by consent) and BR-05 (all accounts in one view).

Runs the real flow through the HTTP API with the mock provider: start consent,
visit the mock bank page, follow Approve/Cancel to the callback, run a real arq
worker, then read accounts. Postgres and Redis are real (testcontainers).
"""

import re
import uuid
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Settings
from finance_app.core.crypto import TokenCipher
from finance_app.modules.accounts.models import Account
from finance_app.modules.connections.models import BankConnection, ConnectionStatus
from finance_app.modules.connections.sync import ConnectionSyncService
from finance_app.providers.mock import MockProvider
from tests.integration.conftest import run_worker_burst

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"


async def _sign_in(api: AsyncClient, email: str = "sara@example.com") -> dict[str, str]:
    await api.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    tokens = (
        await api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


async def _start(api: AsyncClient, headers: dict[str, str], institution: str) -> dict[str, Any]:
    response = await api.post(
        "/api/v1/connections", json={"institution_id": institution}, headers=headers
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _bank_link(api: AsyncClient, authorisation_url: str, button: str) -> str:
    """Open the mock bank page and return the Approve or Cancel link."""
    page = await api.get(_path(authorisation_url))
    assert page.status_code == 200
    match = re.search(rf'class="{button}" href="([^"]+)"', page.text)
    assert match, page.text
    return unescape(match.group(1))


async def _connect(api: AsyncClient, headers: dict[str, str], institution: str) -> Response:
    started = await _start(api, headers, institution)
    approve = await _bank_link(api, started["authorisation_url"], "approve")
    return await api.get(_path(approve))


def _redirect_status(response: Response) -> str:
    assert response.status_code == 303
    return parse_qs(urlsplit(response.headers["location"]).query)["status"][0]


# ---------------------------------------------------------------- happy path


async def test_connecting_two_banks_shows_all_accounts_and_totals_br02_br05(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    banks = await api.get("/api/v1/institutions", params={"country": "GB"}, headers=headers)
    assert {b["id"] for b in banks.json()} == {"mock-bank-uk", "mock-credit-union"}

    callback = await _connect(api, headers, "mock-bank-uk")

    assert _redirect_status(callback) == "connected"
    assert callback.headers["location"].startswith(
        f"{migrated_settings.web_app_url}/connections/result?"
    )

    await _connect(api, headers, "mock-credit-union")
    await run_worker_burst(migrated_settings)  # the queued first syncs

    overview = (await api.get("/api/v1/accounts", headers=headers)).json()
    accounts = {a["name"]: a for a in overview["accounts"]}
    assert set(accounts) == {"Everyday Current", "Rainy Day Saver", "Euro Current", "Credit Card"}
    current = accounts["Everyday Current"]
    assert current["institution_name"] == "Mock Bank (UK)"
    assert current["account_number_masked"] == "•••• 5555"
    assert current["balance"] == {
        "type": "INTERIM_AVAILABLE",
        "amount": "1523.47",  # decimal string, available preferred over booked
        "currency": "GBP",
        "as_of": current["balance"]["as_of"],
    }
    assert len(current["balances"]) == 2
    assert overview["totals"] == [
        {"currency": "EUR", "amount": "642.10", "account_count": 1},
        {"currency": "GBP", "amount": "9477.57", "account_count": 3},
    ]

    connections = (await api.get("/api/v1/connections", headers=headers)).json()
    assert {c["status"] for c in connections} == {"active"}
    assert all(c["last_synced_at"] for c in connections)
    assert all("token" not in key for c in connections for key in c)


async def test_consent_token_is_stored_encrypted_nfr01(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers, "mock-bank-uk")

    connection = (await db.execute(select(BankConnection))).scalar_one()

    assert connection.consent_token_enc is not None
    assert connection.consent_token_enc.startswith("v1:")
    assert "mock-consent" not in connection.consent_token_enc
    cipher = TokenCipher(migrated_settings.encryption_keys(), 1)
    plaintext = cipher.decrypt(connection.consent_token_enc, associated_data=connection.id.bytes)
    assert plaintext.startswith("mock-consent.mock-bank-uk.")


# ---------------------------------------------------------------- cancel and errors


async def test_cancel_at_bank_stores_nothing_br02(api: AsyncClient, db: AsyncSession) -> None:
    headers = await _sign_in(api)
    started = await _start(api, headers, "mock-bank-uk")
    cancel = await _bank_link(api, started["authorisation_url"], "cancel")

    callback = await api.get(_path(cancel))

    assert _redirect_status(callback) == "cancelled"
    assert (await db.execute(select(func.count()).select_from(BankConnection))).scalar() == 0
    assert (await api.get("/api/v1/connections", headers=headers)).json() == []


async def test_state_is_single_use_br02(api: AsyncClient) -> None:
    headers = await _sign_in(api)
    started = await _start(api, headers, "mock-bank-uk")
    approve = _path(await _bank_link(api, started["authorisation_url"], "approve"))

    first, replay = await api.get(approve), await api.get(approve)

    assert _redirect_status(first) == "connected"
    assert _redirect_status(replay) == "invalid_state"


@pytest.mark.parametrize("query", ["", "?state=forged&one-time-token=x", f"?state={'a' * 500}"])
async def test_unknown_or_missing_state_is_rejected_br02(api: AsyncClient, query: str) -> None:
    response = await api.get(f"/api/v1/connections/callback{query}")

    assert _redirect_status(response) == "invalid_state"


async def test_forged_one_time_token_creates_no_connection(
    api: AsyncClient, db: AsyncSession
) -> None:
    headers = await _sign_in(api)
    started = await _start(api, headers, "mock-bank-uk")
    callback = parse_qs(urlsplit(started["authorisation_url"]).query)["callback"][0]

    response = await api.get(_path(f"{callback}&one-time-token=forged"))

    assert _redirect_status(response) == "error"
    assert (await db.execute(select(func.count()).select_from(BankConnection))).scalar() == 0


async def test_unknown_institution_is_404(api: AsyncClient) -> None:
    headers = await _sign_in(api)

    response = await api.post(
        "/api/v1/connections", json={"institution_id": "no-such-bank"}, headers=headers
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/institutions"), ("GET", "/api/v1/connections"), ("GET", "/api/v1/accounts")],
)
async def test_bank_endpoints_require_authentication(
    api: AsyncClient, method: str, path: str
) -> None:
    assert (await api.request(method, path)).status_code == 401


async def test_mock_bank_never_redirects_to_another_site(api: AsyncClient) -> None:
    response = await api.get(
        "/api/v1/mock-bank/authorize",
        params={"institution": "mock-bank-uk", "callback": "https://evil.example/steal?"},
    )

    assert response.status_code == 400


# ---------------------------------------------------------------- isolation and sync


async def test_users_never_see_each_others_banks_or_accounts(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    sara = await _sign_in(api, "sara@example.com")
    omar = await _sign_in(api, "omar@example.com")
    await _connect(api, sara, "mock-bank-uk")
    await run_worker_burst(migrated_settings)

    assert (await api.get("/api/v1/connections", headers=omar)).json() == []
    assert (await api.get("/api/v1/accounts", headers=omar)).json() == {
        "accounts": [],
        "totals": [],
    }


async def test_sync_is_idempotent_br05(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers, "mock-bank-uk")
    connection = (await db.execute(select(BankConnection))).scalar_one()
    cipher = TokenCipher(migrated_settings.encryption_keys(), 1)
    service = ConnectionSyncService(db, MockProvider(migrated_settings.public_api_url), cipher)

    first = await service.sync(connection.id)
    second = await service.sync(connection.id)
    assert first is not None and second is not None
    assert first.accounts == second.accounts == 2

    assert (await db.execute(select(func.count()).select_from(Account))).scalar() == 2


async def test_expired_consent_marks_connection_needs_renewal(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    user_id = (await api.get("/api/v1/me", headers=headers)).json()["id"]
    cipher = TokenCipher(migrated_settings.encryption_keys(), 1)
    connection = BankConnection(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        provider="mock",
        institution_id="mock-bank-uk",
        institution_name="Mock Bank (UK)",
        status=ConnectionStatus.ACTIVE,
    )
    # A token the provider no longer accepts (as after expiry or revocation at the bank).
    connection.consent_token_enc = cipher.encrypt(
        SecretStr("mock-consent.revoked-bank.x").get_secret_value(),
        associated_data=connection.id.bytes,
    )
    db.add(connection)
    await db.commit()

    service = ConnectionSyncService(db, MockProvider(migrated_settings.public_api_url), cipher)
    assert await service.sync(connection.id) is None

    await db.refresh(connection)
    assert connection.status is ConnectionStatus.NEEDS_RENEWAL
    listed = (await api.get("/api/v1/connections", headers=headers)).json()
    assert [c["status"] for c in listed] == ["needs_renewal"]
