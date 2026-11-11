"""BR-07 (auto-categorise), BR-08 (re-categorise, rules), BR-09 (budgets), BR-10 (alerts).

Real Postgres and Redis, with the default categories and rules seeded by the
migration. Budget tests use a month with no demo data and insert transactions
directly, so the numbers are exact (US-07: 300 GBP Eating out, alerts at 240 and 300).
"""

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from html import unescape
from typing import Any, ClassVar
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_app.core.config import Settings
from finance_app.core.crypto import TokenCipher
from finance_app.modules.accounts.models import Account
from finance_app.modules.budgets.service import BudgetService
from finance_app.modules.categories.categorize import CategorizationService
from finance_app.modules.connections.sync import ConnectionSyncService
from finance_app.modules.transactions.models import CategorySource, Transaction, TransactionStatus
from finance_app.providers.base import ProviderTransaction
from finance_app.providers.mock import MockProvider
from tests.integration.conftest import run_worker_burst

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
EMPTY_MONTH = date(2020, 1, 1)  # far outside the demo bank's history


# ---------------------------------------------------------------- helpers


async def _sign_in(api: AsyncClient, email: str = "sara@example.com") -> dict[str, str]:
    await api.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    tokens = (
        await api.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _connect(api: AsyncClient, headers: dict[str, str]) -> str:
    started = (
        await api.post(
            "/api/v1/connections", json={"institution_id": "mock-bank-uk"}, headers=headers
        )
    ).json()
    page = await api.get(_path(started["authorisation_url"]))
    approve = re.search(r'class="approve" href="([^"]+)"', page.text)
    assert approve
    await api.get(_path(unescape(approve.group(1))))
    return str(started["connection_id"])


def _path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


async def _categories(api: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    return {
        c["name"]: c["id"] for c in (await api.get("/api/v1/categories", headers=headers)).json()
    }


async def _all_transactions(api: AsyncClient, headers: dict[str, str], **params: Any) -> list[Any]:
    items: list[Any] = []
    offset = 0
    while True:
        page = (
            await api.get(
                "/api/v1/transactions",
                params={"limit": 100, "offset": offset, **params},
                headers=headers,
            )
        ).json()
        items += page["items"]
        offset += 100
        if offset >= page["total"]:
            return items


async def _user_id(api: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID((await api.get("/api/v1/me", headers=headers)).json()["id"])


async def _spend(
    db: AsyncSession,
    account_id: uuid.UUID,
    amount: str,
    category: str,
    day: int,
    currency: str = "GBP",
) -> None:
    db.add(
        Transaction(
            account_id=account_id,
            dedup_key=uuid.uuid4().hex + uuid.uuid4().hex,
            booking_date=EMPTY_MONTH.replace(day=day),
            amount=Decimal(amount),
            currency=currency,
            description="PRET A MANGER",
            status=TransactionStatus.BOOKED,
            category_id=uuid.UUID(category),
            category_source=CategorySource.RULE,
        )
    )
    await db.commit()


async def _setup_budget_user(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> tuple[dict[str, str], uuid.UUID, uuid.UUID, dict[str, str]]:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    account_id = (await db.execute(select(Account.id))).scalars().first()
    assert account_id is not None
    return headers, await _user_id(api, headers), account_id, await _categories(api, headers)


# ---------------------------------------------------------------- BR-07


async def test_synced_transactions_are_categorised_by_default_rules_br07(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)  # sync, then categorise
    names = {v: k for k, v in (await _categories(api, headers)).items()}

    txs = await _all_transactions(api, headers)
    by_desc = {t["description"]: names.get(t["category_id"]) for t in txs}

    assert len(names) == 12
    assert by_desc["TESCO STORES 2041"] == "Groceries"
    assert by_desc["PRET A MANGER LONDON"] == "Eating out"
    assert by_desc["ACME LTD SALARY"] == "Income"
    assert by_desc["TFL TRAVEL CHARGE"] == "Transport"
    # Regression: the keyword "TFL" once matched inside "NETFLIX" (found in Docker).
    assert by_desc["NETFLIX.COM"] == "Subscriptions"
    assert by_desc["SHELL KINGS CROSS"] == "Fuel"
    assert all(t["category_source"] == "rule" for t in txs if t["category_id"])


async def test_unmatched_transactions_stay_uncategorized_br07(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers, user_id, account_id, _ = await _setup_budget_user(api, db, migrated_settings)
    db.add(
        Transaction(
            account_id=account_id,
            dedup_key="x" * 64,
            booking_date=EMPTY_MONTH,
            amount=Decimal("-9.99"),
            currency="GBP",
            description="MYSTERY SHOP 42",
            status=TransactionStatus.BOOKED,
        )
    )
    await db.commit()

    await CategorizationService(db).categorize_new(user_id)
    await db.commit()

    mystery = await _all_transactions(api, headers, q="MYSTERY")
    assert [(t["category_id"], t["category_source"]) for t in mystery] == [(None, None)]


# ---------------------------------------------------------------- BR-08


async def test_manual_category_sticks_through_resync_and_recategorisation_br08(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    cats = await _categories(api, headers)
    tesco = (await _all_transactions(api, headers, q="TESCO"))[0]

    response = await api.patch(
        f"/api/v1/transactions/{tesco['id']}",
        json={"category_id": cats["Shopping"]},
        headers=headers,
    )
    service = ConnectionSyncService(
        db,
        MockProvider(migrated_settings.public_api_url),
        TokenCipher(migrated_settings.encryption_keys(), 1),
    )
    await service.sync(uuid.UUID(connection_id))
    await CategorizationService(db).recategorize(await _user_id(api, headers))
    await db.commit()

    assert response.status_code == 200
    assert response.json()["transaction"]["category_source"] == "manual"
    after = next(
        t for t in await _all_transactions(api, headers, q="TESCO") if t["id"] == tesco["id"]
    )
    assert (after["category_id"], after["category_source"]) == (cats["Shopping"], "manual")


async def test_apply_to_similar_creates_a_rule_for_past_and_future_br08(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    kids = (await api.post("/api/v1/categories", json={"name": "Kids"}, headers=headers)).json()
    boots = await _all_transactions(api, headers, q="BOOTS")
    assert len(boots) > 1

    response = (
        await api.patch(
            f"/api/v1/transactions/{boots[0]['id']}",
            json={"category_id": kids["id"], "apply_to_similar": True},
            headers=headers,
        )
    ).json()
    rules = (await api.get("/api/v1/category-rules", headers=headers)).json()

    assert response["rule_id"] and response["similar_updated"] == len(boots) - 1
    assert rules == [
        {
            "id": response["rule_id"],
            "match_field": "merchant",
            "operator": "equals",
            "value": "Boots",
            "category_id": kids["id"],
            "priority": 100,
            "created_at": rules[0]["created_at"],
        }
    ]
    assert {t["category_id"] for t in await _all_transactions(api, headers, q="BOOTS")} == {
        kids["id"]
    }

    # A future Boots transaction (simulated by clearing one) is categorised by the rule.
    await db.execute(
        update(Transaction)
        .where(Transaction.id == uuid.UUID(boots[1]["id"]))
        .values(category_id=None, category_source=None)
    )
    await db.commit()
    await CategorizationService(db).categorize_new(await _user_id(api, headers))
    await db.commit()
    future = next(
        t for t in await _all_transactions(api, headers, q="BOOTS") if t["id"] == boots[1]["id"]
    )
    assert future["category_id"] == kids["id"]


async def test_user_rule_overrides_builtin_and_deleting_it_restores_defaults_br08(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    await _connect(api, headers)
    await run_worker_burst(migrated_settings)
    cats = await _categories(api, headers)

    rule = await api.post(
        "/api/v1/category-rules",
        json={
            "match_field": "description",
            "operator": "contains",
            "value": "tesco",
            "category_id": cats["Shopping"],
        },
        headers=headers,
    )
    overridden = {t["category_id"] for t in await _all_transactions(api, headers, q="TESCO")}
    await api.delete(f"/api/v1/category-rules/{rule.json()['id']}", headers=headers)
    restored = {t["category_id"] for t in await _all_transactions(api, headers, q="TESCO")}

    assert rule.status_code == 201
    assert overridden == {cats["Shopping"]}
    assert restored == {cats["Groceries"]}


async def test_category_management_rules(api: AsyncClient) -> None:
    headers = await _sign_in(api)
    other = await _sign_in(api, "omar@example.com")
    cats = await _categories(api, headers)

    duplicate_default = await api.post(
        "/api/v1/categories", json={"name": "groceries"}, headers=headers
    )
    created = await api.post(
        "/api/v1/categories", json={"name": "Gym", "icon": "dumbbell"}, headers=headers
    )
    duplicate_own = await api.post("/api/v1/categories", json={"name": "GYM"}, headers=headers)
    delete_default = await api.delete(f"/api/v1/categories/{cats['Groceries']}", headers=headers)
    others_view = await _categories(api, other)
    delete_as_other = await api.delete(f"/api/v1/categories/{created.json()['id']}", headers=other)
    delete_own = await api.delete(f"/api/v1/categories/{created.json()['id']}", headers=headers)

    assert duplicate_default.status_code == 409
    assert created.status_code == 201 and created.json()["is_default"] is False
    assert duplicate_own.status_code == 409
    assert delete_default.status_code == 409
    assert "Gym" not in others_view
    assert delete_as_other.status_code == 404
    assert delete_own.status_code == 204


async def test_cannot_recategorise_with_someone_elses_category(
    api: AsyncClient, migrated_settings: Settings
) -> None:
    sara, omar = await _sign_in(api), await _sign_in(api, "omar@example.com")
    await _connect(api, sara)
    await run_worker_burst(migrated_settings)
    omar_cat = (await api.post("/api/v1/categories", json={"name": "Secret"}, headers=omar)).json()
    tx = (await _all_transactions(api, sara))[0]

    with_foreign_category = await api.patch(
        f"/api/v1/transactions/{tx['id']}", json={"category_id": omar_cat["id"]}, headers=sara
    )
    foreign_transaction = await api.patch(
        f"/api/v1/transactions/{tx['id']}", json={"category_id": None}, headers=omar
    )

    assert with_foreign_category.status_code == 404
    assert foreign_transaction.status_code == 404


async def test_manual_category_survives_pending_booking_under_new_id_br08(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers = await _sign_in(api)
    connection_id = uuid.UUID(await _connect(api, headers))
    cats = await _categories(api, headers)
    today = datetime.now(UTC).date()

    class Scripted(MockProvider):
        txs: ClassVar[list[ProviderTransaction]] = []

        async def get_transactions(self, *_: Any) -> list[ProviderTransaction]:
            return self.txs

    provider = Scripted(migrated_settings.public_api_url)
    service = ConnectionSyncService(
        db, provider, TokenCipher(migrated_settings.encryption_keys(), 1)
    )

    def tx(provider_id: str, status: str) -> ProviderTransaction:
        return ProviderTransaction(
            provider_transaction_id=provider_id,
            booking_date=today,
            amount=Decimal("-42.00"),
            currency="GBP",
            description="MYSTERY SHOP",
            status=status,  # type: ignore[arg-type]
        )

    Scripted.txs = [tx("p-1", "pending")]
    await service.sync(connection_id)
    pending = await _all_transactions(api, headers, q="MYSTERY", status="pending")
    for item in pending:
        await api.patch(
            f"/api/v1/transactions/{item['id']}",
            json={"category_id": cats["Shopping"]},
            headers=headers,
        )
    Scripted.txs = [tx("b-1", "booked")]
    await service.sync(connection_id)

    booked = await _all_transactions(api, headers, q="MYSTERY")
    assert booked and all(t["status"] == "booked" for t in booked)
    assert {(t["category_id"], t["category_source"]) for t in booked} == {
        (cats["Shopping"], "manual")
    }


# ---------------------------------------------------------------- BR-09 / BR-10


async def test_budget_alerts_at_80_and_100_percent_once_each_br09_br10(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers, user_id, account_id, cats = await _setup_budget_user(api, db, migrated_settings)
    eating_out = cats["Eating out"]

    created = await api.put(
        "/api/v1/budgets",
        json={
            "category_id": eating_out,
            "month": "2020-01",
            "limit_amount": "300.00",
            "currency": "GBP",
        },
        headers=headers,
    )
    assert created.json()["status"] == "ok" and created.json()["spent"] == "0"

    await _spend(db, account_id, "-240.00", eating_out, day=5)
    first_check = await BudgetService(db).check_alerts(user_id, EMPTY_MONTH)
    await db.commit()
    repeat_check = await BudgetService(db).check_alerts(user_id, EMPTY_MONTH)
    await db.commit()
    warning = (
        await api.get("/api/v1/budgets", params={"month": "2020-01"}, headers=headers)
    ).json()[0]

    await _spend(db, account_id, "-60.00", eating_out, day=20)
    await _spend(db, account_id, "-999.00", eating_out, day=21, currency="EUR")  # other currency
    await BudgetService(db).check_alerts(user_id, EMPTY_MONTH)
    await db.commit()
    exceeded = (
        await api.get("/api/v1/budgets", params={"month": "2020-01"}, headers=headers)
    ).json()[0]
    notifications = (await api.get("/api/v1/notifications", headers=headers)).json()

    assert (first_check, repeat_check) == (1, 0)
    assert (warning["status"], warning["spent"], warning["percent_used"]) == (
        "warning",
        "240.00",
        "80.0",
    )
    assert (exceeded["status"], exceeded["spent"], exceeded["remaining"]) == (
        "exceeded",
        "300.00",
        "0.00",
    )
    assert [n["kind"] for n in notifications] == ["budget_exceeded", "budget_warning"]
    assert "240.00 of 300.00 GBP" in notifications[1]["body"]


async def test_refunds_reduce_spend_and_limit_changes_rearm_alerts_br10(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers, user_id, account_id, cats = await _setup_budget_user(api, db, migrated_settings)
    groceries = cats["Groceries"]
    body = {"category_id": groceries, "month": "2020-01", "currency": "GBP"}
    await api.put("/api/v1/budgets", json={**body, "limit_amount": "100.00"}, headers=headers)
    await _spend(db, account_id, "-90.00", groceries, day=3)
    await _spend(db, account_id, "5.00", groceries, day=4)  # refund
    await BudgetService(db).check_alerts(user_id, EMPTY_MONTH)
    await db.commit()

    raised = (
        await api.put("/api/v1/budgets", json={**body, "limit_amount": "500.00"}, headers=headers)
    ).json()
    lowered = (
        await api.put("/api/v1/budgets", json={**body, "limit_amount": "80.00"}, headers=headers)
    ).json()
    kinds = [n["kind"] for n in (await api.get("/api/v1/notifications", headers=headers)).json()]

    assert raised["spent"] == "85.00" and raised["status"] == "ok"
    assert lowered["status"] == "exceeded"
    # 80 % alert at 85/100, re-armed by raising the limit, then 100 % on lowering it.
    assert kinds == ["budget_exceeded", "budget_warning"]


async def test_budget_validation_and_ownership_br09(api: AsyncClient) -> None:
    sara, omar = await _sign_in(api), await _sign_in(api, "omar@example.com")
    cats = await _categories(api, sara)
    secret = (await api.post("/api/v1/categories", json={"name": "Secret"}, headers=omar)).json()
    body = {
        "category_id": cats["Travel"],
        "month": "2026-11",
        "limit_amount": "50",
        "currency": "GBP",
    }

    bad_month = await api.put("/api/v1/budgets", json={**body, "month": "2026-13"}, headers=sara)
    bad_amount = await api.put("/api/v1/budgets", json={**body, "limit_amount": "-1"}, headers=sara)
    foreign_category = await api.put(
        "/api/v1/budgets", json={**body, "category_id": secret["id"]}, headers=sara
    )
    budget = (await api.put("/api/v1/budgets", json=body, headers=sara)).json()
    foreign_delete = await api.delete(f"/api/v1/budgets/{budget['id']}", headers=omar)
    own_delete = await api.delete(f"/api/v1/budgets/{budget['id']}", headers=sara)
    bad_query = await api.get("/api/v1/budgets", params={"month": "11-2026"}, headers=sara)

    assert (bad_month.status_code, bad_amount.status_code, bad_query.status_code) == (422, 422, 422)
    assert foreign_category.status_code == 404
    assert foreign_delete.status_code == 404
    assert own_delete.status_code == 204


async def test_notifications_can_be_marked_read_by_their_owner_only_br10(
    api: AsyncClient, db: AsyncSession, migrated_settings: Settings
) -> None:
    headers, user_id, account_id, cats = await _setup_budget_user(api, db, migrated_settings)
    omar = await _sign_in(api, "omar@example.com")
    await api.put(
        "/api/v1/budgets",
        json={
            "category_id": cats["Travel"],
            "month": "2020-01",
            "limit_amount": "10",
            "currency": "GBP",
        },
        headers=headers,
    )
    await _spend(db, account_id, "-50.00", cats["Travel"], day=2)
    await BudgetService(db).check_alerts(user_id, EMPTY_MONTH)
    await db.commit()
    notification = (
        await api.get("/api/v1/notifications", params={"unread": True}, headers=headers)
    ).json()[0]

    as_other = await api.post(f"/api/v1/notifications/{notification['id']}/read", headers=omar)
    as_owner = await api.post(f"/api/v1/notifications/{notification['id']}/read", headers=headers)
    unread = (
        await api.get("/api/v1/notifications", params={"unread": True}, headers=headers)
    ).json()

    assert as_other.status_code == 404
    assert as_owner.status_code == 200 and as_owner.json()["read_at"]
    assert unread == []
