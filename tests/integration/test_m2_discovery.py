# tests/integration/test_m2_discovery.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.entities import CareContextRecord
from app.services.discovery_service import DiscoveryService
from app.schemas.abdm.discovery import CareContextDiscoverRequest, PatientDiscoveryQuery


@pytest.mark.asyncio
async def test_inbound_discover_endpoint_returns_202(client: AsyncClient):
    req_id = str(uuid4())
    tx_id = str(uuid4())
    payload = {
        "requestId": req_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "transactionId": tx_id,
        "patient": {
            "id": "aditya@sbx",
            "verifiedIdentifiers": [{"type": "MOBILE", "value": "9999999999"}],
            "name": "Aditya Kumar",
            "gender": "M",
            "yearOfBirth": 1995
        },
        "hipId": "MEDTATVAA_HIP_01"
    }

    response = await client.post("/v0.5/care-contexts/discover", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"
    assert response.json()["requestId"] == req_id


@pytest.mark.asyncio
async def test_discovery_service_resolves_care_contexts(db_session: AsyncSession):
    abha_address = f"patient_{uuid4().hex[:6]}@sbx"
    local_pid = f"PAT-{uuid4().hex[:6].upper()}"

    # Pre-seed unlinked care context
    ctx = CareContextRecord(
        local_patient_id=local_pid,
        abha_address=abha_address,
        care_context_reference="STUDY-USG-001",
        display_name="Ultrasound Whole Abdomen",
        is_linked=False
    )
    db_session.add(ctx)
    await db_session.commit()

    request = CareContextDiscoverRequest(
        requestId=uuid4(),
        timestamp=datetime.now(timezone.utc),
        transactionId=uuid4(),
        patient=PatientDiscoveryQuery(
            id=abha_address,
            name="Test Patient"
        )
    )

    result = await DiscoveryService.process_discovery(db_session, request)
    assert result.error is None
    assert result.patient is not None
    assert result.patient.referenceNumber == local_pid
    assert len(result.patient.careContexts) == 1
    assert result.patient.careContexts[0].referenceNumber == "STUDY-USG-001"
    assert result.patient.careContexts[0].display == "Ultrasound Whole Abdomen"


@pytest.mark.asyncio
async def test_discovery_service_not_found(db_session: AsyncSession):
    request = CareContextDiscoverRequest(
        requestId=uuid4(),
        timestamp=datetime.now(timezone.utc),
        transactionId=uuid4(),
        patient=PatientDiscoveryQuery(
            id="unknown_patient_999@sbx"
        )
    )

    result = await DiscoveryService.process_discovery(db_session, request)
    assert result.patient is None
    assert result.error is not None
    assert result.error.code == 1404