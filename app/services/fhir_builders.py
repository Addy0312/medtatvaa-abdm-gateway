# app/services/fhir_builders.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse
from uuid import UUID, uuid5

from app.schemas.canonical_report import CanonicalDiagnosticReportPayload

NRCE_IG_VERSION = "6.5.0"
DEFAULT_FHIR_ID_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

PATIENT_PROFILE = f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/Patient|{NRCE_IG_VERSION}"
ORGANIZATION_PROFILE = f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/Organization|{NRCE_IG_VERSION}"
PRACTITIONER_PROFILE = f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/Practitioner|{NRCE_IG_VERSION}"
OBSERVATION_PROFILE = f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/Observation|{NRCE_IG_VERSION}"

V2_0203_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"
NDHM_IDENTIFIER_TYPE_CS = "https://nrces.in/ndhm/fhir/r4/CodeSystem/ndhm-identifier-type-code"
OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
ORGANIZATION_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/organization-type"
LOINC_SYSTEM = "http://loinc.org"
SNOMED_SYSTEM = "http://snomed.info/sct"

LOINC_RADIOLOGY_STUDY_NARRATIVE = {
    "system": LOINC_SYSTEM,
    "code": "18782-3",
    "display": "Radiology Study observation (narrative)",
}
LOINC_RADIOLOGY_IMPRESSION = {
    "system": LOINC_SYSTEM,
    "code": "19005-8",
    "display": "Radiology Imaging study [Impression] (narrative)",
}
SNOMED_ULTRASONOGRAPHY = {
    "system": SNOMED_SYSTEM,
    "code": "16310003",
    "display": "Ultrasonography",
}

ObservationKind = Literal["findings", "impression"]

_GENDER_MAP: dict[str, str] = {
    "M": "male",
    "F": "female",
    "O": "other",
}

_OBSERVATION_STATUS_MAP: dict[str, str] = {
    "FINAL": "final",
    "AMENDED": "amended",
    "CORRECTED": "corrected",
    "PRELIMINARY": "preliminary",
}

_PRACTITIONER_ID_TYPE_MAP: dict[str, dict[str, str]] = {
    "PRN": {
        "system": V2_0203_SYSTEM,
        "code": "PRN",
        "display": "Provider number",
    },
    "MD": {
        "system": V2_0203_SYSTEM,
        "code": "MD",
        "display": "Medical License number",
    },
}

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_FORBIDDEN_URI_RAW_CHARS = set('<>"{}|^`\\')


@dataclass(frozen=True)
class FhirBuilderConfig:
    """
    Explicit caller-supplied namespace and coding configuration for Day 16 FHIR base builders.
    No namespaces or clinical facts are guessed or fabricated.
    """

    facility_identifier_system: str
    patient_identifier_system: str
    practitioner_identifier_system: str
    abha_identifier_system: Optional[str] = None
    practitioner_identifier_type: Literal["PRN", "MD"] = "PRN"
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE


def _encode_identity_parts(*parts: str) -> str:
    return json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)


def _is_xml10_legal_char(ch: str) -> bool:
    code = ord(ch)
    if code in (0x09, 0x0A, 0x0D):
        return True
    if 0x0020 <= code <= 0xD7FF:
        return True
    if 0xE000 <= code <= 0xFFFD:
        return True
    if 0x10000 <= code <= 0x10FFFF:
        return True
    return False


def _validate_xml10_text(value: str, field_name: str) -> None:
    for ch in value:
        if not _is_xml10_legal_char(ch):
            raise ValueError(f"{field_name} contains illegal XML 1.0 character (code point U+{ord(ch):04X}).")


def _require_non_blank_exact(value: Optional[str], field_name: str) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty non-whitespace string.")
    _validate_xml10_text(value, field_name)
    return value


def _require_valid_uri(uri_value: Optional[str], field_name: str) -> str:
    val = _require_non_blank_exact(uri_value, field_name)
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch in _FORBIDDEN_URI_RAW_CHARS for ch in val):
        raise ValueError(f"{field_name} must not contain whitespace, control characters, or forbidden URI characters.")
    parsed = urlparse(val)
    if not parsed.scheme or not _SCHEME_RE.match(parsed.scheme):
        raise ValueError(f"{field_name} must be a valid URI with a scheme.")
    scheme_lower = parsed.scheme.lower()
    if scheme_lower in {"http", "https"}:
        if not parsed.hostname:
            raise ValueError(f"{field_name} with http/https scheme must include a valid host.")
    else:
        after_scheme = val.split(":", 1)[1]
        if not after_scheme:
            raise ValueError(f"{field_name} must include a non-empty scheme-specific part.")
    return val


def _require_tz_aware_datetime(dt: datetime, field_name: str) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must include a valid timezone offset.")
    return dt


def _validate_config(config: FhirBuilderConfig) -> None:
    if not isinstance(config, FhirBuilderConfig):
        raise ValueError("config must be a FhirBuilderConfig instance.")
    _require_valid_uri(config.facility_identifier_system, "config.facility_identifier_system")
    _require_valid_uri(config.patient_identifier_system, "config.patient_identifier_system")
    _require_valid_uri(config.practitioner_identifier_system, "config.practitioner_identifier_system")
    if config.abha_identifier_system is not None:
        _require_valid_uri(config.abha_identifier_system, "config.abha_identifier_system")
    if config.practitioner_identifier_type not in _PRACTITIONER_ID_TYPE_MAP:
        raise ValueError(
            f"Unsupported practitioner_identifier_type: {config.practitioner_identifier_type!r}."
        )
    if not isinstance(config.id_namespace, UUID):
        raise ValueError("config.id_namespace must be a UUID.")


def _validate_payload(payload: CanonicalDiagnosticReportPayload) -> None:
    if not isinstance(payload, CanonicalDiagnosticReportPayload):
        raise ValueError("payload must be a CanonicalDiagnosticReportPayload instance.")

    _require_non_blank_exact(payload.facility.facility_id, "facility.facility_id")
    _require_non_blank_exact(payload.facility.name, "facility.name")

    _require_non_blank_exact(payload.patient.local_patient_id, "patient.local_patient_id")
    if payload.patient.abha_address is not None:
        _validate_xml10_text(payload.patient.abha_address, "patient.abha_address")
    _require_non_blank_exact(payload.patient.name, "patient.name")
    if payload.patient.gender not in _GENDER_MAP:
        raise ValueError(f"Unsupported patient.gender: {payload.patient.gender!r}.")
    if payload.patient.year_of_birth < 1900 or payload.patient.year_of_birth > 9999:
        raise ValueError(f"Invalid patient.year_of_birth: {payload.patient.year_of_birth!r}.")

    modality = _require_non_blank_exact(payload.study.modality, "study.modality").strip().upper()
    if modality != "US":
        raise ValueError(f"Unsupported study.modality {payload.study.modality!r}; only 'US' is supported.")
    _require_non_blank_exact(payload.study.local_study_id, "study.local_study_id")
    _require_non_blank_exact(payload.study.study_instance_uid, "study.study_instance_uid")
    _require_non_blank_exact(payload.study.description, "study.description")

    _require_non_blank_exact(payload.report.local_report_id, "report.local_report_id")
    normalized_status = _require_non_blank_exact(payload.report.status, "report.status").strip().upper()
    if normalized_status not in _OBSERVATION_STATUS_MAP:
        raise ValueError(f"Unsupported report.status: {payload.report.status!r}.")
    _require_non_blank_exact(payload.report.title, "report.title")
    _require_non_blank_exact(payload.report.findings, "report.findings")
    _require_non_blank_exact(payload.report.impression, "report.impression")

    _require_non_blank_exact(payload.reporting_practitioner.name, "reporting_practitioner.name")
    _require_non_blank_exact(
        payload.reporting_practitioner.registration_number,
        "reporting_practitioner.registration_number",
    )

    study_dt = _require_tz_aware_datetime(payload.study.study_date_time, "study.study_date_time")
    finalized_dt = _require_tz_aware_datetime(payload.report.finalized_at, "report.finalized_at")
    if finalized_dt < study_dt:
        raise ValueError("report.finalized_at cannot be earlier than study.study_date_time.")


def _xhtml_narrative(text_content: str) -> dict[str, str]:
    _validate_xml10_text(text_content, "narrative")
    escaped = escape(text_content, quote=True)
    return {
        "status": "generated",
        "div": '<div xmlns="http://www.w3.org/1999/xhtml"><p>' + escaped + "</p></div>",
    }


def build_patient_fhir_id(
    facility_identifier_system: str,
    facility_id: str,
    patient_identifier_system: str,
    local_patient_id: str,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    fac_sys = _require_valid_uri(facility_identifier_system, "facility_identifier_system")
    fac = _require_non_blank_exact(facility_id, "facility_id")
    pat_sys = _require_valid_uri(patient_identifier_system, "patient_identifier_system")
    pat = _require_non_blank_exact(local_patient_id, "local_patient_id")
    encoded = _encode_identity_parts("Patient", fac_sys, fac, pat_sys, pat)
    return str(uuid5(id_namespace, encoded))


def build_organization_fhir_id(
    facility_identifier_system: str,
    facility_id: str,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    fac_sys = _require_valid_uri(facility_identifier_system, "facility_identifier_system")
    fac = _require_non_blank_exact(facility_id, "facility_id")
    encoded = _encode_identity_parts("Organization", fac_sys, fac)
    return str(uuid5(id_namespace, encoded))


def build_practitioner_fhir_id(
    practitioner_identifier_system: str,
    registration_number: str,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    sys_uri = _require_valid_uri(practitioner_identifier_system, "practitioner_identifier_system")
    reg_no = _require_non_blank_exact(registration_number, "registration_number")
    encoded = _encode_identity_parts("Practitioner", sys_uri, reg_no)
    return str(uuid5(id_namespace, encoded))


def build_observation_fhir_id(
    facility_identifier_system: str,
    facility_id: str,
    patient_identifier_system: str,
    local_patient_id: str,
    local_study_id: str,
    local_report_id: str,
    kind: ObservationKind,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    if kind not in ("findings", "impression"):
        raise ValueError(f"Unsupported observation kind: {kind!r}.")
    fac_sys = _require_valid_uri(facility_identifier_system, "facility_identifier_system")
    fac = _require_non_blank_exact(facility_id, "facility_id")
    pat_sys = _require_valid_uri(patient_identifier_system, "patient_identifier_system")
    pat = _require_non_blank_exact(local_patient_id, "local_patient_id")
    study = _require_non_blank_exact(local_study_id, "local_study_id")
    rep = _require_non_blank_exact(local_report_id, "local_report_id")
    encoded = _encode_identity_parts("Observation", fac_sys, fac, pat_sys, pat, study, rep, kind)
    return str(uuid5(id_namespace, encoded))


def build_patient_resource(
    payload: CanonicalDiagnosticReportPayload,
    config: FhirBuilderConfig,
) -> dict[str, Any]:
    _validate_config(config)
    _validate_payload(payload)

    facility_id = _require_non_blank_exact(payload.facility.facility_id, "facility.facility_id")
    local_patient_id = _require_non_blank_exact(payload.patient.local_patient_id, "patient.local_patient_id")
    patient_name = _require_non_blank_exact(payload.patient.name, "patient.name")

    fhir_id = build_patient_fhir_id(
        facility_identifier_system=config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=config.patient_identifier_system,
        local_patient_id=local_patient_id,
        id_namespace=config.id_namespace,
    )

    identifiers: list[dict[str, Any]] = [
        {
            "type": {
                "coding": [
                    {
                        "system": V2_0203_SYSTEM,
                        "code": "MR",
                        "display": "Medical record number",
                    }
                ]
            },
            "system": config.patient_identifier_system,
            "value": local_patient_id,
        }
    ]

    if config.abha_identifier_system is not None and payload.patient.abha_address.strip():
        identifiers.append(
            {
                "type": {
                    "coding": [
                        {
                            "system": NDHM_IDENTIFIER_TYPE_CS,
                            "code": "ABHA",
                            "display": "Ayushman Bharat Health Account (ABHA) ID",
                        }
                    ],
                    "text": "ABHA address",
                },
                "system": config.abha_identifier_system,
                "value": payload.patient.abha_address,
            }
        )

    return {
        "resourceType": "Patient",
        "id": fhir_id,
        "meta": {"profile": [PATIENT_PROFILE]},
        "text": _xhtml_narrative("Patient: " + patient_name + " (" + local_patient_id + ")"),
        "identifier": identifiers,
        "name": [{"text": patient_name}],
        "gender": _GENDER_MAP[payload.patient.gender],
        "birthDate": f"{payload.patient.year_of_birth:04d}",
    }


def build_organization_resource(
    payload: CanonicalDiagnosticReportPayload,
    config: FhirBuilderConfig,
) -> dict[str, Any]:
    _validate_config(config)
    _validate_payload(payload)

    facility_id = _require_non_blank_exact(payload.facility.facility_id, "facility.facility_id")
    facility_name = _require_non_blank_exact(payload.facility.name, "facility.name")

    fhir_id = build_organization_fhir_id(
        facility_identifier_system=config.facility_identifier_system,
        facility_id=facility_id,
        id_namespace=config.id_namespace,
    )

    return {
        "resourceType": "Organization",
        "id": fhir_id,
        "meta": {"profile": [ORGANIZATION_PROFILE]},
        "text": _xhtml_narrative("Organization: " + facility_name + " (" + facility_id + ")"),
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": V2_0203_SYSTEM,
                            "code": "XX",
                            "display": "Organization identifier",
                        }
                    ]
                },
                "system": config.facility_identifier_system,
                "value": facility_id,
            }
        ],
        "type": [
            {
                "coding": [
                    {
                        "system": ORGANIZATION_TYPE_SYSTEM,
                        "code": "prov",
                        "display": "Healthcare Provider",
                    }
                ]
            }
        ],
        "name": facility_name,
    }


def build_practitioner_resource(
    payload: CanonicalDiagnosticReportPayload,
    config: FhirBuilderConfig,
) -> dict[str, Any]:
    _validate_config(config)
    _validate_payload(payload)

    pract_name = _require_non_blank_exact(payload.reporting_practitioner.name, "reporting_practitioner.name")
    reg_no = _require_non_blank_exact(
        payload.reporting_practitioner.registration_number,
        "reporting_practitioner.registration_number",
    )

    fhir_id = build_practitioner_fhir_id(
        practitioner_identifier_system=config.practitioner_identifier_system,
        registration_number=reg_no,
        id_namespace=config.id_namespace,
    )

    id_type_coding = dict(_PRACTITIONER_ID_TYPE_MAP[config.practitioner_identifier_type])

    return {
        "resourceType": "Practitioner",
        "id": fhir_id,
        "meta": {"profile": [PRACTITIONER_PROFILE]},
        "text": _xhtml_narrative("Practitioner: " + pract_name + " (" + reg_no + ")"),
        "identifier": [
            {
                "type": {"coding": [id_type_coding]},
                "system": config.practitioner_identifier_system,
                "value": reg_no,
            }
        ],
        "name": [{"text": pract_name}],
    }


def _build_ultrasound_observation(
    payload: CanonicalDiagnosticReportPayload,
    config: FhirBuilderConfig,
    kind: ObservationKind,
) -> dict[str, Any]:
    _validate_config(config)
    _validate_payload(payload)

    facility_id = _require_non_blank_exact(payload.facility.facility_id, "facility.facility_id")
    local_patient_id = _require_non_blank_exact(payload.patient.local_patient_id, "patient.local_patient_id")
    local_study_id = _require_non_blank_exact(payload.study.local_study_id, "study.local_study_id")
    local_report_id = _require_non_blank_exact(payload.report.local_report_id, "report.local_report_id")

    if kind == "findings":
        narrative_text = _require_non_blank_exact(payload.report.findings, "report.findings")
        loinc_coding = dict(LOINC_RADIOLOGY_STUDY_NARRATIVE)
        label = "Findings"
    elif kind == "impression":
        narrative_text = _require_non_blank_exact(payload.report.impression, "report.impression")
        loinc_coding = dict(LOINC_RADIOLOGY_IMPRESSION)
        label = "Impression"
    else:
        raise ValueError(f"Unsupported observation kind: {kind!r}.")

    obs_id = build_observation_fhir_id(
        facility_identifier_system=config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=config.patient_identifier_system,
        local_patient_id=local_patient_id,
        local_study_id=local_study_id,
        local_report_id=local_report_id,
        kind=kind,
        id_namespace=config.id_namespace,
    )
    patient_id = build_patient_fhir_id(
        facility_identifier_system=config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=config.patient_identifier_system,
        local_patient_id=local_patient_id,
        id_namespace=config.id_namespace,
    )
    practitioner_id = build_practitioner_fhir_id(
        practitioner_identifier_system=config.practitioner_identifier_system,
        registration_number=_require_non_blank_exact(
            payload.reporting_practitioner.registration_number,
            "reporting_practitioner.registration_number",
        ),
        id_namespace=config.id_namespace,
    )
    organization_id = build_organization_fhir_id(
        facility_identifier_system=config.facility_identifier_system,
        facility_id=facility_id,
        id_namespace=config.id_namespace,
    )

    fhir_status = _OBSERVATION_STATUS_MAP[
        _require_non_blank_exact(payload.report.status, "report.status").strip().upper()
    ]
    effective_dt = _require_tz_aware_datetime(payload.study.study_date_time, "study.study_date_time")
    issued_dt = _require_tz_aware_datetime(payload.report.finalized_at, "report.finalized_at")

    return {
        "resourceType": "Observation",
        "id": obs_id,
        "meta": {"profile": [OBSERVATION_PROFILE]},
        "text": _xhtml_narrative(label + ": " + narrative_text),
        "status": fhir_status,
        "category": [
            {
                "coding": [
                    {
                        "system": OBSERVATION_CATEGORY_SYSTEM,
                        "code": "imaging",
                        "display": "Imaging",
                    }
                ]
            }
        ],
        "code": {
            "coding": [loinc_coding],
            "text": label,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": effective_dt.isoformat(),
        "issued": issued_dt.isoformat(),
        "performer": [
            {"reference": f"Practitioner/{practitioner_id}"},
            {"reference": f"Organization/{organization_id}"},
        ],
        "valueString": narrative_text,
        "method": {
            "coding": [dict(SNOMED_ULTRASONOGRAPHY)],
        },
    }


def build_findings_observation(
    payload: CanonicalDiagnosticReportPayload,
    config: FhirBuilderConfig,
) -> dict[str, Any]:
    return _build_ultrasound_observation(payload=payload, config=config, kind="findings")


def build_impression_observation(
    payload: CanonicalDiagnosticReportPayload,
    config: FhirBuilderConfig,
) -> dict[str, Any]:
    return _build_ultrasound_observation(payload=payload, config=config, kind="impression")
