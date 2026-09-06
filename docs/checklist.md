# 实施检查清单（可勾选）

对应主文档：[`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md)

## M0 设计与约定

- [x] 撰写总体设计与计划
- [x] 明确「文档上传 + 自我学习总结」为 P0 能力
- [ ] 确认开放决策（语言 / UI / LLM / 自动学习 / 部署）
- [ ] 准备 30–100 篇黄金测试语料（含长文）
- [ ] 初始化项目骨架与 docker-compose（Qdrant）

## M1 上传、摄入与索引

- [ ] `POST /api/uploads` + 进度状态机
- [ ] Web 拖拽/多文件上传区
- [ ] Parser：Markdown / TXT / PDF / DOCX
- [ ] Chunker + Embedding → Qdrant
- [ ] SQLite：UploadJob / Source / Document
- [ ] CLI：`upload` / `ingest` / `status` / `reindex`

## M2 自我学习总结 + 检索问答

- [ ] 自动 LearningArtifact（摘要/大纲/要点/标签/相关）
- [ ] 知识卡片向量化
- [ ] 学习报告 UI（查看 / 修订 / 确认）
- [ ] 混合检索（chunk + 卡片）+ Rerank
- [ ] 流式回答 + 引用
- [ ] 会话历史
- [ ] 评测：学习字段完整率 + Recall@5

## M3 Agent

- [ ] P0 工具：upload / search / learn / review / cite 等
- [ ] 「总结这批上传」「对比 A 与 B」复合任务
- [ ] 多步编排与步数上限
- [ ] 写入操作确认 + AgentRun 轨迹

## M4 体验

- [ ] 目录 watch 自动同步
- [ ] URL 摄入
- [ ] 增量学习 Insight
- [ ] 周摘要 / 主题地图
- [ ] 学习失败告警与 relearn

## M5 强化（按需）

- [ ] Ollama 本地模型切换
- [ ] 简易知识图谱
- [ ] OCR / 音视频转写 + 自动学习
- [ ] Obsidian 导入与备份导出
