"""Fixed-window rate limiting on the async Redis client (ADR 0002).

Each check runs one Redis transaction: ``INCR`` the window's counter, ``EXPIRE``
it only if no expiry is set yet (so the window doesn't slide on every hit), and
read its ``TTL`` for ``Retry-After``. Everything is async, so a check never
blocks the event loop.

If Redis is unreachable the limiter fails open: the request is allowed and a
warning is logged. For this app, availability of login beats strict throttling
during a cache outage; the readiness probe reports Redis as down meanwhile.
"""

import hashlib
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from finance_app.core.errors import RateLimitedError

KEY_PREFIX = "ratelimit"

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimit:
    """At most ``requests`` per ``window_seconds``."""

    requests: int
    window_seconds: int


def hashed_key_part(value: str) -> str:
    """Hash a value (e.g. an email) so personal data never appears in Redis keys."""
    return hashlib.sha256(value.encode()).hexdigest()[:32]


class RateLimiter:
    """Counts requests per key in fixed windows stored in Redis.

    Args:
        redis: The shared async Redis client.
        enabled: When False, every check passes (local debugging, load tests).
    """

    def __init__(self, redis: Redis, *, enabled: bool = True) -> None:
        self._redis = redis
        self._enabled = enabled

    async def hit(self, key: str, limit: RateLimit) -> None:
        """Record one request for ``key`` and enforce ``limit``.

        Args:
            key: What is being limited, e.g. ``"login:ip:203.0.113.7"``.
            limit: The allowed requests per window.

        Raises:
            RateLimitedError: The limit for the current window is exceeded.
        """
        if not self._enabled:
            return
        redis_key = f"{KEY_PREFIX}:{key}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, limit.window_seconds, nx=True)
                pipe.ttl(redis_key)
                count, _, ttl = await pipe.execute()
        except RedisError as exc:
            log.warning("rate_limit_unavailable", error_type=type(exc).__name__)
            return
        if int(count) > limit.requests:
            scope = key.split(":", 1)[0]
            log.warning("rate_limited", scope=scope)  # no IPs or emails in logs
            raise RateLimitedError(retry_after=max(int(ttl), 1))
