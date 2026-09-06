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

**E6 — Frontend** (login / upload / learn / ask / members)

## Quick start

```bash
python3 -m pip install -e ".[dev]"
cp .env.example .env
mkdir -p data
make test          # API regression (E0–E6)
make run-api       # http://127.0.0.1:8000/healthz

cd apps/web && cp .env.example .env.local && npm install && npm run dev
# Web UI: http://127.0.0.1:3000
```

## Layout

```
apps/api          FastAPI
apps/workers      ingest / learn workers
apps/web          Next.js UI (E6)
packages/shared   config, db, acl, search, learn, ask
deploy/compose    Postgres / Redis / Qdrant / MinIO
docs/             architecture & plans
tests/            automated tests
```
