# 对照「DeepSeek V3 个人知识库教程」的优化方案与完整链路计划

> 对照来源：[DeepSeek V3搭建个人知识库教程（百度智能云）](https://cloud.baidu.com/article/3559904)  
> 对照对象：本仓库 Atrium KB（企业架构下的个人/团队知识库 Agent）  
> 状态：方案定稿（可执行）  
> 日期：2026-09-08

---

## 1. 一句话结论

该教程是 **「本地模型 + 向量库 + 简易 UI」的 DIY RAG 手册**；我们已是 **「租户/ACL/审计 + 入库学习问答 + Gateway + 图谱」的产品骨架**。  
优化方向不是照搬 LoRA 微调 DeepSeek V3，而是 **补齐检索与摄入的工业级短板**，把教程里真正值钱的链路接到我们已有的治理与产品壳上。

---

## 2. 教程链路 vs 我们现状

### 2.1 教程完整链路（原文结构）

```text
环境（conda / CUDA / transformers）
  → 数据采集（PDF/Word/MD / 网页 / Notion·Obsidian）
  → 清洗结构化
  → Embedding（sentence-transformers，中文用 multilingual MiniLM）
  → 向量库（Chroma / FAISS）
  → DeepSeek V3 加载 / LoRA 微调
  → 混合检索（语义 + 关键词）
  → FastAPI 检索 API + Streamlit UI
  → 量化 / Docker 部署
  → HTTPS / AES / JWT / 查询日志
  → 进阶：多模态、增量更新
```

### 2.2 本仓库已具备

| 能力 | 状态 |
|------|------|
| 多租户 + JWT + Workspace + 文档 ACL | ✅ |
| 上传 → 解析分块 → 入库（personal 同步） | ✅（格式偏 MD/TXT） |
| 学习总结 LearnReport | ✅ |
| ACL 检索 + Ask 引用二次校验 | ✅ |
| LLM Gateway（OpenAI 兼容 / Ollama / local） | ✅（可接 DeepSeek API，无需本地 V3 权重） |
| 配额 / 审计 / 敏感级路由 / Agent 骨架 | ✅ |
| 知识图谱抽取 + Ask 图谱增强 + 中文 UI | ✅ |
| Next.js 产品壳（优于 Streamlit） | ✅ |

### 2.3 对照差距（按优先级）

| # | 教程要点 | 我们 | 差距性质 | 优先级 |
|---|----------|------|----------|--------|
| G1 | 真 Embedding（sentence-transformers / 多语） | 本地 hashing stub → `embedding_json` | **检索质量核心短板** | P0 |
| G2 | Chroma / FAISS / 向量库 | 未接 Qdrant（设计有、未落地） | **检索性能与召回** | P0 |
| G3 | 混合检索（语义 + 关键词） | 仅向量近似 stub | **中文专名/精确匹配弱** | P0 |
| G4 | PDF / Word / 网页 / Notion·Obsidian | 以 MD/TXT 为主 | **数据入口窄** | P0 |
| G5 | 问答流式交互 | 无 SSE | **体验** | P1 |
| G6 | 增量更新知识 | 有重学/重抽，缺 embedding 版本演进与增量 embed | **运维与成本** | P1 |
| G7 | 评测（文称 85%+ 准确率） | 缺 Recall / 隔离评测门禁 CI | **质量门禁** | P1 |
| G8 | 4bit 量化本地 DeepSeek V3 | 不走本地巨模型；走 Gateway API | **刻意不做**（见 §3） | — |
| G9 | LoRA 领域微调 | 无 | **刻意不做（首期）** | — |
| G10 | Streamlit | Next.js | **我们更优，保持** | — |
| G11 | AES 静态加密全文 | 凭证轻量密封；对象/库加密未硬 | 企业加固项 | P2 |
| G12 | 多模态图像 | M5 未做 | 后续 | P2 |

---

## 3. 明确「不照搬」的部分

| 教程做法 | 我们立场 |
|----------|----------|
| 本地加载 `deepseek-ai/DeepSeek-V3` 权重 | 个人机难落地；产品路径用 **OpenAI 兼容 API（含 DeepSeek）+ Ollama**，已有治理页配 Key |
| LoRA 微调 8–16 GPU | 非个人知识库 P0；知识更新靠 **入库 + 检索 + 图谱**，不靠改基座权重 |
| Streamlit | 保留 Next.js 中文产品 UI |
| 无租户的单机 collection | 坚持 `tenant_id` + ACL；向量 payload 必带租户字段 |

**原则：** 教程补的是 **「检得准、吃得下、答得顺」**；我们补的是把这些能力嵌进已有企业壳，而不是退回单机脚本。

---

## 4. 目标完整链路（优化后）

```text
┌─────────────── 采集入口 ───────────────┐
│ 上传(MD/TXT/PDF/DOCX)  连接器(S3/…)   │
│ 网页导入(可选)  笔记导入(可选)          │
└──────────────────┬────────────────────┘
                   ▼
┌─────────────── 摄入流水线 ─────────────┐
│ Parse → Chunk → Embed(真模型)          │
│ → 向量库(Qdrant) + 元数据(SQLite/PG)   │
│ → Learn(摘要) →（可选）Graph Extract   │
│ 全程 tenant_id / ACL / audit / usage   │
└──────────────────┬────────────────────┘
                   ▼
┌─────────────── 检索与推理 ─────────────┐
│ Hybrid：向量召回 + 关键词/BM25         │
│ → ACL 过滤 →（可选）图谱邻域增强       │
│ → LLM Gateway（DeepSeek/Ollama/local） │
│ → 流式回答 + 引用二次校验              │
└──────────────────┬────────────────────┘
                   ▼
┌─────────────── 产品与治理 ─────────────┐
│ 文库 / 问答 / 图谱 / 学习 / 成员 / 治理 │
│ 配额 · 敏感级 · 审批 · 审计导出         │
│ 评测门禁 · SLO · 增量重嵌               │
└────────────────────────────────────────┘
```

与教程的关键差异：**每一跳都过 ACL/审计**；LLM 走 Gateway 而非裸绑单一本地权重。

---

## 5. 分阶段执行计划（完整可排期）

> 阶段命名：`OPT.*`，挂在 tip 链之后；每阶段仍执行 **review + 回归** 门禁。

### OPT.0 — 方案冻结（本文）

- [x] 对照教程差距表与「不照搬」边界  
- [ ] 产品确认：P0 = Embed + 向量库 + 混合检索 + PDF/DOCX  

**出口：** 本文合入；checklist 增加 OPT 条目指针。

---

### OPT.1 — 真 Embedding + 向量库（P0）

**目标：** 替换 hashing stub，检索质量接近教程水准，且租户隔离不破。

| 任务 | 说明 |
|------|------|
| 1.1 Embedding Provider | `local_hash`（兼容）/ `sentence_transformers` / `openai_compatible_embed`（可接 DeepSeek/通义等） |
| 1.2 默认中文模型 | `paraphrase-multilingual-MiniLM-L12-v2` 或等价 API embedding |
| 1.3 Vector Store | 落地 `Qdrant`（compose 已有草案）；personal 可 `qdrant-local` 或嵌入式模式 |
| 1.4 Payload 强制字段 | `tenant_id`, `document_id`, `chunk_id`, `workspace_id`, `acl` 摘要 |
| 1.5 双写过渡 | 写入 Qdrant + 保留/淘汰 `embedding_json`（迁移开关） |
| 1.6 回归 | 双租户隔离 + 专名召回样例（中文） |

**验收：** 同库文档「星河实验室」类专名 Ask 命中率显著优于 hash；跨租户仍为空。

**预估改动：** `packages/shared/ingest.py`, `search.py`, `config.py`, compose, Alembic 可选 `embedding_model` 字段, 测试。

---

### OPT.2 — 混合检索（P0）

**目标：** 语义 + 关键词，对齐教程 hybrid_search。

| 任务 | 说明 |
|------|------|
| 2.1 关键词通道 | SQLite FTS5 / Postgres `tsvector` / 简易 BM25 |
| 2.2 融合 | RRF 或加权融合；统一 top_k |
| 2.3 Ask 接线 | `search_chunks` 改为 hybrid；引用校验不变 |
| 2.4 可观测 | usage/audit 记录 `retrieve_mode=hybrid` |

**验收：** 精确标题/专名查询不依赖语义也能命中。

---

### OPT.3 — 多格式摄入（P0）

**目标：** 对齐教程「PDF/Word/MD」主路径。

| 任务 | 说明 |
|------|------|
| 3.1 PDF | 文本型 PDF → 文本；扫描件可先拒或 OCR 钩子（P1） |
| 3.2 DOCX | python-docx / unstructured 适配 |
| 3.3 清洗 | 去页眉页脚噪声、空块合并 |
| 3.4 UI | 文库上传 accept 扩展；失败原因可读 |
| 3.5（可选）网页导入 | URL → 抓取正文（授权域名白名单） |

**验收：** 上传 PDF/DOCX → indexed → Ask 可引用。

---

### OPT.4 — 问答体验：流式 + DeepSeek 一键档（P1）

| 任务 | 说明 |
|------|------|
| 4.1 SSE Ask | `POST /v1/ask/stream`；前端逐 token |
| 4.2 DeepSeek 预设 | 治理页「DeepSeek」一键：base_url + 模型名提示 |
| 4.3 上下文窗口 | Gateway `max_tokens` / 截断策略可配 |

**验收：** UI 流式可见；DeepSeek Key 可通。

---

### OPT.5 — 增量更新与评测门禁（P1）

| 任务 | 说明 |
|------|------|
| 5.1 embedding_version | 模型变更可批量重嵌 |
| 5.2 增量 embed | 仅新/变 chunk 入队 |
| 5.3 评测集 | 租户隔离 + Recall@k + 学习字段完整率 |
| 5.4 CI | PR 跑最小评测子集 |

**验收：** checklist「评测门禁」可勾；教程式「准确率」有可复现指标替代口头 85%。

---

### OPT.6 — 安全加固与多模态（P2）

| 任务 | 说明 |
|------|------|
| 6.1 对象存储加密 / 库字段加密策略 | 对齐教程 AES 意图 |
| 6.2 查询审计字段增强 | user + query_hash + latency |
| 6.3 多模态 | 图片 caption → chunk（教程 vision）；接 M5 |

---

## 6. 建议实施顺序（完整链路甘特逻辑）

```text
OPT.0 方案冻结
   │
   ├─► OPT.1 Embed + Qdrant  ──┐
   │                           ├─► OPT.2 Hybrid ──► OPT.4 SSE/DeepSeek 体验
   └─► OPT.3 PDF/DOCX ─────────┘
                    │
                    └─► OPT.5 增量 + 评测 CI
                              │
                              └─► OPT.6 加密 / 多模态
```

**个人版最短闭环（对齐教程「能用」）：** OPT.1 → OPT.2 → OPT.3 → OPT.4  
**企业不退步：** 全程保留 ACL / Gateway / 审计；向量查询必须带租户过滤。

---

## 7. 成功标准（优化后相对教程）

| 维度 | 达标 |
|------|------|
| 检索 | 真向量 + hybrid；中文专名可命中 |
| 入口 | MD/TXT/PDF/DOCX |
| 生成 | DeepSeek（或任意兼容 API）经 Gateway；可流式 |
| 安全 | 仍强于教程（租户 ACL + 审计导出） |
| 产品 | Next.js 中文 UI + 学习 + 图谱保留 |
| 不做 | 本地 V3 全量微调作为默认路径 |

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 本地拉 sentence-transformers / Qdrant 过重 | personal 提供「API embedding」轻路径；CI 用小模型或 mock |
| 向量与 ACL 不一致 | 写入/删除文档级联删点；检索强制 payload filter + 二次校验 |
| 盲目上微调 | 文档与 ADR 写明非目标；用评测证明检索增益优先 |
| 教程数据源（随意爬站） | 仅白名单域名 / 用户主动粘贴；遵守授权 |

---

## 9. 即时下一步

1. **确认 OPT.1–OPT.3 为下一开发主轴**（真检索 + 多格式）。  
2. 从 tip 拉分支 `cursor/opt1-embeddings-qdrant-4365` 开工 OPT.1。  
3. 同步更新 `docs/checklist.md` / `docs/execution-plan.md` 增加 OPT 进度段。

---

## 10. 附录：能力雷达（相对教程）

```text
                教程 ★★★★☆    我们现状 ★★☆☆☆ → OPT后 ★★★★★
Embedding/向量库
混合检索
多格式摄入
LLM 生成质量（有 Key 时）
流式体验
租户/ACL/审计
学习总结
知识图谱
治理/配额
本地巨模型微调
```

我们应在左侧「检索与摄入」追上教程，在右侧「治理与产品」保持领先。
