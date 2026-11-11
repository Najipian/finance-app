"""Domain exceptions and their mapping to RFC 9457 problem responses.

Services raise ``DomainError`` subclasses and never import FastAPI; this module is
the single place that turns any error into an ``application/problem+json`` body.
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"

log = structlog.get_logger(__name__)


class DomainError(Exception):
    """Base class for business-rule errors raised by services.

    Subclasses set ``status_code`` and ``title``; ``detail`` explains this
    occurrence and is safe to show to the client.
    """

    status_code: int = 400
    title: str = "Bad request"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class NotFoundError(DomainError):
    """The resource does not exist or belongs to another user (never leak which)."""

    status_code = 404
    title = "Not found"


class ConflictError(DomainError):
    """The request conflicts with current state, e.g. a duplicate email."""

    status_code = 409
    title = "Conflict"


def problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str | None = None,
    **extensions: Any,
) -> JSONResponse:
    """Build an RFC 9457 problem details response.

    Args:
        request: The current request; its path becomes ``instance``.
        status: HTTP status code.
        title: Short, human-readable summary of the problem type.
        detail: Explanation specific to this occurrence.
        **extensions: Extra members, e.g. ``errors`` for validation failures.

    Returns:
        A JSON response with the problem media type.
    """
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    body.update(extensions)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)  # noqa: S101 - narrowed by registration
    return problem_response(request, exc.status_code, exc.title, exc.detail)


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - narrowed by registration
    title = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    response = problem_response(request, exc.status_code, title)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - narrowed by registration
    # Drop the offending "input" values: they can contain passwords or tokens.
    errors = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return problem_response(
        request, 422, "Validation failed", "The request is not valid.", errors=errors
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, error_type=type(exc).__name__)
    return problem_response(request, 500, "Internal server error")


def register_exception_handlers(app: FastAPI) -> None:
    """Register every exception-to-problem mapping on the app.

    Args:
        app: The FastAPI application to configure.
    """
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
