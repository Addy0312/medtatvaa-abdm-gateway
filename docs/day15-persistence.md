# Day 15: canonical report persistence

## Day 15 Scope & Out-of-Scope Boundaries

### In Scope (Day 15)
- Canonical diagnostic report persistence in `DiagnosticReportStore` (`diagnostic_reports`) keyed by patient/care-context identity and report identifier.
- Atomic transaction and care-context registration alongside report persistence on `POST /api/v1/records/diagnostic-report`.
- Safe idempotency and conflict handling returning HTTP `409` without overwriting existing records.
- Alembic migration `20261124_0015` revising `734706997e4e` in `migrations/versions/`.
- Integration and service tests in `tests/test_day15_diagnostic_report_store.py` and schema initialization fixture in `tests/conftest.py`.

### Out of Scope (Day 16+ / Not Due Today)
- FHIR bundle/resource conversion or NRCeS transmission.
- Field-level or column-level encryption or cryptographic signing (`payload_json` is stored in plaintext; restrict database/access controls accordingly).
- Consent/HIP transfer workflows or later-day deliverables.

---

## Model, Table, Keying & Non-Overwrite Semantics

- **ORM Model & Table:** `DiagnosticReportStore` (`app/models/entities.py`) backed by table `diagnostic_reports` (`migrations/versions/20261124_0015_add_diagnostic_reports.py`).
- **Keying & Constraints:**
  - Natural unique key: `UniqueConstraint("abha_address", "care_context_reference", "local_report_id", name="uq_diag_report_abha_care_context_report_id")`.
  - Patient identity tracking: `abha_address` and `local_patient_id` are persisted and validated against existing care contexts (`CareContextRecord`) and existing reports under `(abha_address, care_context_reference)`.
  - Idempotency & transaction linkage: `idempotency_key` has a unique index (`ix_diagnostic_reports_idempotency_key`), and `gateway_transaction_id` is a non-null foreign key to `gateway_transactions.gateway_transaction_id` (`ondelete="RESTRICT"`).
  - Canonical storage: `payload_json` stores the full canonical JSON payload (plaintext, synthetic test/clinical fixtures only), paired with `payload_hash` (SHA-256 digest of canonical JSON).
- **No Overwrites / No Versioning:** Existing `DiagnosticReportStore` rows are never overwritten in place and no report version history table is introduced in Day 15. Conflicting submissions reject with HTTP `409`.

---

## Endpoint Behavior, Replay & Error Codes

`POST /api/v1/records/diagnostic-report` preserves the `TransactionResponse` contract on HTTP `202 Accepted` and returns top-level `ErrorResponse` JSON (`status: "FAILED_FINAL"`, `error_code`, `message`, `transaction_id`, `details`) on HTTP `409 Conflict`.

- **202 & Current-Status Replay:** Replaying the same `X-Idempotency-Key` with an identical canonical payload, matching patient/care-context/report identity, matching `gateway_transaction_id`, and `operation_type == "REPORT_SHARE"` returns HTTP `202` with the existing `transaction_id`, `abdm_request_id`, and the transaction's **current** `status` (including after status advancements such as `LINKED`, `SHARED`, or `COMPLETED`).
- **New Key for Same Report (`409`):** Submitting an already-persisted `(abha_address, care_context_reference, local_report_id)` under a **new** `X-Idempotency-Key` returns HTTP `409` (`CARE_CONTEXT_REPORT_CONFLICT`) and persists no new `GatewayTransaction` or `DiagnosticReportStore` row.
- **Atomic Rollback:** Care context creation, transaction creation, and canonical report persistence run within a single unit of work (`commit=False` until all steps succeed). Any conflict, `IntegrityError`, or unexpected exception (such as `RuntimeError`) triggers `await db.rollback()` so partial or orphan rows are not committed.

### HTTP 409 Error Codes
- `IDEMPOTENCY_OPERATION_CONFLICT`: Existing transaction for `idempotency_key` is missing or has an `operation_type` other than `REPORT_SHARE`.
- `IDEMPOTENCY_PAYLOAD_CONFLICT`: Reused `idempotency_key` has a different canonical payload hash, patient/care-context/report identity, or transaction association.
- `PATIENT_IDENTITY_CONFLICT`: `local_patient_id` conflicts with an existing `CareContextRecord` or existing report for `(abha_address, care_context_reference)`.
- `CARE_CONTEXT_REPORT_CONFLICT`: `(abha_address, care_context_reference, local_report_id)` already exists (including when submitted with a new idempotency key).
- `CONCURRENT_PERSISTENCE_CONFLICT`: IntegrityError at the endpoint. Service-level race conflicts may return `DIAGNOSTIC_REPORT_CONFLICT` or `IDEMPOTENCY_CONFLICT`.

---

## Setup, Migration & Verification Notes

> **Data & Security Note:** Use synthetic data only. Canonical report JSON (`payload_json`) is stored in plaintext (no application-layer encryption); enforce database access controls and least privilege. Because `tests/conftest.py` initializes `Base.metadata` against the configured `engine` (`DATABASE_URL`), always point `pytest` at a disposable `DATABASE_URL` and **never** a production database.

### Commands
```bash
git apply day15-gemini.patch
pip install -r requirements.txt
pytest -q
python scripts/export_docs.py
```

## Reported Verification & Migration Caveats

Reported Test & Schema Status: Reported as passing 40/40 tests from a clean database, applying cleanly on commit a289247, and passing SQLite roundtrip/model comparison for revision 20261124_0015 (revising 734706997e4e). PostgreSQL and live sandbox execution were not verified in this review (tests were not executed by the reviewer).

Prior Revision 734706997e4e on Fresh SQLite: Prior revision 734706997e4e fails on a fresh SQLite database due to an ALTER COLUMN TYPE operation. Databases already migrated through 734706997e4e can upgrade to 20261124_0015, whereas a fresh SQLite migration chain requires a separate fix to 734706997e4e—do not use alembic stamp as a deployment workaround.

Preexisting Issues (Not Day 15 Bugs): consent_artefacts currently lacks an Alembic migration, and test_m2_discovery duplicates linking behavior; both are preexisting.

API Sample & Postman: Reuse the existing canonical diagnostic report Postman request and canonical schema payload unchanged.

Day 15 Requirement Matrix
Day 15 Requirement	Implementation / Artifact	Tests / Docs
Persist full canonical report JSON + hash under patient & care-context identity	app/models/entities.py (DiagnosticReportStore), app/services/diagnostic_report_service.py	tests/test_day15_diagnostic_report_store.py, docs/day15-persistence.md
Coexisting reports per care context & patient identity validation	app/models/entities.py (uq_diag_report_abha_care_context_report_id), app/services/diagnostic_report_service.py	tests/test_day15_diagnostic_report_store.py
Preserve TransactionResponse (202) & replay current status for REPORT_SHARE	app/api/v1/records.py, app/services/transaction_service.py	tests/test_day15_diagnostic_report_store.py
Reject conflicts with HTTP 409 & never overwrite existing records	app/api/v1/records.py, app/services/diagnostic_report_service.py, app/services/transaction_service.py	tests/test_day15_diagnostic_report_store.py
Atomic commit/rollback across transaction, care context & report store	app/api/v1/records.py	tests/test_day15_diagnostic_report_store.py
Migration revising 734706997e4e in migrations/versions/	migrations/versions/20261124_0015_add_diagnostic_reports.py	tests/conftest.py, docs/day15-persistence.md
Later-Day Deliverables Not Due Today

FHIR bundle/resource mapping and validation

Encryption at rest / field-level encryption / key management

ABDM health information transfer / HIP data push & consent fulfillment flows

## Contract and evidence

`docs/openapi.json` is regenerated from the integrated app. `python scripts/export_docs.py` also regenerated the Postman collection without a content change; its synthetic canonical-report request remains valid. `docs/day15-tests.txt` records the full clean test run. Python 3.10 was available for execution here; the architecture recommends Python 3.12+, which was not separately verified. No sandbox or PostgreSQL execution is claimed.

The relevant brief requirements are versioned API compatibility, canonical payload independence from FHIR, persistent transaction correlation, DB uniqueness and duplicate-request tests, migrations, synthetic-only fixtures, synchronized OpenAPI, reproducible testing and known-limitations disclosure. This Day 15 patch covers those for report ingestion. The wider brief's Docker clean-machine acceptance, full M1/M2 sandbox evidence, wrapper evaluation, callback security and final production handover are not completed by this increment. Existing test fixture creates schema in the configured database; always use a disposable database for tests.
