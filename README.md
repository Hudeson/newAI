# newAI — 个人知识库 Agent

在本仓库搭建**个人知识库 Agent**：

**上传文档 → 自动学习总结 → 检索增强问答 → Agent 整理与复习**

## 文档

- 详细设计与计划：[`docs/personal-knowledge-base-agent.md`](./docs/personal-knowledge-base-agent.md)
- 实施勾选清单：[`docs/checklist.md`](./docs/checklist.md)

重点能力（P0）：

1. **文档上传**：Web/API 拖拽多文件（md/txt/pdf/docx），进度可追踪
2. **自我学习总结**：入库后自动生成摘要、大纲、要点、标签与相关笔记
3. **带引用问答**：基于原文 chunk + 知识卡片检索作答
4. **复习总结 Agent**：按主题/时间批量对照总结

## 当前状态

- **M0（设计）**：已覆盖上传与学习总结方案
- **M1+（实现）**：待启动

## 默认技术建议

| 项 | 默认 |
|----|------|
| 语言 | Python 3.11+ |
| 向量库 | Qdrant（本地 Docker） |
| MVP UI | Streamlit（含上传区）→ 再迁 Next.js |
| LLM | OpenAI 兼容云端 API + 预留 Ollama |
| 学习时机 | 上传索引完成后自动学习（可关） |

确认决策后，优先打通竖切：**上传 1 个文件 → 学习报告 → 带引用回答**。
