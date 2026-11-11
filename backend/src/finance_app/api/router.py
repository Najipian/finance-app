"""Top-level API router mounting every v1 route under ``/api/v1``."""

from fastapi import APIRouter

from finance_app.api.v1 import health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
