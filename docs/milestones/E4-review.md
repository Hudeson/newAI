# E4 Milestone Review & Regression (M1 Gate)

**Milestone**: E4 — ACL + Search Isolation (M1 exit)  
**Date**: 2026-09-06  
**Gate**: Review + regression **PASS** → M1 closed; E5 only after this gate

## 1. Scope completed

| Item | Status |
|------|--------|
| `document_acls` + default owner/workspace grants | Done |
| `readable_document_ids` / `can_read_document` | Done |
| `PUT /v1/documents/{id}/acl` (admin replace) | Done |
| `GET /v1/documents/{id}` ACL-enforced (404) | Done |
| `POST /v1/search` with mandatory tenant + ACL filter | Done |
| Score floor (`score > 0`) to avoid unrelated hits | Done |
| Invite user in-tenant (`POST /v1/users/invite`) | Done |
| Dual-tenant isolation suite (T1–T5) | Done |
| Static check: search requires tenant_id/user_id | Done (T6) |

## 2. Isolation suite

| ID | Case | Result |
|----|------|--------|
| T1 | Tenant A upload → indexed | Pass |
| T2 | Tenant B search A-unique phrase → 0 hits | Pass |
| T3 | Tenant B GET A document → 404 | Pass |
| T4 | Viewer with workspace ACL can read; private ACL denies | Pass |
| T5 | Cross-tenant job GET → 404 | Pass |
| T6 | Search path always filters `Chunk.tenant_id` + ACL | Pass |

## 3. Known limits (M1)

- No Learning worker / ask API yet (E5+)
- Embeddings are local hashing stub (not production model / Qdrant cluster)
- No UI; API-only
- SCIM / OIDC / connectors deferred

## 4. Regression

```bash
PYTHONPATH=packages:apps python3 -m pytest -q
# 15 passed
```

## 5. Decision

**E4 / M1 CLOSED.** Do not start E5 until this review remains green on the delivery branch.
