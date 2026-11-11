"""The worker must work as its own process, not only inside the test process.

Regression test: the worker once failed in Docker with ``NoReferencedTableError``
because it never imported the ``User`` model. In-process tests didn't catch it,
since the API had already imported every model. This runs a fresh interpreter.
"""

import os
import subprocess
import sys

CHECK = (
    "import finance_app.worker.settings\n"
    "from sqlalchemy.orm import configure_mappers\n"
    "from finance_app.db.base import Base\n"
    "configure_mappers()\n"
    "for table in Base.metadata.sorted_tables:\n"
    "    for fk in table.foreign_keys:\n"
    "        fk.column  # raises NoReferencedTableError if the target isn't registered\n"
    "print(sorted(Base.metadata.tables))\n"
)


def test_worker_process_registers_every_model() -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", CHECK],
        capture_output=True,
        text=True,
        env={**os.environ, "ENVIRONMENT": "test"},
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for table in ("users", "refresh_tokens", "bank_connections", "accounts", "balances"):
        assert table in result.stdout
