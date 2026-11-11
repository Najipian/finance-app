"""Worker jobs: registration, retries with backoff, giving up (NFR-07)."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from arq.worker import Retry

from finance_app.providers.base import ProviderError
from finance_app.worker import settings as worker
from finance_app.worker.settings import WorkerSettings, ping, retry_delay


async def test_ping_job_returns_pong() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_jobs_and_schedules() -> None:
    names = {f.__name__ for f in WorkerSettings.functions}
    assert {"ping", "sync_connection", "revoke_consent"} <= names
    crons = {c.name for c in WorkerSettings.cron_jobs}
    assert crons == {"cron:schedule_syncs", "cron:check_consent_expiry"}
    assert WorkerSettings.max_tries == 5


def test_backoff_doubles_from_thirty_seconds() -> None:
    assert [retry_delay(n) for n in (1, 2, 3, 4)] == [30, 60, 120, 240]


class _FailingSync:
    """Stands in for ConnectionSyncService: always hits a provider outage."""

    finals: list[bool]

    def __init__(self, *_: Any) -> None:
        pass

    async def sync(self, _connection_id: uuid.UUID) -> None:
        raise ProviderError("bank down")

    async def record_failure(self, _connection_id: uuid.UUID, *, final: bool) -> None:
        _FailingSync.finals.append(final)


@asynccontextmanager
async def _no_session() -> AsyncIterator[None]:
    yield None


def _ctx(job_try: int) -> dict[str, Any]:
    return {"sessionmaker": _no_session, "provider": None, "cipher": None, "job_try": job_try}


async def test_transient_failure_is_retried_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    _FailingSync.finals = []
    monkeypatch.setattr(worker, "ConnectionSyncService", _FailingSync)

    with pytest.raises(Retry) as exc_info:
        await worker.sync_connection(_ctx(job_try=2), str(uuid.uuid4()))

    assert exc_info.value.defer_score == 60_000  # milliseconds
    assert _FailingSync.finals == [False]  # shown as "retrying"


async def test_last_try_gives_up_and_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _FailingSync.finals = []
    monkeypatch.setattr(worker, "ConnectionSyncService", _FailingSync)

    assert await worker.sync_connection(_ctx(job_try=5), str(uuid.uuid4())) is None
    assert _FailingSync.finals == [True]  # shown as "failed"


class _Provider:
    name = "mock"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.revoked: list[str] = []

    async def revoke_consent(self, consent_id: str) -> None:
        if self.failures:
            self.failures -= 1
            raise ProviderError("down")
        self.revoked.append(consent_id)


class _RecordingSession:
    """Captures audit events the job stages."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False

    def add(self, item: Any) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.committed = True


async def test_revoke_job_retries_then_succeeds_and_is_audited_br04() -> None:
    provider = _Provider(failures=1)
    session = _RecordingSession()

    @asynccontextmanager
    async def sessionmaker() -> AsyncIterator[_RecordingSession]:
        yield session

    ctx: dict[str, Any] = {"provider": provider, "sessionmaker": sessionmaker}
    with pytest.raises(Retry):
        await worker.revoke_consent({**ctx, "job_try": 1}, "mock", "c-1")
    assert await worker.revoke_consent({**ctx, "job_try": 2}, "mock", "c-1")

    assert provider.revoked == ["c-1"]
    assert [e.action for e in session.added] == ["consent.revoked"] and session.committed


async def test_revoke_job_gives_up_and_skips_other_providers() -> None:
    assert not await worker.revoke_consent({"provider": _Provider(9), "job_try": 5}, "mock", "c")
    assert not await worker.revoke_consent({"provider": _Provider(0)}, "yapily", "c")
