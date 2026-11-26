# app/services/fhir_bundle_assembler.py
from __future__ import annotations

import base64
import binascii
import copy
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from uuid import UUID, uuid5

from app.schemas.canonical_report import CanonicalDiagnosticReportPayload
from app.services.fhir_builders import (
    DEFAULT_FHIR_ID_NAMESPACE,
    NRCE_IG_VERSION,
    SNOMED_SYSTEM,
    FhirBuilderConfig,
    _encode_identity_parts,
    _require_non_blank_exact,
    _require_tz_aware_datetime,
    _require_valid_uri,
    _validate_config,
    _validate_payload,
    _xhtml_narrative,
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

DOCUMENT_BUNDLE_PROFILE = (
    f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle|{NRCE_IG_VERSION}"
)
DIAGNOSTIC_REPORT_RECORD_PROFILE = (
    f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord|{NRCE_IG_VERSION}"
)
DIAGNOSTIC_REPORT_IMAGING_PROFILE = (
    f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging|{NRCE_IG_VERSION}"
)

LOINC_SYSTEM = "http://loinc.org"
DIAGNOSTIC_REPORT_LOINC_CODE = "18748-4"
DIAGNOSTIC_REPORT_LOINC_DISPLAY = "Diagnostic imaging study"

IMAGING_REPORT_SNOMED_CODE = "4201000179104"
IMAGING_REPORT_SNOMED_DISPLAY = "Imaging report"

RADIOLOGY_SPECIALTY_SNOMED_CODE = "394914008"
RADIOLOGY_SPECIALTY_SNOMED_DISPLAY = "Radiology - specialty (qualifier value)"

PDF_CONTENT_TYPE = "application/pdf"
DEFAULT_MAX_PDF_BYTES = 10 * 1024 * 1024  # Arbitrary gateway safeguard (10 MiB), not an ABDM rule.
_PDF_MAGIC_PREFIX = b"%PDF-"

_COMPOSITION_STATUS_MAP: dict[str, str] = {
    "FINAL": "final",
    "AMENDED": "amended",
    "CORRECTED": "amended",
    "PRELIMINARY": "preliminary",
}

_DIAGNOSTIC_REPORT_STATUS_MAP: dict[str, str] = {
    "FINAL": "final",
    "AMENDED": "amended",
    "CORRECTED": "corrected",
    "PRELIMINARY": "preliminary",
}


class FhirAssemblyError(ValueError):
    """Raised when Day 17 FHIR R4 Bundle/Composition/DiagnosticReport assembly inputs are invalid."""


@dataclass(frozen=True)
class FhirBundleConfig:
    """
    Explicit caller-supplied identifier systems and PDF size safeguard for Day 17 bundle assembly.
    `max_pdf_bytes` (default 10 MiB = 10,485,760 bytes) is an arbitrary operational safeguard,
    not an NRCeS or ABDM specification limit.

    Known profile gap (not fabricated here): NRCeS `DiagnosticReportImaging|6.5.0` specifies
    `media` (`1..*` image Media resources), which is absent from `CanonicalDiagnosticReportPayload`.
    No synthetic or placeholder `media` entries are generated; downstream Day 18 strict validation
    will surface this gap.
    """

    bundle_identifier_system: str
    report_identifier_system: str
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES


def _validate_bundle_config(bundle_config: FhirBundleConfig) -> None:
    if not isinstance(bundle_config, FhirBundleConfig):
        raise FhirAssemblyError("bundle_config must be a FhirBundleConfig instance.")
    try:
        _require_valid_uri(bundle_config.bundle_identifier_system, "bundle_config.bundle_identifier_system")
        _require_valid_uri(bundle_config.report_identifier_system, "bundle_config.report_identifier_system")
    except ValueError as exc:
        raise FhirAssemblyError(str(exc)) from exc

    if (
        isinstance(bundle_config.max_pdf_bytes, bool)
        or not isinstance(bundle_config.max_pdf_bytes, int)
        or bundle_config.max_pdf_bytes <= 0
    ):
        raise FhirAssemblyError("bundle_config.max_pdf_bytes must be a positive integer.")


def _validate_and_encode_pdf(pdf_bytes: bytes, max_pdf_bytes: int) -> tuple[bytes, int, str]:
    if isinstance(pdf_bytes, (str, bytearray)):
        if isinstance(pdf_bytes, str):
            raise FhirAssemblyError("pdf_bytes must be bytes, not str.")
        raw = bytes(pdf_bytes)
    elif isinstance(pdf_bytes, (bytes, memoryview)):
        raw = bytes(pdf_bytes)
    else:
        raise FhirAssemblyError("pdf_bytes must be bytes.")

    if len(raw) == 0:
        raise FhirAssemblyError("pdf_bytes must not be empty.")
    if len(raw) > max_pdf_bytes:
        raise FhirAssemblyError(
            f"pdf_bytes size ({len(raw)} bytes) exceeds max_pdf_bytes ({max_pdf_bytes} bytes)."
        )
    if not raw.startswith(_PDF_MAGIC_PREFIX):
        raise FhirAssemblyError("pdf_bytes must start with %PDF-.")

    encoded = base64.b64encode(raw).decode("ascii")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise FhirAssemblyError("Failed to produce valid RFC 4648 base64 for pdf_bytes.") from exc

    if decoded != raw:
        raise FhirAssemblyError("Base64 round-trip verification failed for pdf_bytes.")

    return raw, len(raw), encoded


def _normalize_report_status(raw_status: str) -> str:
    try:
        status_str = _require_non_blank_exact(raw_status, "report.status")
    except ValueError as exc:
        raise FhirAssemblyError(str(exc)) from exc
    normalized = status_str.strip().upper()
    if normalized not in _COMPOSITION_STATUS_MAP or normalized not in _DIAGNOSTIC_REPORT_STATUS_MAP:
        raise FhirAssemblyError(f"Unsupported report.status: {raw_status!r}.")
    return normalized


def _validate_inputs_for_assembly(
    payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
    pdf_bytes: bytes,
    bundle_timestamp: datetime,
) -> tuple[str, bytes, int, str, datetime]:
    _validate_bundle_config(bundle_config)
    try:
        _validate_config(builder_config)
        _validate_payload(payload)
        ts = _require_tz_aware_datetime(bundle_timestamp, "bundle_timestamp")
    except ValueError as exc:
        raise FhirAssemblyError(str(exc)) from exc

    normalized_status = _normalize_report_status(payload.report.status)
    raw_pdf, pdf_size, pdf_b64 = _validate_and_encode_pdf(pdf_bytes, bundle_config.max_pdf_bytes)
    return normalized_status, raw_pdf, pdf_size, pdf_b64, ts


def build_composition_fhir_id(
    facility_identifier_system: str,
    facility_id: str,
    patient_identifier_system: str,
    local_patient_id: str,
    local_study_id: str,
    local_report_id: str,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    fac_sys = _require_valid_uri(facility_identifier_system, "facility_identifier_system")
    fac = _require_non_blank_exact(facility_id, "facility_id")
    pat_sys = _require_valid_uri(patient_identifier_system, "patient_identifier_system")
    pat = _require_non_blank_exact(local_patient_id, "local_patient_id")
    study = _require_non_blank_exact(local_study_id, "local_study_id")
    rep = _require_non_blank_exact(local_report_id, "local_report_id")
    encoded = _encode_identity_parts("Composition", fac_sys, fac, pat_sys, pat, study, rep)
    return str(uuid5(id_namespace, encoded))


def build_diagnostic_report_fhir_id(
    facility_identifier_system: str,
    facility_id: str,
    patient_identifier_system: str,
    local_patient_id: str,
    local_study_id: str,
    local_report_id: str,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    fac_sys = _require_valid_uri(facility_identifier_system, "facility_identifier_system")
    fac = _require_non_blank_exact(facility_id, "facility_id")
    pat_sys = _require_valid_uri(patient_identifier_system, "patient_identifier_system")
    pat = _require_non_blank_exact(local_patient_id, "local_patient_id")
    study = _require_non_blank_exact(local_study_id, "local_study_id")
    rep = _require_non_blank_exact(local_report_id, "local_report_id")
    encoded = _encode_identity_parts("DiagnosticReport", fac_sys, fac, pat_sys, pat, study, rep)
    return str(uuid5(id_namespace, encoded))


def build_bundle_fhir_id(
    facility_identifier_system: str,
    facility_id: str,
    patient_identifier_system: str,
    local_patient_id: str,
    local_study_id: str,
    local_report_id: str,
    id_namespace: UUID = DEFAULT_FHIR_ID_NAMESPACE,
) -> str:
    fac_sys = _require_valid_uri(facility_identifier_system, "facility_identifier_system")
    fac = _require_non_blank_exact(facility_id, "facility_id")
    pat_sys = _require_valid_uri(patient_identifier_system, "patient_identifier_system")
    pat = _require_non_blank_exact(local_patient_id, "local_patient_id")
    study = _require_non_blank_exact(local_study_id, "local_study_id")
    rep = _require_non_blank_exact(local_report_id, "local_report_id")
    encoded = _encode_identity_parts("Bundle", fac_sys, fac, pat_sys, pat, study, rep)
    return str(uuid5(id_namespace, encoded))


def build_diagnostic_report_resource(
    payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
    pdf_bytes: bytes,
) -> dict[str, Any]:
    """
    Build a FHIR R4 DiagnosticReport (NRCeS DiagnosticReportImaging|6.5.0) with relative-style
    internal references ("Type/id") prior to bundle urn:uuid rewriting.
    """
    try:
        _validate_bundle_config(bundle_config)
        _validate_config(builder_config)
        _validate_payload(payload)
    except ValueError as exc:
        raise FhirAssemblyError(str(exc)) from exc

    normalized_status = _normalize_report_status(payload.report.status)
    _, pdf_size, pdf_b64 = _validate_and_encode_pdf(pdf_bytes, bundle_config.max_pdf_bytes)

    facility_id = payload.facility.facility_id
    local_patient_id = payload.patient.local_patient_id
    local_study_id = payload.study.local_study_id
    local_report_id = payload.report.local_report_id
    report_title = payload.report.title
    impression_exact = payload.report.impression

    dr_id = build_diagnostic_report_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=local_patient_id,
        local_study_id=local_study_id,
        local_report_id=local_report_id,
        id_namespace=builder_config.id_namespace,
    )
    patient_id = build_patient_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=local_patient_id,
        id_namespace=builder_config.id_namespace,
    )
    organization_id = build_organization_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        id_namespace=builder_config.id_namespace,
    )
    practitioner_id = build_practitioner_fhir_id(
        practitioner_identifier_system=builder_config.practitioner_identifier_system,
        registration_number=payload.reporting_practitioner.registration_number,
        id_namespace=builder_config.id_namespace,
    )
    findings_obs_id = build_observation_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=local_patient_id,
        local_study_id=local_study_id,
        local_report_id=local_report_id,
        kind="findings",
        id_namespace=builder_config.id_namespace,
    )
    impression_obs_id = build_observation_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=local_patient_id,
        local_study_id=local_study_id,
        local_report_id=local_report_id,
        kind="impression",
        id_namespace=builder_config.id_namespace,
    )

    effective_dt = _require_tz_aware_datetime(payload.study.study_date_time, "study.study_date_time")
    issued_dt = _require_tz_aware_datetime(payload.report.finalized_at, "report.finalized_at")

    return {
        "resourceType": "DiagnosticReport",
        "id": dr_id,
        "meta": {"profile": [DIAGNOSTIC_REPORT_IMAGING_PROFILE]},
        "text": _xhtml_narrative(f"{report_title}: {impression_exact}"),
        "identifier": [
            {
                "system": bundle_config.report_identifier_system,
                "value": local_report_id,
            }
        ],
        "status": _DIAGNOSTIC_REPORT_STATUS_MAP[normalized_status],
        "category": [
            {
                "coding": [
                    {
                        "system": SNOMED_SYSTEM,
                        "code": RADIOLOGY_SPECIALTY_SNOMED_CODE,
                        "display": RADIOLOGY_SPECIALTY_SNOMED_DISPLAY,
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": LOINC_SYSTEM,
                    "code": DIAGNOSTIC_REPORT_LOINC_CODE,
                    "display": DIAGNOSTIC_REPORT_LOINC_DISPLAY,
                }
            ],
            "text": report_title,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": effective_dt.isoformat(),
        "issued": issued_dt.isoformat(),
        "performer": [{"reference": f"Organization/{organization_id}"}],
        "resultsInterpreter": [{"reference": f"Practitioner/{practitioner_id}"}],
        "result": [
            {"reference": f"Observation/{findings_obs_id}"},
            {"reference": f"Observation/{impression_obs_id}"},
        ],
        "conclusion": impression_exact,
        "presentedForm": [
            {
                "contentType": PDF_CONTENT_TYPE,
                "data": pdf_b64,
                "size": pdf_size,
                "title": report_title,
            }
        ],
    }


def build_composition_resource(
    payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    diagnostic_report_id: str,
) -> dict[str, Any]:
    """
    Build a FHIR R4 Composition (NRCeS DiagnosticReportRecord|6.5.0) with relative-style
    internal references ("Type/id") prior to bundle urn:uuid rewriting.
    """
    try:
        _validate_config(builder_config)
        _validate_payload(payload)
        dr_id_exact = _require_non_blank_exact(diagnostic_report_id, "diagnostic_report_id")
    except ValueError as exc:
        raise FhirAssemblyError(str(exc)) from exc

    normalized_status = _normalize_report_status(payload.report.status)
    finalized_dt = _require_tz_aware_datetime(payload.report.finalized_at, "report.finalized_at")

    facility_id = payload.facility.facility_id
    local_patient_id = payload.patient.local_patient_id
    local_study_id = payload.study.local_study_id
    local_report_id = payload.report.local_report_id
    report_title = payload.report.title

    comp_id = build_composition_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=local_patient_id,
        local_study_id=local_study_id,
        local_report_id=local_report_id,
        id_namespace=builder_config.id_namespace,
    )
    patient_id = build_patient_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=local_patient_id,
        id_namespace=builder_config.id_namespace,
    )
    practitioner_id = build_practitioner_fhir_id(
        practitioner_identifier_system=builder_config.practitioner_identifier_system,
        registration_number=payload.reporting_practitioner.registration_number,
        id_namespace=builder_config.id_namespace,
    )
    organization_id = build_organization_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=facility_id,
        id_namespace=builder_config.id_namespace,
    )

    return {
        "resourceType": "Composition",
        "id": comp_id,
        "meta": {"profile": [DIAGNOSTIC_REPORT_RECORD_PROFILE]},
        "text": _xhtml_narrative(report_title),
        "status": _COMPOSITION_STATUS_MAP[normalized_status],
        "type": {
            "coding": [
                {
                    "system": SNOMED_SYSTEM,
                    "code": IMAGING_REPORT_SNOMED_CODE,
                    "display": IMAGING_REPORT_SNOMED_DISPLAY,
                }
            ],
            "text": report_title,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": finalized_dt.isoformat(),
        "author": [{"reference": f"Practitioner/{practitioner_id}"}],
        "title": report_title,
        "custodian": {"reference": f"Organization/{organization_id}"},
        "section": [
            {
                "title": report_title,
                "code": {
                    "coding": [
                        {
                            "system": SNOMED_SYSTEM,
                            "code": IMAGING_REPORT_SNOMED_CODE,
                            "display": IMAGING_REPORT_SNOMED_DISPLAY,
                        }
                    ]
                },
                "entry": [
                    {
                        "reference": f"DiagnosticReport/{dr_id_exact}",
                        "type": "DiagnosticReport",
                    }
                ],
            }
        ],
    }


def _rewrite_references_to_urn_uuid(node: Any, ref_to_urn: dict[str, str]) -> Any:
    if isinstance(node, dict):
        rewritten: dict[str, Any] = {}
        for key, value in node.items():
            if key == "reference" and isinstance(value, str):
                if value not in ref_to_urn:
                    raise FhirAssemblyError(f"Unresolvable internal reference: {value!r}.")
                rewritten[key] = ref_to_urn[value]
            else:
                rewritten[key] = _rewrite_references_to_urn_uuid(value, ref_to_urn)
        return rewritten
    if isinstance(node, list):
        return [_rewrite_references_to_urn_uuid(item, ref_to_urn) for item in node]
    return node


def build_diagnostic_report_bundle(
    payload: CanonicalDiagnosticReportPayload,
    builder_config: FhirBuilderConfig,
    bundle_config: FhirBundleConfig,
    pdf_bytes: bytes,
    bundle_timestamp: datetime,
) -> dict[str, Any]:
    """
    Assemble a deterministic FHIR R4 Document Bundle conforming to NRCeS DocumentBundle|6.5.0.
    Does not mutate inputs or Day 16 resource builders; returns an independent JSON-serializable dict.
    """
    _, _, _, _, ts = _validate_inputs_for_assembly(
        payload=payload,
        builder_config=builder_config,
        bundle_config=bundle_config,
        pdf_bytes=pdf_bytes,
        bundle_timestamp=bundle_timestamp,
    )

    patient_res = copy.deepcopy(build_patient_resource(payload, builder_config))
    practitioner_res = copy.deepcopy(build_practitioner_resource(payload, builder_config))
    organization_res = copy.deepcopy(build_organization_resource(payload, builder_config))
    findings_obs_res = copy.deepcopy(build_findings_observation(payload, builder_config))
    impression_obs_res = copy.deepcopy(build_impression_observation(payload, builder_config))
    diagnostic_report_res = copy.deepcopy(
        build_diagnostic_report_resource(
            payload=payload,
            builder_config=builder_config,
            bundle_config=bundle_config,
            pdf_bytes=pdf_bytes,
        )
    )
    composition_res = copy.deepcopy(
        build_composition_resource(
            payload=payload,
            builder_config=builder_config,
            diagnostic_report_id=diagnostic_report_res["id"],
        )
    )

    ordered_resources = [
        composition_res,
        patient_res,
        practitioner_res,
        organization_res,
        diagnostic_report_res,
        findings_obs_res,
        impression_obs_res,
    ]

    ref_to_urn: dict[str, str] = {}
    for res in ordered_resources:
        rtype = res["resourceType"]
        rid = res["id"]
        rel_ref = f"{rtype}/{rid}"
        urn_uuid = f"urn:uuid:{rid}"
        if rel_ref in ref_to_urn:
            raise FhirAssemblyError(f"Duplicate resource identity inside bundle: {rel_ref!r}.")
        ref_to_urn[rel_ref] = urn_uuid

    rewritten_entries: list[dict[str, Any]] = []
    for res in ordered_resources:
        rewritten_res = _rewrite_references_to_urn_uuid(res, ref_to_urn)
        rewritten_entries.append(
            {
                "fullUrl": f"urn:uuid:{rewritten_res['id']}",
                "resource": rewritten_res,
            }
        )

    bundle_id = build_bundle_fhir_id(
        facility_identifier_system=builder_config.facility_identifier_system,
        facility_id=payload.facility.facility_id,
        patient_identifier_system=builder_config.patient_identifier_system,
        local_patient_id=payload.patient.local_patient_id,
        local_study_id=payload.study.local_study_id,
        local_report_id=payload.report.local_report_id,
        id_namespace=builder_config.id_namespace,
    )

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {
            "versionId": "1",
            "lastUpdated": ts.isoformat(),
            "profile": [DOCUMENT_BUNDLE_PROFILE],
        },
        "identifier": {
            "system": bundle_config.bundle_identifier_system,
            "value": bundle_id,
        },
        "type": "document",
        "timestamp": ts.isoformat(),
        "entry": rewritten_entries,
    }

    # Ensure JSON serializability and deep independence
    json.dumps(bundle)
    return copy.deepcopy(bundle)
