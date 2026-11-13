import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from datetime import datetime
from app.main import app

@pytest.fixture
async def async_client():
    """Asynchronous test client using the FastAPI ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Verifies gateway liveness and database connectivity."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"

@pytest.mark.asyncio
async def test_patient_registration_and_idempotency(async_client: AsyncClient):
    """Verifies patient registration and ensures duplicate requests return the same record."""
    idempotency_key = f"idemp-pat-{uuid.uuid4().hex[:8]}"
    payload = {
        "local_patient_id": "P-TEST-001",
        "abha_address": "test-patient@sbx",
        "name": "Integration Test Patient",
        "gender": "F",
        "year_of_birth": 1992
    }
    headers = {"x-idempotency-key": idempotency_key}

    # First submission
    res1 = await async_client.post("/api/v1/patients", json=payload, headers=headers)
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["local_patient_id"] == "P-TEST-001"
    assert data1["is_registered"] is True

    # Duplicate submission with same idempotency key
    res2 = await async_client.post("/api/v1/patients", json=payload, headers=headers)
    assert res2.status_code == 201
    assert res2.json() == data1

@pytest.mark.asyncio
async def test_care_context_creation(async_client: AsyncClient):
    """Verifies study care-context registration."""
    idempotency_key = f"idemp-cc-{uuid.uuid4().hex[:8]}"
    payload = {
        "local_patient_id": "P-TEST-001",
        "abha_address": "test-patient@sbx",
        "care_context_reference": f"US-{uuid.uuid4().hex[:6].upper()}",
        "display_name": "Ultrasound Whole Abdomen"
    }
    headers = {"x-idempotency-key": idempotency_key}

    res = await async_client.post("/api/v1/care-contexts", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["abha_address"] == "test-patient@sbx"
    assert data["is_linked"] is False

@pytest.mark.asyncio
async def test_diagnostic_report_submission_and_transaction_polling(async_client: AsyncClient):
    """Verifies diagnostic report ingestion, transaction creation, and status polling."""
    idempotency_key = f"idemp-rpt-{uuid.uuid4().hex[:8]}"
    study_id = f"US-{uuid.uuid4().hex[:6].upper()}"

    payload = {
        "schema_version": "1.0",
        "facility": {
            "facility_id": "SBX-FACILITY-001",
            "name": "Demo Imaging Centre"
        },
        "patient": {
            "local_patient_id": "P-TEST-001",
            "abha_address": "test-patient@sbx",
            "name": "Integration Test Patient",
            "gender": "F",
            "year_of_birth": 1992
        },
        "study": {
            "local_study_id": study_id,
            "study_instance_uid": f"1.2.840.113619.2.55.3.{uuid.uuid4().hex[:8]}",
            "modality": "US",
            "study_date_time": datetime.now().isoformat(),
            "description": "Ultrasound Abdomen"
        },
        "report": {
            "local_report_id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
            "status": "FINAL",
            "title": "US Abdomen",
            "findings": "All abdominal organs appear normal.",
            "impression": "Normal ultrasound abdomen.",
            "finalized_at": datetime.now().isoformat()
        },
        "reporting_practitioner": {
            "name": "Dr. Test Radiologist",
            "registration_number": "MED-TEST-999"
        }
    }
    headers = {"x-idempotency-key": idempotency_key}

    # 1. Submit Report
    submit_res = await async_client.post("/api/v1/records/diagnostic-report", json=payload, headers=headers)
    assert submit_res.status_code == 202
    submit_data = submit_res.json()
    tx_id = submit_data["transaction_id"]
    assert tx_id.startswith("gw_")
    assert submit_data["status"] == "PENDING"

    # 2. Poll Transaction Status
    poll_res = await async_client.get(f"/api/v1/transactions/{tx_id}")
    assert poll_res.status_code == 200
    poll_data = poll_res.json()
    assert poll_data["transaction_id"] == tx_id
    assert poll_data["operation_type"] == "REPORT_SHARE"
    assert poll_data["status"] == "PENDING"

@pytest.mark.asyncio
async def test_transaction_not_found_error(async_client: AsyncClient):
    """Verifies normalized 404 response when querying a non-existent transaction."""
    fake_id = "gw_non_existent_uuid_12345"
    response = await async_client.get(f"/api/v1/transactions/{fake_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error_code"] == "TRANSACTION_NOT_FOUND"

@pytest.mark.asyncio
async def test_malformed_report_validation_error(async_client: AsyncClient):
    """Verifies that an invalid report payload returns Medtatvaa normalized 422 error."""
    invalid_payload = {
        "schema_version": "1.0",
        "patient": {"name": "Incomplete Payload"}  # Missing facility, study, report, etc.
    }
    headers = {"x-idempotency-key": "bad-payload-key"}
    response = await async_client.post("/api/v1/records/diagnostic-report", json=invalid_payload, headers=headers)
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "FHIR_VALIDATION_FAILED"
    assert data["status"] == "FAILED_FINAL"