# 知识图谱（Knowledge Graph）详细设计

> 状态：设计定稿（KG.0）  
> 依赖：`cursor/real-llm-gateway-4365`（LLM Gateway + 凭证 + 抽取能力）  
> 分支：`cursor/m5-knowledge-graph-plan-4365`（本文档）→ 实现分支 `cursor/m5-knowledge-graph-4365`  
> 目标：在现有个人/团队知识库之上，构建 **租户隔离、ACL 可审计、可与 RAG Ask 联动** 的知识图谱能力。

---

## 1. 背景与目标

### 1.1 当前状态

仓库已具备：上传 → 解析分块 → ACL 检索 → Learn/Ask → 治理/审批 → Real-LLM Gateway。  
`docs/checklist.md` M5 中「知识图谱」尚未开工；无实体表、无抽取流水线、无图谱 API/UI。

### 1.2 产品目标

| 目标 | 说明 |
|------|------|
| **从文档自动建图** | 对已就绪文档抽取实体与关系，写入租户内图谱 |
| **可浏览可查询** | 列表/邻接查询；后续可加可视化 |
| **服务问答** | Ask 时可选用「图谱增强」：先查实体邻域，再拼证据回答 |
| **企业约束** | 租户隔离、文档 ACL 继承、敏感级路由、审计与配额 |
| **可演进** | 先用 SQL 邻接表落地；预留图数据库适配层，不绑定 Neo4j |

### 1.3 非目标（本阶段不做）

- 全量属性图算法（PageRank/社区发现）生产化  
- 跨租户联邦图谱  
- 多模态实体（图片/视频主体检测）— 属 M5 多模态  
- 实时协同编辑图谱画布  
- 自动替代向量检索（图谱是增强，不是替换）

---

## 2. 设计原则

1. **文档仍是真理来源**：图谱是派生索引；文档删除/ACL 变更必须级联影响可见性。  
2. **Mention 锚定证据**：每条实体/关系尽量挂回 `chunk_id` + 原文 span，保证可引用、可审计。  
3. **抽取可异步、可重试**：与 ingest 解耦；失败不阻断文档 `ready`。  
4. **复用 LLM Gateway**：抽取走已有 `openai_compatible` / `ollama` / local fallback；尊重 L1–L4。  
5. **SQL 优先**：个人版零新中间件；团队版可后续挂 Neo4j/Memgraph，接口不变。  
6. **最小可用 UI**：先列表+实体详情+邻接；画布可视化列为增强项。

---

## 3. 领域模型

### 3.1 核心概念

```
Document ──has──> Chunk
   │                  │
   │                  └── mentioned_in ──> EntityMention ──> Entity
   │                                                          │
   └── (ACL/sensitivity)                                      ├── Relation (from→to)
                                                              └── EntityAlias
```

| 对象 | 含义 |
|------|------|
| **Entity** | 租户内规范实体（人/组织/产品/概念/地点/事件…） |
| **EntityAlias** | 别名与规范化映射（「OpenAI」「openai」→ 同一实体） |
| **EntityMention** | 某 chunk 中出现实体的一次提及（含 offset/证据文本） |
| **Relation** | 有向关系边（subject → predicate → object），可带属性 JSON |
| **RelationMention** | 关系证据（可选，首版可与 Relation 合并存 evidence_chunk_id） |
| **GraphExtractJob** | 文档级抽取任务状态机 |

### 3.2 实体类型（首版受控词表）

```
person | organization | product | concept | location | event | document_ref | other
```

允许租户后续扩展 `custom_types`（配置表），首版写死枚举 + `other`。

### 3.3 关系谓词（首版受控词表）

```
related_to | part_of | works_at | authored_by | depends_on | defines | references | located_in | occurs_in | synonym_of
```

未知谓词落入 `related_to`，并在 `attributes.raw_predicate` 保留原文。

### 3.4 规范化与去重

- `canonical_name`：小写、去首尾空白、折叠连续空格  
- `name_hash`：`sha256(tenant_id + "|" + type + "|" + canonical_name)` 唯一  
- 合并策略（首版）：同 type + 同 canonical → 复用；别名写入 `entity_aliases`  
- **不做**跨 type 自动合并（避免「Apple 公司」与「apple 水果」误并）

---

## 4. 存储设计（SQL）

### 4.1 表结构草案

```sql
-- 实体
CREATE TABLE entities (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  name_hash TEXT NOT NULL,
  description TEXT,
  properties_json TEXT NOT NULL DEFAULT '{}',
  mention_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, name_hash)
);
CREATE INDEX ix_entities_tenant_type ON entities(tenant_id, type);
CREATE INDEX ix_entities_tenant_canonical ON entities(tenant_id, canonical_name);

-- 别名
CREATE TABLE entity_aliases (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  canonical_alias TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'extract', -- extract|user|import
  created_at TEXT NOT NULL,
  UNIQUE(tenant_id, entity_id, canonical_alias)
);

-- 提及（证据）
CREATE TABLE entity_mentions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL,
  mention_text TEXT NOT NULL,
  start_offset INTEGER,
  end_offset INTEGER,
  confidence REAL NOT NULL DEFAULT 0.5,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_mentions_entity ON entity_mentions(tenant_id, entity_id);
CREATE INDEX ix_mentions_document ON entity_mentions(tenant_id, document_id);
CREATE INDEX ix_mentions_chunk ON entity_mentions(chunk_id);

-- 关系边
CREATE TABLE relations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  subject_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  predicate TEXT NOT NULL,
  object_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  attributes_json TEXT NOT NULL DEFAULT '{}',
  evidence_chunk_id TEXT,
  evidence_document_id TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_relations_subject ON relations(tenant_id, subject_entity_id);
CREATE INDEX ix_relations_object ON relations(tenant_id, object_entity_id);
CREATE INDEX ix_relations_pred ON relations(tenant_id, predicate);
-- 软去重：同 tenant+subject+predicate+object 可多条证据；查询时聚合
CREATE INDEX ix_relations_spo ON relations(tenant_id, subject_entity_id, predicate, object_entity_id);

-- 抽取任务
CREATE TABLE graph_extract_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  status TEXT NOT NULL, -- queued|running|succeeded|failed|cancelled
  chunks_total INTEGER NOT NULL DEFAULT 0,
  chunks_done INTEGER NOT NULL DEFAULT 0,
  entities_created INTEGER NOT NULL DEFAULT 0,
  relations_created INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  trigger TEXT NOT NULL DEFAULT 'manual', -- manual|ingest|reextract
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX ix_graph_jobs_doc ON graph_extract_jobs(tenant_id, document_id, created_at);
```

### 4.2 与现有表关系

- `document_id` / `chunk_id` 逻辑外键对齐现有 `documents` / `chunks`（SQLite 不强依赖 FK，代码层保证）。  
- **不修改** `chunks.embedding_json`；图谱独立。  
- 文档硬删除：级联删除 mentions；实体若 `mention_count=0` 可惰性清理或定时 GC。  
- ACL：**不在实体上存 ACL**；可见性 = 用户对 `evidence_document_id` / mention 所属文档是否有权。

### 4.3 迁移

- Alembic `0007_knowledge_graph.py`  
- 个人版 SQLite / 团队版 Postgres 同一模型

### 4.4 图数据库适配（预留，不实现）

```
GraphStore Protocol:
  upsert_entity(...)
  upsert_relation(...)
  neighbors(entity_id, depth, limit) -> Subgraph
  search_entities(query, types, limit) -> list[Entity]
```

首版 `SqlGraphStore`；未来 `Neo4jGraphStore` 实现同一 Protocol，Ask 增强层只依赖 Protocol。

---

## 5. 抽取流水线

### 5.1 触发方式

| 触发 | 行为 |
|------|------|
| `POST /v1/graph/extract` | 指定 document_id，创建/入队任务（默认） |
| 可选 `GRAPH_EXTRACT_ON_INGEST=true` | 文档 ingest 成功后自动入队（默认 **关**，避免成本突增） |
| `POST /v1/graph/extract` + `force=true` | 重抽：先软清理该文档 mentions/relations 证据，再抽 |

### 5.2 流程

```
document ready?
  → create GraphExtractJob(queued)
  → for each chunk (按序，可批):
       build prompt (title + chunk text + type/predicate schema)
       gateway_complete(purpose=graph_extract, max_tokens=…)
       parse JSON {entities[], relations[]}
       normalize → upsert entities/aliases
       insert mentions
       upsert/insert relations (+ evidence)
       update job progress
  → job succeeded | failed
  → audit: graph.extract.*
```

### 5.3 Prompt 契约（JSON）

模型必须返回：

```json
{
  "entities": [
    {"name": "…", "type": "organization", "aliases": ["…"]}
  ],
  "relations": [
    {
      "subject": "…",
      "predicate": "works_at",
      "object": "…",
      "evidence": "原文短句"
    }
  ]
}
```

- Local fallback：规则抽取（大写专名/中文《书名》/简单「A 属于 B」正则）→ 低置信度，保证无 Key 也能演示。  
- JSON 解析失败：该 chunk 记 warning，继续下一块（不整单失败，除非 0 成功且全部失败）。

### 5.4 成本与限流

- 复用 `UsageEvent`：`feature=graph_extract`  
- 配额：`GRAPH_EXTRACT_MAX_CHUNKS_PER_DOC`（默认 40）、`GRAPH_EXTRACT_MAX_DOCS_PER_DAY`（默认 20）  
- L3/L4 文档：仅允许 `ollama`/`local` 路由（与 Ask 一致）

### 5.5 幂等

- 同一文档同时只允许一个 `queued|running` job（409）  
- `force` 重抽前删除该 `document_id` 下 mentions，及 `evidence_document_id` 匹配的 relations

---

## 6. ACL 与安全

### 6.1 可见性规则

用户 U 可见实体 E，当且仅当存在至少一条 `entity_mentions`：

- mention.document 对 U 可读（复用现有 ACL：owner / 文档 acl_json / 公开策略）  
- 且文档状态为可读（非 deleted）

用户 U 可见关系 R，当且仅当：

- R.subject 与 R.object **都**对 U 可见，**且**  
- 若存在 `evidence_document_id`，该文档对 U 可读；无证据时默认不可见（防幽灵边）

### 6.2 搜索与邻接

所有 list/get/neighbors/path API **在服务端过滤**，禁止“先查全图再前端藏”。

### 6.3 审计

| 动作 | audit action |
|------|----------------|
| 开始抽取 | `graph.extract.started` |
| 抽取成功/失败 | `graph.extract.succeeded` / `failed` |
| 查询实体 | `graph.entity.viewed`（可选采样，避免刷屏；首版仅写 get by id） |
| 图谱增强 Ask | `agent.ask` metadata 增加 `graph_augmented=true` |

### 6.4 敏感信息

- 实体 `properties` 禁止存原始密钥/PII 大段；抽取 prompt 要求不输出证件号等（软约束）  
- 导出图谱子集走与 audit export 相同的管理员权限

---

## 7. API 设计

统一前缀 `/v1/graph`，鉴权同现有 Bearer。

| Method | Path | 说明 |
|--------|------|------|
| POST | `/v1/graph/extract` | body: `{document_id, force?}` → job |
| GET | `/v1/graph/jobs/{job_id}` | 任务状态 |
| GET | `/v1/graph/jobs?document_id=` | 最近任务 |
| GET | `/v1/graph/entities` | q, type, limit, cursor |
| GET | `/v1/graph/entities/{id}` | 详情 + 别名 + mention 摘要 |
| GET | `/v1/graph/entities/{id}/neighbors` | depth=1..2, limit |
| GET | `/v1/graph/relations` | subject_id?, object_id?, predicate?, limit |
| GET | `/v1/graph/stats` | 实体数/关系数/文档覆盖率（ACL 内） |
| POST | `/v1/ask` 扩展 | `graph_augment?: bool`（默认 false） |

### 7.1 Neighbors 响应形状

```json
{
  "center": {"id": "…", "name": "…", "type": "…"},
  "nodes": [{"id": "…", "name": "…", "type": "…"}],
  "edges": [{"id": "…", "subject_id": "…", "predicate": "…", "object_id": "…", "confidence": 0.8}]
}
```

### 7.2 Ask 图谱增强（KG.3）

1. 从问题中抽候选实体名（LLM 或简单名词匹配 entities 表）  
2. 取 depth=1 邻域（ACL 过滤）  
3. 将「实体 —谓词→ 实体」序列化为短文本上下文  
4. 与原有 chunk 检索结果一并送入 `gateway_complete`  
5. citations 可增加 `kind: graph_relation`（可选）

---

## 8. 前端设计

### 8.1 路由

- `/app/graph`：图谱工作台  
  - 统计条（实体/关系/覆盖文档）  
  - 「从文档抽取」：选文档 + 触发 + job 进度  
  - 实体搜索列表  
  - 实体详情抽屉：别名、提及证据链（跳转文档）、邻接表  
- `/app/ask`：增加开关「图谱增强」  
- 侧栏增加「图谱」入口

### 8.2 可视化（增强，非 MVP）

- 可用轻量 SVG/canvas 画 depth=1 星型图；或接入 `react-force-graph`（需评估包体）  
- MVP **用表格+邻接列表** 即可过门禁

### 8.3 视觉

延续 Atrium KB 既有设计变量与布局，不新开品牌体系。

---

## 9. 配置项

| 变量 | 默认 | 说明 |
|------|------|------|
| `GRAPH_EXTRACT_ON_INGEST` | `false` | ingest 后自动抽 |
| `GRAPH_EXTRACT_MAX_CHUNKS_PER_DOC` | `40` | 单文档上限 |
| `GRAPH_EXTRACT_MAX_DOCS_PER_DAY` | `20` | 租户日配额 |
| `GRAPH_NEIGHBOR_MAX_DEPTH` | `2` | API 硬顶 |
| `GRAPH_ASK_AUGMENT_DEFAULT` | `false` | Ask 默认是否增强 |
| `GRAPH_LOCAL_FALLBACK` | `true` | 无 LLM 时规则抽取 |

---

## 10. 测试策略

| 层级 | 用例 |
|------|------|
| 单元 | normalize/canonical/name_hash；JSON 解析容错；规则 fallback 抽到实体 |
| API | extract → job succeeded；entities list ACL；无权限文档的实体不可见；neighbors 过滤 |
| Ask | `graph_augment=true` 时 prompt/上下文包含关系句（可 mock gateway） |
| 回归 | 现有 search/learn/ask/governance 全绿 |
| 门禁 | `docs/milestones/M5-kg-review.md` + checklist 勾选 |

---

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 幻觉实体/关系 | 要求 evidence；低置信度展示；用户可忽略；后续加人工确认 |
| 成本飙升 | 默认不自动抽；chunk/日配额；L3/L4 本地路由 |
| 实体爆炸同义词 | alias + canonical；同 type 合并；不做激进跨类合并 |
| ACL 泄漏 | 所有读路径强制文档 ACL；无证据边不可见 |
| SQLite 大图性能 | 索引 SPO；neighbors limit；超大规模再迁图库 |
| 与向量检索重复 | 产品上定位互补；默认 Ask 不强制开增强 |

---

## 12. 成功标准（MVP 门禁）

1. 对一份 ready 文档可触发抽取并得到 ≥1 实体（有 LLM 或 local fallback）。  
2. ACL 用户看不到无权文档支撑的实体/边。  
3. `/app/graph` 可搜实体、看邻接与证据。  
4. Ask 可选图谱增强且有测试覆盖。  
5. `pytest` 回归通过；`M5-kg-review.md` 签署。  
6. `/v1/meta.milestone` 更新为含 `Knowledge-Graph` 标识。

---

## 13. 与总计划关系

- 挂在 **M5 探索** 下的「知识图谱」条目。  
- 不阻塞多区域/OpenSearch/多模态；可并行。  
- 实现完成后勾选 `docs/checklist.md` 对应项，并回写 `docs/execution-plan.md` 进度。
