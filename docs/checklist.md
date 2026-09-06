# 实施检查清单（可勾选）

对应主文档：[`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md)

## M0 设计与约定

- [x] 撰写总体设计与计划
- [ ] 确认开放决策（语言 / UI / LLM / 资料来源 / 部署）
- [ ] 准备 30–100 篇黄金测试语料
- [ ] 初始化项目骨架与 docker-compose（Qdrant）

## M1 摄入与索引

- [ ] Source 扫描 + 内容哈希增量
- [ ] Parser：Markdown / TXT / PDF
- [ ] Chunker + Embedding → Qdrant
- [ ] SQLite 元数据
- [ ] CLI：`ingest` / `status` / `reindex`

## M2 检索问答

- [ ] 混合检索 + Rerank
- [ ] 流式回答 + 引用
- [ ] 会话历史
- [ ] 评测集 Recall@5 基线

## M3 Agent

- [ ] P0 工具：search / get_doc / list_sources / summarize / cite
- [ ] 多步编排与步数上限
- [ ] 写入操作确认
- [ ] AgentRun 轨迹

## M4 体验

- [ ] Web 来源管理与引用跳转
- [ ] 目录 watch 自动同步
- [ ] URL 摄入
- [ ] 标签建议 / 相关笔记 / 周摘要

## M5 强化（按需）

- [ ] Ollama 本地模型切换
- [ ] 简易知识图谱
- [ ] OCR / 音视频转写
- [ ] Obsidian 导入与备份导出
