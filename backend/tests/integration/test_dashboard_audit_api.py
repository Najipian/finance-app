"""BR-11 (dashboard), NFR-08 (fast with 12 months), NFR-06 (append-only audit log)."""

import re
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from html import unescape
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Settings
from finance_app.modules.accounts.models import Account
from finance_app.modules.audit.models import AuditEvent
from finance_app.modules.transactions.models import CategorySource, Transaction, TransactionStatus
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


async def _connect(api: AsyncClient, headers: dict[str, str], button: str = "approve") -> str:
    started = (
        await api.post(
            "/api/v1/connections", json={"institution_id": "mock-bank-uk"}, headers=headers
        )
    ).json()
    page = await api.get(_path(started["authorisation_url"]))
    link = re.search(rf'class="{button}" href="([^"]+)"', page.text)
    assert link
    await api.get(_path(unescape(link.group(1))))
    return str(started["connection_id"])


async def _categories(api: AsyncClient, headers: dict[str, str]) -> dict[str, uuid.UUID]:
    rows = (await api.get("/api/v1/categories", headers=headers)).json()
    return {c["name"]: uuid.UUID(c["id"]) for c in rows}


# ---------------------------------------------------------------- BR-11


async def test_dashboard_numbers_are_exact_br11(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    account_id = (await db.execute(select(Account.id))).scalars().first()
    cats = await _categories(api, headers)

    def tx(amount: str, category: str | None, day: int = 10) -> Transaction:
        return Transaction(
            account_id=account_id,
            dedup_key=uuid.uuid4().hex * 2,
            booking_date=date(2020, 1, day),
            amount=Decimal(amount),
            currency="GBP",
            description="TEST",
            status=TransactionStatus.BOOKED,
            category_id=cats[category] if category else None,
            category_source=CategorySource.RULE if category else None,
        )

    db.add_all(
        [
            tx("-40.00", "Eating out"),
            tx("10.00", "Eating out"),  # refund reduces spend
            tx("-70.00", "Groceries"),
            tx("-500.00", "Transfers"),  # own-account transfer: excluded
            tx("1000.00", "Income"),
            tx("-5.00", None),  # Uncategorized still counts as spending
        ]
    )
    await db.commit()

    summary = (
        await api.get("/api/v1/dashboard/summary", params={"month": "2020-01"}, headers=headers)
    ).json()

    assert summary["month"] == "2020-01"
    gbp = next(c for c in summary["currencies"] if c["currency"] == "GBP")
    assert (gbp["spending"], gbp["income"]) == ("105.00", "1000.00")
    assert [(c["name"], c["amount"], c["share_percent"]) for c in gbp["by_category"]] == [
        ("Groceries", "70.00", "66.7"),
        ("Eating out", "30.00", "28.6"),
        ("Uncategorized", "5.00", "4.8"),
    ]
    assert [m["month"] for m in gbp["trend"]] == [
        "2019-08",
        "2019-09",
        "2019-10",
        "2019-11",
        "2019-12",
        "2020-01",
    ]
    assert gbp["trend"][-1] == {"month": "2020-01", "spending": "105.00", "income": "1000.00"}
    assert all(m["spending"] == "0.00" for m in gbp["trend"][:-1])


async def test_dashboard_with_a_year_of_data_is_fast_and_consistent_br11_nfr08(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    today = datetime.now(UTC).date()
    last_month = f"{date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1):%Y-%m}"

    started = time.perf_counter()
    response = await api.get(
        "/api/v1/dashboard/summary", params={"month": last_month}, headers=headers
    )
    elapsed = time.perf_counter() - started

    gbp = next(c for c in response.json()["currencies"] if c["currency"] == "GBP")
    names = [c["name"] for c in gbp["by_category"]]
    amounts = [Decimal(c["amount"]) for c in gbp["by_category"]]
    assert elapsed < 2.0  # NFR-08
    assert gbp["income"] == "2850.00"  # one salary on the 25th
    assert "Transfers" not in names and "Income" not in names
    assert amounts == sorted(amounts, reverse=True)
    assert sum(amounts) == Decimal(gbp["spending"])
    assert len(gbp["trend"]) == 6 and gbp["trend"][-1]["month"] == last_month


async def test_dashboard_is_per_user_and_validated(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    sara, omar = await _sign_in(api), await _sign_in(api, "omar@example.com")
    await _connect(api, sara)
    await run_worker_burst(migrated_settings)

    omars = (await api.get("/api/v1/dashboard/summary", headers=omar)).json()
    bad = await api.get("/api/v1/dashboard/summary", params={"month": "2026-00"}, headers=sara)
    anonymous = await api.get("/api/v1/dashboard/summary")

    assert omars["currencies"] == []
    assert bad.status_code == 422
    assert anonymous.status_code == 401


# ---------------------------------------------------------------- NFR-06


async def test_consent_sync_and_deletion_are_audited_nfr06(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    await api.delete(f"/api/v1/connections/{connection_id}", headers=headers)

    trail = (await api.get("/api/v1/audit-log", headers=headers)).json()

    actions = [e["action"] for e in trail["items"]]
    assert actions == [
        "connection.deleted",
        "consent.revoked",
        "sync.succeeded",
        "consent.granted",
        "consent.started",
    ]
    assert trail["total"] == 5
    assert {e["entity_id"] for e in trail["items"]} == {connection_id}
    sync = next(e for e in trail["items"] if e["action"] == "sync.succeeded")
    assert sync["details"]["accounts"] == 2 and sync["details"]["transactions"] > 0
    deleted = trail["items"][0]["details"]
    assert deleted == {"revoked_at_provider": True, "revocation_deferred": False}
    flat = str(trail)
    assert "mock-consent" not in flat and "token" not in flat  # no secrets in the trail


async def test_cancelled_consent_is_audited_and_trails_are_private_nfr06(api: AsyncClient) -> None:
    sara, omar = await _sign_in(api), await _sign_in(api, "omar@example.com")
    await _connect(api, sara, button="cancel")

    saras = [
        e["action"] for e in (await api.get("/api/v1/audit-log", headers=sara)).json()["items"]
    ]
    omars = (await api.get("/api/v1/audit-log", headers=omar)).json()

    assert saras == ["consent.not_granted", "consent.started"]
    assert omars == {"items": [], "total": 0}


async def test_audit_log_cannot_be_changed_even_by_the_app_nfr06(
    api: AsyncClient, db: AsyncSession
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers, button="cancel")
    before = (await db.execute(select(AuditEvent))).scalars().all()
    assert before

    for statement in (
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(statement))
        await db.rollback()

    after = (await db.execute(select(AuditEvent.action))).scalars().all()
    assert "tampered" not in after and len(after) >= len(before)
