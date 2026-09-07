# 实施检查清单（企业级架构）

对应主文档：[`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md)

## M0 架构基线

- [x] 企业级架构与实施计划
- [x] **完整技术架构总览** [`technical-architecture.md`](./technical-architecture.md)
- [x] **项目整体计划** [`project-plan.md`](./project-plan.md)
- [x] **执行计划** [`execution-plan.md`](./execution-plan.md)
- [x] 明确：上传、自我学习总结、多租户/ACL 为 Day 1 约束
- [x] 设计审阅遗漏清单（主文档 §18）
- [x] API 契约草案 [`api-contracts.md`](./api-contracts.md)
- [x] 数据模型 / 状态机草案 [`data-model.md`](./data-model.md)
- [x] 明确：ACL↔向量一致性、文档版本、切块/超长学习、幂等去重、embedding 版本
- [x] （P1）[`ops-slo-dr.md`](./ops-slo-dr.md) 配额 / SLO / DR / Runbook
- [x] （P1）[`connectors-and-scim.md`](./connectors-and-scim.md) SCIM / 服务账号 / 连接器
- [x] 仓库骨架 + `personal` / `team` / `enterprise` profile
- [x] 错误码、request_id、health/ready 端点
- [x] Compose 草案（`deploy/compose/docker-compose.yml`）
- [x] Alembic 基线迁移
- [x] **E0 整体 review + 回归** [`milestones/E0-review.md`](./milestones/E0-review.md)
- [x] **E1 身份 / 租户 / Workspace**（本地注册登录 + JWT + 租户隔离）
- [x] **E1 整体 review + 回归** [`milestones/E1-review.md`](./milestones/E1-review.md)
- [x] **E2 上传 / UploadJob**
- [x] **E2 整体 review + 回归** [`milestones/E2-review.md`](./milestones/E2-review.md)
- [ ] 冻结 Tenant / Workspace / ACL 字段级评审（对照 data-model，并入 E2/E4）

## M1 身份、空间、上传入库

- [x] personal 本地账号（注册/登录/JWT）
- [x] Tenant / Workspace / RBAC 最小集（admin 建空间）
- [x] 预签名上传（本地对象存储适配器，E2） → 对象存储（MinIO/S3 或本地适配器）
- [x] Parse / Embed Worker + 队列（personal 同步入库；worker 可认领 queued）
- [x] PostgreSQL/SQLite Schema（documents/versions/jobs/chunks/acls，全表 `tenant_id`）
- [x] 向量载荷强制租户字段（本地 `chunks.embedding_json` stub；Qdrant 后续替换）
- [x] 文档 ACL 最小实现（owner + workspace + replace API）
- [x] **验收**：双租户隔离测试通过（上传/检索）— `tests/test_e4_search_acl.py`
- [x] **E3 review + 回归** [`milestones/E3-review.md`](./milestones/E3-review.md)
- [x] **E4 / M1 review + 全量回归** [`milestones/E4-review.md`](./milestones/E4-review.md)

## M2 学习总结 + 安全问答

- [x] Learning Worker（摘要/大纲/要点；本地 extractive，E5）
- [x] LearningReport：draft / published（personal `publish_mode=auto`）
- [ ] 知识卡片向量化（E5 后延，当前复用 chunk 向量）
- [x] ACL 过滤检索 + Ask 引用二次校验
- [x] LLM Gateway 初版（local provider + `usage_ledger`）
- [x] Next.js：上传、学习报告、对话（E6）
- [x] **E6 review + 全量回归** [`milestones/E6-review.md`](./milestones/E6-review.md)
- [ ] 评测：隔离 + Recall + 学习字段完整率（持续）

## M3 Agent 与治理

- [x] 工具白名单 + 调用前鉴权（E7 Agent allowlist + dry-run）
- [x] 复习总结 / 对比等复合任务（E7 提供 `review_summarize` 骨架，复合编排后续加深）
- [x] 配额与 usage_ledger（强制 429 + usage 面板）
- [x] 管理台：成员、配额、失败任务、审计查询（E6 成员 + E7 governance）
- [x] AgentRun 轨迹落库

## M4 企业加固

- [x] 空间级发布策略（auto / approval）
- [x] 敏感分级 + 私有模型路由（L1–L4 policy + Ask 路由）
- [x] 至少一个企业连接器（网盘/Wiki）— E7 S3 stub sync
- [x] 审计导出（`POST /v1/admin/audit-exports` + download）
- [ ] 渗透与租户隔离测试报告（持续；自动化隔离测试已有）
- [x] SCIM Users/Groups 供给骨架 + Group ACL

## M5 规模与增强

- [ ] 多区域 / 只读副本
- [ ] OpenSearch（如需要）
- [ ] 知识图谱 / 多模态
- [ ] 质量评测门禁接入 CI
- [ ] 成本优化（小模型摘要、缓存、批处理）
