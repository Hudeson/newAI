# newAI — 企业级知识库 Agent

按**企业级架构**设计的知识库 Agent 平台：多租户、权限可控 RAG、文档上传、自动学习总结、可审计 Agent。

个人/小团队通过 `profile=personal|team` 收缩部署，与企业版共用同一领域模型。

## 文档

- 架构与计划：[`docs/personal-knowledge-base-agent.md`](./docs/personal-knowledge-base-agent.md)
- 数据模型 / 状态机：[`docs/data-model.md`](./docs/data-model.md)
- API 契约草案：[`docs/api-contracts.md`](./docs/api-contracts.md)
- 运维 / SLO / 灾备：[`docs/ops-slo-dr.md`](./docs/ops-slo-dr.md)
- 实施清单：[`docs/checklist.md`](./docs/checklist.md)
- 企业 vs 个人对照：[`docs/enterprise-vs-personal.md`](./docs/enterprise-vs-personal.md)

## 能力总览

| 能力 | 说明 |
|------|------|
| 多租户 | `tenant_id` + Workspace；向量检索强制 ACL filter |
| 上传入库 | 预签名上传 → 异步解析/向量化 |
| 自我学习 | 摘要/大纲/要点/标签；可自动发布或审批 |
| 安全问答 | 权限内混合检索 + 引用校验 |
| 治理 | SSO、配额、审计、LLM 路由、敏感级 |

## 默认技术栈（企业）

| 层 | 选型 |
|----|------|
| 前端 | Next.js |
| API | FastAPI |
| 元数据 | PostgreSQL |
| 对象存储 | S3 兼容（MinIO/OSS/S3） |
| 向量 | Qdrant |
| 队列/缓存 | Redis（或 NATS） |
| 认证 | OIDC（Keycloak / 企业 IdP） |

## 当前状态

- **M0**：企业级设计已就绪
- **M1+**：待实现（身份与隔离竖切优先）

下一步建议竖切：**租户 A 上传 → 学习 → 问答；租户 B 不可见**。
