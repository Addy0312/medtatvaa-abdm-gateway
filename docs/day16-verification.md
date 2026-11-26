# Day 16: NRCeS FHIR R4 base resource builders

## Scope

Pure deterministic builders in app/services/fhir_builders.py generate Patient, Organization, Practitioner, and two ultrasound Observations (findings and impression) from CanonicalDiagnosticReportPayload. No new API, migration, transaction state or persistence changes. No DiagnosticReport, Composition, Bundle, PDF assembly, crypto, transfer or Day 17+ implementation.

## Mapping and caller configuration

FhirBuilderConfig requires caller-verified absolute identifier namespaces for facility IDs, facility-scoped patient MRNs and practitioner registration numbers. Example domains in samples are synthetic placeholders, not official ABDM namespaces. Supply the real deployment namespaces before use. Do not relabel a registration number as an HPR ID. The default practitioner identifier type is PRN; MD is available for an actual medical licence number.

Patient M/F/O maps to male/female/other. Birth year stays YYYY, with no invented month/day. ABHA address is omitted unless a namespace is explicitly configured, then uses the IG ABHA identifier type. It is not converted to an ABHA number. Local identifiers and clinical findings/impression preserve exact text. No diagnosis, anatomy or normality coding is inferred.

Observation findings code: LOINC 18782-3, Radiology Study observation (narrative). Impression code: LOINC 19005-8, Radiology Imaging study [Impression] (narrative). Ultrasound method: SNOMED CT 16310003, Ultrasonography. Category is imaging. The builders reject non-US modalities, unsupported report statuses, blank required strings, naive/chronologically inconsistent timestamps, illegal XML characters and invalid namespace forms. These are focused guards, not a complete FHIR validator.

Resource IDs are UUIDv5 over unambiguous JSON-encoded identity parts. Patient/organization/observation identity includes configured namespace scope; observation identity also includes patient, study, report and observation kind. Caller must keep namespaces and local identities stable. Subject and performer references match the corresponding builder outputs. Year-only dates and timezone offsets are retained. XHTML is escaped.

## Use

```python
from app.services.fhir_builders import FhirBuilderConfig, build_patient_resource
config = FhirBuilderConfig(
    facility_identifier_system="https://example.org/facility",
    patient_identifier_system="https://example.org/mrn",
    practitioner_identifier_system="https://example.org/registration",
)
patient = build_patient_resource(payload, config)
```

Run from repository root:

```sh
python -m pip install -r requirements.txt
pytest -q
PYTHONPATH=. python scripts/generate_day16_fhir_samples.py
```

The sample JSON is an object containing five standalone resources, not a FHIR Bundle. API/OpenAPI/Postman contracts are unchanged by this internal service-only increment.

## Verification on November 24, 2026

- 53/53 repository tests pass in the requirements-only environment used for the Day 15 repair.
- Nine Day 16 tests cover all resource mappings, reference agreement, deterministic JSON, delimiter collisions, namespace/study scope, status and gender mappings, exact text preservation, XHTML escaping, input/output isolation, invalid inputs and URI edge cases.
- Official NRCeS 6.5.0 profile snapshots were read directly. Generated samples were independently checked for top-level required fields and profile declarations; present identifiers carry type/value.
- Gemini generated and iteratively corrected implementation/tests. Final actual builder source was pasted for static review, which found no further concrete bugs. That review did not execute tests or an official validator.
- Full HL7/NRCeS profile, FHIRPath invariant and terminology validation is not claimed. That remains Day 18. No live ABDM, PostgreSQL or Docker run. Python 3.10 used, not recommended 3.12+.

## Sources

Current published NRCeS IG is 6.5.0, based on FHIR 4.0.1. Normative profile constraints take precedence over illustrative examples.

- https://www.nrces.in/ndhm/fhir/r4/profiles.html
- https://www.nrces.in/ndhm/fhir/r4/StructureDefinition-Patient.html
- https://www.nrces.in/ndhm/fhir/r4/StructureDefinition-Organization.html
- https://www.nrces.in/ndhm/fhir/r4/StructureDefinition-Practitioner.html
- https://www.nrces.in/ndhm/fhir/r4/StructureDefinition-Observation.html
- https://www.nrces.in/ndhm/fhir/r4/ValueSet-ndhm-identifier-type-code.html
- https://loinc.org/18782-3
- https://loinc.org/19005-8
- http://hl7.org/fhir/R4/datatypes.html
- https://www.ebi.ac.uk/ols4/ontologies/snomed/classes/http%253A%252F%252Fsnomed.info%252Fid%252F16310003?lang=en
- Generation and review: https://gemini.google.com/app/a73780708bc4753e

LOINC panel pages contained older display labels; the direct current term pages above were used instead.
