# 个人知识库 Agent — 详细设计文档与实施计划

> 目标：搭建一个**可长期演进**的个人知识库 Agent，能摄入、索引、检索你的私有资料，并以 Agent 方式回答问题、整理笔记、主动发现关联。

---

## 1. 项目愿景

### 1.1 一句话定义

**个人知识库 Agent** = 私有资料库（Knowledge Base） + 检索增强生成（RAG） + 具备工具调用能力的 Agent。

它不是普通 ChatGPT 对话框，而是：

- 只基于**你自己的资料**作答，并标明出处
- 能**持续摄入**新内容（笔记、PDF、网页、聊天记录等）
- 能**主动整理**：打标签、摘要、建立主题图谱、提醒知识缺口
- 可本地或私有部署，数据主权归你

### 1.2 成功标准（Definition of Done）

| 维度 | 达标表现 |
|------|----------|
| 摄入 | 支持 Markdown / PDF / 网页 / 纯文本；增量同步无明显重复 |
| 检索 | 问答能返回相关原文片段 + 来源路径；Top-K 命中率主观可用 |
| 对话 | 多轮追问不丢上下文；可要求「只根据某文件夹回答」 |
| Agent | 至少 5 个工具：搜索、摘要、对比、打标签、列出相关笔记 |
| 可维护 | 一键启动；配置与密钥外置；日志可排查摄入/检索失败 |
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

1. **导入资料**：指定目录 / 拖拽文件 / 粘贴 URL，系统切块并向量化
2. **自然语言问答**：提问 → 检索 → 带引用回答
3. **限定范围问答**：只查某个主题、标签或文件夹
4. **笔记摘要 / 大纲**：对单篇或一批文档生成结构化摘要
5. **相关笔记推荐**：打开一篇时推荐「你可能还想看」

### 2.3 进阶用例（P1）

6. **知识整理 Agent**：自动建议标签、合并重复笔记、生成主题地图
7. **定期回顾**：每周摘要「本周新增知识」
8. **写作助手**：基于知识库起草文章，并强制引用库内来源
9. **多模态**：图片 OCR、音视频转写后入库

---

## 3. 系统架构

### 3.1 逻辑架构

```
┌─────────────────────────────────────────────────────────────┐
│                        交互层                                │
│   Web UI  ·  CLI  ·  API (OpenAI-compatible optional)         │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     Agent 编排层                              │
│  Planner / Tool Router · Memory · Citation Guard · Policies  │
└───────┬─────────────────┬─────────────────┬─────────────────┘
        │                 │                 │
┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
│  RAG 检索服务  │ │  知识管理工具  │ │  LLM 推理服务  │
│ hybrid search │ │ tag/summarize │ │ local / cloud │
└───────┬───────┘ └───────┬───────┘ └───────────────┘
        │                 │
┌───────▼─────────────────▼───────────────────────────────────┐
│                       数据层                                  │
│  文档存储 · 元数据 DB · 向量索引 · 图谱(可选) · 任务队列        │
└─────────────────────────────────────────────────────────────┘
                            ▲
┌───────────────────────────┴─────────────────────────────────┐
│                      摄入流水线                               │
│  Source Watcher → Parser → Chunker → Embedder → Indexer      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 关键数据流

**摄入**

```
文件/URL → 解析为纯文本+元数据 → 分块(chunk) → Embedding
  → 写入向量库 + 元数据 DB → 可选：更新主题标签
```

**问答**

```
用户问题 → （可选）查询改写 / HyDE
  → 混合检索(向量 + 关键词) → 重排序(Rerank)
  → 组装 Prompt（问题 + 证据片段 + 引用约束）
  → LLM 生成 → 校验引用 → 返回答案 + sources
```

**Agent 任务**

```
用户意图 → Agent 选择工具序列
  → search_kb / get_doc / summarize / tag / compare ...
  → 聚合结果 → 最终回答
```

### 3.3 目录建议（实现阶段落地）

```
/
├── apps/
│   ├── api/                 # FastAPI / Node 后端
│   ├── web/                 # 对话与知识浏览 UI
│   └── cli/                 # 摄入、重建索引、运维命令
├── packages/
│   ├── ingest/              # 解析、切块、embedding
│   ├── retrieval/           # 检索、rerank、引用组装
│   ├── agent/               # 工具定义与编排
│   └── shared/              # 类型、配置、日志
├── data/                    # 本地运行时数据（gitignore）
│   ├── raw/                 # 原始文件镜像或软链
│   ├── processed/           # 解析后文本
│   └── indexes/             # 向量库持久化
├── docs/
│   └── personal-knowledge-base-agent.md
├── docker-compose.yml
└── README.md
```

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
```

---

## 5. 数据模型

### 5.1 核心实体

**Source（来源）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid | 主键 |
| type | enum | file / url / note / chat_export |
| uri | string | 路径或 URL |
| title | string | 标题 |
| hash | string | 内容哈希，用于增量更新 |
| mtime | datetime | 来源修改时间 |
| status | enum | pending / indexed / failed |
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
| summary | text | 可选自动摘要 |
| tags | string[] | |

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

## 6. Agent 能力设计

### 6.1 工具清单

| 工具名 | 作用 | 优先级 |
|--------|------|--------|
| `search_knowledge` | 语义+关键词混合检索 | P0 |
| `get_document` | 按 ID/路径取全文或章节 | P0 |
| `list_sources` | 列出已索引来源与状态 | P0 |
| `summarize` | 对检索结果或指定文档摘要 | P0 |
| `cite_answer` | 强制输出带引用的最终答案 | P0 |
| `tag_documents` | 建议或写入标签 | P1 |
| `compare_concepts` | 对比多篇笔记中的观点 | P1 |
| `find_related` | 基于当前文档找相似笔记 | P1 |
| `ingest_url` / `ingest_path` | 即时摄入新内容 | P1 |
| `weekly_digest` | 生成时间窗口内新增知识摘要 | P2 |

### 6.2 Agent 行为约束（系统策略）

1. **证据优先**：无检索证据时明确说「知识库中未找到」，禁止编造出处
2. **引用可点击**：每条关键结论对应 chunk / 文件路径
3. **范围尊重**：用户指定文件夹/标签时不得越界检索
4. **最小权限**：默认只读；写入标签/新建笔记需显式确认（可配置）
5. **可审计**：保留本轮工具调用与命中 chunk 列表

### 6.3 提示词骨架（示意）

```text
你是用户的个人知识库助手。
只能依据提供的【证据】回答；证据不足时说明缺口。
回答中用 [n] 标注引用，并在文末列出对应来源。
优先结构化输出：结论 → 依据 → 延伸阅读建议。
```

---

## 7. 产品界面（MVP）

### 7.1 页面结构

1. **对话页**：主输入框 + 流式回答 + 引用来源面板
2. **知识库页**：来源列表、同步状态、失败重试
3. **文档页**：单篇查看、相关推荐、手动标签
4. **设置页**：模型、API Key、监视目录、切块参数

### 7.2 CLI（运维必备）

```bash
kb ingest ./notes --watch
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

- [x] 撰写本设计文档
- [ ] 初始化 monorepo / 项目骨架与依赖管理
- [ ] 约定配置文件、环境变量、`.gitignore`（排除 `data/`）
- [ ] 选定 MVP 交互：优先 `API + 简易 Web` 或 `CLI + Streamlit`

**验收**：本地能 `docker compose up` 拉起空服务健康检查。

---

### 阶段 1 — 摄入与索引（MVP 地基）

**目标**：任意 Markdown/TXT/PDF 可被解析、切块、入库。

**任务**

- [ ] Source 扫描与内容哈希增量更新
- [ ] Parser：md / txt / pdf（先三件套）
- [ ] Chunker + Embedding 写入 Qdrant
- [ ] SQLite 元数据表
- [ ] CLI：`ingest` / `status` / `reindex`

**验收**

- 导入 50+ 篇中文笔记后，`kb status` 显示全部 indexed
- 修改一篇笔记再 ingest，仅该文件相关 chunk 更新

**风险**：PDF 解析质量差 → 先支持文本型 PDF，扫描件后续再加 OCR。

---

### 阶段 2 — 检索问答（可用的 RAG）

**目标**：问一句，得到带引用的答案。

**任务**

- [ ] 混合检索（dense + BM25/sparse）
- [ ] Rerank Top-N → Top-K
- [ ] Prompt 组装与流式输出
- [ ] 引用解析与前端展示
- [ ] 基础对话历史（会话级）

**验收**

- 准备 20 条「问题-应命中文档」评测集，Recall@5 ≥ 0.7（主观可再调）
- 答案中至少 80% 的引用可回溯到真实 chunk

**风险**：短问句检索差 → 加查询改写；专有名词 → 加强关键词通道。

---

### 阶段 3 — Agent 化（工具编排）

**目标**：从「单次 RAG」升级为「可多步使用工具的助手」。

**任务**

- [ ] 实现 P0 工具集与统一 Tool Schema
- [ ] 编排循环：思考 → 选工具 → 观察 → 再决策（限制最大步数）
- [ ] 写入类操作二次确认
- [ ] AgentRun 轨迹落库

**验收**

- 「对比我笔记里关于 A 与 B 的说法」能自动多次检索并输出对比表
- 无证据时拒绝编造

---

### 阶段 4 — 体验与自动化

**目标**：日常愿意持续用。

**任务**

- [ ] Web UI 完善（来源管理、引用跳转）
- [ ] 目录 watch 自动增量同步
- [ ] URL 摄入、网页正文抽取
- [ ] 标签建议、相关笔记、周摘要
- [ ] 基础评测面板 / 失败日志

**验收**：日常笔记目录保存后数秒内可被检索到。

---

### 阶段 5 — 强化与个性化（可选）

**任务**

- [ ] 本地模型一键切换（Ollama）
- [ ] 简单知识图谱（实体-关系）辅助导航
- [ ] 多模态（OCR / 语音转写）
- [ ] 插件：Obsidian / Logseq 双链导入
- [ ] 备份与导出（Markdown zip + 向量快照）

---

## 9. 质量保障与评测

### 9.1 自动化测试

| 类型 | 覆盖 |
|------|------|
| 单元 | chunker、hash 增量、引用解析 |
| 集成 | ingest → search → answer 管道 |
| 回归 | 固定语料 + 固定问题的 retrieval 指标 |

### 9.2 人工评测集（建议持续维护）

`eval/questions.jsonl` 每行：

```json
{"id":"q1","question":"...","must_include_paths":["notes/rag.md"],"notes":"应提到混合检索"}
```

指标：

- Retrieval：Recall@K、MRR
- Generation：忠实度（是否胡编）、引用正确率、可读性（人工 1–5 分）

### 9.3 观测清单

- 每次回答记录：改写后的 query、命中 chunk、rerank 分数、latency、token
- 摄入失败按 source 聚合告警

---

## 10. 安全与隐私

1. API Key 仅环境变量 / 本地 secret，不入库、不进 git
2. 默认不把整库原文上传到第三方（仅发送检索到的片段）
3. 可选「敏感集合」标记：强制走本地模型
4. Web 若暴露到局域网，加简单 Token / Basic Auth
5. 提供一键清除：删除向量集合 + 元数据 + 缓存

---

## 11. 成本与资源粗算（个人规模）

| 项目 | 量级假设 | 备注 |
|------|----------|------|
| 笔记 | 2,000 篇，平均 2k 字 | 约 4M 字 |
| Chunk | ~15,000–25,000 | 视切块而定 |
| 磁盘 | 向量 + 原文 < 5–10 GB | 单机轻松 |
| Embedding | 一次性本地或少量云端费用 | 增量后成本低 |
| LLM | 按对话次数计费 | Agent 多步会放大 2–5 倍 |

---

## 12. 里程碑总览

| 里程碑 | 关键交付物 |
|--------|------------|
| M0 | 设计文档、仓库结构约定 |
| M1 | 可摄入 + 可索引（CLI） |
| M2 | 可问答 + 有引用（API/简易 UI） |
| M3 | Agent 工具编排可用 |
| M4 | 自动同步 + 日常可用 Web |
| M5 | 本地模型 / 图谱 / 多模态（按需） |

---

## 13. 近期行动清单（建议立刻执行）

按优先级排序：

1. **确认约束**：资料主要格式？是否必须离线？更熟 Python 还是 TS？
2. **准备语料**：挑 30–100 篇真实笔记作为黄金测试集
3. **搭骨架**：`docker-compose`（Qdrant）+ FastAPI hello + 配置加载
4. **打通竖切**：单文件 Markdown → chunk → embed → search → 一句回答
5. **再扩面**：PDF、增量更新、UI、Agent 工具

---

## 14. 开放决策（需你拍板）

下面几项会显著影响实现路径，建议先定：

| 决策项 | 选项 | 默认建议 |
|--------|------|----------|
| 主语言 | Python / TypeScript | **Python** |
| MVP UI | Streamlit / Next.js | **先 Streamlit，后 Next** |
| LLM | 云端兼容 API / 纯本地 | **云端可配 + 预留 Ollama** |
| 笔记来源 | 本地文件夹 / Obsidian / 混合 | **本地文件夹监视** |
| 部署形态 | 仅本机 / 家里 NAS / 云主机 | **本机 Docker** |

---

## 15. 附录：术语表

| 术语 | 含义 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| Chunk | 检索与引用的最小文本单元 |
| Embedding | 文本向量表示 |
| Hybrid Search | 向量检索 + 关键词检索融合 |
| Rerank | 对初检结果二次精排 |
| Agent | 可规划并调用工具完成任务的 LLM 系统 |
| Citation | 答案中可回溯的来源引用 |

---

## 16. 文档维护

- 本文档随实现同步更新「阶段勾选」与选型变更
- 重大架构变更请在 PR 中说明对本文第 3/4/8 节的影响
