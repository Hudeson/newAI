# E1 Milestone Review & Regression

**Milestone**: E1 — Identity & tenancy  
**Date**: 2026-09-06  
**Gate**: Review + regression **PASS** → proceed to E2

## 1. Scope completed

| Item | Status |
|------|--------|
| Local register creates tenant + admin + default workspace | Done |
| Login issues JWT with `tenant_id` / `user_id` / `role` | Done |
| `GET /v1/me` requires auth | Done |
| `GET/POST /v1/workspaces` tenant-scoped | Done |
| Admin-only workspace create | Done |
| Dual-tenant isolation tests for workspace listing | Done |

## 2. Review notes

- Tokens always bind `tenant_id`; workspace queries filter by token tenant.
- Password hashing uses PBKDF2-HMAC (no external crypto service in E1).
- OIDC deferred to enterprise profile wiring later; personal local auth is the E1 path.
- JWT secret in tests is short (warning only); production must use ≥32-byte secret.

## 3. Regression

```bash
PYTHONPATH=packages:apps python3 -m pytest -q
# 8 passed (E0 + E1)
```

## 4. Exit criteria

- [x] Register / login / me
- [x] Workspace CRUD (create + list) tenant scoped
- [x] Unauthenticated `/v1/me` → 401
- [x] Cross-tenant workspace list isolation
- [x] Prior E0 tests still green

## 5. Decision

**E1 CLOSED.** Next: **E2 — Presigned upload + UploadJob**.
