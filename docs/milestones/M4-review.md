# M4 Review — Enterprise hardening

**Date**: 2026-09-07  
**Branch**: `cursor/m4-enterprise-4365`  
**Gate**: Review + regression **PASS** → local deploy / M5 optional

## Scope delivered

| Item | Status |
|------|--------|
| Workspace `publish_mode` auto/approval + admin-only publish | Done |
| Pending approvals admin list | Done |
| Document `sensitivity` L1–L4 + PATCH API | Done |
| Model route policies + Ask routing by max cited sensitivity | Done |
| Audit export create + download | Done |
| CORS via `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` | Done |
| Governance UI: publish mode, approvals, policy, export | Done |
| Learn UI: approve/publish + sensitivity | Done |
| `scripts/local-deploy.sh` | Done |
| Alembic `0005_m4_enterprise` | Done |

## Regression

```bash
ruff check packages apps tests   # All checks passed
PYTHONPATH=packages:apps python3 -m pytest -q   # 30 passed
cd apps/web && npm run build
```

## Deferred (M5+)

- Multi-region / OpenSearch / knowledge graph
- Eval gates in CI
- Full BPM approval integration
- Real private GPU model backends

**M4 CLOSED** when tests green and local deploy healthy.
