# scripts/generate_day17_bundle_sample.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

from app.schemas.canonical_report import (
    CanonicalDiagnosticReportPayload,
    FacilityInfo,
    PatientDemographics,
    ReportingPractitioner,
    ReportInfo,
    StudyInfo,
)
from app.services.fhir_builders import FhirBuilderConfig
from app.services.fhir_bundle_assembler import FhirBundleConfig, build_diagnostic_report_bundle

SYNTHETIC_PDF_BYTES: bytes = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>\nendobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n"
    b"0000000061 00000 n \n0000000118 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n182\n%%EOF\n"
)


def main() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    payload = CanonicalDiagnosticReportPayload(
        schema_version="1.0",
        facility=FacilityInfo(
            facility_id="SBX-FACILITY-ID",
            name="Demo Imaging Centre",
        ),
        patient=PatientDemographics(
            local_patient_id="P12345",
            abha_address="sandbox-user@sbx",
            name="Test Patient",
            gender="F",
            year_of_birth=1980,
        ),
        study=StudyInfo(
            local_study_id="US-2026-0001",
            study_instance_uid="1.2.840.113619.2.55.3.12345",
            modality="US",
            study_date_time=datetime(2026, 10, 31, 10, 0, 0, tzinfo=ist),
            description="Ultrasound Abdomen",
        ),
        report=ReportInfo(
            local_report_id="RPT-0001",
            status="FINAL",
            title="US Abdomen",
            findings="Synthetic test findings only. Liver and kidneys appear normal.",
            impression="Synthetic test impression only. No focal abnormalities.",
            finalized_at=datetime(2026, 10, 31, 10, 20, 0, tzinfo=ist),
        ),
        reporting_practitioner=ReportingPractitioner(
            name="Dr Test",
            registration_number="TEST-REG-1234",
        ),
    )

    builder_config = FhirBuilderConfig(
        facility_identifier_system="https://facility.medtatvaa.example/id",
        patient_identifier_system="https://patient.medtatvaa.example/mrn",
        practitioner_identifier_system="https://nmc.medtatvaa.example/reg",
        abha_identifier_system="https://abha.abdm.gov.in/address",
        practitioner_identifier_type="PRN",
        id_namespace=UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
    )
    bundle_config = FhirBundleConfig(
        bundle_identifier_system="https://bundle.medtatvaa.example/id",
        report_identifier_system="https://report.medtatvaa.example/id",
        max_pdf_bytes=10 * 1024 * 1024,
    )
    bundle_timestamp = datetime(2026, 10, 31, 10, 25, 0, tzinfo=ist)

    bundle = build_diagnostic_report_bundle(
        payload=payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SYNTHETIC_PDF_BYTES,
        bundle_timestamp=bundle_timestamp,
    )

    out_path = Path("docs/samples/day17-diagnostic-report-bundle.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
