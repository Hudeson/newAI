# 个人知识库 Agent — 详细设计文档与实施计划

> 目标：搭建一个**可长期演进**的个人知识库 Agent，支持**上传文档**、自动**学习总结**，再基于私有资料检索问答、整理笔记、主动发现关联。

---

## 1. 项目愿景

### 1.1 一句话定义

**个人知识库 Agent** = 文档上传与摄入 + 自我学习总结 + 私有 RAG 问答 + 工具化 Agent。

它不是普通 ChatGPT 对话框，而是：

- **上传即入库**：Web/API 上传 PDF、Word、Markdown、TXT 等，异步解析索引
- **上传即学习**：入库后自动生成摘要、大纲、关键要点、标签与关联笔记
- 只基于**你自己的资料**作答，并标明出处
- 能**持续自我迭代**：新文档与旧知识对照，提炼增量洞察、知识卡片
- 可本地或私有部署，数据主权归你

### 1.2 成功标准（Definition of Done）

| 维度 | 达标表现 |
|------|----------|
| 上传 | Web 拖拽/多文件上传；进度可见；失败可重试；支持 md/txt/pdf/docx |
| 学习总结 | 每篇入库后自动产出：摘要、大纲、要点列表、建议标签；可人工修订 |
| 摄入 | 上传 + 目录同步 + URL；增量更新无明显重复 |
| 检索 | 问答返回相关原文片段 + 来源路径；Top-K 命中率主观可用 |
| 对话 | 多轮追问不丢上下文；可要求「只根据某文件夹/某次上传回答」 |
| Agent | 至少含：搜索、单篇总结、批量复习总结、对比、打标签 |
| 可维护 | 一键启动；配置与密钥外置；日志可排查上传/学习/检索失败 |
| 隐私 | 默认本地向量库；云端 LLM 可选，敏感库可切本地模型 |

### 1.3 非目标（本期不做）

- 不做企业级多租户 / 权限系统
- 不做完整 Notion 替代编辑器
- 不做自动爬取全网（仅用户主动导入的来源）
- 不做端侧 App（先 Web + CLI）

---

## 2. 用户场景与核心用例

### 2.1 典型人物

| 角色 | 诉求 |
|------|------|
| 个人学习者 | 「把我半年读过的文章串起来，回答这个问题」 |
| 独立开发者 | 「根据我的技术笔记解释这段架构为什么这么设计」 |
| 研究者 / 写作者 | 「找出所有提到 X 概念的笔记并生成对比表」 |

### 2.2 核心用例（P0）

1. **上传文档**：Web 拖拽/多选上传（md/txt/pdf/docx）；显示解析与学习进度
2. **自我学习总结（单篇）**：上传完成后自动生成摘要、大纲、关键要点、建议标签
3. **自然语言问答**：提问 → 检索 → 带引用回答（优先结合已学习摘要 + 原文 chunk）
4. **限定范围问答**：只查某次上传、某个主题、标签或文件夹
5. **批量 / 主题复习总结**：对一批文档或某主题做对照总结与知识卡片
6. **相关笔记推荐**：打开一篇时推荐「你可能还想看」

### 2.3 进阶用例（P1）

7. **增量学习**：新文档 vs 旧知识，输出「新增了什么 / 修正了什么 / 仍有矛盾」
8. **知识整理 Agent**：合并重复笔记、生成主题地图、提醒知识缺口
9. **定期回顾**：每日/每周「新学到的内容」摘要推送
10. **写作助手**：基于知识库起草文章，并强制引用库内来源
11. **多模态**：图片 OCR、音视频转写后入库并学习总结

---

## 3. 系统架构

### 3.1 逻辑架构

```
┌─────────────────────────────────────────────────────────────┐
│                        交互层                                │
│  上传区 · 学习报告 · 对话 UI · CLI · API                      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     Agent 编排层                              │
│  Planner / Tool Router · Memory · Citation Guard · Policies  │
└───────┬─────────────────┬─────────────────┬─────────────────┘
        │                 │                 │
┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
│  RAG 检索服务  │ │  学习总结引擎  │ │  LLM 推理服务  │
│ hybrid search │ │ summary/card  │ │ local / cloud │
└───────┬───────┘ └───────┬───────┘ └───────────────┘
        │                 │
┌───────▼─────────────────▼───────────────────────────────────┐
│                       数据层                                  │
│  上传对象存储 · 元数据 DB · 向量索引 · 学习产物 · 任务队列      │
└─────────────────────────────────────────────────────────────┘
                            ▲
┌───────────────────────────┴─────────────────────────────────┐
│                 上传 / 摄入 + 学习流水线                       │
│  Upload → Parser → Chunker → Embedder → Indexer              │
│                         └→ Learner（摘要/要点/标签/关联）      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 关键数据流

**上传摄入**

```
用户上传文件 → 校验类型/大小 → 落入 data/uploads/
  → 创建 Source(status=pending) → 入队 ingest job
  → Parser → Chunker → Embedding → 向量库 + 元数据
  → Source(status=indexed) → 触发 learn job
```

**自我学习总结**

```
Document indexed → Learner 读取全文/分章
  → 生成 LearningArtifact：
       summary（摘要） / outline（大纲） / key_points（要点）
       / suggested_tags / related_doc_ids / open_questions
  → 写入 DB；可选再向量化「知识卡片」便于日后检索
  → UI 展示「学习报告」，用户可编辑确认
```

**增量学习（P1）**

```
新文档学习完成 → 检索库内相似旧文档
  → 对比：新增观点 / 冲突观点 / 可合并主题
  → 生成 Insight 记录，供周回顾与 Agent 使用
```

**问答**

```
用户问题 → （可选）查询改写 / HyDE
  → 混合检索(原文 chunk + 学习卡片) → 重排序(Rerank)
  → 组装 Prompt（问题 + 证据 + 已有摘要 + 引用约束）
  → LLM 生成 → 校验引用 → 返回答案 + sources
```

**Agent 任务**

```
用户意图 → Agent 选择工具序列
  → upload_status / search_kb / learn_summarize / compare ...
  → 聚合结果 → 最终回答
```

### 3.3 目录建议（实现阶段落地）

```
/
├── data/                    # 本地运行时数据（gitignore）
│   ├── uploads/             # Web/API 上传原文件
│   ├── raw/                 # 目录同步镜像或软链
│   ├── processed/           # 解析后文本
│   ├── learning/            # 学习产物（摘要/卡片 markdown 备份）
│   └── indexes/             # 向量库持久化
├── packages/
│   ├── ingest/              # 解析、切块、embedding
│   ├── learning/            # 自我学习总结引擎
│   ├── retrieval/           # 检索、rerank、引用组装
│   ├── agent/               # 工具定义与编排
│   └── shared/              # 类型、配置、日志
├── apps/
│   ├── api/                 # FastAPI：上传、学习、问答 API
│   ├── web/                 # 上传区 + 学习报告 + 对话 UI
│   └── cli/                 # 摄入、重建索引、运维命令
├── docs/
│   └── personal-knowledge-base-agent.md
├── docker-compose.yml
└── README.md
```

> 注：上表为逻辑分组；实现时可先扁平单包，再拆 packages。

---

## 4. 技术选型建议

> 原则：**先跑通、可替换、隐私可控**。下列为推荐默认栈，括号内为可替换项。

### 4.1 推荐默认栈（个人 / 单机优先）

| 层级 | 推荐 | 备选 | 说明 |
|------|------|------|------|
| 语言 | Python 3.11+ | TypeScript | RAG/生态成熟，先 Python |
| API | FastAPI | Hono / Nest | 异步友好，OpenAPI 自动生成 |
| 前端 | Next.js + 简洁对话 UI | Streamlit（MVP） | MVP 可用 Streamlit 加速 |
| 向量库 | Qdrant（本地 Docker） | Chroma / LanceDB / pgvector | Qdrant 过滤与混合检索强 |
| 元数据 | SQLite → PostgreSQL | — | 先 SQLite，规模上来再迁 |
| Embedding | `bge-m3` / `text-embedding-3` | nomic / voyage | 中英混合优先 bge-m3 |
| Rerank | `bge-reranker-v2-m3` | Cohere Rerank | 显著提升准确率 |
| LLM | 可配置：DeepSeek / OpenAI / Claude / Ollama | — | 通过统一 Provider 抽象 |
| 编排 | LangGraph 或自研轻量 Agent | LlamaIndex Workflow | 工具少时自研更可控 |
| 任务队列 | RQ / Celery / 进程内队列 | — | 摄入异步化 |
| 观测 | structlog + 简单 dashboard | Langfuse | 追踪检索质量 |

### 4.2 选型决策树

```
需要完全离线？
  ├─ 是 → Ollama/本地 vLLM + 本地 embedding + Qdrant/LanceDB
  └─ 否 → 云端 LLM +（本地或云端）embedding；原文仍建议本地存

资料量级？
  ├─ < 1万文档 / < 50万 chunk → SQLite + Qdrant 单机足够
  └─ 更大 → Postgres + 独立向量服务 + 异步 worker

中文为主？
  └─ Embedding/Rerank 优先选中英双语模型（如 bge-m3 系列）
```

### 4.3 配置外置（示例）

```yaml
# config.example.yaml
llm:
  provider: openai_compatible
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: deepseek-chat

embedding:
  provider: local  # or openai_compatible
  model: BAAI/bge-m3

vector_store:
  type: qdrant
  url: http://localhost:6333
  collection: personal_kb

ingest:
  watch_dirs:
    - ~/Notes
  chunk_size: 800
  chunk_overlap: 120
  upload:
    max_file_mb: 50
    max_batch_files: 20
    allowed_ext: [md, txt, pdf, docx, html]

learning:
  auto_on_ingest: true          # 索引完成后自动学习总结
  outputs: [summary, outline, key_points, tags, related]
  write_knowledge_cards: true   # 将要点写成可检索知识卡片
  incremental_compare: true     # 与旧文档做增量对照（P1）
```

---

## 5. 数据模型

### 5.1 核心实体

**UploadJob（上传任务）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 |
| filename | string | 原始文件名 |
| stored_path | string | `data/uploads/...` |
| content_type | string | MIME |
| size_bytes | int | |
| status | enum | uploaded / ingesting / learning / ready / failed |
| progress | float | 0–1，供 UI 进度条 |
| error | text | 失败原因 |
| source_id | uuid? | 关联 Source |
| created_at | datetime | |

**Source（来源）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 |
| type | enum | upload / file / url / note / chat_export |
| uri | string | 路径或 URL |
| title | string | 标题 |
| hash | string | 内容哈希，用于增量更新 |
| mtime | datetime | 来源修改时间 |
| status | enum | pending / indexed / learning / ready / failed |
| meta | json | 作者、标签、自定义字段 |

**Document（逻辑文档）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 |
| source_id | uuid | 外键 |
| title | string | |
| plain_text_path | string | 解析后文本位置 |
| language | string | zh / en / mixed |
| word_count | int | |
| summary | text | 最新确认摘要（可来自学习产物） |
| tags | string[] | |
| learn_status | enum | none / pending / done / failed |

**Chunk（检索单元）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 / 向量点 ID |
| document_id | uuid | |
| ordinal | int | 块序号 |
| content | text | 块文本 |
| token_count | int | |
| heading_path | string | 如 `架构/数据层` |
| embedding | vector | 存向量库 |
| sparse_vector | optional | 混合检索用 |

**LearningArtifact（学习产物）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 |
| document_id | uuid | |
| version | int | 同一文档可多次重学 |
| summary | text | 一段话摘要 |
| outline | json/text | 层级大纲 |
| key_points | json | `[{point, evidence_chunk_ids}]` |
| suggested_tags | string[] | |
| open_questions | json | 文档未解答/待深入问题 |
| related_doc_ids | uuid[] | 相似旧文档 |
| card_ids | uuid[] | 生成的知识卡片 |
| model | string | 所用 LLM |
| created_at | datetime | |
| confirmed | bool | 用户是否确认/修订过 |

**KnowledgeCard（知识卡片，可选但推荐）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | |
| document_id | uuid | 来源文档 |
| title | string | 概念/结论标题 |
| body | text | 1–3 句可复用知识点 |
| embedding | vector | 参与检索 |
| tags | string[] | |

**Insight（增量学习洞察，P1）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | |
| new_document_id | uuid | |
| old_document_id | uuid | |
| type | enum | addition / conflict / merge_candidate |
| detail | text | 说明 |
| evidence | json | 双方引用 |

**Conversation / Message**

标准多轮消息表，附带 `citations[]`（chunk_id + quote）。

**AgentRun（可选）**

记录工具调用轨迹，便于调试与评测。

### 5.2 切块策略（关键）

1. 优先按标题 / 段落语义切分，再按 token 上限二次切分
2. `chunk_size` 建议 500–1000 tokens（中文按字近似亦可）
3. `overlap` 10%–15%，避免答案跨块丢失
4. 每个 chunk 附带：文件路径、标题路径、前后文指针
5. 代码块、表格尽量整块保留，不强行切断

---

## 6. 文档上传与自我学习总结（详细设计）

### 6.1 上传能力

**支持格式（MVP）**

| 格式 | 处理方式 |
|------|----------|
| `.md` / `.txt` / `.markdown` | 直接解码文本 |
| `.pdf` | 文本抽取（扫描件后续 OCR） |
| `.docx` | 抽取段落与标题 |
| `.html` | 正文抽取（可选） |

**API 草图**

```http
POST /api/uploads                  # multipart 单文件或多文件
GET  /api/uploads/{id}             # 状态：uploaded→ingesting→learning→ready
GET  /api/uploads                  # 列表
POST /api/uploads/{id}/retry       # 失败重试
DELETE /api/uploads/{id}           # 删除上传及关联索引（需确认）

GET  /api/documents/{id}/learning  # 获取学习报告
POST /api/documents/{id}/relearn   # 强制重新学习总结
PATCH /api/documents/{id}/learning # 用户修订摘要/标签并确认
```

**前端交互要点**

1. 知识库页顶部：**拖拽上传区** + 文件选择；支持批量
2. 列表展示每条：文件名、大小、状态徽章、进度条
3. `ready` 后可一键打开「学习报告」或「基于此文档提问」
4. 上传中可继续聊天；学习完成后轻提示「《xxx》已学完」

**限制与安全**

- 单文件大小上限（默认 50MB）、批量数量上限
- 扩展名白名单；服务端再验 MIME/魔数
- 文件名消毒；禁止路径穿越
- 上传目录与处理目录隔离；病毒扫描可选（后期）

### 6.2 自我学习总结引擎

上传/摄入成功后自动执行（`learning.auto_on_ingest: true`），也可手动「重新学习」。

**单篇学习输出（P0）**

1. **摘要（Summary）**：200–400 字，说明文档在讲什么、对你可能有何用
2. **大纲（Outline）**：按原文章节或逻辑重构的层级目录
3. **关键要点（Key Points）**：5–12 条，每条尽量挂 `evidence_chunk_ids`
4. **建议标签**：3–8 个，便于过滤检索
5. **开放问题**：文档留下的疑问 / 值得继续查的点
6. **相关已有笔记**：向量相似 Top-N，帮助建立关联

**知识卡片（推荐默认开启）**

- 从要点提炼为短卡片（标题 + 1–3 句）
- 单独 embedding，问答时可与原文 chunk 混合召回
- 好处：长文档「先命中卡片再下钻原文」，总结能力可被检索复用

**批量 / 主题复习总结（P0/P1）**

用户说「总结我这周上传的 AI 相关文档」时：

```
筛选文档集合 → 读取各 LearningArtifact
  → 聚类主题 → 生成对照表 / 共识 / 分歧 / 行动项
  → 产出复习报告（可导出 Markdown）
```

**增量学习（P1）**

新文档学完后，自动与相似旧文档对比，写入 `Insight`：

- addition：新补充了哪些观点
- conflict：与旧笔记冲突之处（标出双方引用）
- merge_candidate：建议合并的重复主题

### 6.3 学习 Prompt 骨架

```text
你是用户的个人知识学习助手。请只依据给定文档内容产出结构化学习结果。
输出 JSON，字段：summary, outline, key_points[], suggested_tags[], open_questions[]。
key_points 每项包含 point 与 evidence_quotes（必须来自原文）。
不要编造文档中不存在的事实；不确定则写入 open_questions。
```

### 6.4 失败与重试

| 阶段 | 失败表现 | 处理 |
|------|----------|------|
| 上传 | 类型/大小不符 | 立即 4xx，不入队 |
| 解析 | PDF 损坏等 | status=failed，可 retry |
| 索引 | embedding 超时 | 指数退避重试 |
| 学习 | LLM 超时/JSON 损坏 | 保留 indexed，learn_status=failed，可 relearn |

原则：**索引成功与学习成功解耦**——即使总结失败，仍可检索原文。

---

## 7. Agent 能力与产品界面

### 7.1 工具清单

| 工具名 | 作用 | 优先级 |
|--------|------|--------|
| `upload_document` | 触发/查询上传与处理状态 | P0 |
| `search_knowledge` | 语义+关键词混合检索（含知识卡片） | P0 |
| `get_document` | 按 ID/路径取全文或章节 | P0 |
| `get_learning_report` | 获取单篇学习总结报告 | P0 |
| `learn_summarize` | 对指定文档（重新）执行学习总结 | P0 |
| `review_summarize` | 对一批文档/主题做复习总结 | P0 |
| `list_sources` | 列出已索引来源与状态 | P0 |
| `cite_answer` | 强制输出带引用的最终答案 | P0 |
| `tag_documents` | 建议或写入标签 | P1 |
| `compare_concepts` | 对比多篇笔记中的观点 | P1 |
| `find_related` | 基于当前文档找相似笔记 | P1 |
| `incremental_learn` | 新文档 vs 旧知识增量对照 | P1 |
| `ingest_url` / `ingest_path` | 即时摄入新内容 | P1 |
| `weekly_digest` | 生成时间窗口内新增知识摘要 | P2 |

### 7.2 Agent 行为约束

1. **证据优先**：无检索证据时明确说「知识库中未找到」，禁止编造出处
2. **引用可点击**：每条关键结论对应 chunk / 文件路径
3. **范围尊重**：用户指定文件夹/标签/某次上传时不得越界检索
4. **最小权限**：默认只读；写入标签/确认学习报告需显式确认（可配置）
5. **可审计**：保留本轮工具调用与命中 chunk 列表
6. **学习可追溯**：总结中的要点尽量绑定原文证据

### 7.3 对话提示词骨架

```text
你是用户的个人知识库助手，也能在用户上传文档后帮助学习总结。
只能依据提供的【证据】与【学习报告】回答；证据不足时说明缺口。
回答中用 [n] 标注引用，并在文末列出对应来源。
优先结构化输出：结论 → 依据 → 延伸阅读建议。
```

### 7.4 页面结构（MVP）

1. **上传与知识库页**（首页之一）：拖拽上传、进度列表、失败重试
2. **学习报告页**：摘要 / 大纲 / 要点 / 标签 / 相关笔记；支持编辑确认
3. **对话页**：流式回答 + 引用来源；可「基于当前文档提问」
4. **文档页**：原文查看、相关推荐、手动标签
5. **设置页**：模型、API Key、上传限制、监视目录、是否自动学习

### 7.5 CLI

```bash
kb upload ./paper.pdf                 # 等价于 API 上传
kb ingest ./notes --watch
kb learn <doc_id>                     # 触发/重跑学习总结
kb learn --since 7d                   # 复习总结最近文档
kb reindex --full
kb search "向量检索如何调优"
kb status
kb eval ./eval/questions.jsonl
```

---

## 8. 分阶段实施计划

### 阶段 0 — 立项与基线（产出：本仓库骨架）

**目标**：明确范围、目录、配置约定。

**任务**

- [x] 撰写本设计文档（含上传与自我学习总结）
- [ ] 初始化项目骨架与依赖管理
- [ ] 约定配置文件、环境变量、`.gitignore`（排除 `data/uploads` 等）
- [ ] 选定 MVP 交互：`API + Web 上传区`（可用 Streamlit 加速）

**验收**：本地能 `docker compose up` 拉起空服务健康检查。

---

### 阶段 1 — 上传、摄入与索引（MVP 地基）

**目标**：文档可上传；Markdown/TXT/PDF/DOCX 可解析、切块、入库。

**任务**

- [ ] `POST /api/uploads` 多文件上传 + 进度状态机
- [ ] UploadJob / Source / Document 元数据表
- [ ] Parser：md / txt / pdf / docx
- [ ] Chunker + Embedding 写入 Qdrant
- [ ] CLI：`upload` / `ingest` / `status` / `reindex`
- [ ] 简易 Web 拖拽上传区

**验收**

- 浏览器上传 3 个不同格式文件，全部进入 `indexed`
- 导入 50+ 篇中文笔记后状态正确；修改后增量更新

**风险**：PDF 解析质量差 → 先支持文本型 PDF，扫描件后续再加 OCR。

---

### 阶段 2 — 自我学习总结 + 检索问答

**目标**：上传后自动出学习报告；同时可带引用问答。

**任务**

- [ ] LearningArtifact 生成流水线（摘要/大纲/要点/标签/相关）
- [ ] 知识卡片写入与向量化
- [ ] 学习报告 UI（查看 / 修订 / 确认）
- [ ] 混合检索（原文 chunk + 知识卡片）+ Rerank
- [ ] 流式问答 + 引用展示
- [ ] 基础对话历史

**验收**

- 上传一篇长文后自动出现完整学习报告，要点可回溯原文
- 20 条评测问 Recall@5 ≥ 0.7；引用可回溯真实 chunk

**风险**：超长文档超上下文 → 分章学习再归并；JSON 损坏 → 校验重试。

---

### 阶段 3 — Agent 化（工具编排）

**目标**：从「单次 RAG / 单次总结」升级为可多步工具助手。

**任务**

- [ ] 实现 P0 工具集（含 upload/learn/review）
- [ ] 编排循环与最大步数限制
- [ ] 「总结这批上传」「对比 A 与 B」等复合任务
- [ ] 写入类操作二次确认；AgentRun 轨迹落库

**验收**

- 「把我今天上传的文档做成复习总结」可自动完成
- 无证据时拒绝编造

---

### 阶段 4 — 体验与自动化

**目标**：日常愿意持续用。

**任务**

- [ ] 目录 watch 自动同步
- [ ] URL 摄入
- [ ] 增量学习 Insight（新 vs 旧）
- [ ] 周摘要 / 主题地图
- [ ] 学习失败告警与一键 relearn

**验收**：保存/上传后数十秒内可检索，并收到「已学完」提示。

---

### 阶段 5 — 强化与个性化（可选）

**任务**

- [ ] 本地模型一键切换（Ollama）
- [ ] 简单知识图谱
- [ ] 多模态（OCR / 语音转写）后自动学习总结
- [ ] Obsidian / Logseq 导入
- [ ] 备份与导出（原文 + 学习报告 zip）

---

## 9. 质量保障与评测

### 9.1 自动化测试

| 类型 | 覆盖 |
|------|------|
| 单元 | chunker、上传校验、学习 JSON 解析、引用解析 |
| 集成 | upload → ingest → learn → search → answer |
| 回归 | 固定语料的 retrieval + 学习报告字段完整性 |

### 9.2 人工评测集（建议持续维护）

`eval/questions.jsonl` 与 `eval/learning_cases.jsonl`：

```json
{"id":"q1","question":"...","must_include_paths":["notes/rag.md"],"notes":"应提到混合检索"}
{"id":"l1","doc":"samples/long-article.md","must_have":["summary","outline","key_points"],"min_points":5}
```

指标：

- Retrieval：Recall@K、MRR
- Learning：字段完整率、要点可回溯率、摘要忠实度（人工 1–5）
- Generation：忠实度、引用正确率、可读性

### 9.3 观测清单

- 上传任务：耗时分阶段（upload/parse/embed/learn）、失败原因
- 每次回答：query、命中 chunk/卡片、rerank 分数、latency、token
- 学习失败按 document 聚合告警

---

## 10. 安全与隐私

1. API Key 仅环境变量 / 本地 secret，不入库、不进 git
2. 上传文件扩展名白名单 + 大小限制；文件名消毒
3. 默认不把整库原文上传到第三方（学习时按章发送；问答仅发送检索片段）
4. 可选「敏感集合」标记：强制走本地模型
5. Web 若暴露到局域网，加简单 Token / Basic Auth
6. 提供一键清除：删除上传文件 + 向量集合 + 元数据 + 学习产物

---

## 11. 成本与资源粗算（个人规模）

| 项目 | 量级假设 | 备注 |
|------|----------|------|
| 笔记 | 2,000 篇，平均 2k 字 | 约 4M 字 |
| Chunk | ~15,000–25,000 | 视切块而定 |
| 磁盘 | 上传原文 + 向量 + 学习产物 < 10–20 GB | 单机轻松 |
| Embedding | 一次性本地或少量云端费用 | 增量后成本低 |
| LLM | 对话 + **每篇自动学习** | 学习是主要增量成本；可对短文用小模型 |

---

## 12. 里程碑总览

| 里程碑 | 关键交付物 |
|--------|------------|
| M0 | 设计文档（含上传与自我学习） |
| M1 | Web/API 上传 + 解析索引 |
| M2 | 自动学习报告 + 带引用问答 |
| M3 | Agent 工具编排（复习总结等） |
| M4 | 自动同步 + 增量学习 + 周摘要 |
| M5 | 本地模型 / 图谱 / 多模态（按需） |

---

## 13. 近期行动清单（建议立刻执行）

1. **确认约束**：主要上传格式？是否必须离线？Python 还是 TS？
2. **准备语料**：30–100 篇真实文档作黄金测试集（含至少 5 篇长文测学习总结）
3. **搭骨架**：docker-compose（Qdrant）+ FastAPI 上传接口 + 配置加载
4. **打通竖切**：上传 1 个 Markdown → 索引 → 自动学习报告 → 一句带引用回答
5. **再扩面**：PDF/DOCX、批量上传、复习总结、Agent 工具

---

## 14. 开放决策（需你拍板）

| 决策项 | 选项 | 默认建议 |
|--------|------|----------|
| 主语言 | Python / TypeScript | **Python** |
| MVP UI | Streamlit / Next.js | **先 Streamlit（含上传区），后 Next** |
| LLM | 云端兼容 API / 纯本地 | **云端可配 + 预留 Ollama** |
| 学习时机 | 上传后自动 / 仅手动 | **自动学习（可关）** |
| 知识卡片 | 开启 / 关闭 | **开启**（利于检索复用总结） |
| 笔记来源 | 上传为主 / 文件夹监视 / 混合 | **上传 + 本地文件夹** |
| 部署形态 | 仅本机 / 家里 NAS / 云主机 | **本机 Docker** |

---

## 15. 附录：术语表

| 术语 | 含义 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| UploadJob | 一次文档上传及其处理状态机 |
| LearningArtifact | 对单篇文档的自动学习产物（摘要/大纲/要点等） |
| KnowledgeCard | 从要点提炼的可检索短知识单元 |
| Insight | 新文档相对旧知识的增量对照结论 |
| Chunk | 检索与引用的最小文本单元 |
| Embedding | 文本向量表示 |
| Hybrid Search | 向量检索 + 关键词检索融合 |
| Rerank | 对初检结果二次精排 |
| Agent | 可规划并调用工具完成任务的 LLM 系统 |
| Citation | 答案中可回溯的来源引用 |

---

## 16. 文档维护

- 本文档随实现同步更新「阶段勾选」与选型变更
- 重大架构变更请在 PR 中说明对本文第 3/4/6/8 节的影响
