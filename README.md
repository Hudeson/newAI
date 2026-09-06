# newAI — Enterprise Knowledge Base Agent

Multi-tenant knowledge-base agent: document ingest, auto learning summaries,
ACL-aware RAG, and auditable tool-using agents. `personal` / `team` /
`enterprise` share one domain model.

## Docs

- **Technical architecture**: [`docs/technical-architecture.md`](./docs/technical-architecture.md)
- **Project plan**: [`docs/project-plan.md`](./docs/project-plan.md)
- **Execution plan**: [`docs/execution-plan.md`](./docs/execution-plan.md)
- Data model / API / Ops / Connectors: see `docs/`
- Checklist: [`docs/checklist.md`](./docs/checklist.md)

## Current milestone

**E0 — scaffold** (in progress → gate with review + regression)

## Quick start (E0)

```bash
python3 -m pip install -e ".[dev]"
cp .env.example .env
mkdir -p data
make test          # regression
make run-api       # http://127.0.0.1:8000/healthz
```

Optional dependencies (when Docker is available):

```bash
docker compose -f deploy/compose/docker-compose.yml up -d
# then set DATABASE_URL / REDIS_URL / QDRANT_URL / S3_ENDPOINT in .env
```

## Milestone gate policy

Each `E*` / `M*` exit requires:

1. Checklist review against exit criteria
2. Full regression of tests up to that milestone
3. Short review note under `docs/milestones/`

## Layout

```
apps/api          FastAPI
apps/workers      async workers (stub in E0)
packages/shared   config, db, errors, logging
deploy/compose    Postgres / Redis / Qdrant / MinIO
docs/             architecture & plans
tests/            automated tests
```
