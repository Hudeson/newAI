# 设计方案对比：Karpathy LLM Wiki × Microsoft llmwiki × Atrium 现状 × Atrium Wiki 方案

> 目的：把「真正的」LLM Wiki 原方案与本仓库设计并排放在一起，标清 **一致 / 增强 / 偏离 / 刻意不做**。  
> 依据：Karpathy gist、Microsoft llmwiki ARCHITECTURE、本仓库 [`llm-wiki-design.md`](./llm-wiki-design.md) 与现网实现。

---

## 1. 四套方案分别是什么

| 方案 | 本质 | 形态 |
|------|------|------|
| **A. Karpathy LLM Wiki** | 理念与工作流模式（idea file） | Markdown 目录 + Schema；Obsidian 浏览；Agent 维护 |
| **B. Microsoft llmwiki** | 把 A 工程化 | Git 仓三层 + VS Code/MCP + typed pages + index/log |
| **C. Atrium 现网（已实现）** | 企业 RAG 产品骨架 | 上传→分块→ACL 检索→Learn/Ask→Graph→治理 |
| **D. Atrium LLM Wiki（设计稿）** | 把 A/B 嵌进 C | 服务化 Wiki 编译层 + 保留 ACL/RAG/Gateway |

一句话：

- **A** = 真正的理念源头（「编译而非每次检索拼装」）。  
- **B** = 理念的参考实现骨架（仍偏本地 Git/Agent）。  
- **C** = 我们已上线的「企业 RAG + 学习 + 图谱」。  
- **D** = 用 A 的理念改造 C，而不是推倒重来成 Obsidian 仓库。

---

## 2. 理念层对比（是否「真 Wiki」）

| 命题（Karpathy） | A 原方案 | B MS | C 现网 | D 设计稿 |
|------------------|----------|------|-------|--------|----------|
| 综合发生在摄入时，而非仅查询时 | ✅ 核心 | ✅ | ❌ 偏 Query-time RAG；Learn 只单文档摘要 | ✅ Ingest 编译多页 |
| Wiki 是持久复利制品 | ✅ md 文件 | ✅ md + git | △ LearningReport / Entity 表有持久，但非交叉链接 Wiki | ✅ `wiki_pages` |
| LLM 拥有 Wiki 写入，人策展/提问 | ✅ | ✅ | △ LLM 写 Learn/抽 Graph；无人读的「维基网络」 | ✅ Worker 写、人只读/批准 |
| Schema 约束维护纪律 | ✅ AGENTS.md | ✅ 自动生成七段 | ❌ 无 Wiki Schema | ✅ `wiki_schemas` + 默认模板 |
| 答案可回写知识库 | ✅ 归档页 | ✅ | ❌ Ask 不归档 | ✅ `archive_to_wiki` |
| 周期 Lint 健康检查 | ✅ | ✅ 规则化 | ❌ | ✅ `/v1/wiki/lint` |
| 反对「只靠 RAG、每次重发现」 | ✅ 明确 | ✅ 文档写 Why not RAG | ❌ 现网主路径仍是 RAG | ✅ Wiki 优先 + RAG 回落 |

**结论：** C 还不是真正的 LLM Wiki；D 才按 A 的命题对齐。C 的 Learn/Graph 是「局部编译」，缺少 **跨源综合页 + 交叉引用维护 + Schema + Lint + 问答回写**。

---

## 3. 架构层对比

| 维度 | A Karpathy | B Microsoft | C Atrium 现网 | D Atrium Wiki 设计 |
|------|------------|---------------|---------------|---------------------|
| Raw | `raw/` 不可变 | 同左 | `documents`+对象存储+版本 | 同 C，映射为 Raw |
| Wiki | `wiki/*.md` | typed md + frontmatter | 无统一 Wiki 层 | `wiki_pages` 等表（可导出 md） |
| Schema | CLAUDE/AGENTS.md | `AGENTS.md` 七段 | 无 | 租户级 `schema_md` |
| 运行时 | 本地 Agent + Obsidian | VS Code 扩展 + MCP + Git | FastAPI + Next.js + DB | 同 C，加 Wiki API/Worker |
| 多租户/ACL | 未定义（个人默契） | 仓库级协作 | ✅ Day1 | ✅ 页可见性绑 Raw ACL |
| 审计/配额 | 无 / 弱 | git 历史 | ✅ | ✅ `wiki.*` 审计 |
| 索引 | `index.md` 扫目录 | 同左 + 工具 | 向量 stub /（OPT）Qdrant | index API + 可接混合检索 |
| 图谱 | `[[links]]` 即轻量图 | 链接图 | SQL KG 实体关系 | Wiki-primary，KG 投影 |

```text
A/B：  人 ↔ Agent ↔ Git(md) ↔ Obsidian
C：    人 ↔ Web ↔ API ↔ DB/对象存储  （RAG 主路径）
D：    人 ↔ Web ↔ API ↔ DB(Raw+Wiki+Schema) ↔ Gateway
              ↘ 仍可用 RAG/Graph 作证据与边
```

---

## 4. 操作层对比（Ingest / Query / Lint）

| 操作 | A/B「正统」行为 | C 现网近似物 | D 设计对齐方式 |
|------|-----------------|--------------|----------------|
| **Ingest** | 读源→多页更新（source/entity/concept）→index→log | 入库+Learn（单文档）+可选 Graph 抽取 | 正式 Wiki Ingest，触达 5–15 页 |
| **Query** | 先 index 再下钻 Wiki；答案可归档 | Ask = 检索 chunks + LLM | `retrieve=wiki\|auto\|chunks` + 归档 |
| **Lint** | 矛盾/孤儿/悬空/缺口 | 无 | Lint API + 报告 |

**差距最大的是 Ingest 深度：**  
C 的 Graph 抽取 ≈「抽边」；A 的 Ingest ≈「改写一整片维基邻域」。D 采用 A 的深度，并用 job/配额控成本。

---

## 5. 与「真正方案」的偏离清单（诚实账）

### 5.1 D 相对 A **有意增强**（企业必要）

| 增强 | 原因 |
|------|------|
| 服务化 DB，而非默认纯 Git md | 租户、ACL、并发、审计 |
| Wiki ACL（all_sources） | 防半源综合泄密 |
| supervised Ingest | 企业审批 |
| Gateway + 敏感级路由 | 已有治理能力 |
| 与 Hybrid RAG 并存 | chunk 级引用与合规 |

### 5.2 D 相对 A **有意简化/推迟**

| 原方案常见配套 | D 首期 |
|----------------|--------|
| Obsidian 为 IDE | Web `/app/wiki`；md 导出后期 |
| Marp/幻灯片等产出格式 | 不做 |
| 本地图片附件工作流 | 跟多模态 OPT/M5 |
| 纯「废除向量库」 | **不废除**；Wiki 优先，RAG 兜底 |

### 5.3 C 相对 A **尚未具备（故不算真 Wiki）**

- 无跨文档持续维护的 Wiki 页面网  
- 无 Schema 纪律文件  
- 无 Query 结果回写  
- 无 Lint  
- Learn ≠ 维基编译（范围与链接强度都不够）

---

## 6. 能力雷达（相对 Karpathy 原命题）

```text
                    A(理想)  B(MS)  C(现网)  D(设计)
摄入时编译综合        ████    ███    █       ███░
持久交叉链接          ████    ███    █       ███░
Schema 纪律           ████    ███    ░       ███░
问答回写              ████    ███    ░       ███░
Lint                  ████    ███    ░       ███░
人机策展体验          ████    ███    ██      ███░
多租户/ACL            ░       █      ████    ████
可观测/配额审计       ░       █      ████    ████
证据级引用(chunk)     █       █      ███     ████
检索工程(向量/混合)   可选     可选    弱→OPT  保留+增强
```

---

## 7. 推荐采纳结论

| 问题 | 回答 |
|------|------|
| 什么是「真正的」LLM Wiki 设计？ | **A（Karpathy）** 的命题与三层 + 三操作；**B** 是其工程样板。 |
| 我们现网算不算？ | **不算完整 Wiki**；是企业 RAG + 局部编译（Learn/Graph）。 |
| [`llm-wiki-design.md`](./llm-wiki-design.md) 算不算真？ | **理念对齐 A**，实现形态对齐 **C 的服务化约束**，参考 **B 的页面类型/index/log**。 |
| 和 OPT 真向量方案谁优先？ | **正交**：OPT 补「检得准」；WIKI 补「综合会积累」。并行或 WIKI.1–2 与 OPT.1 穿插。 |

### 决策建议（产品）

1. **承认 C ≠ LLM Wiki**，避免用「已有学习/图谱」对外等同 Karpathy 方案。  
2. **按 D 实施 WIKI.1–5**，才达到「真 Wiki」最小闭环。  
3. **保留 RAG**：这是对 A「个人 md 仓」在企业场景的必要修正，不是背叛理念。  
4. **Wiki-primary + KG 投影**：综合读 Wiki，结构查询走 Graph。

---

## 8. 最小「真 Wiki」验收（对照 A）

若下列全部为真，可宣称「已实现 LLM Wiki 核心」：

1. Raw 不可被 Wiki 作业改写  
2. 一次 Ingest 更新 **多页**（含交叉引用），不只生成单文档摘要  
3. 存在可浏览的 index + 追加 log  
4. Query 主要读 Wiki，且答案可归档为新页  
5. Lint 能发现至少一类结构健康问题  
6. （Atrium 附加）ACL 下无权限综合不可见  

---

## 9. 一页对照总结

| | 真正的 LLM Wiki（A/B） | Atrium 现网（C） | Atrium 设计（D） |
|--|------------------------|-----------------|------------------|
| 关键词 | 编译、复利、Schema、Lint | 租户、RAG、治理 | 两者合一 |
| 主工件 | 维基页面网 | Chunk + Report + Entity 表 | 维基页面网（服务化） |
| 主风险 | 无 ACL/难多租户 | 综合不积累 | 成本与幻觉写库 |
| 下一步 | — | 勿自我标榜已是 Wiki | 落地 WIKI.1 |

正式设计正文仍以 [`llm-wiki-design.md`](./llm-wiki-design.md) 为准；本文只负责 **真伪与差异对齐**。
