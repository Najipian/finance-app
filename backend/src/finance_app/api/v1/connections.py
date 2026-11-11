"""Institutions and bank connection endpoints (BR-02)."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import RedirectResponse

from finance_app.api.deps import ConnectionServiceDep, CurrentUser
from finance_app.core.errors import problem
from finance_app.modules.connections.schemas import (
    ConnectionRead,
    ConnectionStarted,
    InstitutionRead,
    StartConnectionRequest,
)

router = APIRouter(tags=["connections"])

_UNAUTHORIZED = problem("Missing, invalid or expired token.")
_PROVIDER_DOWN = problem("The Open Banking provider is unavailable; try again later.")
_MAX_CALLBACK_PARAM_LENGTH = 4096


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
    description="The user's connected banks and their status.",
    response_model=list[ConnectionRead],
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED},
)
async def list_connections(
    user: CurrentUser, service: ConnectionServiceDep
) -> list[ConnectionRead]:
    """List the user's bank connections."""
    return [ConnectionRead.model_validate(c) for c in await service.list_connections(user.id)]


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
