# E3 Milestone Review & Regression

**Milestone**: E3 — Parse / Embed / Index  
**Date**: 2026-09-06  
**Gate**: Review + regression **PASS** → proceed to E4

## 1. Scope completed

| Item | Status |
|------|--------|
| Chunker (`chunk_text`) with size/overlap | Done |
| Deterministic local embedder (`embed_text`) | Done |
| `Chunk` model + ordered writes (`ordinal`, `embedding_json`) | Done |
| `process_upload_job` pipeline (parse → chunk → embed → ACL) | Done |
| Personal profile: complete → inline ingest → `indexed` | Done |
| `POST /v1/upload-jobs/{id}/process` re-run / idempotent | Done |
| Worker claim loop for queued jobs | Done |
| Audit: `upload.completed`, `document.indexed` | Done |
| Alembic `0002_e2_e3_ingest` | Done |

## 2. Review notes

- Qdrant is stubbed via Postgres/SQLite `chunks.embedding_json` for local/dev; payload always carries `tenant_id`.
- PDF/docx parsers are deferred; md/txt UTF-8 path is the E3 acceptance slice.
- DLQ/retry counts are minimal (failed status + error_message); full Redis queue comes later.

## 3. Regression

```bash
PYTHONPATH=packages:apps python3 -m pytest -q
# 15 passed (E0–E4)
```

## 4. Exit criteria

- [x] Upload Markdown → job `indexed`
- [x] Chunks stored with tenant_id + embeddings
- [x] Default ACL granted on index
- [x] Prior milestone tests still green

## 5. Decision

**E3 CLOSED.** Next: **E4 — ACL-aware search + dual-tenant isolation (M1 gate)**.
