"""Top-level API router mounting every v1 route under ``/api/v1``."""

from fastapi import APIRouter

from finance_app.api.v1 import (
    accounts,
    auth,
    budgets,
    categories,
    connections,
    dashboard,
    health,
    notifications,
    transactions,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(connections.router)
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)
api_router.include_router(categories.router)
api_router.include_router(budgets.router)
api_router.include_router(notifications.router)
api_router.include_router(dashboard.router)
