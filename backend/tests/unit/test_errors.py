"""RFC 9457 problem responses for domain, HTTP, validation and unexpected errors."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from finance_app.core.errors import PROBLEM_MEDIA_TYPE, ConflictError, NotFoundError


class Payload(BaseModel):
    password: str
    age: int


def _add_routes(app: FastAPI) -> None:
    async def missing() -> None:
        raise NotFoundError("Connection not found.")

    async def conflict() -> None:
        raise ConflictError()

    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    async def validate(payload: Payload) -> Payload:
        return payload

    app.add_api_route("/t/missing", missing)
    app.add_api_route("/t/conflict", conflict)
    app.add_api_route("/t/boom", boom)
    app.add_api_route("/t/validate", validate, methods=["POST"])


async def test_domain_error_maps_to_problem_details(app: FastAPI, client: AsyncClient) -> None:
    _add_routes(app)

    response = await client.get("/t/missing")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "about:blank",
        "title": "Not found",
        "status": 404,
        "instance": "/t/missing",
        "detail": "Connection not found.",
    }


async def test_domain_error_without_detail_omits_detail(app: FastAPI, client: AsyncClient) -> None:
    _add_routes(app)

    body = (await client.get("/t/conflict")).json()

    assert body["status"] == 409
    assert "detail" not in body


async def test_unknown_route_is_problem_details(client: AsyncClient) -> None:
    response = await client.get("/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE


async def test_validation_error_never_echoes_submitted_values(
    app: FastAPI, client: AsyncClient
) -> None:
    _add_routes(app)

    response = await client.post("/t/validate", json={"password": "hunter2", "age": "old"})

    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Validation failed"
    assert body["errors"][0]["loc"] == ["body", "age"]
    assert "hunter2" not in response.text
    assert "old" not in response.text


async def test_unexpected_error_returns_500_without_internals(app: FastAPI) -> None:
    _add_routes(app)
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/t/boom")

    assert response.status_code == 500
    assert response.json()["title"] == "Internal server error"
    assert "secret internal detail" not in response.text
