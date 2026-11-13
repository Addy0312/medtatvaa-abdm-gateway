import sys
import os

# Ensure project root is in Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from app.main import app

def export_documentation():
    os.makedirs("docs", exist_ok=True)

    # 1. Export OpenAPI JSON
    openapi_data = app.openapi()
    openapi_path = os.path.join("docs", "openapi.json")
    with open(openapi_path, "w", encoding="utf-8") as f:
        json.dump(openapi_data, f, indent=2)
    print(f"✅ Exported OpenAPI specification to: {openapi_path}")

    # 2. Build Postman Collection v2.1.0
    postman_collection = {
        "info": {
            "name": "Medtatvaa ABDM Gateway API",
            "description": "Standalone REST API contract for MistiqRad and iMagic Neo integration",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": [
            {
                "name": "System Health Check",
                "request": {
                    "method": "GET",
                    "header": [],
                    "url": {
                        "raw": "{{base_url}}/api/v1/health",
                        "host": ["{{base_url}}"],
                        "path": ["api", "v1", "health"]
                    }
                }
            },
            {
                "name": "Register Patient",
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "x-idempotency-key", "value": "req-patient-001", "type": "text"},
                        {"key": "Content-Type", "value": "application/json", "type": "text"}
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": json.dumps({
                            "local_patient_id": "P12345",
                            "abha_address": "sandbox-user@sbx",
                            "name": "Test Patient",
                            "gender": "F",
                            "year_of_birth": 1980
                        }, indent=2)
                    },
                    "url": {
                        "raw": "{{base_url}}/api/v1/patients",
                        "host": ["{{base_url}}"],
                        "path": ["api", "v1", "patients"]
                    }
                }
            },
            {
                "name": "Create Care Context",
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "x-idempotency-key", "value": "req-cc-001", "type": "text"},
                        {"key": "Content-Type", "value": "application/json", "type": "text"}
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": json.dumps({
                            "local_patient_id": "P12345",
                            "abha_address": "sandbox-user@sbx",
                            "care_context_reference": "US-2026-0001",
                            "display_name": "Ultrasound Abdomen - 31 Oct 2026"
                        }, indent=2)
                    },
                    "url": {
                        "raw": "{{base_url}}/api/v1/care-contexts",
                        "host": ["{{base_url}}"],
                        "path": ["api", "v1", "care-contexts"]
                    }
                }
            },
            {
                "name": "Submit Canonical Diagnostic Report",
                "request": {
                    "method": "POST",
                    "header": [
                        {"key": "x-idempotency-key", "value": "req-report-001", "type": "text"},
                        {"key": "Content-Type", "value": "application/json", "type": "text"}
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": json.dumps({
                            "schema_version": "1.0",
                            "facility": {
                                "facility_id": "SBX-FACILITY-001",
                                "name": "Demo Imaging Centre"
                            },
                            "patient": {
                                "local_patient_id": "P12345",
                                "abha_address": "sandbox-user@sbx",
                                "name": "Test Patient",
                                "gender": "F",
                                "year_of_birth": 1980
                            },
                            "study": {
                                "local_study_id": "US-2026-0001",
                                "study_instance_uid": "1.2.840.113619.2.55.3.12345",
                                "modality": "US",
                                "study_date_time": "2026-10-31T10:00:00+05:30",
                                "description": "Ultrasound Abdomen"
                            },
                            "report": {
                                "local_report_id": "RPT-0001",
                                "status": "FINAL",
                                "title": "US Abdomen",
                                "findings": "Normal ultrasound whole abdomen study.",
                                "impression": "No focal abnormality detected.",
                                "finalized_at": "2026-10-31T10:20:00+05:30"
                            },
                            "reporting_practitioner": {
                                "name": "Dr. Test Radiologist",
                                "registration_number": "TEST-REG-1234"
                            }
                        }, indent=2)
                    },
                    "url": {
                        "raw": "{{base_url}}/api/v1/records/diagnostic-report",
                        "host": ["{{base_url}}"],
                        "path": ["api", "v1", "records", "diagnostic-report"]
                    }
                }
            },
            {
                "name": "Get Transaction Status",
                "request": {
                    "method": "GET",
                    "header": [],
                    "url": {
                        "raw": "{{base_url}}/api/v1/transactions/{{transaction_id}}",
                        "host": ["{{base_url}}"],
                        "path": ["api", "v1", "transactions", "{{transaction_id}}"]
                    }
                }
            }
        ],
        "variable": [
            {"key": "base_url", "value": "http://localhost:8000", "type": "string"},
            {"key": "transaction_id", "value": "gw_example_id", "type": "string"}
        ]
    }

    postman_path = os.path.join("docs", "Medtatvaa_Gateway_Postman_Collection.json")
    with open(postman_path, "w", encoding="utf-8") as f:
        json.dump(postman_collection, f, indent=2)
    print(f"✅ Exported Postman collection to: {postman_path}")

if __name__ == "__main__":
    export_documentation()