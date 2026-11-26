# Fixes through Day 15

Apply this patch after day15-gemini.patch, not instead of it. No Day 16 FHIR code is included.

## Changes

- Correct historical revision 734706997e4e to add only model-aligned link_sessions. It no longer drops transaction columns or changes care_contexts.
- Add missing consent_artefacts table in revision 20261124_0015b, after 20261124_0015.
- Isolate pytest from the application database using a disposable database selected before app imports.
- Replace copied linking tests with actual discovery normalization, patient isolation, correlation, callback, malformed input, duplicate and cross-operation conflict tests.
- Handle repeated discovery request IDs without duplicate transactions or repeated callbacks.
- Include asyncpg for the PostgreSQL driver and offline migration generation.

## Verification

On November 24, 2026, a new virtual environment installed only requirements.txt. All 44 tests passed. Tests cover fresh SQLite upgrade head, zero metadata differences including server defaults, downgrade base and upgrade head, preservation of seeded base transaction/care-context rows, and SQLite/PostgreSQL offline SQL generation. Full-suite test database is disposable. Python 3.10 was used; target Python 3.12+ was not available in this run.

No live PostgreSQL server, Docker deployment, or ABDM sandbox integration was exercised. PostgreSQL offline SQL is not a substitute for a real PostgreSQL migration run. Existing callback delivery remains in-process background work, not a durable retry queue.

## Existing databases

Back up first. This corrects a historical migration for fresh installations. An Alembic revision stamp does not prove the schema is correct. If the previous destructive version of 734706997e4e actually ran, do not merely upgrade or stamp over it: inspect the live schema and restore/reconcile transaction and care-context data from backup. This patch cannot recreate dropped data. Databases built with create_all may already have consent_artefacts without an Alembic record; reconcile that state before running the new create-table migration. Do not drop tables to make the upgrade pass.

For an empty database:

```sh
python -m pip install -r requirements.txt
alembic upgrade head
pytest -q
```

Generation and iterative source review: Gemini, https://gemini.google.com/app/a73780708bc4753e . Independently integrated and tested. The alternative z.ai response was still generating and was not merged.
