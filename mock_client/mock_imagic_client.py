import httpx
import uuid
import time
from datetime import datetime

GATEWAY_BASE_URL = "http://localhost:8000/api/v1"

def run_unified_clinical_simulation():
    print("=" * 68)
    print("  SIMULATING iMagic Neo / MistiqRad ABDM WORKFLOW (M1 + REPORT)")
    print("=" * 68)

    patient_abha = "sandbox-user@sbx"
    test_otp = "123456"
    study_id = f"US-{uuid.uuid4().hex[:6].upper()}"

    with httpx.Client(base_url=GATEWAY_BASE_URL, timeout=10.0) as client:

        # -------------------------------------------------------------
        # STEP 1: M1 - Initiate ABHA Identity Verification
        # -------------------------------------------------------------
        print(f"\n[STEP 1] Patient arrives. Initiating ABHA Verification for: {patient_abha}")
        m1_init_res = client.post(
            "/abha/verify-or-link",
            json={"abha_address": patient_abha, "auth_mode": "MOBILE_OTP"},
            headers={"x-idempotency-key": f"m1-init-{uuid.uuid4().hex[:8]}"}
        )
        assert m1_init_res.status_code == 200, f"M1 Init Failed: {m1_init_res.text}"
        m1_data = m1_init_res.json()
        tx_id = m1_data["transaction_id"]
        print(f"✅ OTP Dispatched to patient's registered mobile.")
        print(f"    - Transaction ID: {tx_id}")
        print(f"    - Required Action: {m1_data['action_required']}")

        # -------------------------------------------------------------
        # STEP 2: M1 - Patient Enters OTP & Retrieve Profile
        # -------------------------------------------------------------
        print(f"\n[STEP 2] Patient provides OTP: '{test_otp}'. Submitting for verification...")
        otp_res = client.post(
            "/abha/confirm-otp",
            json={"transaction_id": tx_id, "otp": test_otp}
        )
        assert otp_res.status_code == 200, f"OTP Confirm Failed: {otp_res.text}"
        verified_profile = otp_res.json()["profile"]
        print(f"✅ Patient Identity Verified Successfully!")
        print(f"    - Full Name:       {verified_profile['name']}")
        print(f"    - Gender:          {verified_profile['gender']}")
        print(f"    - Year of Birth:   {verified_profile['year_of_birth']}")
        print(f"    - ABHA Number:     {verified_profile['abha_number']}")

        # -------------------------------------------------------------
        # STEP 3: Register / Index Patient in Gateway
        # -------------------------------------------------------------
        print(f"\n[STEP 3] Indexing patient demographics in Medtatvaa Gateway...")
        local_patient_id = "P-1092"
        pat_res = client.post(
            "/patients",
            json={
                "local_patient_id": local_patient_id,
                "abha_address": patient_abha,
                "name": verified_profile["name"],
                "gender": verified_profile["gender"],
                "year_of_birth": verified_profile["year_of_birth"]
            },
            headers={"x-idempotency-key": f"pat-reg-{uuid.uuid4().hex[:8]}"}
        )
        assert pat_res.status_code == 201
        print(f"✅ Patient registered: {local_patient_id} ➔ {patient_abha}")

        # -------------------------------------------------------------
        # STEP 4: Ultrasound Scan Conducted & Care Context Created
        # -------------------------------------------------------------
        print(f"\n[STEP 4] Ultrasound procedure conducted. Registering Care Context: {study_id}...")
        cc_res = client.post(
            "/care-contexts",
            json={
                "local_patient_id": local_patient_id,
                "abha_address": patient_abha,
                "care_context_reference": study_id,
                "display_name": "Ultrasound Whole Abdomen"
            },
            headers={"x-idempotency-key": f"cc-{uuid.uuid4().hex[:8]}"}
        )
        assert cc_res.status_code == 201
        print(f"✅ Care Context created and linked to study reference: {study_id}")

        # -------------------------------------------------------------
        # STEP 5: Radiologist Finalizes Canonical Diagnostic Report
        # -------------------------------------------------------------
        print(f"\n[STEP 5] Radiologist finalizes report. Submitting canonical JSON...")
        canonical_report = {
            "schema_version": "1.0",
            "facility": {
                "facility_id": "SBX-FACILITY-001",
                "name": "Demo Imaging Centre"
            },
            "patient": {
                "local_patient_id": local_patient_id,
                "abha_address": patient_abha,
                "name": verified_profile["name"],
                "gender": verified_profile["gender"],
                "year_of_birth": verified_profile["year_of_birth"]
            },
            "study": {
                "local_study_id": study_id,
                "study_instance_uid": f"1.2.840.113619.2.55.3.{uuid.uuid4().hex[:8]}",
                "modality": "US",
                "study_date_time": datetime.now().isoformat(),
                "description": "Ultrasound Whole Abdomen"
            },
            "report": {
                "local_report_id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
                "status": "FINAL",
                "title": "Ultrasound Whole Abdomen Report",
                "findings": "Liver, gallbladder, spleen, pancreas, and both kidneys appear completely normal. No calculi or focal lesions detected.",
                "impression": "Normal ultrasound whole abdomen study.",
                "finalized_at": datetime.now().isoformat()
            },
            "reporting_practitioner": {
                "name": "Dr. Ananya Sharma",
                "registration_number": "MCI-54321"
            }
        }

        rpt_res = client.post(
            "/records/diagnostic-report",
            json=canonical_report,
            headers={"x-idempotency-key": f"rpt-{uuid.uuid4().hex[:8]}"}
        )
        assert rpt_res.status_code == 202
        rpt_tx_id = rpt_res.json()["transaction_id"]
        print(f"✅ Diagnostic Report accepted by Gateway (HTTP 202 Accepted)!")
        print(f"    - Assigned Transaction ID: {rpt_tx_id}")

        # -------------------------------------------------------------
        # STEP 6: Poll Status of Report Ingestion
        # -------------------------------------------------------------
        print(f"\n[STEP 6] Polling transaction status for: {rpt_tx_id}...")
        time.sleep(1)
        status_res = client.get(f"/transactions/{rpt_tx_id}")
        assert status_res.status_code == 200
        tx_data = status_res.json()
        print(f"✅ Transaction Status Verified:")
        print(f"    - Operation:    {tx_data['operation_type']}")
        print(f"    - State:        {tx_data['status']}")
        print(f"    - Timestamp:    {tx_data['created_at']}")

    print("\n" + "=" * 68)
    print("  🎉 COMPLETE CLINICAL M1 + REPORT LIFECYCLE VERIFIED!")
    print("=" * 68)

if __name__ == "__main__":
    run_unified_clinical_simulation()