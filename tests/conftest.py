import os
import tempfile
from pathlib import Path

_test_root = Path(tempfile.mkdtemp(prefix="raphael-ws-test-"))
os.environ["RAPHAEL_HOME"] = str(_test_root)
os.environ["RAPHAEL_BLOB_DIR"] = str(_test_root / "blobs")
os.environ.setdefault("RAPHAEL_AI_URL", "http://127.0.0.1:1")

import pytest


@pytest.fixture(scope="session", autouse=True)
def _postgres_migrations() -> None:
    if os.environ.get("RAPHAEL_DATABASE_URL"):
        from raphael_contracts.db import run_migrations

        run_migrations()
