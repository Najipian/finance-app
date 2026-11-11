"""Health endpoints used by Docker, load balancers and uptime alarms."""

from fastapi import APIRouter, Response, status

from finance_app.api.deps import DbSession, RedisClient
from finance_app.modules.health import service
from finance_app.modules.health.schemas import LivenessStatus, ReadinessStatus

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    summary="Liveness probe",
    description="Returns 200 while the process is running. Touches no dependencies.",
    response_model=LivenessStatus,
)
async def liveness() -> LivenessStatus:
    """Report that the process is alive."""
    return LivenessStatus()


@router.get(
    "/ready",
    summary="Readiness probe",
    description="Checks Postgres and Redis. Returns 503 if any dependency is unreachable.",
    response_model=ReadinessStatus,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessStatus,
            "description": "At least one dependency is unreachable.",
        }
    },
)
async def readiness(db: DbSession, redis: RedisClient, response: Response) -> ReadinessStatus:
    """Report whether the app can reach its dependencies."""
    result = await service.check_readiness(db, redis)
    if result.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
