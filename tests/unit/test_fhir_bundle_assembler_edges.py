# tests/unit/test_fhir_bundle_assembler_edges.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.schemas.canonical_report import (
    CanonicalDiagnosticReportPayload,
    FacilityInfo,
    PatientDemographics,
    ReportingPractitioner,
    ReportInfo,
    StudyInfo,
)
from app.services.fhir_builders import FhirBuilderConfig
from app.services.fhir_bundle_assembler import (
    FhirAssemblyError,
    FhirBundleConfig,
    build_diagnostic_report_bundle,
)

VALID_PDF = b"%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"


@pytest.fixture
def valid_builder_config() -> FhirBuilderConfig:
    return FhirBuilderConfig(
        facility_identifier_system="https://facility.medtatvaa.example/id",
        patient_identifier_system="https://patient.medtatvaa.example/mrn",
        practitioner_identifier_system="https://nmc.medtatvaa.example/reg",
        id_namespace=UUID("12345678-1234-5678-1234-567812345678"),
    )


@pytest.fixture
def valid_bundle_config() -> FhirBundleConfig:
    return FhirBundleConfig(
        bundle_identifier_system="https://bundle.medtatvaa.example/id",
        report_identifier_system="https://report.medtatvaa.example/id",
        max_pdf_bytes=1024 * 1024,
    )


@pytest.fixture
def valid_payload() -> CanonicalDiagnosticReportPayload:
    tz = timezone(timedelta(hours=5, minutes=30))
    return CanonicalDiagnosticReportPayload(
        facility=FacilityInfo(facility_id="FAC-1", name="Clinic"),
        patient=PatientDemographics(
            local_patient_id="PAT-1",
            abha_address="user@sbx",
            name="Test Name",
            gender="M",
            year_of_birth=1990,
        ),
        study=StudyInfo(
            local_study_id="STD-1",
            study_instance_uid="1.2.840.113619.2.55.3.1",
            modality="US",
            study_date_time=datetime(2026, 11, 1, 8, 0, 0, tzinfo=tz),
            description="Abdomen US",
        ),
        report=ReportInfo(
            local_report_id="RPT-1",
            status="FINAL",
            title="Abdomen Report",
            findings="Normal liver.",
            impression="Normal study.",
            finalized_at=datetime(2026, 11, 1, 9, 0, 0, tzinfo=tz),
        ),
        reporting_practitioner=ReportingPractitioner(
            name="Dr. Demo",
            registration_number="REG-1",
        ),
    )


def test_naive_and_non_datetime_timestamp_rejected(
    valid_payload: CanonicalDiagnosticReportPayload,
    valid_builder_config: FhirBuilderConfig,
    valid_bundle_config: FhirBundleConfig,
) -> None:
    naive_ts = datetime(2026, 11, 1, 9, 30, 0)
    with pytest.raises(FhirAssemblyError):
        build_diagnostic_report_bundle(
            valid_payload, valid_builder_config, valid_bundle_config, VALID_PDF, naive_ts
        )

    with pytest.raises(FhirAssemblyError):
        build_diagnostic_report_bundle(
            valid_payload,
            valid_builder_config,
            valid_bundle_config,
            VALID_PDF,
            "2026-11-01T09:30:00+05:30",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "bad_pdf",
    [
        "%PDF-1.4 string instead of bytes",
        b"",
        b"NOT-A-PDF-FILE",
        b"%PDF-1.4\n" + (b"A" * 2048),
    ],
)
def test_invalid_pdf_inputs_rejected(
    valid_payload: CanonicalDiagnosticReportPayload,
    valid_builder_config: FhirBuilderConfig,
    bad_pdf: Any,
) -> None:
    tight_config = FhirBundleConfig(
        bundle_identifier_system="https://bundle.medtatvaa.example/id",
        report_identifier_system="https://report.medtatvaa.example/id",
        max_pdf_bytes=200,
    )
    ts = datetime(2026, 11, 1, 9, 30, 0, tzinfo=timezone.utc)
    with pytest.raises(FhirAssemblyError):
        build_diagnostic_report_bundle(
            valid_payload, valid_builder_config, tight_config, bad_pdf, ts
        )


@pytest.mark.parametrize(
    ("bad_bundle_sys", "bad_report_sys", "bad_max_bytes"),
    [
        ("not-a-uri", "https://report.medtatvaa.example/id", 1000),
        ("https://bundle.medtatvaa.example/id", "relative/path/only", 1000),
        ("https://bundle.medtatvaa.example/id", "", 1000),
        ("https://bundle.medtatvaa.example/id", "https://report.medtatvaa.example/id", 0),
        ("https://bundle.medtatvaa.example/id", "https://report.medtatvaa.example/id", -10),
        ("https://bundle.medtatvaa.example/id", "https://report.medtatvaa.example/id", True),
    ],
)
def test_invalid_bundle_config_rejected(
    valid_payload: CanonicalDiagnosticReportPayload,
    valid_builder_config: FhirBuilderConfig,
    bad_bundle_sys: str,
    bad_report_sys: str,
    bad_max_bytes: Any,
) -> None:
    ts = datetime(2026, 11, 1, 9, 30, 0, tzinfo=timezone.utc)
    bad_cfg = FhirBundleConfig(
        bundle_identifier_system=bad_bundle_sys,
        report_identifier_system=bad_report_sys,
        max_pdf_bytes=bad_max_bytes,
    )
    with pytest.raises(FhirAssemblyError):
        build_diagnostic_report_bundle(
            valid_payload, valid_builder_config, bad_cfg, VALID_PDF, ts
        )


def test_unknown_report_status_and_blank_title_rejected(
    valid_payload: CanonicalDiagnosticReportPayload,
    valid_builder_config: FhirBuilderConfig,
    valid_bundle_config: FhirBundleConfig,
) -> None:
    ts = datetime(2026, 11, 1, 9, 30, 0, tzinfo=timezone.utc)

    bad_status_report = valid_payload.report.model_copy(update={"status": "ENTERED-IN-ERROR-FAKE"})
    with pytest.raises(FhirAssemblyError):
        build_diagnostic_report_bundle(
            valid_payload.model_copy(update={"report": bad_status_report}),
            valid_builder_config,
            valid_bundle_config,
            VALID_PDF,
            ts,
        )

    blank_title_report = valid_payload.report.model_copy(update={"title": "   "})
    with pytest.raises(FhirAssemblyError):
        build_diagnostic_report_bundle(
            valid_payload.model_copy(update={"report": blank_title_report}),
            valid_builder_config,
            valid_bundle_config,
            VALID_PDF,
            ts,
        )
