# E5 Milestone Review & Regression

**Milestone**: E5 — Learn + Ask with citations (M2 slice)  
**Date**: 2026-09-06  
**Gate**: Review + regression **PASS** → UI (E6) may start

## 1. Scope completed

| Item | Status |
|------|--------|
| Extractive Learn Worker (`summary` / `outline` / `key_points`) | Done |
| `LearningReport` draft/published (`publish_mode=auto` → published) | Done |
| Inline learn after index (personal profile) | Done |
| `GET /v1/documents/{id}/learning`, `POST .../learn`, publish | Done |
| `POST /v1/ask` with citations | Done |
| Citation ACL re-validation (`validate_citations`) | Done |
| Local LLM gateway + `usage_ledger` | Done |
| `GET /v1/usage` | Done |
| Alembic `0003_e5_learn_ask` | Done |

## 2. Review notes

- Learner/ask use a **local extractive** provider (no external API keys required in CI).
- Citations are filtered twice: search ACL + `validate_citations` before answer assembly.
- Cross-tenant ask returns empty citations (isolation preserved from E4).
- Document status may become `published` after auto-learn; E3 tests accept `indexed|published|learned`.

## 3. Regression

```bash
PYTHONPATH=packages:apps python3 -m pytest -q
# 18 passed (E0–E5)
```

## 4. Exit criteria

- [x] Upload → indexed → learning report readable
- [x] Ask returns answer + authorized citations
- [x] Unauthorized/cross-tenant citations never appear
- [x] Usage ledger records learn/ask
- [x] Prior milestone tests still green

## 5. Decision

**E5 CLOSED (M2 API slice).** Next: **E6 — Frontend** (upload/learn/ask UI). Do not weaken isolation tests.
