# scripts/generate_day16_fhir_samples.py
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.schemas.canonical_report import CanonicalDiagnosticReportPayload
from app.services.fhir_builders import (
    FhirBuilderConfig,
    build_findings_observation,
    build_impression_observation,
    build_organization_resource,
    build_patient_resource,
    build_practitioner_resource,
)


def main() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    payload = CanonicalDiagnosticReportPayload.model_validate(
        {
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
                "study_date_time": datetime(2026, 10, 31, 10, 0, 0, tzinfo=ist),
                "description": "Ultrasound Abdomen",
            },
            "report": {
                "local_report_id": "RPT-0001",
                "status": "FINAL",
                "title": "US Abdomen",
                "findings": "Synthetic test findings only. Liver and kidneys appear normal.",
                "impression": "Synthetic test impression only. No focal abnormalities.",
                "finalized_at": datetime(2026, 10, 31, 10, 20, 0, tzinfo=ist),
            },
            "reporting_practitioner": {
                "name": "Dr Test",
                "registration_number": "TEST-REG-1234",
            },
        }
    )

    config = FhirBuilderConfig(
        facility_identifier_system="https://example.org/fhir/sid/facility",
        patient_identifier_system="https://example.org/fhir/sid/mrn",
        practitioner_identifier_system="https://example.org/fhir/sid/practitioner",
        abha_identifier_system=None,
        practitioner_identifier_type="PRN",
        id_namespace=UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
    )

    samples = {
        "patient": build_patient_resource(payload, config),
        "organization": build_organization_resource(payload, config),
        "practitioner": build_practitioner_resource(payload, config),
        "observation_findings": build_findings_observation(payload, config),
        "observation_impression": build_impression_observation(payload, config),
    }
    print(json.dumps(samples, indent=2))


if __name__ == "__main__":
    main()
