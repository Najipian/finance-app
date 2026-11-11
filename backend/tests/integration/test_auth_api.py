"""BR-01: a user can register and log in securely (real Postgres, real HTTP)."""

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

EMAIL = "sara@example.com"
PASSWORD = "correct-horse-battery-staple"


async def _register(api: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Any:
    response = await api.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


async def _login(api: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Any:
    response = await api.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- register


async def test_register_creates_user_without_exposing_password_br01(api: AsyncClient) -> None:
    body = await _register(api, email="Sara@Example.COM")

    assert body["email"] == "sara@example.com"  # stored lower-case
    assert set(body) == {"id", "email", "created_at"}


async def test_register_rejects_duplicate_email_case_insensitively_br01(api: AsyncClient) -> None:
    await _register(api)

    response = await api.post(
        "/api/v1/auth/register", json={"email": "SARA@example.com", "password": PASSWORD}
    )

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": EMAIL, "password": "Pw-9xQ"},
        {"email": EMAIL, "password": "x" * 129},
    ],
)
async def test_register_validates_email_and_password_length_br01(
    api: AsyncClient, payload: dict[str, str]
) -> None:
    response = await api.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422
    assert payload["password"] not in response.text  # never echoed back


# ---------------------------------------------------------------- login


async def test_login_returns_token_pair_br01(api: AsyncClient) -> None:
    await _register(api)

    tokens = await _login(api, email="SARA@example.com")  # any case works

    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60
    assert tokens["access_token"] and tokens["refresh_token"]


@pytest.mark.parametrize(
    ("email", "password"), [(EMAIL, "wrong-password-123"), ("nobody@example.com", PASSWORD)]
)
async def test_login_failure_does_not_reveal_whether_email_exists_br01(
    api: AsyncClient, email: str, password: str
) -> None:
    await _register(api)

    response = await api.post("/api/v1/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password."
    assert response.headers["www-authenticate"] == "Bearer"


# ---------------------------------------------------------------- /me


async def test_me_returns_current_user_with_valid_token_br01(api: AsyncClient) -> None:
    user = await _register(api)
    tokens = await _login(api)

    response = await api.get("/api/v1/me", headers=_bearer(tokens["access_token"]))

    assert response.status_code == 200
    assert response.json()["id"] == user["id"]


@pytest.mark.parametrize("headers", [{}, _bearer("not-a-jwt"), {"Authorization": "Basic abc"}])
async def test_me_rejects_missing_or_invalid_token_br01(
    api: AsyncClient, headers: dict[str, str]
) -> None:
    response = await api.get("/api/v1/me", headers=headers)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"


# ---------------------------------------------------------------- refresh rotation


async def test_refresh_rotates_tokens_and_old_token_stops_working_br01(api: AsyncClient) -> None:
    await _register(api)
    first = await _login(api)

    response = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]

    me = await api.get("/api/v1/me", headers=_bearer(second["access_token"]))
    assert me.status_code == 200


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_session_br01(
    api: AsyncClient,
) -> None:
    await _register(api)
    stolen = (await _login(api))["refresh_token"]
    rotated = (await api.post("/api/v1/auth/refresh", json={"refresh_token": stolen})).json()

    replay = await api.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401

    # The legitimate client's newer token is now revoked too.
    after = await api.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert after.status_code == 401


async def test_refresh_with_unknown_token_is_rejected_br01(api: AsyncClient) -> None:
    response = await api.post("/api/v1/auth/refresh", json={"refresh_token": "made-up"})

    assert response.status_code == 401


async def test_separate_logins_are_independent_sessions_br01(api: AsyncClient) -> None:
    await _register(api)
    laptop, phone = await _login(api), await _login(api)

    await api.post("/api/v1/auth/logout", json={"refresh_token": laptop["refresh_token"]})

    response = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": phone["refresh_token"]}
    )
    assert response.status_code == 200


# ---------------------------------------------------------------- logout


async def test_logout_revokes_refresh_token_br01(api: AsyncClient) -> None:
    await _register(api)
    tokens = await _login(api)

    response = await api.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 204

    refresh = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 401


async def test_logout_with_unknown_token_is_a_no_op_br01(api: AsyncClient) -> None:
    response = await api.post("/api/v1/auth/logout", json={"refresh_token": "made-up"})

    assert response.status_code == 204
