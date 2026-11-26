# tests/unit/test_fhir_bundle_assembler.py
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import json
from typing import Any
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
from app.services import fhir_builders
from app.services.fhir_builders import FhirBuilderConfig
from app.services.fhir_bundle_assembler import (
    DIAGNOSTIC_REPORT_IMAGING_PROFILE,
    DIAGNOSTIC_REPORT_LOINC_CODE,
    DIAGNOSTIC_REPORT_LOINC_DISPLAY,
    DIAGNOSTIC_REPORT_RECORD_PROFILE,
    DOCUMENT_BUNDLE_PROFILE,
    IMAGING_REPORT_SNOMED_CODE,
    IMAGING_REPORT_SNOMED_DISPLAY,
    LOINC_SYSTEM,
    RADIOLOGY_SPECIALTY_SNOMED_CODE,
    RADIOLOGY_SPECIALTY_SNOMED_DISPLAY,
    SNOMED_SYSTEM,
    FhirBundleConfig,
    build_bundle_fhir_id,
    build_composition_fhir_id,
    build_composition_resource,
    build_diagnostic_report_bundle,
    build_diagnostic_report_fhir_id,
    build_diagnostic_report_resource,
)

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer << /Size 4 /Root 1 0 R >>\nstartxref\n178\n%%EOF\n"
)


@pytest.fixture
def builder_config() -> FhirBuilderConfig:
    return FhirBuilderConfig(
        facility_identifier_system="https://facility.medtatvaa.example/id",
        patient_identifier_system="https://patient.medtatvaa.example/mrn",
        practitioner_identifier_system="https://nmc.medtatvaa.example/reg",
        abha_identifier_system="https://abha.abdm.gov.in/address",
        practitioner_identifier_type="PRN",
        id_namespace=UUID("12345678-1234-5678-1234-567812345678"),
    )


@pytest.fixture
def bundle_config() -> FhirBundleConfig:
    return FhirBundleConfig(
        bundle_identifier_system="https://bundle.medtatvaa.example/id",
        report_identifier_system="https://report.medtatvaa.example/id",
        max_pdf_bytes=1024 * 1024,
    )


@pytest.fixture
def sample_payload() -> CanonicalDiagnosticReportPayload:
    tz = timezone(timedelta(hours=5, minutes=30))
    return CanonicalDiagnosticReportPayload(
        schema_version="1.0",
        facility=FacilityInfo(
            facility_id="FAC-001",
            name="Medtatvaa Diagnostic Centre",
        ),
        patient=PatientDemographics(
            local_patient_id="PAT-001",
            abha_address="patient001@sbx",
            name="Asha Rao",
            gender="F",
            year_of_birth=1988,
        ),
        study=StudyInfo(
            local_study_id="STD-001",
            study_instance_uid="1.2.840.113619.2.55.3.999001",
            modality="US",
            study_date_time=datetime(2026, 11, 20, 9, 30, 0, tzinfo=tz),
            description="Ultrasound Pelvis",
        ),
        report=ReportInfo(
            local_report_id="RPT-001",
            status="FINAL",
            title="US Pelvis Report",
            findings="Uterus and ovaries normal in size & echotexture.",
            impression="Normal pelvic ultrasound <no mass> & 'clear' \"margins\" — 日本語.",
            finalized_at=datetime(2026, 11, 20, 10, 15, 0, tzinfo=tz),
        ),
        reporting_practitioner=ReportingPractitioner(
            name="Dr. Vikram Nair",
            registration_number="REG-778899",
        ),
    )


def _collect_reference_strings(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reference" and isinstance(v, str):
                found.append(v)
            else:
                found.extend(_collect_reference_strings(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_reference_strings(item))
    return found


def test_bundle_structure_profiles_first_entry_and_full_urls(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
) -> None:
    ts = datetime(2026, 11, 20, 10, 20, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    bundle = build_diagnostic_report_bundle(
        payload=sample_payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
        bundle_timestamp=ts,
    )

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "document"
    assert bundle["timestamp"] == ts.isoformat()
    assert bundle["meta"]["versionId"] == "1"
    assert bundle["meta"]["lastUpdated"] == ts.isoformat()
    assert bundle["meta"]["profile"] == [DOCUMENT_BUNDLE_PROFILE]
    assert bundle["identifier"] == {
        "system": bundle_config.bundle_identifier_system,
        "value": bundle["id"],
    }

    entries = bundle["entry"]
    assert len(entries) == 7
    assert entries[0]["resource"]["resourceType"] == "Composition"
    assert [e["resource"]["resourceType"] for e in entries] == [
        "Composition",
        "Patient",
        "Practitioner",
        "Organization",
        "DiagnosticReport",
        "Observation",
        "Observation",
    ]

    full_urls = [e["fullUrl"] for e in entries]
    assert len(set(full_urls)) == len(full_urls)
    for entry in entries:
        res = entry["resource"]
        assert entry["fullUrl"] == f"urn:uuid:{res['id']}"


def test_zero_dangling_references_across_entire_bundle(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
) -> None:
    ts = datetime(2026, 11, 20, 10, 20, 0, tzinfo=timezone.utc)
    bundle = build_diagnostic_report_bundle(
        payload=sample_payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
        bundle_timestamp=ts,
    )

    valid_full_urls = {entry["fullUrl"] for entry in bundle["entry"]}
    all_refs = _collect_reference_strings(bundle)
    assert len(all_refs) > 0
    for ref in all_refs:
        assert ref.startswith("urn:uuid:")
        assert ref in valid_full_urls


def test_fixed_systems_codes_composition_and_diagnostic_report_fields(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
) -> None:
    ts = datetime(2026, 11, 20, 10, 20, 0, tzinfo=timezone.utc)
    bundle = build_diagnostic_report_bundle(
        payload=sample_payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
        bundle_timestamp=ts,
    )

    comp = bundle["entry"][0]["resource"]
    assert comp["meta"]["profile"] == [DIAGNOSTIC_REPORT_RECORD_PROFILE]
    assert comp["status"] == "final"
    assert comp["title"] == sample_payload.report.title
    assert comp["date"] == sample_payload.report.finalized_at.isoformat()
    assert comp["type"] == {
        "coding": [
            {
                "system": SNOMED_SYSTEM,
                "code": IMAGING_REPORT_SNOMED_CODE,
                "display": IMAGING_REPORT_SNOMED_DISPLAY,
            }
        ],
        "text": sample_payload.report.title,
    }
    assert len(comp["section"]) == 1
    sec = comp["section"][0]
    assert sec["title"] == sample_payload.report.title
    assert sec["code"]["coding"] == [
        {
            "system": SNOMED_SYSTEM,
            "code": IMAGING_REPORT_SNOMED_CODE,
            "display": IMAGING_REPORT_SNOMED_DISPLAY,
        }
    ]
    dr_entries = [e for e in sec["entry"] if e.get("type") == "DiagnosticReport"]
    assert len(dr_entries) == 1

    dr = bundle["entry"][4]["resource"]
    assert dr["meta"]["profile"] == [DIAGNOSTIC_REPORT_IMAGING_PROFILE]
    assert dr["identifier"] == [
        {
            "system": bundle_config.report_identifier_system,
            "value": sample_payload.report.local_report_id,
        }
    ]
    assert dr["code"] == {
        "coding": [
            {
                "system": LOINC_SYSTEM,
                "code": DIAGNOSTIC_REPORT_LOINC_CODE,
                "display": DIAGNOSTIC_REPORT_LOINC_DISPLAY,
            }
        ],
        "text": sample_payload.report.title,
    }
    assert dr["category"] == [
        {
            "coding": [
                {
                    "system": SNOMED_SYSTEM,
                    "code": RADIOLOGY_SPECIALTY_SNOMED_CODE,
                    "display": RADIOLOGY_SPECIALTY_SNOMED_DISPLAY,
                }
            ]
        }
    ]
    assert dr["effectiveDateTime"] == sample_payload.study.study_date_time.isoformat()
    assert dr["issued"] == sample_payload.report.finalized_at.isoformat()

    # Exact impression preservation including <, &, quotes, unicode
    assert dr["conclusion"] == sample_payload.report.impression

    # PDF round-trip verification
    form = dr["presentedForm"][0]
    assert form["contentType"] == "application/pdf"
    assert form["size"] == len(SAMPLE_PDF_BYTES)
    assert form["title"] == sample_payload.report.title
    assert "\n" not in form["data"] and "\r" not in form["data"]
    assert base64.b64decode(form["data"], validate=True) == SAMPLE_PDF_BYTES

    # Observation order, performer, resultsInterpreter, author, custodian
    findings_full_url = bundle["entry"][5]["fullUrl"]
    impression_full_url = bundle["entry"][6]["fullUrl"]
    assert [r["reference"] for r in dr["result"]] == [findings_full_url, impression_full_url]

    org_full_url = bundle["entry"][3]["fullUrl"]
    pract_full_url = bundle["entry"][2]["fullUrl"]
    assert [p["reference"] for p in dr["performer"]] == [org_full_url]
    assert [ri["reference"] for ri in dr["resultsInterpreter"]] == [pract_full_url]
    assert [a["reference"] for a in comp["author"]] == [pract_full_url]
    assert comp["custodian"]["reference"] == org_full_url
    assert dr_entries[0]["reference"] == bundle["entry"][4]["fullUrl"]


@pytest.mark.parametrize(
    ("raw_status", "expected_comp_status", "expected_dr_status"),
    [
        ("FINAL", "final", "final"),
        ("AMENDED", "amended", "amended"),
        ("CORRECTED", "amended", "corrected"),
        ("PRELIMINARY", "preliminary", "preliminary"),
    ],
)
def test_status_mappings(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
    raw_status: str,
    expected_comp_status: str,
    expected_dr_status: str,
) -> None:
    updated_report = sample_payload.report.model_copy(update={"status": raw_status})
    payload = sample_payload.model_copy(update={"report": updated_report})
    ts = datetime(2026, 11, 20, 10, 20, 0, tzinfo=timezone.utc)

    bundle = build_diagnostic_report_bundle(
        payload=payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
        bundle_timestamp=ts,
    )
    assert bundle["entry"][0]["resource"]["status"] == expected_comp_status
    assert bundle["entry"][4]["resource"]["status"] == expected_dr_status


def test_determinism_immutability_and_json_serializable(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ts = datetime(2026, 11, 20, 10, 20, 0, tzinfo=timezone.utc)
    payload_snapshot = copy.deepcopy(sample_payload.model_dump())

    # Wrap Day 16 resource builders to detect any mutation of returned dicts
    built_snapshots: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for fn_name in (
        "build_patient_resource",
        "build_practitioner_resource",
        "build_organization_resource",
        "build_findings_observation",
        "build_impression_observation",
    ):
        orig_fn = getattr(fhir_builders, fn_name)

        def _wrapped(p: Any, c: Any, _orig: Any = orig_fn) -> dict[str, Any]:
            res = _orig(p, c)
            built_snapshots.append((res, copy.deepcopy(res)))
            return res

        monkeypatch.setattr(fhir_builders, fn_name, _wrapped)

    b1 = build_diagnostic_report_bundle(
        payload=sample_payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
        bundle_timestamp=ts,
    )
    b2 = build_diagnostic_report_bundle(
        payload=sample_payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
        bundle_timestamp=ts,
    )

    assert b1 == b2
    json_1 = json.dumps(b1, sort_keys=True)
    json_2 = json.dumps(b2, sort_keys=True)
    assert json_1 == json_2

    assert sample_payload.model_dump() == payload_snapshot
    for actual_res, expected_res in built_snapshots:
        assert actual_res == expected_res

    # Mutating b1 must not affect b2
    b1["entry"][0]["resource"]["title"] = "MUTATED"
    b1["timestamp"] = "1999-01-01T00:00:00+00:00"
    assert b2["entry"][0]["resource"]["title"] == sample_payload.report.title
    assert b2["timestamp"] == ts.isoformat()


def test_id_collision_resistance_and_delimiter_safety(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
) -> None:
    base_comp = build_composition_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        sample_payload.study.local_study_id,
        sample_payload.report.local_report_id,
        builder_config.id_namespace,
    )
    base_dr = build_diagnostic_report_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        sample_payload.study.local_study_id,
        sample_payload.report.local_report_id,
        builder_config.id_namespace,
    )
    base_bnd = build_bundle_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        sample_payload.study.local_study_id,
        sample_payload.report.local_report_id,
        builder_config.id_namespace,
    )

    # Changing report, study, patient, facility, or namespace changes IDs
    assert base_comp != build_composition_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        sample_payload.study.local_study_id,
        "RPT-OTHER",
        builder_config.id_namespace,
    )
    assert base_dr != build_diagnostic_report_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        "STD-OTHER",
        sample_payload.report.local_report_id,
        builder_config.id_namespace,
    )
    assert base_bnd != build_bundle_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        "PAT-OTHER",
        sample_payload.study.local_study_id,
        sample_payload.report.local_report_id,
        builder_config.id_namespace,
    )
    assert base_bnd != build_bundle_fhir_id(
        builder_config.facility_identifier_system,
        "FAC-OTHER",
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        sample_payload.study.local_study_id,
        sample_payload.report.local_report_id,
        builder_config.id_namespace,
    )
    assert base_bnd != build_bundle_fhir_id(
        builder_config.facility_identifier_system,
        sample_payload.facility.facility_id,
        builder_config.patient_identifier_system,
        sample_payload.patient.local_patient_id,
        sample_payload.study.local_study_id,
        sample_payload.report.local_report_id,
        UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )

    # Delimiter-like characters ('/', ':', '#') do not collide across part boundaries
    id_a = build_bundle_fhir_id(
        builder_config.facility_identifier_system,
        "FAC/1:A",
        builder_config.patient_identifier_system,
        "PAT#1",
        "STD/1",
        "RPT:1",
        builder_config.id_namespace,
    )
    id_b = build_bundle_fhir_id(
        builder_config.facility_identifier_system,
        "FAC",
        builder_config.patient_identifier_system,
        "1:A/PAT#1",
        "STD",
        "1/RPT:1",
        builder_config.id_namespace,
    )
    assert id_a != id_b


def test_standalone_composition_and_diagnostic_report_builders(
    sample_payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
) -> None:
    dr = build_diagnostic_report_resource(
        payload=sample_payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=SAMPLE_PDF_BYTES,
    )
    assert dr["resourceType"] == "DiagnosticReport"
    assert dr["subject"]["reference"].startswith("Patient/")
    assert dr["performer"][0]["reference"].startswith("Organization/")
    assert dr["resultsInterpreter"][0]["reference"].startswith("Practitioner/")
    assert dr["result"][0]["reference"].startswith("Observation/")
    assert dr["result"][1]["reference"].startswith("Observation/")

    comp = build_composition_resource(
        payload=sample_payload,
        builder_config=builder_config,
        diagnostic_report_id=dr["id"],
    )
    assert comp["resourceType"] == "Composition"
    assert comp["subject"]["reference"].startswith("Patient/")
    assert comp["author"][0]["reference"].startswith("Practitioner/")
    assert comp["custodian"]["reference"].startswith("Organization/")
    assert comp["section"][0]["entry"][0]["reference"] == f"DiagnosticReport/{dr['id']}"
