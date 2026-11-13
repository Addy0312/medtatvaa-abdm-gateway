import httpx
import uuid
import time
from datetime import datetime

GATEWAY_BASE_URL = "http://localhost:8000/api/v1"

def generate_sample_ultrasound_payload():
    """Generates the canonical ultrasound diagnostic report payload matching Section 9.2."""
    return {
        "schema_version": "1.0",
        "facility": {
            "facility_id": "SBX-FACILITY-001",
            "name": "Demo Imaging Centre"
        },
        "patient": {
            "local_patient_id": "P-1092",
            "abha_address": "sandbox-user@sbx",
            "name": "Ramesh Kumar",
            "gender": "M",
            "year_of_birth": 1985
        },
        "study": {
            "local_study_id": f"US-{uuid.uuid4().hex[:6].upper()}",
            "study_instance_uid": f"1.2.840.113619.2.55.3.{uuid.uuid4().hex[:8]}",
            "modality": "US",
            "study_date_time": datetime.now().isoformat(),
            "description": "Ultrasound Whole Abdomen"
        },
        "report": {
            "local_report_id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
            "status": "FINAL",
            "title": "Ultrasound Whole Abdomen Report",
            "findings": "Liver is normal in size and echotexture. Gall bladder is well distended, no calculi. Both kidneys normal in size and position.",
            "impression": "Normal ultrasound whole abdomen study. No focal abnormalities.",
            "finalized_at": datetime.now().isoformat()
        },
        "reporting_practitioner": {
            "name": "Dr. Ananya Sharma",
            "registration_number": "MCI-54321"
        }
    }

def run_simulation():
    print("=" * 60)
    print("  SIMULATING iMagic Neo ULTRASOUND WORKSTATION SUBMISSION")
    print("=" * 60)

    payload = generate_sample_ultrasound_payload()
    idempotency_key = f"mock-req-{uuid.uuid4().hex[:8]}"

    print(f"\n[1] Preparing synthetic ultrasound report for: {payload['patient']['name']}")
    print(f"    - Study ID: {payload['study']['local_study_id']}")
    print(f"    - Modality: {payload['study']['modality']}")
    print(f"    - Idempotency Key: {idempotency_key}")

    # Step 1: Submit Diagnostic Report
    print("\n[2] Submitting report to Medtatvaa ABDM Gateway...")
    headers = {
        "x-idempotency-key": idempotency_key,
        "Content-Type": "application/json"
    }

    with httpx.Client(base_url=GATEWAY_BASE_URL, timeout=10.0) as client:
        response = client.post("/records/diagnostic-report", json=payload, headers=headers)

        if response.status_code != 202:
            print(f"❌ Failed to submit report: {response.status_code} - {response.text}")
            return

        tx_data = response.json()
        tx_id = tx_data["transaction_id"]
        print("✅ Report accepted by Gateway (HTTP 202 Accepted)!")
        print(f"    - Assigned Transaction ID: {tx_id}")
        print(f"    - Initial Status: {tx_data['status']}")

        # Step 2: Poll transaction status
        print(f"\n[3] Polling transaction status for: {tx_id}...")
        time.sleep(1)
        status_res = client.get(f"/transactions/{tx_id}")

        if status_res.status_code == 200:
            status_data = status_res.json()
            print("✅ Transaction record retrieved successfully:")
            print(f"    - Operation: {status_data['operation_type']}")
            print(f"    - Current Status: {status_data['status']}")
            print(f"    - Created At: {status_data['created_at']}")
        else:
            print(f"❌ Could not poll status: {status_res.status_code}")

    print("\n" + "=" * 60)
    print("  SIMULATION COMPLETE: End-to-End Contract Flow Verified!")
    print("=" * 60)

if __name__ == "__main__":
    run_simulation()