"""Rate limiter behaviour that doesn't need a real Redis."""

from types import TracebackType
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from finance_app.core.errors import RateLimitedError
from finance_app.core.rate_limit import RateLimit, RateLimiter, hashed_key_part

LIMIT = RateLimit(requests=1, window_seconds=60)


class BrokenPipeline:
    async def __aenter__(self) -> "BrokenPipeline":
        return self

    async def __aexit__(
        self, *_: type[BaseException] | BaseException | TracebackType | None
    ) -> None:
        return None

    def __getattr__(self, _name: str) -> Any:
        return lambda *_a, **_k: None

    async def execute(self) -> list[Any]:
        raise RedisConnectionError("redis down")


class BrokenRedis:
    def pipeline(self, transaction: bool = True) -> BrokenPipeline:
        return BrokenPipeline()


async def test_limiter_fails_open_when_redis_is_down() -> None:
    limiter = RateLimiter(BrokenRedis())  # type: ignore[arg-type]

    for _ in range(5):
        await limiter.hit("login:ip:203.0.113.7", LIMIT)  # never raises


async def test_disabled_limiter_never_touches_redis() -> None:
    limiter = RateLimiter(None, enabled=False)  # type: ignore[arg-type]

    await limiter.hit("anything", LIMIT)


def test_rate_limited_error_carries_retry_after() -> None:
    error = RateLimitedError(retry_after=42)

    assert error.status_code == 429
    assert error.headers == {"Retry-After": "42"}
    assert "42 seconds" in (error.detail or "")


def test_hashed_key_part_hides_the_value_and_is_stable() -> None:
    key = hashed_key_part("sara@example.com")

    assert "sara" not in key
    assert key == hashed_key_part("sara@example.com")
    assert len(key) == 32


def test_error_headers_are_not_shared_between_instances() -> None:
    first, second = RateLimitedError(retry_after=1), RateLimitedError(retry_after=99)

    assert first.headers["Retry-After"] == "1"
    assert second.headers["Retry-After"] == "99"


@pytest.mark.parametrize("retry_after", [1, 900])
def test_retry_after_is_whole_seconds(retry_after: int) -> None:
    assert RateLimitedError(retry_after).headers["Retry-After"] == str(retry_after)
