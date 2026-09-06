# 实施检查清单（企业级架构）

对应主文档：[`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md)

## M0 架构基线

- [x] 企业级架构与实施计划
- [x] **完整技术架构总览** [`technical-architecture.md`](./technical-architecture.md)
- [x] 明确：上传、自我学习总结、多租户/ACL 为 Day 1 约束
- [x] 设计审阅遗漏清单（主文档 §18）
- [x] API 契约草案 [`api-contracts.md`](./api-contracts.md)
- [x] 数据模型 / 状态机草案 [`data-model.md`](./data-model.md)
- [x] 明确：ACL↔向量一致性、文档版本、切块/超长学习、幂等去重、embedding 版本
- [x] （P1）[`ops-slo-dr.md`](./ops-slo-dr.md) 配额 / SLO / DR / Runbook
- [x] （P1）[`connectors-and-scim.md`](./connectors-and-scim.md) SCIM / 服务账号 / 连接器
- [ ] 冻结 Tenant / Workspace / ACL 字段级评审（对照 data-model 签字）
- [ ] 仓库骨架 + `personal` / `team` / `enterprise` profile
- [ ] 错误码、request_id、审计事件字典（与 api-contracts 对齐落地）
- [ ] Compose（dev）与 Helm 草案

## M1 身份、空间、上传入库

- [ ] OIDC 登录（dev 可用 Keycloak；personal 可本地账号）
- [ ] Tenant / Workspace / RBAC 最小集
- [ ] 预签名上传 → 对象存储（MinIO/S3）
- [ ] Parse / Embed Worker + 队列
- [ ] PostgreSQL Schema（全表 `tenant_id`）
- [ ] Qdrant payload 强制租户/空间/文档字段
- [ ] 文档 ACL 最小实现
- [ ] **验收**：双租户隔离测试通过

## M2 学习总结 + 安全问答

- [ ] Learning Worker（摘要/大纲/要点/标签）
- [ ] LearningArtifact：draft / approved / published
- [ ] 知识卡片向量化
- [ ] ACL 过滤混合检索 + 引用校验
- [ ] LLM Gateway（路由/计量）
- [ ] Next.js：上传、学习报告、对话
- [ ] 评测：隔离 + Recall + 学习字段完整率

## M3 Agent 与治理

- [ ] 工具白名单 + 调用前鉴权
- [ ] 复习总结 / 对比等复合任务
- [ ] 配额与 usage_ledger
- [ ] 管理台：成员、配额、失败任务、审计查询
- [ ] AgentRun 轨迹落库

## M4 企业加固

- [ ] 空间级发布策略（auto / approval）
- [ ] 敏感分级 + 私有模型路由
- [ ] 至少一个企业连接器（网盘/Wiki）
- [ ] 审计导出、备份恢复演练
- [ ] 渗透与租户隔离测试报告

## M5 规模与增强

- [ ] 多区域 / 只读副本
- [ ] OpenSearch（如需要）
- [ ] 知识图谱 / 多模态
- [ ] 质量评测门禁接入 CI
- [ ] 成本优化（小模型摘要、缓存、批处理）
