# newAI — 个人知识库 Agent

在本仓库搭建**个人知识库 Agent**：摄入私有资料 → 检索增强问答 → 工具化整理与写作辅助。

## 文档

详细设计与实施计划见：

- [`docs/personal-knowledge-base-agent.md`](./docs/personal-knowledge-base-agent.md)

内容涵盖：愿景与成功标准、架构、技术选型、数据模型、Agent 工具、分阶段计划（M0–M5）、评测与隐私、待拍板决策。

## 当前状态

- **M0（设计）**：文档已就绪
- **M1+（实现）**：待启动（摄入流水线 / RAG / Agent / UI）

## 快速决策（默认建议）

| 项 | 默认 |
|----|------|
| 语言 | Python 3.11+ |
| 向量库 | Qdrant（本地 Docker） |
| MVP UI | Streamlit → 再迁 Next.js |
| LLM | OpenAI 兼容云端 API + 预留 Ollama |

确认或修改上述决策后，即可按文档第 13 节启动骨架与竖切实现。
