"""Response schemas for the health endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

CheckResult = Literal["ok", "fail"]


class LivenessStatus(BaseModel):
    """The process is up and serving requests."""

    status: Literal["ok"] = Field(default="ok", examples=["ok"])


class ReadinessStatus(BaseModel):
    """Whether the app can reach every dependency it needs to serve traffic."""

    status: Literal["ok", "degraded"] = Field(
        description="`ok` only when every check passes.", examples=["ok"]
    )
    checks: dict[str, CheckResult] = Field(
        description="Result per dependency.",
        examples=[{"database": "ok", "redis": "ok"}],
    )
