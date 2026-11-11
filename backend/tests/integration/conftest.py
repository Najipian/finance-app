"""Integration-test setup (real containers via testcontainers)."""

import os
import sys

# On Windows with Docker Desktop, testcontainers can read the Ryuk reaper's port
# mapping before Docker publishes it ("Port mapping ... 8080 is not available").
# Our fixtures stop their containers via context managers, so Ryuk is not needed
# locally. CI runs on Linux and keeps Ryuk enabled.
if sys.platform == "win32":
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
