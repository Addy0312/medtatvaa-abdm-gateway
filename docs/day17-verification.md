# Day 17 Verification Notes: NRCeS FHIR R4 DiagnosticReportRecord Document Bundle Assembler

## Scope and Non-Goals
- Implemented Day 17 only: `app/services/fhir_bundle_assembler.py`, unit tests in `tests/unit/test_fhir_bundle_assembler.py` and `tests/unit/test_fhir_bundle_assembler_edges.py`, sample generator in `scripts/generate_day17_bundle_sample.py`, and this verification document.
- Reuses Day 16 `app/services/fhir_builders.py` and `app/schemas/canonical_report.py` without modifying Day 15/16 files, API endpoints, database models/migrations, crypto modules, or Day 18 validators.
- Uses Python standard library only beyond the existing schema/test stack (`pydantic`, `pytest`).

## Requirements Checklist
- [x] `FhirBundleConfig` frozen dataclass with `bundle_identifier_system`, `report_identifier_system`, and `max_pdf_bytes` (default `10 * 1024 * 1024` bytes = 10 MiB; documented as an arbitrary gateway safeguard, not an ABDM rule).
- [x] Validated URI requirements for both identifier systems via Day 16 URI validation; no identifier namespaces invented or defaulted.
- [x] Deterministic UUIDv5 ID builders (`build_composition_fhir_id`, `build_diagnostic_report_fhir_id`, `build_bundle_fhir_id`) using Day 16 `_encode_identity_parts` and `builder_config.id_namespace`.
- [x] Standalone `build_diagnostic_report_resource(...)` and `build_composition_resource(...)` returning dicts with relative `"Type/id"` references prior to bundling.
- [x] `build_diagnostic_report_bundle(...)` producing a FHIR R4 `Bundle` (`type = "document"`, `meta.versionId = "1"`, `meta.profile = ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle|6.5.0"]`, `timestamp`, `identifier`).
- [x] Bundle entry order: `Composition`, `Patient`, `Practitioner`, `Organization`, `DiagnosticReport`, findings `Observation`, impression `Observation`, with `fullUrl = "urn:uuid:<id>"` and all internal `Reference.reference` values rewritten to matching `urn:uuid:<id>`.
- [x] `presentedForm` populated with `contentType = "application/pdf"`, RFC 4648 base64 without line breaks, `size` (byte count), and `title`, with PDF validation (`bytes`/bytearray-compatible, not `str`, non-empty, starts with `b"%PDF-"`, `len <= max_pdf_bytes`).
- [x] `FhirAssemblyError(ValueError)` raised consistently for invalid bundle config, naive/non-datetime `bundle_timestamp`, invalid PDF inputs, unknown report status, and blank/invalid fields.
- [x] Status mappings implemented: Composition (`FINAL -> final`, `AMENDED -> amended`, `CORRECTED -> amended`, `PRELIMINARY -> preliminary`) and DiagnosticReport (`FINAL -> final`, `AMENDED -> amended`, `CORRECTED -> corrected`, `PRELIMINARY -> preliminary`).
- [x] Exact preservation of clinical strings (including `DiagnosticReport.conclusion` and special/Unicode characters) and deep-copy isolation from inputs and Day 16 outputs.

## Official Profile Facts (NRCeS ABDM FHIR R4 IG 6.5.0, FHIR 4.0.1)
- **DocumentBundle (`https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle|6.5.0`)**: `meta` (`1..1`) with `meta.versionId` (`1..1`), `identifier` (`1..1` with `system` and `value`), fixed `type = "document"`, timezone-aware `timestamp` (`1..1`), and `Composition` as the first entry.
- **DiagnosticReportRecord (`https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord|6.5.0`)**: `status` (`1..1`), `type` (`1..1`, single SNOMED coding `4201000179104` `"Imaging report"` plus `text`), `subject` (`1..1` -> `Patient`), `date` (`1..1`), `author` (`1..*` -> `Practitioner`), `title` (`1..1`), `custodian` -> `Organization`, and one `section` (`1..1`) with `code` (SNOMED `4201000179104` `"Imaging report"`), `title`, and `entry` referencing `DiagnosticReport` with `type = "DiagnosticReport"` (omitting the unused `0..1` `DocumentReference` slice).
- **DiagnosticReportImaging (`https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging|6.5.0`)**: `status` (`1..1`), `code` (`1..1`, LOINC `18748-4` `"Diagnostic imaging study"`, `text = report.title`), `category` (SNOMED `394914008` `"Radiology - specialty (qualifier value)"`), `subject` -> `Patient`, `performer` -> `Organization`, `resultsInterpreter` (`1..*`) -> `Practitioner`, `result` referencing findings `Observation` then impression `Observation`, `conclusion` set to exact `report.impression`, `effectiveDateTime` set to `study.study_date_time`, `issued` set to `report.finalized_at`, `presentedForm` (`application/pdf`, base64 `data`, `size`, `title`), and versioned `meta.profile`.

## Known Limitations
- **Missing `DiagnosticReportImaging.media` (`1..*`)**: NRCeS `DiagnosticReportImaging|6.5.0` requires `media` (`1..*` image `Media` resources), whereas `CanonicalDiagnosticReportPayload` provides no image payloads. This assembler does not fabricate placeholder `Media` resources or fake image bytes; downstream Day 18 strict profile validation is expected to flag this gap until image payloads are added upstream.
- **Terminology not checked**: SNOMED, LOINC and MIME codes were not checked against a terminology server (the public tx.fhir.org run did not finish in the time allowed). Offline, the HL7 validator reports `application/pdf` as not found in the MimeType value set only because it could not load that code system; treat it as unverified, not as confirmed valid or invalid.
- **Not tested**: real PostgreSQL, ABDM sandbox, Windows, Python 3.12. Python 3.10 on Linux only.

## Independent Verification (run after integration)
- `PYTHONPATH=. python scripts/generate_day17_bundle_sample.py` regenerates `docs/samples/day17-diagnostic-report-bundle.json`.
- `pytest`: full suite passes (see `docs/day17-tests.txt`).
- Real app run: `alembic upgrade head` on an empty SQLite file, `uvicorn` started, `POST /api/v1/records/diagnostic-report` (202, identical replay 202, changed body 409, invalid gender 422), stored `payload_json` read back from the database and assembled into a Bundle with a PDF. 7 entries, 15 references, 0 dangling, PDF base64 round trip exact, findings text with `<`, `&`, quotes and non-ASCII preserved, repeat call identical, and 7 invalid inputs rejected with `FhirAssemblyError`.
- HL7 FHIR validator 6.3.11 with the NRCeS 6.5.0 package (`ndhm.in#6.5.0`), FHIR 4.0.1, offline terminology. Patient, Practitioner, Organization and both Observations validate with no errors. Remaining errors: `DiagnosticReport.media` minimum 1 not met (the known gap above), which also stops the Composition `section.entry` from matching `DiagnosticReportImaging`, plus the MIME code item above. No other structural errors against `DocumentBundle` or `DiagnosticReportRecord`.
