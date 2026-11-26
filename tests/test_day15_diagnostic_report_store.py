# tests/test_day15_diagnostic_report_store.py
import json
from typing import AsyncGenerator
from unittest.mock import patch
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.records import router as records_router
from app.core.database import Base, get_db
from app.models.entities import (
    CareContextRecord,
    DiagnosticReportStore,
    GatewayTransaction,
    TransactionStatus,
)
from app.schemas.canonical_report import CanonicalDiagnosticReportPayload
from app.services.diagnostic_report_service import DiagnosticReportService
from app.services.transaction_service import TransactionConflictError, TransactionService


def _sample_payload(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "facility": {
            "facility_id": "SBX-FACILITY-ID",
            "name": "Demo Imaging Centre",
        },
        "patient": {
            "local_patient_id": "P12345",
            "abha_address": "sandbox-user@sbx",
            "name": "Test Patient",
            "gender": "F",
            "year_of_birth": 1980,
        },
        "study": {
            "local_study_id": "US-2026-0001",
            "study_instance_uid": "1.2.840.113619.2.55.3.12345",
            "modality": "US",
            "study_date_time": "2026-10-31T10:00:00+05:30",
            "description": "Ultrasound Abdomen",
        },
        "report": {
            "local_report_id": "RPT-0001",
            "status": "FINAL",
            "title": "US Abdomen",
            "findings": "Synthetic test findings only. Liver and kidneys appear normal.",
            "impression": "Synthetic test impression only. No focal abnormalities.",
            "finalized_at": "2026-10-31T10:20:00+05:30",
        },
        "reporting_practitioner": {
            "name": "Dr Test",
            "registration_number": "TEST-REG-1234",
        },
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            base[key].update(val)
        else:
            base[key] = val
    return base


@pytest_asyncio.fixture
async def isolated_db() -> AsyncGenerator[tuple[AsyncSession, async_sessionmaker[AsyncSession]], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session, session_factory

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(isolated_db) -> AsyncGenerator[AsyncSession, None]:
    session, _ = isolated_db
    yield session


@pytest_asyncio.fixture
async def api_client(isolated_db) -> AsyncGenerator[AsyncClient, None]:
    _, session_factory = isolated_db
    app = FastAPI()
    app.include_router(records_router, prefix="/api/v1")

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_store_persists_full_canonical_json_under_care_context_and_patient_identity(
    db_session: AsyncSession,
):
    payload_dict = _sample_payload()
    payload = CanonicalDiagnosticReportPayload.model_validate(payload_dict)

    tx = GatewayTransaction(
        gateway_transaction_id="gw_test001",
        idempotency_key="idem-day15-001",
        abdm_request_id="req-001",
        operation_type="REPORT_SHARE",
        status=TransactionStatus.PENDING,
        retry_count=0,
    )
    db_session.add(tx)
    await db_session.flush()

    record, created = await DiagnosticReportService.persist_canonical_report(
        db=db_session,
        payload=payload,
        idempotency_key="idem-day15-001",
        gateway_transaction=tx,
        commit=True,
    )

    assert created is True
    assert isinstance(record, DiagnosticReportStore)
    assert record.gateway_transaction_id == "gw_test001"

    fetched = await DiagnosticReportService.get_by_key_tuple(
        db=db_session,
        abha_address="sandbox-user@sbx",
        care_context_reference="US-2026-0001",
        local_report_id="RPT-0001",
    )
    assert fetched is not None
    assert fetched.id == record.id
    stored_obj = json.loads(fetched.payload_json)
    assert stored_obj["schema_version"] == "1.0"
    assert stored_obj["facility"]["facility_id"] == "SBX-FACILITY-ID"
    assert stored_obj["patient"]["local_patient_id"] == "P12345"
    assert stored_obj["patient"]["abha_address"] == "sandbox-user@sbx"
    assert stored_obj["study"]["local_study_id"] == "US-2026-0001"
    assert stored_obj["report"]["local_report_id"] == "RPT-0001"
    assert stored_obj["report"]["findings"] == payload_dict["report"]["findings"]
    assert stored_obj["reporting_practitioner"]["registration_number"] == "TEST-REG-1234"


@pytest.mark.asyncio
async def test_two_reports_same_care_context_coexist(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    r1 = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(report={"local_report_id": "RPT-0001", "title": "Initial Report"}),
        headers={"X-Idempotency-Key": "idem-cc-r1"},
    )
    r2 = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(report={"local_report_id": "RPT-0002", "title": "Follow-up Report"}),
        headers={"X-Idempotency-Key": "idem-cc-r2"},
    )

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["transaction_id"] != r2.json()["transaction_id"]

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(DiagnosticReportStore)
            .where(
                DiagnosticReportStore.abha_address == "sandbox-user@sbx",
                DiagnosticReportStore.care_context_reference == "US-2026-0001",
            )
        )
    ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_patient_isolation_across_care_contexts(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    r1 = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(
            patient={"local_patient_id": "P-A", "abha_address": "patient-a@sbx"},
            study={"local_study_id": "US-2026-A"},
            report={"local_report_id": "RPT-A"},
        ),
        headers={"X-Idempotency-Key": "idem-pat-a"},
    )
    r2 = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(
            patient={"local_patient_id": "P-B", "abha_address": "patient-b@sbx"},
            study={"local_study_id": "US-2026-B"},
            report={"local_report_id": "RPT-B"},
        ),
        headers={"X-Idempotency-Key": "idem-pat-b"},
    )

    assert r1.status_code == 202
    assert r2.status_code == 202

    rep_a = await DiagnosticReportService.get_by_key_tuple(
        db=db_session,
        abha_address="patient-a@sbx",
        care_context_reference="US-2026-A",
        local_report_id="RPT-A",
    )
    rep_b = await DiagnosticReportService.get_by_key_tuple(
        db=db_session,
        abha_address="patient-b@sbx",
        care_context_reference="US-2026-B",
        local_report_id="RPT-B",
    )
    assert rep_a is not None and rep_a.local_patient_id == "P-A"
    assert rep_b is not None and rep_b.local_patient_id == "P-B"


@pytest.mark.asyncio
async def test_mismatched_patient_identity_rejected_with_409_and_does_not_write(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    first = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(
            patient={"local_patient_id": "P12345", "abha_address": "sandbox-user@sbx"},
            study={"local_study_id": "US-2026-0001"},
            report={"local_report_id": "RPT-0001"},
        ),
        headers={"X-Idempotency-Key": "idem-id-ok"},
    )
    assert first.status_code == 202

    mismatch = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(
            patient={"local_patient_id": "P-WRONG", "abha_address": "sandbox-user@sbx"},
            study={"local_study_id": "US-2026-0001"},
            report={"local_report_id": "RPT-0002"},
        ),
        headers={"X-Idempotency-Key": "idem-id-mismatch"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error_code"] == "PATIENT_IDENTITY_CONFLICT"

    tx_exists = (
        await db_session.execute(
            select(func.count())
            .select_from(GatewayTransaction)
            .where(GatewayTransaction.idempotency_key == "idem-id-mismatch")
        )
    ).scalar_one()
    rep_exists = (
        await db_session.execute(
            select(func.count())
            .select_from(DiagnosticReportStore)
            .where(DiagnosticReportStore.local_report_id == "RPT-0002")
        )
    ).scalar_one()
    assert tx_exists == 0
    assert rep_exists == 0


@pytest.mark.asyncio
async def test_identical_report_with_new_key_returns_409_and_persists_no_new_tx_or_report(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    payload = _sample_payload()
    first = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=payload,
        headers={"X-Idempotency-Key": "idem-tuple-first"},
    )
    assert first.status_code == 202
    first_tx_id = first.json()["transaction_id"]

    duplicate = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=payload,
        headers={"X-Idempotency-Key": "idem-tuple-new-key"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "CARE_CONTEXT_REPORT_CONFLICT"
    assert duplicate.json()["transaction_id"] == first_tx_id

    new_tx_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GatewayTransaction)
            .where(GatewayTransaction.idempotency_key == "idem-tuple-new-key")
        )
    ).scalar_one()
    total_reports = (
        await db_session.execute(select(func.count()).select_from(DiagnosticReportStore))
    ).scalar_one()
    assert new_tx_count == 0
    assert total_reports == 1


@pytest.mark.asyncio
async def test_same_key_conflicting_body_with_different_study_does_not_create_care_context(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    initial_payload = _sample_payload()
    first = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=initial_payload,
        headers={"X-Idempotency-Key": "idem-study-conflict"},
    )
    assert first.status_code == 202

    conflicting_different_study = _sample_payload(
        study={"local_study_id": "US-2026-OTHER-STUDY", "description": "Ultrasound Pelvis"},
        report={"findings": "Different findings with reused idempotency key"},
    )
    res = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=conflicting_different_study,
        headers={"X-Idempotency-Key": "idem-study-conflict"},
    )
    assert res.status_code == 409
    assert res.json()["error_code"] == "IDEMPOTENCY_PAYLOAD_CONFLICT"

    other_cc_count = (
        await db_session.execute(
            select(func.count())
            .select_from(CareContextRecord)
            .where(CareContextRecord.care_context_reference == "US-2026-OTHER-STUDY")
        )
    ).scalar_one()
    other_report_count = (
        await db_session.execute(
            select(func.count())
            .select_from(DiagnosticReportStore)
            .where(DiagnosticReportStore.care_context_reference == "US-2026-OTHER-STUDY")
        )
    ).scalar_one()
    assert other_cc_count == 0
    assert other_report_count == 0


@pytest.mark.asyncio
async def test_replay_across_status_advancements_returns_current_status_and_payload_conflict(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    payload = _sample_payload()
    headers = {"X-Idempotency-Key": "idem-status-advance"}

    res1 = await api_client.post("/api/v1/records/diagnostic-report", json=payload, headers=headers)
    assert res1.status_code == 202
    body1 = res1.json()
    tx_id = body1["transaction_id"]
    req_id = body1["abdm_request_id"]
    assert body1["status"] == TransactionStatus.PENDING.value

    for next_status in (
        TransactionStatus.LINKED.value,
        TransactionStatus.SHARED.value,
        TransactionStatus.COMPLETED.value,
    ):
        tx = await db_session.get(GatewayTransaction, tx_id)
        assert tx is not None
        tx.status = next_status
        await db_session.commit()

        replay = await api_client.post("/api/v1/records/diagnostic-report", json=payload, headers=headers)
        assert replay.status_code == 202
        replay_body = replay.json()
        assert replay_body["transaction_id"] == tx_id
        assert replay_body["abdm_request_id"] == req_id
        assert replay_body["status"] == next_status

    mutated_payload = _sample_payload(report={"findings": "Changed findings on replay"})
    res_conflict = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=mutated_payload,
        headers=headers,
    )
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error_code"] == "IDEMPOTENCY_PAYLOAD_CONFLICT"


@pytest.mark.asyncio
async def test_cross_operation_idempotency_key_returns_409_in_endpoint_and_service(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    other_tx = GatewayTransaction(
        gateway_transaction_id="gw_other_op_001",
        idempotency_key="idem-cross-op",
        abdm_request_id="req-cross-op",
        operation_type="CARE_CONTEXT_LINK",
        status=TransactionStatus.LINKED.value,
        retry_count=0,
    )
    db_session.add(other_tx)
    await db_session.commit()

    res = await api_client.post(
        "/api/v1/records/diagnostic-report",
        json=_sample_payload(),
        headers={"X-Idempotency-Key": "idem-cross-op"},
    )
    assert res.status_code == 409
    assert res.json()["error_code"] == "IDEMPOTENCY_OPERATION_CONFLICT"

    with pytest.raises(TransactionConflictError):
        await TransactionService.get_or_create_transaction(
            db=db_session,
            idempotency_key="idem-cross-op",
            operation_type="REPORT_SHARE",
            commit=False,
        )


@pytest.mark.asyncio
async def test_actual_helper_integrity_error_maps_to_409_and_rolls_back(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    race_payload = _sample_payload(
        patient={"local_patient_id": "P-HELPER-RACE", "abha_address": "helper-race@sbx"},
        study={"local_study_id": "US-HELPER-RACE-01"},
        report={"local_report_id": "RPT-HELPER-RACE-01"},
    )

    with patch.object(
        TransactionService,
        "get_or_create_transaction",
        side_effect=IntegrityError(
            "UNIQUE constraint failed: gateway_transactions.idempotency_key",
            params=None,
            orig=Exception("unique violation in transaction helper"),
        ),
    ):
        res = await api_client.post(
            "/api/v1/records/diagnostic-report",
            json=race_payload,
            headers={"X-Idempotency-Key": "idem-helper-race-01"},
        )

    assert res.status_code == 409
    assert res.json()["error_code"] == "CONCURRENT_PERSISTENCE_CONFLICT"

    tx_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GatewayTransaction)
            .where(GatewayTransaction.idempotency_key == "idem-helper-race-01")
        )
    ).scalar_one()
    cc_count = (
        await db_session.execute(
            select(func.count())
            .select_from(CareContextRecord)
            .where(CareContextRecord.care_context_reference == "US-HELPER-RACE-01")
        )
    ).scalar_one()
    rep_count = (
        await db_session.execute(
            select(func.count())
            .select_from(DiagnosticReportStore)
            .where(DiagnosticReportStore.care_context_reference == "US-HELPER-RACE-01")
        )
    ).scalar_one()
    assert tx_count == 0
    assert cc_count == 0
    assert rep_count == 0


@pytest.mark.asyncio
async def test_conflict_does_not_write_race_maps_to_409_and_runtime_error_rolls_back(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    payload = _sample_payload()
    headers = {"X-Idempotency-Key": "idem-conflict-nowrite"}

    res1 = await api_client.post("/api/v1/records/diagnostic-report", json=payload, headers=headers)
    assert res1.status_code == 202

    # Conflict with same idempotency key and modified report does not write new records
    mutated = _sample_payload(report={"findings": "Changed findings"})
    res_conflict = await api_client.post("/api/v1/records/diagnostic-report", json=mutated, headers=headers)
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error_code"] == "IDEMPOTENCY_PAYLOAD_CONFLICT"

    total_reports = (
        await db_session.execute(select(func.count()).select_from(DiagnosticReportStore))
    ).scalar_one()
    assert total_reports == 1

    # Simulate concurrent IntegrityError during store persistence -> 409 and rollback
    race_payload = _sample_payload(
        patient={"local_patient_id": "P-RACE", "abha_address": "race@sbx"},
        study={"local_study_id": "US-RACE-01"},
        report={"local_report_id": "RPT-RACE-01"},
    )
    with patch.object(
        DiagnosticReportService,
        "persist_canonical_report",
        side_effect=IntegrityError("UNIQUE constraint failed", params=None, orig=Exception("race")),
    ):
        res_race = await api_client.post(
            "/api/v1/records/diagnostic-report",
            json=race_payload,
            headers={"X-Idempotency-Key": "idem-race-01"},
        )

    assert res_race.status_code == 409
    assert res_race.json()["error_code"] == "CONCURRENT_PERSISTENCE_CONFLICT"

    race_tx_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GatewayTransaction)
            .where(GatewayTransaction.idempotency_key == "idem-race-01")
        )
    ).scalar_one()
    race_cc_count = (
        await db_session.execute(
            select(func.count())
            .select_from(CareContextRecord)
            .where(CareContextRecord.care_context_reference == "US-RACE-01")
        )
    ).scalar_one()
    assert race_tx_count == 0
    assert race_cc_count == 0

    # RuntimeError rollback test: no orphan transaction, care context, or report is committed
    rollback_payload = _sample_payload(
        patient={"local_patient_id": "P-ROLLBACK", "abha_address": "rollback@sbx"},
        study={"local_study_id": "US-ROLLBACK-01"},
        report={"local_report_id": "RPT-ROLLBACK-01"},
    )
    with patch.object(
        DiagnosticReportService,
        "persist_canonical_report",
        side_effect=RuntimeError("Simulated unexpected failure during persistence"),
    ):
        with pytest.raises(RuntimeError, match="Simulated unexpected failure during persistence"):
            await api_client.post(
                "/api/v1/records/diagnostic-report",
                json=rollback_payload,
                headers={"X-Idempotency-Key": "idem-runtime-rollback"},
            )

    rb_tx_count = (
        await db_session.execute(
            select(func.count())
            .select_from(GatewayTransaction)
            .where(GatewayTransaction.idempotency_key == "idem-runtime-rollback")
        )
    ).scalar_one()
    rb_cc_count = (
        await db_session.execute(
            select(func.count())
            .select_from(CareContextRecord)
            .where(CareContextRecord.care_context_reference == "US-ROLLBACK-01")
        )
    ).scalar_one()
    rb_rep_count = (
        await db_session.execute(
            select(func.count())
            .select_from(DiagnosticReportStore)
            .where(DiagnosticReportStore.care_context_reference == "US-ROLLBACK-01")
        )
    ).scalar_one()
    assert rb_tx_count == 0
    assert rb_cc_count == 0
    assert rb_rep_count == 0
