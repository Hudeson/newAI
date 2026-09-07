# M5 Knowledge Graph — Review

**Branch**: `cursor/m5-knowledge-graph-4365`  
**Depends on**: `cursor/m5-knowledge-graph-plan-4365` / Real-LLM tip  
**Gate**: Review + regression **PASS** → optional M5 siblings (OpenSearch / multimodal)

## Scope delivered (KG.1–KG.5 MVP)

| Item | Status |
|------|--------|
| Alembic `0007_knowledge_graph` + SQLAlchemy models | Done |
| Rule + LLM extract job (`POST /v1/graph/extract`) | Done |
| ACL-aware entities / neighbors / relations / stats | Done |
| Ask `graph_augment` | Done |
| Web `/app/graph` + Ask toggle + sidebar | Done |
| Tests `tests/test_m5_knowledge_graph.py` | Done |
| `/v1/meta.milestone` = `Knowledge-Graph` | Done |

## Design locks respected

- SQL adjacency first (no Neo4j)
- List / neighbor table UI (no force-graph dependency)
- Graph augment default off
- Evidence-backed edges; cross-tenant isolation tested
- Extract uses gateway when configured; local `rule-extract` fallback

## Regression

```bash
pytest -q
```

## Deferred

- Neo4j / Memgraph adapter
- Force-directed canvas
- `GRAPH_EXTRACT_ON_INGEST=true` default
- Multimodal entities
- Field-level entity properties editing UI

## Verdict

**M5 Knowledge-Graph MVP CLOSED** for the planned KG.1–KG.5 slice.
