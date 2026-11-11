"""Top-level API router mounting every v1 route under ``/api/v1``."""

from fastapi import APIRouter

from finance_app.api.v1 import auth, health, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
