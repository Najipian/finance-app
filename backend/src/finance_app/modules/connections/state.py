"""Single-use OAuth ``state`` values for the bank consent callback.

The callback is a browser redirect from the bank and carries no access token, so
the ``state`` is what proves which user started the flow. Values are random,
expire after a few minutes, and are consumed atomically (``GETDEL``), which
stops CSRF and replay.
"""

import json
import secrets
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

KEY_PREFIX = "consent_state"
STATE_BYTES = 32


@dataclass(frozen=True, slots=True)
class StateBinding:
    """Who started a consent flow, for which connection, and whether it renews one."""

    user_id: uuid.UUID
    connection_id: uuid.UUID
    renew: bool = False


class ConsentStateStore:
    """Issues and consumes consent ``state`` values in Redis.

    Args:
        redis: The shared async Redis client.
        ttl_seconds: How long a state stays valid.
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def issue(self, binding: StateBinding) -> str:
        """Create a new state bound to a user and connection."""
        state = secrets.token_urlsafe(STATE_BYTES)
        payload = json.dumps(
            {
                "user_id": str(binding.user_id),
                "connection_id": str(binding.connection_id),
                "renew": binding.renew,
            }
        )
        await self._redis.set(f"{KEY_PREFIX}:{state}", payload, ex=self._ttl)
        return state

    async def consume(self, state: str) -> StateBinding | None:
        """Return and delete the binding for a state; None if unknown or expired."""
        if not state or len(state) > 128:
            return None
        raw = await self._redis.getdel(f"{KEY_PREFIX}:{state}")
        if raw is None:
            return None
        data = json.loads(raw)
        return StateBinding(
            user_id=uuid.UUID(data["user_id"]),
            connection_id=uuid.UUID(data["connection_id"]),
            renew=bool(data.get("renew", False)),
        )
