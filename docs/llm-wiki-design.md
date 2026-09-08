# Atrium LLM Wiki — 设计文档

> 理念来源：[Andrej Karpathy — LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)  
> 对照实现参考：Microsoft llmwiki 三层架构、Obsidian LLM Wiki 实践  
> 落地对象：本仓库 **Atrium KB**（企业级个人/团队知识库 Agent）  
> 状态：设计定稿（可评审、可分阶段实施）  
> 关联：[`llm-wiki-comparison.md`](./llm-wiki-comparison.md)（与原方案对照）、[`optimization-plan-full-pipeline.md`](./optimization-plan-full-pipeline.md)、[`knowledge-graph.md`](./knowledge-graph.md)、[`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md)

---

## 0. 一句话定义

**LLM Wiki** = 把「综合」从**查询时临时拼装**前移到**摄入时持久编译**；由 LLM 维护一层可演化、可交叉引用的 Wiki，人负责策展与提问。

**Atrium LLM Wiki** = 在 Atrium 已有 **Raw（文档）+ ACL/RAG + Learn + Graph + Gateway** 之上，增加 **Wiki 编译层 + Schema 契约 + Ingest/Query/Lint 工作流**，使知识**复利积累**，而不是每次问答从零检索。

---

## 1. 理念：为什么不是「再做一个 RAG」

### 1.1 RAG 的结构性局限

| RAG 典型体验 | 问题 |
|--------------|------|
| 每次提问重新检索 chunk | 无积累；跨文档综合每次重算 |
| 答案沉入聊天记录 | 探索不沉淀 |
| 矛盾与交叉引用靠当场推理 | 不稳定、不可浏览 |
| 人要自己维护笔记链接 | 维护成本 > 价值 → 放弃 |

Karpathy 的判断：**痛苦的不是阅读/思考，而是记账**（更新交叉引用、合并矛盾、保持一致性）。LLM 正好擅长、且愿意做这件「零趣味」的维护。

### 1.2 LLM Wiki 的核心命题

```text
Raw（不可变事实） ──编译──▶ Wiki（持久、交叉链接、可演化）
                              ▲
                              │ Schema（约定：页面类型 / 流程 / 规范）
人：策展来源、提问、定方向
LLM：摘要、归档、链接、更新、查矛盾、记日志
```

关键差异：

| | 传统 RAG | LLM Wiki |
|--|----------|----------|
| 综合发生时点 | Query-time | **Ingest-time（为主）** |
| 知识形态 | 临时上下文 | **持久 Markdown/页面制品** |
| 谁维护链接 | 无人 / 人手 | **LLM** |
| 问答结果 | 易丢失 | **可回写 Wiki** |
| 健康度 | 无 | **Lint 周期检修** |

### 1.3 与 Memex 的关系

Vannevar Bush《As We May Think》(1945) 的 Memex：私人、策展、**联想小径**与文档同等重要。Web 走向了公共超链；LLM Wiki 更接近 Memex：**私有、主动策展、连接本身是资产**——缺的「谁来维护」由 LLM 补上。

### 1.4 Atrium 的立场：Wiki 与 RAG **互补，不互斥**

| 层 | 作用 |
|----|------|
| Raw + Chunk + Vector | 证据与精确引用（企业 ACL 红线） |
| Wiki 编译层 | 综合、实体/概念页、矛盾、综述（复利） |
| Graph | 结构化边（可从 Wiki 链接/实体表派生） |
| Ask | 优先读 Wiki；不足时回落 Hybrid RAG；答案可归档 |

**不放弃 RAG**：企业场景要 chunk 级引用与 ACL；Wiki 解决「综合不积累」。  
**不照搬纯文件 Obsidian 单机**：租户、审计、配额、Gateway 仍走 Atrium 服务。

---

## 2. 目标与非目标

### 2.1 目标

1. **三层分离**：Raw / Wiki / Schema，职责清晰。  
2. **三大操作**：Ingest · Query · Lint，契约可执行、可审计。  
3. **页面类型化**：source / entity / concept / synthesis / comparison / overview + index/log。  
4. **与现网融合**：Document=Raw；LearningReport/Graph 可迁移或双写进 Wiki；Ask 可「Wiki 优先」。  
5. **企业约束**：Wiki 页面继承来源文档 ACL 并集（或更严）；全操作审计。  
6. **人机分工**：人策展与审批（可选）；LLM 写 Wiki；Schema 共进化。

### 2.2 非目标（首期）

- 完整 Notion 协作编辑器  
- 纯文件系统 Obsidian 插件替代产品 Web  
- 废除向量检索  
- 自动全网爬取补洞（Lint 可「建议」来源，不擅自外采入 Raw）  
- 跨租户联邦 Wiki  

---

## 3. 三层架构（Atrium 映射）

```text
┌─────────────────────────────────────────────────────────────┐
│  Schema（约定层）                                             │
│  wiki_schema 表 / 租户级 WIKI.md 文本                         │
│  页面类型 · frontmatter · 命名 · ingest/query/lint 流程       │
└───────────────────────────┬─────────────────────────────────┘
                            │ 约束
┌───────────────────────────▼─────────────────────────────────┐
│  Wiki（编译层，LLM 拥有写权限）                                 │
│  wiki_pages + wiki_links + wiki_index_snapshot + wiki_log    │
│  类型：source / entity / concept / synthesis / …             │
│  特殊页：index、log、overview                                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ 溯源
┌───────────────────────────▼─────────────────────────────────┐
│  Raw（事实层，不可变）                                         │
│  documents / versions / objects / chunks                     │
│  人上传或连接器导入；LLM 只读                                  │
└─────────────────────────────────────────────────────────────┘
```

| Karpathy 层 | Atrium 落地 |
|-------------|-------------|
| `raw/` | `documents` + 对象存储；版本不可原地篡改（新 version） |
| `wiki/` | `wiki_pages`（正文 Markdown）+ 可选导出为租户 `wiki/` 目录 |
| `AGENTS.md` / Schema | 租户 `WikiSchema` 记录 + 内置默认 Schema 模板 |

---

## 4. 领域模型

### 4.1 页面类型（受控词表）

| type | 含义 | 典型触发 |
|------|------|----------|
| `source` | 单篇 Raw 的摘要页（主张、引用、开放问题） | Ingest 必出 |
| `entity` | 人/组织/产品/项目… | 抽取与合并 |
| `concept` | 概念/方法/理论 | 抽取与合并 |
| `synthesis` | 主题综述 / 保存的优质问答 | Query 归档、Lint 建议 |
| `comparison` | 多实体/概念对照 | Query 归档 |
| `overview` | 全局活综述 | 定期 Lint / 手动刷新 |
| `index` | 目录花名册（逻辑上可物化） | 每次 Ingest 更新 |
| `log` | 追加-only 操作日志 | 每次操作追加 |

### 4.2 表结构草案

```sql
-- 租户 Wiki Schema（自然语言 + 结构化覆盖）
CREATE TABLE wiki_schemas (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL UNIQUE,
  schema_md TEXT NOT NULL,           -- 完整约定文本（类 AGENTS.md）
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE wiki_pages (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  workspace_id TEXT,                 -- 可选：空间级 Wiki；空=租户级
  slug TEXT NOT NULL,                -- kebab-case 或 TitleCase 规则见 Schema
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  summary_one_liner TEXT NOT NULL DEFAULT '',
  body_md TEXT NOT NULL,            -- 含 YAML frontmatter 或分离存储
  frontmatter_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active', -- active|archived
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id, workspace_id, slug)
);

CREATE TABLE wiki_page_sources (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  page_id TEXT NOT NULL,
  document_id TEXT NOT NULL,        -- Raw 溯源
  chunk_ids_json TEXT DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE wiki_links (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  from_page_id TEXT NOT NULL,
  to_page_id TEXT NOT NULL,         -- 解析后的目标；悬空链单独表或 status
  raw_label TEXT NOT NULL,         -- [[Label]]
  created_at TEXT NOT NULL
);

CREATE TABLE wiki_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  kind TEXT NOT NULL,              -- ingest|query_archive|lint|recompile
  status TEXT NOT NULL,
  document_id TEXT,                 -- ingest 时
  request_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE wiki_log_entries (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  verb TEXT NOT NULL,              -- ingest|query|lint|schema_update
  subject TEXT NOT NULL,
  detail_md TEXT NOT NULL,
  actor_id TEXT,
  created_at TEXT NOT NULL
);
```

### 4.3 Frontmatter 最小约定

```yaml
---
title: 星河实验室
type: entity
tags: [组织, 研究]
sources: [doc-uuid-…]
related: [nebula-protocol, 张三]
contradictions: []
last_updated: 2026-09-08
confidence: medium
---
```

### 4.4 与现有对象关系

| 现有 | Wiki 关系 |
|------|-----------|
| `Document` | Raw；Ingest 输入 |
| `LearningReport` | 可投影为 `source` 初稿或并入 body 的「学习摘要」节 |
| `Entity` / `Relation`（KG） | 与 `entity`/`concept` 页双向同步策略见 §7 |
| `Ask` 会话 | 优质答案 → `synthesis` / `comparison` |
| `AuditEvent` | Wiki 操作另记 `wiki.*` action |

---

## 5. 三大操作（完整契约）

### 5.1 Ingest（摄入编译）

**触发：** 文档 indexed 后手动 / `WIKI_INGEST_ON_READY=true` / API `POST /v1/wiki/ingest`。

**流程：**

```text
1. 校验 Raw 可读（ACL）
2. 读 Schema
3. Gateway 完成：
   - 写/更新 source 页
   - upsert 相关 entity/concept（合并同名）
   - 更新交叉链接与 contradictions
   - 刷新 index 条目
   - 可选轻量刷新 overview 相关段落
4. 追加 wiki_log：## [ISO] ingest | {title}
5. 审计 wiki.ingest.succeeded
6. （可选）同步 KG Entity/Relation
```

**人机协同模式（Schema 可配）：**

| 模式 | 行为 |
|------|------|
| `supervised` | 生成 diff 提案 → 人确认后提交（企业默认可开） |
| `auto` | 个人版默认；直接写入 |
| `batch` | 多文档队列；降低交互 |

**单源触达页数：** 目标 5–15 页/源（与 Karpathy 经验一致）；用配额限制。

### 5.2 Query（面向 Wiki 的问答）

**流程：**

```text
1. 读 index（及 overview 摘要）缩小候选
2. 拉取相关 wiki_pages（+ 必要时 Hybrid RAG chunks）
3. Gateway 作答，引用优先 Wiki 节选 + Raw chunk
4. 若用户勾选「归档到 Wiki」或答案评分高：
   → 创建 synthesis/comparison 页并回链
5. 追加 log：query | {question_slug}
```

**与现有 Ask 合流：**

| Ask 模式 | 行为 |
|----------|------|
| `retrieve=chunks` | 现网 Hybrid/向量（OPT 后） |
| `retrieve=wiki` | Wiki 优先 |
| `retrieve=auto` | index 命中强 → Wiki；否则 chunks；可融合 |
| `graph_augment` | 保留；Wiki 链接图可替代/补充 SQL KG |

### 5.3 Lint（健康检修）

**周期：** 手动 `POST /v1/wiki/lint` / 日更 cron。

**检查项：**

| 规则 | 说明 |
|------|------|
| contradictions | 页间冲突未归档 |
| stale | 被更新 Raw 否定的旧主张 |
| orphans | 无入链页面 |
| missing_concept | 正文提到但无独立 concept 页 |
| dangling_links | `[[x]]` 无目标 |
| acl_drift | 来源文档 ACL 变更导致页过曝风险 |
| gap_hints | 建议补充的来源类型（不自动外采） |

**产出：** Lint 报告页或 `result_json`；可选自动修链（Schema 开关）。

---

## 6. Schema 设计（租户「大脑」）

### 6.1 默认 Schema 七段（初始化模板）

1. 页面类型与目录约定  
2. Frontmatter 字段  
3. 命名规范（slug）  
4. 交叉引用与矛盾处理  
5. Ingest 工作流  
6. Query 工作流（含归档规则）  
7. Lint 规则与严重级别  

### 6.2 共进化

- 租户 Admin 可编辑 `schema_md`  
- Lint/使用中发现模式 → 建议 Schema PR（提案，不静默改）  
- Schema 变更升 `version`，旧页逐步符合新规范  

### 6.3 企业扩展

- 审批：`supervised` Ingest 的 diff 走 workspace `publish_mode=approval`  
- 敏感级：L3/L4 Raw 仅允许本地/Ollama 路由写 Wiki（复用 policy）  

---

## 7. Wiki ↔ 知识图谱 ↔ Learn

```text
Ingest
  ├─▶ wiki source/entity/concept 页
  ├─▶（可选）LearningReport 字段回填 / 或 Learn 仅作 Raw 侧摘要
  └─▶（可选）KG entities/relations 从 wiki frontmatter.related 与正文链接生成
```

| 策略 | 说明 |
|------|------|
| **Wiki-primary** | Wiki 为综合真相；KG 为可查询边索引 |
| **KG-primary** | 保留现 KG 抽取；Wiki 页由实体表生成（弱综合） |
| **推荐** | **Wiki-primary + KG 投影**：问答综合走 Wiki；邻居/统计走 KG |

Learn：个人版可把 Learn 视为 Ingest 的快速路径；完整 Wiki Ingest 覆盖并超越单文档摘要。

---

## 8. ACL 与安全

### 8.1 可见性

用户可见 Wiki 页 **当且仅当**：

- 对该页所有 `wiki_page_sources.document_id` 均有读权限；**或**  
- Schema 配置 `acl_mode=any_source`（较弱，仅个人租户建议）且至少一源可读。

**默认 `acl_mode=all_sources`（企业）**，防止「半源综合」泄漏。

### 8.2 写权限

- 仅 LLM 作业身份 / 系统 Worker 写 Wiki 正文  
- 人通过「批准提案」间接写；禁止绕过审计的直写 API（Admin 可 break-glass）  

### 8.3 审计

`wiki.ingest.*` / `wiki.query` / `wiki.lint.*` / `wiki.schema.updated` / `wiki.page.viewed`（采样）。

---

## 9. API 草案

| Method | Path | 说明 |
|--------|------|------|
| GET | `/v1/wiki/schema` | 读 Schema |
| PUT | `/v1/wiki/schema` | Admin 更新 |
| POST | `/v1/wiki/ingest` | `{document_id, mode?}` |
| GET | `/v1/wiki/jobs/{id}` | 任务状态 |
| GET | `/v1/wiki/pages` | 列表/按 type/q |
| GET | `/v1/wiki/pages/{slug}` | 详情 |
| GET | `/v1/wiki/index` | 目录 |
| GET | `/v1/wiki/log` | 最近日志 |
| POST | `/v1/wiki/lint` | 触发检修 |
| POST | `/v1/ask` | 扩展 `retrieve=wiki\|chunks\|auto`，`archive_to_wiki?` |

---

## 10. 前端（产品映射）

| 入口 | 能力 |
|------|------|
| `/app/wiki` | 浏览 index、页面、图谱式链接（可复用 Graph 邻接 UI） |
| `/app` 文库 | 文档行增加「编译进 Wiki」 |
| `/app/ask` | 检索模式 +「归档到 Wiki」 |
| `/app/governance` | Schema 编辑、Lint 报告、监督模式开关 |
| 侧栏 | 「Wiki」与「知识图谱」并存：Wiki=可读综合；Graph=结构边 |

视觉：延续 Atrium「日中庭」设计语言；Wiki 阅读区偏编辑器排版（正文 Literata）。

---

## 11. 完整链路（端到端）

```text
人策展 Raw
  │ 上传 / 连接器
  ▼
Parse → Chunk →（OPT）Embed → 向量库
  │
  ├─▶ Learn（可选快速摘要）
  │
  └─▶ Wiki Ingest（Schema 约束）
        ├─ source / entity / concept 页
        ├─ links / contradictions
        ├─ index + log
        └─（投影）KG
              │
              ▼
        Query：Wiki 优先 ± Hybrid RAG ± Graph augment
              │
              ├─▶ 流式回答 + 引用（Raw 可点回）
              └─▶ 优质答案归档 synthesis
                    │
                    ▼
              Lint 周期：修链、标旧、找缺口
                    │
                    ▼
              Schema 共进化 ← 人批准
```

这与教程式「仅向量检索」和纯文件「仅 Obsidian」都不同：**服务化、可 ACL、可审计的 LLM Wiki**。

---

## 12. 分阶段实施计划（WIKI.*）

| 阶段 | 内容 | 依赖 | 出口 |
|------|------|------|------|
| **WIKI.0** | 本文设计 + Schema 默认模板 | — | 评审通过 |
| **WIKI.1** | 表结构 + Schema API + 默认模板种子 | Real-LLM | 可读写 Schema |
| **WIKI.2** | Ingest job：source 页 + index/log | WIKI.1, Gateway | 一文一 source 页 |
| **WIKI.3** | entity/concept 合并更新 + links | WIKI.2, 可复用 graph 抽取 | 多页触达 |
| **WIKI.4** | Ask `retrieve=wiki\|auto` + 归档 | WIKI.3 | 问答可沉淀 |
| **WIKI.5** | Lint + `/app/wiki` 浏览 | WIKI.4 | 健康报告 + UI |
| **WIKI.6** | supervised 审批 + KG 投影 + 导出 md | WIKI.5, M4 | 企业可开 |

建议与 OPT.1–3（真向量/混合/多格式）**并行**：Wiki 编译提升综合；OPT 提升证据召回。

---

## 13. 配置项

| 变量 | 默认 | 说明 |
|------|------|------|
| `WIKI_INGEST_ON_READY` | `false` | 入库后自动编译 |
| `WIKI_INGEST_MODE` | `auto` | auto\|supervised\|batch |
| `WIKI_ACL_MODE` | `all_sources` | all_sources\|any_source |
| `WIKI_MAX_PAGES_PER_INGEST` | `20` | 单源触达上限 |
| `WIKI_QUERY_DEFAULT` | `auto` | ask 默认 retrieve |
| `WIKI_LINT_CRON` | 空 | 定时 Lint |

---

## 14. 测试策略

| 层 | 用例 |
|----|------|
| 单元 | frontmatter 解析；slug 规范；链接抽取 |
| API | ingest → source+index；ACL 负向；lint 检出悬空链 |
| Ask | retrieve=wiki 引用 Wiki；archive 产生 synthesis |
| 回归 | 现有 search/learn/ask/graph/governance 全绿 |

---

## 15. 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 胡写 Wiki | 强制溯源 `sources`；矛盾显式节；supervised 模式 |
| Token/成本暴涨 | 页数上限、增量更新、日配额 |
| 与 Learn/Graph 重复 | 明确 Wiki-primary；Learn 降级为可选；KG 投影 |
| 大规模 index 扫不动 | 中期接 OPT 混合检索扫 Wiki；远期专用 wiki search |
| 人想手改 Wiki | 只读 UI +「建议修改」工单；或 fork 私人 annotation 层（后期） |

---

## 16. 成功标准

1. 对一篇 Raw 执行 Ingest 后，存在 source 页 + index 条目 + log。  
2. 第二次相关文档 Ingest 会**更新**已有 entity/concept，而非只堆 source。  
3. Ask（wiki/auto）能基于编译页作答，并可归档 synthesis。  
4. Lint 能报告至少一类问题（孤儿/悬空/矛盾）。  
5. ACL：无权限 Raw 支撑的综合页不可见。  
6. `/v1/meta` 可增加能力位 `wiki: true`（或 milestone 备注）。

---

## 17. 与 OPT / KG 路线图关系

```text
OPT.1–3  真检索与多格式     ← 补「检得准、吃得下」
WIKI.0–6 编译与复利         ← 补「综合会积累」
KG       结构边与邻域增强   ← 补「可计算关系」
Gateway  DeepSeek 等       ← 补「写 Wiki 的笔」
```

三者叠加，才接近 Karpathy 愿景的**产品化、企业化**形态。

---

## 18. 附录 A — 默认页面骨架示例（source）

```markdown
---
title: 星河实验室周报-2026-09
type: source
sources: ["…document_id…"]
last_updated: 2026-09-08
---

# 星河实验室周报-2026-09

## 摘要
…

## 关键主张
1. … （证据：chunk …）

## 实体与概念
- [[星河实验室]] · [[Nebula Protocol]]

## 矛盾与待核
- …

## 开放问题
- …

## Connections
- [[概述]] · [[星河实验室]]
```

## 附录 B — 理念对照表（给评审）

| Karpathy 原话要点 | Atrium 设计响应 |
|-------------------|-----------------|
| Wiki 是持久复利制品 | `wiki_pages` 持久存储 + 版本/日志 |
| LLM 拥有 Wiki 写入 | Worker/Gateway 写；人只读/批准 |
| Schema 使 LLM 守纪律 | `wiki_schemas.schema_md` |
| Ingest 触达多页 | job + max pages |
| Query 答案可归档 | `archive_to_wiki` |
| Lint 健康检查 | `/v1/wiki/lint` |
| index + log | 物化 API + 表 |
| Obsidian 作 IDE | Web `/app/wiki`；可导出 md 给 Obsidian |
| 不绑死实现细节 | Provider 化存储；个人可导出纯 md |

## 附录 C — 参考文献

1. Andrej Karpathy, *LLM Wiki* gist  
2. Microsoft `llmwiki` ARCHITECTURE（三层、index/log、typed pages）  
3. 社区实践：Obsidian LLM Wiki、研究 Wiki 页类型扩展  
4. 本仓库：`knowledge-graph.md`、`optimization-plan-full-pipeline.md`
