# E6 Milestone Review & Regression

**Milestone**: E6 — Frontend (login / upload / learn / ask / members)  
**Date**: 2026-09-06  
**Gate**: Review + regression **PASS** → E7 enterprise features may start

## 1. Scope completed

| Item | Status |
|------|--------|
| Next.js app at `apps/web` (App Router) | Done |
| Login + register + workspace switcher | Done |
| Upload zone + document library + job status | Done |
| Learning report page + re-learn | Done |
| Ask page + citation drawer | Done |
| Members read-only roster | Done |
| Backend list helpers `GET /v1/documents`, `GET /v1/users` | Done |
| CORS for local web origin | Done |

## 2. Review notes

- UI brand: **Atrium KB** (ink/teal + chartreuse accent; Fraunces + Manrope).
- Frontend talks to FastAPI via `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`).
- Personal ingest still auto-learns; library shows `published`/`indexed` documents.
- Members page is read-only (invite remains API-only for now).

## 3. Regression

```bash
PYTHONPATH=packages:apps python3 -m pytest -q
# includes E0–E6 API tests

cd apps/web && npm run build
# Next.js production build must succeed
```

## 4. Exit criteria

- [x] Auth + workspace switching in UI
- [x] Upload → indexed document visible in library
- [x] Learning report page reachable
- [x] Ask shows answer + citations drawer
- [x] Members list readable
- [x] Prior milestone tests still green

## 5. Decision

**E6 CLOSED.** Next: **E7 — governance / enterprise extras** (quota UI, SCIM, connectors) without relaxing isolation.
