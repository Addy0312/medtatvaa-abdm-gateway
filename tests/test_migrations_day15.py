# tests/test_migrations_day15.py
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.database import Base
import app.models.entities  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(args: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_sqlite_upgrade_head_zero_diff_and_downgrade_upgrade_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".db", prefix="mig_roundtrip_", delete=False) as tmp:
        db_path = tmp.name

    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    try:
        _run_alembic(["upgrade", "head"], async_url)

        script = (
            "from alembic.autogenerate import api as autogen_api\n"
            "from alembic.migration import MigrationContext\n"
            "from sqlalchemy import create_engine\n"
            "from app.core.database import Base\n"
            "import app.models.entities  # noqa: F401\n"
            f"engine = create_engine({sync_url!r})\n"
            "with engine.connect() as conn:\n"
            "    mc = MigrationContext.configure(conn, opts={'compare_type': True, 'compare_server_default': True})\n"
            "    diff = autogen_api.compare_metadata(mc, Base.metadata)\n"
            "assert diff == [], f'Schema diff not empty: {diff}'\n"
            "engine.dispose()\n"
        )
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            env={**os.environ, "DATABASE_URL": async_url},
            check=True,
        )

        _run_alembic(["downgrade", "base"], async_url)
        _run_alembic(["upgrade", "head"], async_url)
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


def test_link_session_migration_preserves_seeded_base_data():
    with tempfile.NamedTemporaryFile(suffix=".db", prefix="mig_seed_", delete=False) as tmp:
        db_path = tmp.name

    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    try:
        _run_alembic(["upgrade", "f5d1f786413e"], async_url)

        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO gateway_transactions (
                            gateway_transaction_id, idempotency_key, abdm_request_id,
                            operation_type, status, retry_count
                        ) VALUES (
                            'gw_seed_001', 'idem_seed_001', 'req_seed_001',
                            'CARE_CONTEXT_DISCOVER', 'CREATED', 0
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO care_contexts (
                            id, local_patient_id, abha_address, care_context_reference, display_name, is_linked
                        ) VALUES (
                            'cc_seed_001', 'PAT_SEED_001', 'seed@sbx', 'REF_SEED_001', 'Seed Study', 0
                        )
                        """
                    )
                )
        finally:
            engine.dispose()

        _run_alembic(["upgrade", "734706997e4e"], async_url)

        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                tx_row = conn.execute(
                    text(
                        "SELECT gateway_transaction_id, operation_type "
                        "FROM gateway_transactions WHERE gateway_transaction_id = 'gw_seed_001'"
                    )
                ).fetchone()
                cc_row = conn.execute(
                    text(
                        "SELECT id, local_patient_id, care_context_reference "
                        "FROM care_contexts WHERE id = 'cc_seed_001'"
                    )
                ).fetchone()
                ls_table = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='link_sessions'")
                ).fetchone()
        finally:
            engine.dispose()

        assert tx_row is not None and tx_row[0] == "gw_seed_001"
        assert cc_row is not None and cc_row[1] == "PAT_SEED_001"
        assert ls_table is not None
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


def test_offline_sql_compilation_sqlite_and_postgresql():
    sqlite_proc = _run_alembic(["upgrade", "head", "--sql"], "sqlite+aiosqlite:///:memory:")
    assert "CREATE TABLE link_sessions" in sqlite_proc.stdout
    assert "CREATE TABLE diagnostic_reports" in sqlite_proc.stdout
    assert "CREATE TABLE consent_artefacts" in sqlite_proc.stdout

    pg_proc = _run_alembic(["upgrade", "head", "--sql"], "postgresql+asyncpg://testuser:testpass@localhost:5432/testdb")
    assert "CREATE TABLE link_sessions" in pg_proc.stdout
    assert "CREATE TABLE diagnostic_reports" in pg_proc.stdout
    assert "CREATE TABLE consent_artefacts" in pg_proc.stdout
    assert "TIMESTAMP WITH TIME ZONE" in pg_proc.stdout
