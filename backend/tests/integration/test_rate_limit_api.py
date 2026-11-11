"""Rate limiting on auth endpoints against real Redis (NFR-02/03, ADR 0002)."""

import pytest

from finance_app.core.config import Settings
from tests.integration.conftest import running_app

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"


def _with(settings: Settings, **overrides: object) -> Settings:
    return settings.model_copy(update=overrides)


async def test_login_is_limited_per_account_even_with_correct_password_br01(
    migrated_settings: Settings,
) -> None:
    settings = _with(migrated_settings, login_account_rate_limit=3)
    async with running_app(settings) as api:
        await api.post(
            "/api/v1/auth/register", json={"email": "sara@example.com", "password": PASSWORD}
        )
        for _ in range(3):
            wrong = await api.post(
                "/api/v1/auth/login", json={"email": "sara@example.com", "password": "guess-123456"}
            )
            assert wrong.status_code == 401

        # 4th attempt in the window is refused before the password is even checked,
        # and changing the email's case doesn't get around it.
        blocked = await api.post(
            "/api/v1/auth/login", json={"email": "SARA@example.com", "password": PASSWORD}
        )

    assert blocked.status_code == 429
    assert blocked.headers["content-type"] == "application/problem+json"
    retry_after = int(blocked.headers["retry-after"])
    assert 0 < retry_after <= settings.login_account_window_seconds
    assert blocked.json()["title"] == "Too many requests"


async def test_account_limit_does_not_block_other_accounts_br01(
    migrated_settings: Settings,
) -> None:
    settings = _with(migrated_settings, login_account_rate_limit=2)
    async with running_app(settings) as api:
        for email in ("sara@example.com", "omar@example.com"):
            await api.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
        for _ in range(3):
            await api.post(
                "/api/v1/auth/login", json={"email": "sara@example.com", "password": "guess-123456"}
            )

        other = await api.post(
            "/api/v1/auth/login", json={"email": "omar@example.com", "password": PASSWORD}
        )

    assert other.status_code == 200


async def test_auth_endpoint_is_limited_per_client_ip(migrated_settings: Settings) -> None:
    settings = _with(migrated_settings, auth_rate_limit_per_minute=3)
    async with running_app(settings) as api:
        statuses = [
            (
                await api.post(
                    "/api/v1/auth/register",
                    json={"email": f"user{i}@example.com", "password": PASSWORD},
                )
            ).status_code
            for i in range(4)
        ]
        # Limits are per endpoint: refresh still has its own budget.
        refresh = await api.post("/api/v1/auth/refresh", json={"refresh_token": "made-up"})

    assert statuses == [201, 201, 201, 429]
    assert refresh.status_code == 401


async def test_rate_limiting_can_be_disabled(migrated_settings: Settings) -> None:
    settings = _with(migrated_settings, rate_limit_enabled=False, auth_rate_limit_per_minute=1)
    async with running_app(settings) as api:
        statuses = [
            (await api.post("/api/v1/auth/refresh", json={"refresh_token": "x"})).status_code
            for _ in range(3)
        ]

    assert statuses == [401, 401, 401]
