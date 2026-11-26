# tests/conftest.py
import atexit
import os
import tempfile
from typing import AsyncGenerator

import pytest_asyncio


def _configure_disposable_test_db() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", prefix="pytest_day15_", delete=False)
    tmp_path = tmp.name
    tmp.close()

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path}"

    def _cleanup() -> None:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    atexit.register(_cleanup)
    return tmp_path


_DISPOSABLE_DB_PATH = _configure_disposable_test_db()

from app.core.database import Base, engine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _ensure_schema_initialized() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
