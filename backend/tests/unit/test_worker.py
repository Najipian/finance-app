from finance_app.worker.settings import WorkerSettings, ping


async def test_ping_job_returns_pong() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_ping() -> None:
    assert ping in WorkerSettings.functions
