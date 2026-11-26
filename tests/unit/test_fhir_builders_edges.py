# tests/unit/test_fhir_builders_edges.py
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID
import xml.etree.ElementTree as ET

import pytest

try:
    from tests.unit.test_fhir_builders import _sample_config, _sample_payload
except ImportError:
    import importlib.util

    _primary_path = Path(__file__).resolve().with_name("test_fhir_builders.py")
    _spec = importlib.util.spec_from_file_location("test_fhir_builders", _primary_path)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _sample_config = _mod._sample_config
    _sample_payload = _mod._sample_payload

from app.services.fhir_builders import (
    V2_0203_SYSTEM,
    build_findings_observation,
    build_impression_observation,
    build_organization_resource,
    build_patient_resource,
    build_practitioner_resource,
)


def test_all_four_statuses_and_utc_timezone_preservation():
    utc_dt_study = datetime(2026, 10, 31, 4, 30, 0, tzinfo=timezone.utc)
    utc_dt_final = datetime(2026, 10, 31, 4, 50, 0, tzinfo=timezone.utc)
    cfg = _sample_config()

    expected_map = {
        "FINAL": "final",
        "AMENDED": "amended",
        "CORRECTED": "corrected",
        "PRELIMINARY": "preliminary",
    }
    for raw_status, fhir_status in expected_map.items():
        payload = _sample_payload(
            study={"study_date_time": utc_dt_study},
            report={"status": raw_status, "finalized_at": utc_dt_final},
        )
        obs = build_findings_observation(payload, cfg)
        assert obs["status"] == fhir_status
        assert obs["effectiveDateTime"] == "2026-10-31T04:30:00+00:00"
        assert obs["issued"] == "2026-10-31T04:50:00+00:00"


def test_blank_and_illegal_xml10_characters_rejected():
    cfg = _sample_config()
    for field_group, key, val in [
        ("facility", "facility_id", "   "),
        ("facility", "name", "\t\n "),
        ("patient", "local_patient_id", "  "),
        ("patient", "name", "   "),
        ("study", "local_study_id", " "),
        ("study", "study_instance_uid", "  "),
        ("study", "description", "   "),
        ("report", "local_report_id", " "),
        ("report", "title", "  "),
        ("report", "findings", "   "),
        ("report", "impression", "  "),
        ("reporting_practitioner", "name", "  "),
        ("reporting_practitioner", "registration_number", "   "),
    ]:
        with pytest.raises(ValueError):
            build_findings_observation(_sample_payload(**{field_group: {key: val}}), cfg)

    # Illegal XML 1.0 characters (NUL U+0000, lone surrogate U+D800, U+FFFE)
    for bad_str in ["abc\x00def", "abc\ud800def", "abc\ufffeedef"]:
        with pytest.raises(ValueError):
            build_findings_observation(_sample_payload(report={"findings": bad_str}), cfg)
        with pytest.raises(ValueError):
            build_patient_resource(_sample_payload(patient={"local_patient_id": bad_str}), cfg)


def test_md_practitioner_configuration_and_exact_json_determinism():
    cfg = _sample_config(
        facility_identifier_system="urn:oid:2.16.840.1.113883.4.1",
        patient_identifier_system="https://hospital.example.org/mrn",
        practitioner_identifier_system="https://council.example.org/reg",
        practitioner_identifier_type="MD",
        id_namespace=UUID("22222222-3333-5444-8555-666666666666"),
    )
    payload = _sample_payload()

    pract = build_practitioner_resource(payload, cfg)
    assert pract["identifier"][0]["type"]["coding"] == [
        {
            "system": V2_0203_SYSTEM,
            "code": "MD",
            "display": "Medical License number",
        }
    ]

    org = build_organization_resource(payload, cfg)
    assert org["identifier"][0]["system"] == "urn:oid:2.16.840.1.113883.4.1"

    bundle_like_snapshot_1 = json.dumps(
        {
            "patient": build_patient_resource(payload, cfg),
            "organization": build_organization_resource(payload, cfg),
            "practitioner": build_practitioner_resource(payload, cfg),
            "findings": build_findings_observation(payload, cfg),
            "impression": build_impression_observation(payload, cfg),
        },
        sort_keys=True,
    )
    bundle_like_snapshot_2 = json.dumps(
        {
            "patient": build_patient_resource(payload, cfg),
            "organization": build_organization_resource(payload, cfg),
            "practitioner": build_practitioner_resource(payload, cfg),
            "findings": build_findings_observation(payload, cfg),
            "impression": build_impression_observation(payload, cfg),
        },
        sort_keys=True,
    )
    assert bundle_like_snapshot_1 == bundle_like_snapshot_2


def test_valid_and_invalid_uri_edge_cases():
    payload = _sample_payload()
    valid_cfg = _sample_config(
        facility_identifier_system="https://hfr.example.org/facilities",
        patient_identifier_system="urn:oid:1.2.36.1.2001.1003.0",
        practitioner_identifier_system="https://nmc.example.org/practitioners",
        abha_identifier_system="https://abha.example.org/address",
    )
    pat = build_patient_resource(payload, valid_cfg)
    org = build_organization_resource(payload, valid_cfg)
    prac = build_practitioner_resource(payload, valid_cfg)
    assert pat["id"] and org["id"] and prac["id"]

    invalid_uri_cases = [
        "https://:443",
        "http://:80",
        "urn:",
        "https://example.org/<bad>",
        "https://example.org/bad>uri",
        'https://example.org/bad"uri',
        "https://example.org/bad{uri}",
        "https://example.org/bad|uri",
        "https://example.org/bad^uri",
        "https://example.org/bad`uri",
        "https://example.org/bad\\uri",
    ]
    for bad in invalid_uri_cases:
        with pytest.raises(ValueError):
            build_organization_resource(payload, _sample_config(facility_identifier_system=bad))
        with pytest.raises(ValueError):
            build_patient_resource(payload, _sample_config(patient_identifier_system=bad))
        with pytest.raises(ValueError):
            build_practitioner_resource(payload, _sample_config(practitioner_identifier_system=bad))
        with pytest.raises(ValueError):
            build_patient_resource(payload, _sample_config(abha_identifier_system=bad))

    # Ensure narrative remains well-formed XHTML across valid inputs
    obs = build_findings_observation(payload, valid_cfg)
    ET.fromstring(obs["text"]["div"])
