"""BR-03 (renew), BR-04 (disconnect), BR-06 (transactions, no duplicates), NFR-07.

Real Postgres and Redis. The HTTP flow uses the mock provider; where a test must
control exactly what the bank returns (a pending transaction booking under a new
ID, an outage) it drives the services with a scripted provider.
"""

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Settings
from finance_app.core.crypto import TokenCipher
from finance_app.modules.accounts.models import Account, Balance
from finance_app.modules.connections.lifecycle import ConsentLifecycleService
from finance_app.modules.connections.models import BankConnection, ConnectionStatus
from finance_app.modules.connections.service import ConnectionService
from finance_app.modules.connections.state import ConsentStateStore
from finance_app.modules.connections.sync import ConnectionSyncService
from finance_app.modules.transactions.models import Transaction, TransactionStatus
from finance_app.providers.base import ProviderError, ProviderTransaction
from finance_app.providers.mock import MockProvider
from finance_app.worker.settings import schedule_syncs
from tests.integration.conftest import run_worker_burst

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"


# ---------------------------------------------------------------- helpers


async def _sign_in(api: AsyncClient, email: str = "sara@example.com") -> dict[str, str]:
    await api.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    tokens = (
        await api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


async def _bank(api: AsyncClient, authorisation_url: str, button: str) -> Response:
    page = await api.get(_path(authorisation_url))
    match = re.search(rf'class="{button}" href="([^"]+)"', page.text)
    assert match, page.text
    return await api.get(_path(unescape(match.group(1))))


def _outcome(response: Response) -> str:
    assert response.status_code == 303
    return parse_qs(urlsplit(response.headers["location"]).query)["status"][0]


async def _connect(api: AsyncClient, headers: dict[str, str]) -> str:
    started = (
        await api.post(
            "/api/v1/connections", json={"institution_id": "mock-bank-uk"}, headers=headers
        )
    ).json()
    assert _outcome(await _bank(api, started["authorisation_url"], "approve")) == "connected"
    return str(started["connection_id"])


async def _count(db: AsyncSession, model: type[Any]) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


class ScriptedProvider(MockProvider):
    """Mock bank whose transactions (or outage) each test sets explicitly."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.transactions: list[ProviderTransaction] = []
        self.down = False
        self.revoked: list[str] = []

    async def get_transactions(self, *_: Any) -> list[ProviderTransaction]:
        if self.down:
            raise ProviderError("bank down")
        return self.transactions

    async def revoke_consent(self, consent_id: str) -> None:
        if self.down:
            raise ProviderError("bank down")
        self.revoked.append(consent_id)


def _tx(provider_id: str, status: str, day: date) -> ProviderTransaction:
    return ProviderTransaction(
        provider_transaction_id=provider_id,
        booking_date=day,
        amount=Decimal("-3.20"),
        currency="GBP",
        description="PRET A MANGER",
        merchant="Pret A Manger",
        status=status,  # type: ignore[arg-type]
    )


class FakeJobs:
    def __init__(self) -> None:
        self.syncs: list[uuid.UUID] = []
        self.revokes: list[tuple[str, str]] = []

    async def enqueue_sync(self, connection_id: uuid.UUID, *, window_seconds: int = 60) -> bool:
        self.syncs.append(connection_id)
        return True

    async def enqueue_revoke(self, provider: str, consent_id: str) -> None:
        self.revokes.append((provider, consent_id))


def _cipher(settings: Settings) -> TokenCipher:
    return TokenCipher(settings.encryption_keys(), settings.token_encryption_key_version)


# ---------------------------------------------------------------- BR-06 transactions


async def test_sync_imports_transactions_and_resync_adds_no_duplicates_br06(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)
    await run_worker_burst(migrated_settings)

    first = (await api.get("/api/v1/transactions", headers=headers)).json()
    assert first["total"] > 50  # a year of demo history
    stored = await _count(db, Transaction)

    service = ConnectionSyncService(
        db, MockProvider(migrated_settings.public_api_url), _cipher(migrated_settings)
    )
    await service.sync(uuid.UUID(connection_id))
    await service.sync(uuid.UUID(connection_id))

    assert await _count(db, Transaction) == stored
    again = (await api.get("/api/v1/transactions", headers=headers)).json()
    assert again["total"] == first["total"]


async def test_pending_that_books_under_a_new_id_is_not_duplicated_br06(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = uuid.UUID(await _connect(api, headers))
    provider = ScriptedProvider(migrated_settings.public_api_url)
    service = ConnectionSyncService(db, provider, _cipher(migrated_settings))
    today = datetime.now(UTC).date()

    provider.transactions = [_tx("pending-123", "pending", today)]
    await service.sync(connection_id)
    provider.transactions = [_tx("booked-987", "booked", today)]  # new ID once booked
    await service.sync(connection_id)

    rows = (await db.execute(select(Transaction))).scalars().all()
    # The scripted bank reports this transaction on each of its two accounts:
    # exactly one booked row per account, and the stale pending rows are gone.
    per_account = {r.account_id: [] for r in rows}
    for r in rows:
        per_account[r.account_id].append((r.provider_transaction_id, r.status))
    assert len(per_account) == 2
    assert all(v == [("booked-987", TransactionStatus.BOOKED)] for v in per_account.values())


async def test_pending_that_books_under_the_same_id_updates_in_place_br06(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = uuid.UUID(await _connect(api, headers))
    provider = ScriptedProvider(migrated_settings.public_api_url)
    service = ConnectionSyncService(db, provider, _cipher(migrated_settings))
    today = datetime.now(UTC).date()

    provider.transactions = [_tx("tx-1", "pending", today)]
    await service.sync(connection_id)
    first_id = (await db.execute(select(Transaction.id))).scalars().all()
    provider.transactions = [_tx("tx-1", "booked", today)]
    await service.sync(connection_id)

    rows = (await db.execute(select(Transaction))).scalars().all()
    assert len(rows) == 2  # one per account of the bank, each updated in place
    assert all(r.status is TransactionStatus.BOOKED for r in rows)
    assert {r.id for r in rows} == set(first_id)


async def test_transactions_can_be_filtered_and_paged_br06(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    accounts = (await api.get("/api/v1/accounts", headers=headers)).json()["accounts"]
    current = next(a for a in accounts if a["name"] == "Everyday Current")

    page = (
        await api.get("/api/v1/transactions", params={"limit": 5, "offset": 5}, headers=headers)
    ).json()
    salary = (await api.get("/api/v1/transactions", params={"q": "salary"}, headers=headers)).json()
    savings_only = (
        await api.get(
            "/api/v1/transactions", params={"account_id": accounts[1]["id"]}, headers=headers
        )
    ).json()
    month = (
        await api.get(
            "/api/v1/transactions",
            params={
                "date_from": "2026-01-01",
                "date_to": "2026-01-31",
                "account_id": current["id"],
            },
            headers=headers,
        )
    ).json()

    assert len(page["items"]) == 5 and page["offset"] == 5
    dates = [i["booking_date"] for i in page["items"]]
    assert dates == sorted(dates, reverse=True)
    assert salary["total"] >= 1 and all("SALARY" in i["description"] for i in salary["items"])
    assert {i["account_id"] for i in savings_only["items"]} <= {accounts[1]["id"]}
    assert all("2026-01-01" <= i["booking_date"] <= "2026-01-31" for i in month["items"])
    assert all(i["amount"].lstrip("-").replace(".", "").isdigit() for i in page["items"])


async def test_transactions_are_scoped_to_their_owner(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    sara = await _sign_in(api, "sara@example.com")
    omar = await _sign_in(api, "omar@example.com")
    await _connect(api, sara)
    await run_worker_burst(migrated_settings)
    sara_account = (await api.get("/api/v1/accounts", headers=sara)).json()["accounts"][0]["id"]

    mine = (await api.get("/api/v1/transactions", headers=omar)).json()
    snooping = (
        await api.get("/api/v1/transactions", params={"account_id": sara_account}, headers=omar)
    ).json()

    assert mine["total"] == 0
    assert snooping["total"] == 0


# ---------------------------------------------------------------- NFR-07 visible failures


async def test_failed_sync_rolls_back_and_is_visible_nfr07(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = uuid.UUID(await _connect(api, headers))
    provider = ScriptedProvider(migrated_settings.public_api_url)
    provider.down = True
    service = ConnectionSyncService(db, provider, _cipher(migrated_settings))

    with pytest.raises(ProviderError):
        await service.sync(connection_id)
    assert await _count(db, Account) == 0  # partial work rolled back
    await service.record_failure(connection_id, final=False)
    retrying = (await api.get("/api/v1/connections", headers=headers)).json()[0]
    await service.record_failure(connection_id, final=True)
    failed = (await api.get("/api/v1/connections", headers=headers)).json()[0]

    assert retrying["last_sync_status"] == "retrying"
    assert failed["last_sync_status"] == "failed"
    assert failed["last_sync_error"] == "provider_unavailable"


# ---------------------------------------------------------------- manual and scheduled sync


async def test_manual_sync_is_accepted_and_merged_within_a_minute(api: AsyncClient) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)

    first = await api.post(f"/api/v1/connections/{connection_id}/sync", headers=headers)
    second = await api.post(f"/api/v1/connections/{connection_id}/sync", headers=headers)

    assert first.status_code == 202
    # The callback already queued this minute's sync, so both are merged into it.
    assert first.json() == {"queued": False}
    assert second.json() == {"queued": False}


async def test_scheduled_sync_queues_every_active_connection(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    sara, omar = await _sign_in(api, "sara@example.com"), await _sign_in(api, "omar@example.com")
    await _connect(api, sara)
    stale = uuid.UUID(await _connect(api, omar))
    await db.execute(
        update(BankConnection)
        .where(BankConnection.id == stale)
        .values(status=ConnectionStatus.NEEDS_RENEWAL)
    )
    await db.commit()
    jobs = FakeJobs()
    from finance_app.db.session import create_engine, create_sessionmaker

    engine = create_engine(migrated_settings)
    try:
        queued = await schedule_syncs(
            {"sessionmaker": create_sessionmaker(engine), "job_queue": jobs}
        )
    finally:
        await engine.dispose()

    assert queued == 1 and stale not in jobs.syncs


# ---------------------------------------------------------------- BR-03 renewal


async def test_renew_banner_then_expiry_stops_sync_br03(api: AsyncClient, db: AsyncSession) -> None:
    headers = await _sign_in(api)
    connection_id = uuid.UUID(await _connect(api, headers))
    now = datetime.now(UTC)

    await db.execute(
        update(BankConnection)
        .where(BankConnection.id == connection_id)
        .values(consent_expires_at=now + timedelta(days=5, hours=1))
    )
    await db.commit()
    soon = (await api.get("/api/v1/connections", headers=headers)).json()[0]

    await db.execute(
        update(BankConnection)
        .where(BankConnection.id == connection_id)
        .values(consent_expires_at=now - timedelta(minutes=1))
    )
    await db.commit()
    report = await ConsentLifecycleService(db).check_expiry(datetime.now(UTC))
    expired = (await api.get("/api/v1/connections", headers=headers)).json()[0]
    sync = await api.post(f"/api/v1/connections/{connection_id}/sync", headers=headers)

    assert (soon["renewal_due"], soon["days_until_expiry"]) == (True, 5)
    assert report.expired == 1
    assert expired["status"] == "needs_renewal"
    assert sync.status_code == 409


async def test_renewal_replaces_the_consent_and_keeps_the_data_br03(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    await db.execute(
        update(BankConnection)
        .where(BankConnection.id == uuid.UUID(connection_id))
        .values(status=ConnectionStatus.NEEDS_RENEWAL)
    )
    await db.commit()
    old = (await db.execute(select(BankConnection))).scalar_one()
    old_token, accounts_before = old.consent_token_enc, await _count(db, Account)

    renew = await api.post(f"/api/v1/connections/{connection_id}/renew", headers=headers)
    outcome = _outcome(await _bank(api, renew.json()["authorisation_url"], "approve"))

    db.expire_all()
    renewed = (await db.execute(select(BankConnection))).scalar_one()
    assert renew.status_code == 200 and outcome == "connected"
    assert str(renewed.id) == connection_id
    assert renewed.status is ConnectionStatus.ACTIVE
    assert renewed.consent_token_enc != old_token
    assert await _count(db, Account) == accounts_before


async def test_cancelling_a_renewal_keeps_the_connection_br03(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)
    await run_worker_burst(migrated_settings)

    renew = await api.post(f"/api/v1/connections/{connection_id}/renew", headers=headers)
    outcome = _outcome(await _bank(api, renew.json()["authorisation_url"], "cancel"))

    assert outcome == "cancelled"
    assert await _count(db, BankConnection) == 1
    assert await _count(db, Account) == 2


# ---------------------------------------------------------------- BR-04 disconnect


async def test_disconnect_deletes_all_of_the_banks_data_br04(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    assert await _count(db, Transaction) > 0

    response = await api.delete(f"/api/v1/connections/{connection_id}", headers=headers)

    assert response.status_code == 204
    for model in (BankConnection, Account, Balance, Transaction):
        assert await _count(db, model) == 0, model.__name__
    assert (await api.get("/api/v1/accounts", headers=headers)).json()["accounts"] == []


async def test_cannot_touch_another_users_connection(api: AsyncClient) -> None:
    sara, omar = await _sign_in(api, "sara@example.com"), await _sign_in(api, "omar@example.com")
    connection_id = await _connect(api, sara)

    for method, path in (
        ("DELETE", f"/api/v1/connections/{connection_id}"),
        ("POST", f"/api/v1/connections/{connection_id}/renew"),
        ("POST", f"/api/v1/connections/{connection_id}/sync"),
    ):
        assert (await api.request(method, path, headers=omar)).status_code == 404
    assert len((await api.get("/api/v1/connections", headers=sara)).json()) == 1


async def test_disconnect_revokes_at_provider_or_retries_later_br04(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    user_id = uuid.UUID((await api.get("/api/v1/me", headers=headers)).json()["id"])
    first, second = uuid.UUID(await _connect(api, headers)), uuid.UUID(await _connect(api, headers))
    redis = Redis.from_url(migrated_settings.redis_url)
    provider, jobs = ScriptedProvider(migrated_settings.public_api_url), FakeJobs()
    service = ConnectionService(
        db,
        provider,
        _cipher(migrated_settings),
        ConsentStateStore(redis, 600),
        jobs,
        migrated_settings,
    )
    try:
        await service.disconnect(user_id, first)  # provider up: revoked now
        provider.down = True
        await service.disconnect(user_id, second)  # provider down: deleted, revoke queued
    finally:
        await redis.aclose()

    assert len(provider.revoked) == 1
    assert [p for p, _ in jobs.revokes] == ["mock"]
    assert await _count(db, BankConnection) == 0
