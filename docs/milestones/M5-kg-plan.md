# M5 知识图谱 — 执行计划

> 对应设计：[`docs/knowledge-graph.md`](../knowledge-graph.md)  
> 依赖 tip：`cursor/real-llm-gateway-4365`  
> 本分支（KG.0 设计）：`cursor/m5-knowledge-graph-plan-4365`  
> 实现分支（建议）：`cursor/m5-knowledge-graph-4365`

---

## 阶段总览

| 阶段 | 名称 | 交付物 | 门禁 |
|------|------|--------|------|
| **KG.0** | 详细设计与计划 | 本文 + `knowledge-graph.md` | 设计评审通过即可开工实现 |
| **KG.1** | 存储 + 抽取骨架 | migration `0007`、models、SqlGraphStore、extract job、规则 fallback | API 可抽到实体；单测绿 |
| **KG.2** | 查询 API + ACL | entities/relations/neighbors/stats + 审计 | ACL 负向用例通过 |
| **KG.3** | Ask 图谱增强 | `graph_augment` + 上下文拼装 | Ask 测试覆盖增强路径 |
| **KG.4** | 前端工作台 | `/app/graph` + Ask 开关 + 侧栏 | 手动冒烟 + 截图/录屏 |
| **KG.5** | 门禁与文档 | review、checklist、meta milestone | CI 全绿；PR 可合并进 tip 链 |

各阶段 **review + 回归** 通过后再进入下一阶段（与既有 E/M 门禁一致）。

---

## KG.0 — 详细设计（本 PR）

- [x] 领域模型、表结构、ACL、API、前端、配置、风险  
- [x] 执行计划与任务拆分  
- [ ] 人工确认设计方向后进入 KG.1（默认已按「SQL 优先 + 列表 UI + RAG 增强」锁定）

**产出路径**

- `docs/knowledge-graph.md`
- `docs/milestones/M5-kg-plan.md`（本文件）
- checklist / execution-plan 指针更新

---

## KG.1 — 存储与抽取骨架

### 任务

1. Alembic `0007_knowledge_graph.py`：entities / aliases / mentions / relations / graph_extract_jobs  
2. SQLAlchemy models + `packages/shared/graph/`（或 `graph_store.py` + `graph_extract.py`）  
3. `normalize_entity_name` / `name_hash` / 受控 type&predicate  
4. `GraphExtractJob` 状态机；`POST /v1/graph/extract`、`GET /v1/graph/jobs/{id}`  
5. 抽取：LLM JSON（gateway `purpose=graph_extract`）+ **local 规则 fallback**  
6. Usage：`feature=graph_extract`；配额 env  
7. 单元测试：normalize、fallback 抽取、job 成功路径（可用 sync 内联执行，对齐个人版 ingest）

### 验收

- 对 fixture 文档抽取后 DB 中有 entity + mention  
- 无 API Key 时 fallback 仍能产出至少 1 个实体  
- 不影响现有 ingest/search

### 预估改动面

- `packages/shared/` 新模块  
- `apps/api` 新 router  
- `apps/workers` 可选挂钩（默认同进程执行）  
- `tests/` 新增

---

## KG.2 — 查询 API 与 ACL

### 任务

1. `GET /v1/graph/entities`（q/type/limit）— 仅返回当前用户可见  
2. `GET /v1/graph/entities/{id}` + mentions 摘要  
3. `GET /v1/graph/entities/{id}/neighbors`（depth≤2）  
4. `GET /v1/graph/relations`、`GET /v1/graph/stats`  
5. 文档删除/无权：实体与边不可见的负向测试  
6. Audit：`graph.extract.*`；get-by-id 可选 `graph.entity.viewed`

### 验收

- 双用户 ACL fixture：A 可见、B 不可见同一实体支撑文档时 B list 为空或不含该实体  
- neighbors 不泄露无权边

---

## KG.3 — Ask 图谱增强

### 任务

1. Ask 请求体增加 `graph_augment: bool`  
2. 实体链接（名称匹配 / 轻量 LLM）→ neighbors → 序列化关系上下文  
3. 与 chunk 检索结果一并送入 gateway  
4. metadata / audit 标记 `graph_augmented`  
5. 测试：augment=true 时调用链包含 graph context（mock LLM）

### 验收

- 默认 `false` 行为与现网一致  
- `true` 时回答可引用关系句（或至少 prompt 含关系上下文）

---

## KG.4 — 前端

### 任务

1. 侧栏「图谱」→ `/app/graph`  
2. 统计 + 文档选择抽取 + job 轮询  
3. 实体搜索 / 详情 / 邻接表 / 证据跳转文档  
4. Ask 页「图谱增强」开关  
5. 治理页无需大改（复用已有 LLM 密钥配置）

### 验收

- 本地 `make run-api` + `make run-web` 可完成：抽 → 搜 → 看邻接 → Ask 增强一轮

---

## KG.5 — 门禁收尾

### 任务

1. `docs/milestones/M5-kg-review.md`（对照成功标准逐条）  
2. `docs/checklist.md` 勾选「知识图谱」  
3. `docs/execution-plan.md` 进度回写  
4. `/v1/meta` milestone 含 `Knowledge-Graph`  
5. CI / 全量 pytest  
6. Draft PR：`cursor/m5-knowledge-graph-4365` → base `cursor/real-llm-gateway-4365`（或当时 tip）

---

## 建议实现顺序（单 PR 链也可拆 PR）

```
KG.0 (本分支，仅文档)
  → KG.1+KG.2 可同一实现 PR 前半
  → KG.3
  → KG.4
  → KG.5 review
```

若需更小 PR：`m5-kg-schema-extract` → `m5-kg-query-acl` → `m5-kg-ask-ui`。

---

## 明确不做（本里程碑）

- Neo4j/Memgraph 生产接入（仅 Protocol 预留）  
- 力导向大画布标配  
- ingest 默认自动全量抽取  
- 跨租户图谱、多模态实体

---

## 下一步行动

设计 PR 合并或确认后，从 tip 拉出 `cursor/m5-knowledge-graph-4365`，按 KG.1 开工：migration + extract API + fallback + 首批测试。
