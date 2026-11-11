"""Institutions and bank connection endpoints (BR-02)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from finance_app.api.deps import ConnectionServiceDep, CurrentUser, RateLimiterDep
from finance_app.core.errors import problem
from finance_app.core.rate_limit import RateLimit
from finance_app.modules.connections.schemas import (
    ConnectionDetail,
    ConnectionStarted,
    InstitutionRead,
    StartConnectionRequest,
    SyncQueued,
)

router = APIRouter(tags=["connections"])

_UNAUTHORIZED = problem("Missing, invalid or expired token.")
_PROVIDER_DOWN = problem("The Open Banking provider is unavailable; try again later.")
_NOT_FOUND = problem("No such connection.")
_MAX_CALLBACK_PARAM_LENGTH = 4096
SYNC_RATE_LIMIT = RateLimit(requests=5, window_seconds=60)  # per user


@router.get(
    "/institutions",
    summary="List banks",
    description="Banks the user can connect in a country (ISO 3166-1 alpha-2).",
    response_model=list[InstitutionRead],
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_502_BAD_GATEWAY: _PROVIDER_DOWN,
    },
)
async def list_institutions(
    _user: CurrentUser,
    service: ConnectionServiceDep,
    country: Annotated[str, Query(pattern=r"^[A-Za-z]{2}$", examples=["GB"])] = "GB",
) -> list[InstitutionRead]:
    """List banks available in a country."""
    institutions = await service.list_institutions(country.upper())
    return [InstitutionRead.model_validate(i, from_attributes=True) for i in institutions]


@router.post(
    "/connections",
    status_code=status.HTTP_201_CREATED,
    summary="Start connecting a bank",
    description=(
        "Creates a pending connection and returns the bank's authorisation URL. Send the "
        "user's browser there; after approving, the bank redirects to "
        "`/connections/callback`, which finishes the consent and redirects to the web app."
    ),
    response_model=ConnectionStarted,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: problem("Unknown institution."),
        status.HTTP_502_BAD_GATEWAY: _PROVIDER_DOWN,
    },
)
async def start_connection(
    body: StartConnectionRequest, user: CurrentUser, service: ConnectionServiceDep
) -> ConnectionStarted:
    """Start the consent flow for a bank."""
    connection, url = await service.start(user.id, body.institution_id)
    return ConnectionStarted(connection_id=connection.id, authorisation_url=url)


@router.get(
    "/connections",
    summary="List connections",
    description=(
        "The user's connected banks with status, consent expiry, `renewal_due` (expires "
        "within 7 days: show a renew banner) and the outcome of the last sync."
    ),
    response_model=list[ConnectionDetail],
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def list_connections(
    user: CurrentUser, service: ConnectionServiceDep
) -> list[ConnectionDetail]:
    """List the user's bank connections."""
    now = datetime.now(UTC)
    return [ConnectionDetail.from_model(c, now) for c in await service.list_connections(user.id)]


@router.post(
    "/connections/{connection_id}/renew",
    summary="Renew consent",
    description=(
        "Starts re-consent at the bank for an existing connection (BR-03). Send the "
        "browser to `authorisation_url`. Cancelling at the bank keeps the connection."
    ),
    response_model=ConnectionStarted,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_409_CONFLICT: problem("The connection can't be renewed."),
        status.HTTP_502_BAD_GATEWAY: _PROVIDER_DOWN,
    },
)
async def renew_connection(
    connection_id: uuid.UUID, user: CurrentUser, service: ConnectionServiceDep
) -> ConnectionStarted:
    """Start renewing a connection's consent."""
    url = await service.start_renewal(user.id, connection_id)
    return ConnectionStarted(connection_id=connection_id, authorisation_url=url)


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect a bank",
    description=(
        "Revokes the consent at the provider and deletes the bank's accounts, balances "
        "and transactions (BR-04). If the provider is unreachable, data is still deleted "
        "now and the revocation is retried in the background."
    ),
    response_class=Response,
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED, status.HTTP_404_NOT_FOUND: _NOT_FOUND},
)
async def disconnect(
    connection_id: uuid.UUID, user: CurrentUser, service: ConnectionServiceDep
) -> Response:
    """Disconnect a bank and delete its data."""
    await service.disconnect(user.id, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/connections/{connection_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync now",
    description="Queues a background sync. Repeats within a minute are merged.",
    response_model=SyncQueued,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_409_CONFLICT: problem("The connection needs renewal first."),
        status.HTTP_429_TOO_MANY_REQUESTS: problem("Too many sync requests."),
    },
)
async def sync_connection(
    connection_id: uuid.UUID,
    user: CurrentUser,
    service: ConnectionServiceDep,
    limiter: RateLimiterDep,
) -> SyncQueued:
    """Queue a manual sync."""
    await limiter.hit(f"sync:user:{user.id}", SYNC_RATE_LIMIT)
    return SyncQueued(queued=await service.request_sync(user.id, connection_id))


@router.get(
    "/connections/callback",
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Consent callback (bank redirect)",
    description=(
        "The bank redirects the user's browser here after consent. No access token: the "
        "single-use `state` parameter identifies the flow. Always redirects (303) to the "
        "web app with `status` = connected, cancelled, error or invalid_state."
    ),
    response_class=RedirectResponse,
    responses={status.HTTP_303_SEE_OTHER: {"description": "Redirect to the web app."}},
)
async def consent_callback(request: Request, service: ConnectionServiceDep) -> RedirectResponse:
    """Finish the consent and send the browser back to the web app."""
    params = {
        key: value
        for key, value in request.query_params.items()
        if len(value) <= _MAX_CALLBACK_PARAM_LENGTH
    }
    result = await service.complete(params)
    return RedirectResponse(service.web_redirect_url(result), status_code=status.HTTP_303_SEE_OTHER)
