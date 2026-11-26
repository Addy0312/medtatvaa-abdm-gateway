# tests/unit/test_fhir_builders.py
import copy
from datetime import datetime, timedelta, timezone
from uuid import UUID
import xml.etree.ElementTree as ET

import pytest

from app.schemas.canonical_report import CanonicalDiagnosticReportPayload
from app.services.fhir_builders import (
    LOINC_RADIOLOGY_IMPRESSION,
    LOINC_RADIOLOGY_STUDY_NARRATIVE,
    NDHM_IDENTIFIER_TYPE_CS,
    OBSERVATION_PROFILE,
    ORGANIZATION_PROFILE,
    PATIENT_PROFILE,
    PRACTITIONER_PROFILE,
    SNOMED_ULTRASONOGRAPHY,
    V2_0203_SYSTEM,
    FhirBuilderConfig,
    build_findings_observation,
    build_impression_observation,
    build_observation_fhir_id,
    build_organization_fhir_id,
    build_organization_resource,
    build_patient_fhir_id,
    build_patient_resource,
    build_practitioner_fhir_id,
    build_practitioner_resource,
)


def _sample_payload(**overrides) -> CanonicalDiagnosticReportPayload:
    ist = timezone(timedelta(hours=5, minutes=30))
    amp = chr(38)
    data = {
        "schema_version": "1.0",
        "facility": {
            "facility_id": "FAC/01:A#1",
            "name": "Demo Imaging Centre",
        },
        "patient": {
            "local_patient_id": "PAT/001:X",
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
            "local_report_id": "RPT/0001:1",
            "status": "FINAL",
            "title": "US Abdomen",
            "findings": "Synthetic test findings only. <Liver> " + amp + " kidneys appear normal.",
            "impression": 'Synthetic test impression only. "No focal abnormalities" ' + amp + " clear.",
            "finalized_at": datetime(2026, 10, 31, 10, 20, 0, tzinfo=ist),
        },
        "reporting_practitioner": {
            "name": "Dr Test",
            "registration_number": "REG/2026:09",
        },
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and isinstance(data.get(key), dict):
            data[key].update(val)
        else:
            data[key] = val
    return CanonicalDiagnosticReportPayload.model_validate(data)


def _sample_config(**overrides) -> FhirBuilderConfig:
    ns = UUID("11111111-2222-5333-8444-555555555555")
    base = {
        "facility_identifier_system": "https://example.org/fhir/sid/facility",
        "patient_identifier_system": "https://example.org/fhir/sid/mrn",
        "practitioner_identifier_system": "https://example.org/fhir/sid/council",
        "abha_identifier_system": None,
        "practitioner_identifier_type": "PRN",
        "id_namespace": ns,
    }
    base.update(overrides)
    return FhirBuilderConfig(**base)


def _extract_xhtml_p_text(xhtml_div: str) -> str:
    root = ET.fromstring(xhtml_div)
    ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
    p_elem = root.find("xhtml:p", ns)
    assert p_elem is not None
    return "".join(p_elem.itertext())


def test_all_four_resources_and_references_resolved():
    payload = _sample_payload()
    config = _sample_config()

    patient = build_patient_resource(payload, config)
    org = build_organization_resource(payload, config)
    pract = build_practitioner_resource(payload, config)
    findings_obs = build_findings_observation(payload, config)
    impression_obs = build_impression_observation(payload, config)

    assert patient["resourceType"] == "Patient"
    assert patient["meta"]["profile"] == [PATIENT_PROFILE]
    assert patient["name"] == [{"text": "Test Patient"}]
    assert patient["gender"] == "female"
    assert patient["birthDate"] == "1980"

    assert org["resourceType"] == "Organization"
    assert org["meta"]["profile"] == [ORGANIZATION_PROFILE]
    assert org["name"] == "Demo Imaging Centre"

    assert pract["resourceType"] == "Practitioner"
    assert pract["meta"]["profile"] == [PRACTITIONER_PROFILE]
    assert pract["name"] == [{"text": "Dr Test"}]
    assert "qualification" not in pract

    for obs in (findings_obs, impression_obs):
        assert obs["resourceType"] == "Observation"
        assert obs["meta"]["profile"] == [OBSERVATION_PROFILE]
        assert obs["status"] == "final"
        assert obs["subject"] == {"reference": f"Patient/{patient['id']}"}
        assert obs["performer"] == [
            {"reference": f"Practitioner/{pract['id']}"},
            {"reference": f"Organization/{org['id']}"},
        ]
        assert obs["effectiveDateTime"] == "2026-10-31T10:00:00+05:30"
        assert obs["issued"] == "2026-10-31T10:20:00+05:30"
        assert obs["method"] == {"coding": [SNOMED_ULTRASONOGRAPHY]}
        assert obs["category"] == [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "imaging",
                        "display": "Imaging",
                    }
                ]
            }
        ]

    assert findings_obs["code"]["coding"] == [LOINC_RADIOLOGY_STUDY_NARRATIVE]
    assert findings_obs["valueString"] == payload.report.findings
    assert impression_obs["code"]["coding"] == [LOINC_RADIOLOGY_IMPRESSION]
    assert impression_obs["valueString"] == payload.report.impression


def test_delimiter_collision_prevented_and_namespace_and_study_scoping():
    ns = UUID("aaaaaaaa-bbbb-5ccc-8ddd-eeeeeeeeeeee")
    fac_sys = "https://example.org/fhir/sid/fac"
    pat_sys = "https://example.org/fhir/sid/pat"

    p_id_1 = build_patient_fhir_id(fac_sys, "A:B", pat_sys, "C", ns)
    p_id_2 = build_patient_fhir_id(fac_sys, "A", pat_sys, "B:C", ns)
    assert p_id_1 != p_id_2

    o_id_1 = build_organization_fhir_id(fac_sys, "A:B", ns)
    o_id_2 = build_organization_fhir_id(fac_sys, "A", ns)
    assert o_id_1 != o_id_2

    p_sys_a = build_patient_fhir_id(fac_sys, "FAC-1", "https://sys.example/mrn-1", "PAT-1", ns)
    p_sys_b = build_patient_fhir_id(fac_sys, "FAC-1", "https://sys.example/mrn-2", "PAT-1", ns)
    assert p_sys_a != p_sys_b

    o_sys_a = build_organization_fhir_id("https://sys.example/fac-1", "FAC-1", ns)
    o_sys_b = build_organization_fhir_id("https://sys.example/fac-2", "FAC-1", ns)
    assert o_sys_a != o_sys_b

    obs_study_1 = build_observation_fhir_id(
        fac_sys, "FAC-1", pat_sys, "PAT-1", "STUDY-1", "RPT-SHARED", "findings", ns
    )
    obs_study_2 = build_observation_fhir_id(
        fac_sys, "FAC-1", pat_sys, "PAT-1", "STUDY-2", "RPT-SHARED", "findings", ns
    )
    assert obs_study_1 != obs_study_2

    obs_findings = build_observation_fhir_id(
        fac_sys, "FAC-1", pat_sys, "PAT-1", "STUDY-1", "RPT-1", "findings", ns
    )
    obs_impression = build_observation_fhir_id(
        fac_sys, "FAC-1", pat_sys, "PAT-1", "STUDY-1", "RPT-1", "impression", ns
    )
    assert obs_findings != obs_impression

    payload = _sample_payload()
    cfg = _sample_config(id_namespace=ns)
    for rid in (
        build_patient_resource(payload, cfg)["id"],
        build_organization_resource(payload, cfg)["id"],
        build_practitioner_resource(payload, cfg)["id"],
        build_findings_observation(payload, cfg)["id"],
        build_impression_observation(payload, cfg)["id"],
    ):
        assert "/" not in rid
        assert ":" not in rid
        assert " " not in rid
        assert UUID(rid)


def test_all_genders_abha_type_and_exact_string_preservation():
    gender_to_fhir = {"M": "male", "F": "female", "O": "other"}
    for code, expected_gender in gender_to_fhir.items():
        p = _sample_payload(patient={"gender": code, "year_of_birth": 1995})
        res = build_patient_resource(p, _sample_config())
        assert res["gender"] == expected_gender
        assert res["birthDate"] == "1995"

    padded_patient_id = "  PAT-EXACT-01  "
    padded_findings = "  Findings with leading/trailing spaces and <tag>  "
    padded_impression = "  Impression with leading/trailing spaces  "
    payload = _sample_payload(
        patient={"local_patient_id": padded_patient_id, "abha_address": "  User@SBX  "},
        report={"findings": padded_findings, "impression": padded_impression},
    )

    cfg_with_abha = _sample_config(abha_identifier_system="https://example.org/fhir/sid/abha-address")
    patient = build_patient_resource(payload, cfg_with_abha)
    assert patient["identifier"][0]["value"] == padded_patient_id
    assert len(patient["identifier"]) == 2
    assert patient["identifier"][1]["system"] == "https://example.org/fhir/sid/abha-address"
    assert patient["identifier"][1]["value"] == "  User@SBX  "
    assert patient["identifier"][1]["type"] == {
        "coding": [
            {
                "system": NDHM_IDENTIFIER_TYPE_CS,
                "code": "ABHA",
                "display": "Ayushman Bharat Health Account (ABHA) ID",
            }
        ],
        "text": "ABHA address",
    }

    f_obs = build_findings_observation(payload, cfg_with_abha)
    i_obs = build_impression_observation(payload, cfg_with_abha)
    assert f_obs["valueString"] == padded_findings
    assert i_obs["valueString"] == padded_impression

    parsed_f = _extract_xhtml_p_text(f_obs["text"]["div"])
    assert parsed_f == "Findings: " + padded_findings


def test_xhtml_escaping_no_tag_injection_and_input_output_isolation():
    payload = _sample_payload(
        report={
            "findings": "Normal <script>alert(1)</script> text",
            "impression": "Clear <img src=x onerror=1/> impression",
        }
    )
    cfg = _sample_config()
    before_dump = copy.deepcopy(payload.model_dump(mode="json"))

    f_obs = build_findings_observation(payload, cfg)
    i_obs = build_impression_observation(payload, cfg)

    assert payload.model_dump(mode="json") == before_dump

    f_root = ET.fromstring(f_obs["text"]["div"])
    ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
    f_p = f_root.find("xhtml:p", ns)
    assert f_p is not None
    assert list(f_p) == []
    assert "".join(f_p.itertext()) == "Findings: " + payload.report.findings

    i_root = ET.fromstring(i_obs["text"]["div"])
    i_p = i_root.find("xhtml:p", ns)
    assert i_p is not None
    assert list(i_p) == []
    assert "".join(i_p.itertext()) == "Impression: " + payload.report.impression

    f_obs["code"]["coding"][0]["display"] = "Mutated Display"
    f_obs["performer"][0]["reference"] = "Practitioner/mutated"
    f_fresh = build_findings_observation(payload, cfg)
    assert f_fresh["code"]["coding"][0]["display"] == LOINC_RADIOLOGY_STUDY_NARRATIVE["display"]
    assert f_fresh["performer"][0]["reference"] != "Practitioner/mutated"


def test_invalid_uris_and_validation_errors():
    payload = _sample_payload()

    invalid_uris = [
        "",
        "   ",
        "relative/path/without/scheme",
        "https://",
        "http://",
        "https://:443",
        "urn:",
        "https://example.org/<bad>",
        "https://example.org/with space",
        "https://example.org/with\ttab",
        "https://example.org/with\nnewline",
        "123badscheme://example.org/id",
    ]
    for bad_uri in invalid_uris:
        with pytest.raises(ValueError):
            build_patient_resource(payload, _sample_config(patient_identifier_system=bad_uri))
        with pytest.raises(ValueError):
            build_organization_resource(payload, _sample_config(facility_identifier_system=bad_uri))
        with pytest.raises(ValueError):
            build_practitioner_resource(payload, _sample_config(practitioner_identifier_system=bad_uri))
        with pytest.raises(ValueError):
            build_patient_resource(payload, _sample_config(abha_identifier_system=bad_uri))

    cfg = _sample_config()
    with pytest.raises(ValueError):
        build_findings_observation(_sample_payload(study={"modality": "CT"}), cfg)
    with pytest.raises(ValueError):
        build_impression_observation(_sample_payload(study={"modality": "MR"}), cfg)
    with pytest.raises(ValueError):
        build_findings_observation(_sample_payload(report={"status": "UNKNOWN"}), cfg)

    naive_dt = datetime(2026, 10, 31, 10, 0, 0)
    with pytest.raises(ValueError):
        build_findings_observation(_sample_payload(study={"study_date_time": naive_dt}), cfg)
    with pytest.raises(ValueError):
        build_impression_observation(_sample_payload(report={"finalized_at": naive_dt}), cfg)

    tz = timezone(timedelta(hours=5, minutes=30))
    with pytest.raises(ValueError):
        build_findings_observation(
            _sample_payload(
                study={"study_date_time": datetime(2026, 10, 31, 11, 0, 0, tzinfo=tz)},
                report={"finalized_at": datetime(2026, 10, 31, 10, 59, 0, tzinfo=tz)},
            ),
            cfg,
        )
