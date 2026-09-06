# 企业级知识库 Agent — 架构设计与实施计划

> 定位：按**企业级架构**设计的知识库 Agent 平台。个人使用视为「单租户部署配置」，与多租户企业版共用同一套领域模型与服务边界，避免后期推倒重来。

---

## 1. 设计原则

| 原则 | 含义 |
|------|------|
| 租户优先 | 所有业务数据、向量、对象、任务、审计必带 `tenant_id` |
| 零信任 API | 每个请求经认证 → 鉴权 → 范围过滤；禁止「先检索后过滤」漏权 |
| 存算分离 | 原文对象存储、元数据库、向量库、任务队列独立扩展 |
| 异步默认 | 上传、解析、embedding、学习总结一律进队列，API 只受理与查询 |
| 证据可审计 | 问答与学习产物可回溯 chunk / 文档 / 操作者 / 模型版本 |
| 配置分环境 | `personal` / `team` / `enterprise` profile，代码路径同一套 |
| 可替换供应商 | LLM / Embedding / 对象存储 / IdP 通过 Provider 接口替换 |

### 1.1 一句话定义

**企业级知识库 Agent** = 多租户文档平台 + 权限可控的 RAG + 自动学习总结 + 可审计 Agent 工具编排。

核心能力（P0）：

1. **文档上传与摄入**（多格式、异步、可重试）
2. **自我学习总结**（摘要/大纲/要点/标签/知识卡片；可审批）
3. **带引用问答**（租户与 ACL 范围内检索）
4. **组织级治理**（空间/角色/配额/审计/SSO）

### 1.2 成功标准

| 维度 | 达标表现 |
|------|----------|
| 多租户 | 租户间数据物理/逻辑隔离验证通过；跨租户检索必定为空 |
| 权限 | 文档级 ACL + 角色；越权读写/问答被拒绝并记审计 |
| 上传 | 多文件上传、进度、病毒扫描钩子、失败重试 |
| 学习 | 自动学习报告；企业模式可走「生成 → 审批 → 发布」 |
| 问答 | 引用可点回原文；无权限文档永不出现在证据中 |
| 扩展 | 无状态 API 水平扩展；Worker 按队列积压扩容 |
| 安全 | SSO、密钥托管、静态加密、完整审计导出 |
| 可观测 | 追踪上传→学习→问答全链路；核心 SLO 可告警 |

### 1.3 明确非目标（首期仍不做）

- 不做完整协作编辑器（非 Notion 替代）
- 不做公网开放注册的 C 端 SaaS 增长体系（可先私有化/专有云）
- 不做自动全网爬取（仅授权来源）

---

## 2. 角色、空间与用例

### 2.1 组织模型

```
Tenant（租户/公司）
  └── Workspace（空间：部门/项目/知识域）
        └── Document / Collection
              └── ACL（用户/用户组/角色）
```

| 角色 | 能力 |
|------|------|
| Platform Admin | 平台运维、租户开闭、全局配额 |
| Tenant Admin | 成员、SSO 映射、空间、配额、审计导出 |
| Workspace Admin | 空间成员、默认权限、连接器 |
| Editor | 上传、编辑元数据、触发重学、确认学习报告 |
| Viewer | 检索问答、查看已发布学习报告 |
| Auditor | 只读审计日志与引用追溯 |

### 2.2 核心用例（P0）

1. SSO 登录进入租户与空间
2. 上传文档 → 异步解析索引 →（可选）审批后对空间可见
3. 自动学习总结；Editor 确认或走审批流后发布
4. 空间内 / 跨有权空间的带引用问答
5. 批量复习总结（限有权文档集）
6. 管理员查看配额、任务失败、审计事件

### 2.3 进阶用例（P1）

7. 增量学习 Insight（新 vs 旧，限同权范围）
8. 企业连接器：SharePoint / Google Drive / Confluence / S3
9. 敏感分级（L1–L4）与强制本地模型路由
10. 部门知识周报、合规问答模板
11. 多模态（OCR / 音视频转写）后入库学习

---

## 3. 逻辑架构

```
                    ┌──────────────────────────────────────┐
                    │     Clients: Web / Admin / API SDK    │
                    └──────────────────┬───────────────────┘
                                       │
                    ┌──────────────────▼───────────────────┐
                    │  Edge: Ingress / WAF / API Gateway    │
                    │  AuthN (OIDC) · Rate Limit · TLS      │
                    └──────────────────┬───────────────────┘
                                       │
          ┌────────────────────────────┼────────────────────────────┐
          │                            │                            │
┌─────────▼─────────┐      ┌───────────▼──────────┐     ┌──────────▼─────────┐
│  Gateway BFF/API  │      │  Identity & Access   │     │  Admin / Audit API │
│  upload/query/chat│      │  IdP · RBAC · ACL    │     │  quota · export     │
└─────────┬─────────┘      └──────────────────────┘     └────────────────────┘
          │
          │ 命令/查询
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Application Services                                 │
│  Ingest Service · Learning Service · Retrieval/RAG · Agent Orchestrator     │
└─────────┬───────────────────┬─────────────────────┬─────────────────────────┘
          │                   │                     │
          ▼                   ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐
│  Job Queue      │  │  LLM Gateway    │  │  Policy Engine      │
│  parse/embed/   │  │  routing/budget │  │  ACL · DLP · model  │
│  learn/notify   │  │  fallback       │  │  data residency     │
└────────┬────────┘  └─────────────────┘  └─────────────────────┘
         │
         ▼ Workers (水平扩展)
┌─────────────────────────────────────────────────────────────────────────────┐
│  Parse Worker · Embed Worker · Learn Worker · Notify Worker · GC Worker     │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────┬──────────────┬──────────────┬──────────────┬─────────────────┐
│ PostgreSQL   │ Object Store │ Vector DB    │ OpenSearch*  │ Redis           │
│ 元数据/ACL/  │ 原文/导出    │ chunk/卡片   │ 关键词/日志* │ 会话/限流/队列  │
│ 审计/任务    │ (S3 兼容)    │ (Qdrant)     │ 可选         │                 │
└──────────────┴──────────────┴──────────────┴──────────────┴─────────────────┘

* OpenSearch/Elasticsearch 可选；MVP 可用 Postgres FTS + 向量混合检索。
```

### 3.1 关键请求路径

**上传**

```
Client → Gateway(AuthN)
  → Ingest API 校验租户配额/MIME/大小
  → 预签名或直传对象存储
  → 写 UploadJob(tenant_id, workspace_id, status=uploaded)
  → 投递 parse 队列 → embed →（策略允许则）learn
  → 事件总线：DocumentIndexed / LearningReady
  → （企业）发布审批流可选
```

**问答（强制先鉴权过滤）**

```
Client → Gateway(AuthN)
  → 解析 AuthContext(tenant, user, roles, workspace scope)
  → Policy：可得 document_id 集合（或 ACL filter 表达式）
  → Hybrid Search(向量 ∩ ACL filter ∩ workspace filter)
  → Rerank → Prompt(证据) → LLM Gateway
  → 引用校验 → 审计 AnswerEvent → 流式返回
```

**学习总结**

```
DocumentIndexed 事件
  → Learn Worker 拉全文/分章（仍带 tenant）
  → LLM Gateway（按敏感级选模型）
  → 写 LearningArtifact(draft)
  → 若 workspace 策略=auto_publish → published
    否则等待 Editor 确认 / 审批
  → 知识卡片向量化（仅 published 可被默认检索，可配置）
```

---

## 4. 部署与拓扑

### 4.1 环境 Profile

| Profile | 适用 | 差异 |
|---------|------|------|
| `personal` | 单人本机 | 单租户固定 ID；OIDC 可换本地用户；MinIO/本地盘；单副本 |
| `team` | 小团队 | 多空间；基础 RBAC；Docker Compose / 单 K8s ns |
| `enterprise` | 企业 | SSO、多副本、KMS、审批、连接器、专有网络 |

> 代码与 Schema 始终按 enterprise 模型；personal 只是配置收缩。

### 4.2 推荐运行时（企业）

- **编排**：Kubernetes
- **入口**：Ingress + API Gateway（限流、JWT 校验）
- **密钥**：云 KMS / Vault；禁止明文密钥进镜像
- **网络**：LLM 出口可走企业代理；敏感租户可强制私有模型 VPC
- **备份**：Postgres PITR；对象存储版本控制；向量库定期快照

### 4.3 目录/服务边界（实现）

```
/
├── apps/
│   ├── web/                 # Next.js（用户端）
│   ├── admin/               # 管理端（可同 app 分路由）
│   ├── api-gateway/         # BFF / 公共 API
│   └── workers/             # 异步消费者
├── services/                # 若模块化单体可先合仓分 package
│   ├── identity/
│   ├── ingest/
│   ├── learning/
│   ├── retrieval/
│   ├── agent/
│   ├── policy/
│   └── audit/
├── packages/
│   ├── domain/              # 实体、ID、错误码
│   ├── storage/             # S3/本地抽象
│   ├── llm/                 # Provider 抽象
│   └── observability/
├── deploy/
│   ├── compose/             # personal/team
│   ├── helm/                # enterprise
│   └── terraform/           # 可选基础设施
├── data/                    # 仅 local profile
└── docs/
```

---

## 5. 技术选型（企业默认）

| 层级 | 企业默认 | 个人/团队简化 | 说明 |
|------|----------|---------------|------|
| 前端 | **Next.js** + 组件库 | 同左（可减管理台） | 上传、报告、对话、权限感知 |
| API | FastAPI（Python）或 NestJS | FastAPI | RAG 生态优先 Python 时选 FastAPI |
| 认证 | OIDC（Keycloak / 云 IdP） | 本地账号 / Auth.js | 企业必须 SSO |
| 元数据库 | **PostgreSQL** | 同左（可单机） | 不再以 SQLite 为企业主路径 |
| 对象存储 | **S3 兼容**（AWS S3 / MinIO / OSS） | MinIO 或本地适配器 | 上传直传 + 服务端处理 |
| 向量库 | **Qdrant**（集群） | Qdrant 单机 | payload 必含 tenant/workspace/acl 字段 |
| 关键词检索 | Postgres FTS 或 OpenSearch | Postgres FTS | 混合检索 |
| 队列 | Redis Streams / NATS / RabbitMQ | Redis | 任务可重试、死信 |
| 缓存 | Redis | Redis | 会话、限流、热点 ACL |
| LLM 网关 | 自建路由 + 预算 | 直连兼容 API | 模型路由、降级、审计 |
| 观测 | OpenTelemetry + Prometheus + Grafana + Loki | 结构化日志 | 企业要指标与追踪 |
| LLM 追踪 | Langfuse / 自建 | 可选 | prompt/代价/质量 |
| 前端上传 | 直传对象存储（预签名 URL） | 可经 API 中转 | 减网关带宽压力 |

### 5.1 配置示例（企业）

```yaml
profile: enterprise

tenancy:
  mode: multi  # personal 时为 single + default_tenant_id

auth:
  type: oidc
  issuer: ${OIDC_ISSUER}
  audience: kb-agent

db:
  postgres_url: ${DATABASE_URL}

storage:
  type: s3
  bucket: kb-documents
  kms_key_id: ${KMS_KEY_ID}

vector:
  type: qdrant
  url: ${QDRANT_URL}
  collection: kb_chunks_v1

queue:
  broker: redis://${REDIS_URL}

llm_gateway:
  routes:
    - match: { sensitivity: [L1, L2] }
      provider: openai_compatible
      model: deepseek-chat
    - match: { sensitivity: [L3, L4] }
      provider: ollama_vpc
      model: qwen2.5-72b

learning:
  auto_on_ingest: true
  publish_mode: approval  # auto | approval
  write_knowledge_cards: true

quota:
  max_storage_gb_per_tenant: 500
  max_embed_pages_per_day: 100000
  max_llm_tokens_per_day: 5000000
```

---

## 6. 数据架构

### 6.1 核心表（均含租户）

**tenants / users / memberships / roles / workspaces / workspace_members**

标准组织与成员关系。

**documents**

| 字段 | 说明 |
|------|------|
| id, tenant_id, workspace_id | 归属 |
| title, mime, checksum, size | 基础 |
| object_key | 对象存储键 |
| sensitivity | L1–L4 |
| status | draft/processing/indexed/published/archived/failed |
| created_by, updated_at | 审计 |

**document_acl**

| 字段 | 说明 |
|------|------|
| document_id, tenant_id | |
| principal_type | user / group / role / workspace_all |
| principal_id | |
| permission | read / write / admin |

**upload_jobs / ingest_tasks / learning_artifacts / knowledge_cards / insights**

与个人版能力对应，但全部带 `tenant_id`、`workspace_id`；学习产物增加 `state: draft|approved|published|rejected`。

**conversations / messages / answer_citations**

会话与引用；引用只存有权访问时可见的 chunk 快照元数据。

**audit_events**

| 字段 | 说明 |
|------|------|
| id, tenant_id, actor_id | |
| action | login/upload/search/answer/learn/export/delete... |
| resource_type, resource_id | |
| ip, user_agent, request_id | |
| detail jsonb | 不含密钥；可含 token 用量 |
| created_at | 只追加 |

**usage_ledger**

按租户计量：存储字节、embed tokens、llm tokens、任务次数 → 配额与账单。

### 6.2 向量 Payload 强制字段

```json
{
  "tenant_id": "t_xxx",
  "workspace_id": "w_xxx",
  "document_id": "d_xxx",
  "chunk_id": "c_xxx",
  "acl_hash": "…",
  "sensitivity": "L2",
  "status": "published"
}
```

检索过滤器示例：`tenant_id = ? AND workspace_id IN (?) AND status = published AND ...`  
**禁止**拉取全库再在应用层丢弃无权限命中（防侧信道与泄漏）。

### 6.3 对象存储键规范

```
s3://{bucket}/{tenant_id}/{workspace_id}/{document_id}/raw/{filename}
s3://{bucket}/{tenant_id}/{workspace_id}/{document_id}/derived/text.json
s3://{bucket}/{tenant_id}/exports/{export_id}.zip
```

### 6.4 专题文档（P0 已展开）

| 专题 | 文档 |
|------|------|
| 完整 ER、状态机、切块、版本、ACL↔向量、幂等、embedding 版本 | [`data-model.md`](./data-model.md) |
| OpenAPI 风格 API、错误码、权限矩阵、事件 | [`api-contracts.md`](./api-contracts.md) |

**ACL↔向量（摘要）**：向量 payload 带 `acl_hash`；ACL 变更后异步 patch；检索必须「向量 filter + DB ACL 二次校验」。  
**文档版本（摘要）**：`documents` + `document_versions`；内容变更升版本，旧版 `superseded`。  
**切块/超长学习（摘要）**：默认 800/120 tokens；学习 map-reduce 分章再归并。

---

## 7. 安全、合规与策略

1. **认证**：企业 SSO（OIDC/SAML）；服务间 mTLS 或 JWT
2. **授权**：RBAC（角色）+ 文档 ACL；Agent 工具调用前二次授权
3. **DLP**：上传/提示词可过敏感信息规则（正则/分类器）；命中则脱敏或阻断
4. **模型路由**：按 `sensitivity` 与租户策略选择云端或私有模型
5. **加密**：对象存储 SSE-KMS；DB TDE/磁盘加密；传输 TLS1.2+
6. **数据驻留**：租户级 region 绑定；禁止跨区向量复制（可配置）
7. **删除权**：文档删除 → 队列表/向量/对象/学习产物/引用的级联或软删+GC
8. **提示词注入防护**：工具白名单、输出 schema 校验、不可见系统策略与用户内容隔离
9. **供应链**：镜像签名、依赖扫描、最小权限 IAM

---

## 8. 前端（企业）

### 8.1 应用结构

| 模块 | 功能 |
|------|------|
| 登录 / SSO 回调 | OIDC |
| 空间切换器 | 租户内多 Workspace |
| 知识库 | 上传、列表、状态、ACL 管理入口 |
| 学习报告 | 草稿/已发布、审批、修订 |
| 对话 | 流式回答、引用抽屉、范围选择器 |
| 管理台 | 成员、角色、配额、连接器、审计导出 |
| 设置 | 模型策略、自动学习开关、发布模式 |

### 8.2 UX 硬性要求

- 任何列表/搜索结果必须已是权限过滤后的视图
- 上传展示分阶段进度：上传 → 扫描 → 解析 → 索引 → 学习 → 发布
- 无权限资源统一 404（防存在性探测），审计记 403 详情仅管理员可见

---

## 9. Agent 与工具治理

| 工具 | 说明 | 权限 |
|------|------|------|
| `search_knowledge` | ACL 内混合检索 | Viewer+ |
| `get_document` | 取有权文档 | Viewer+ |
| `get_learning_report` | 已发布报告；草稿需 Editor | 视状态 |
| `learn_summarize` | 触发重学 | Editor+ |
| `review_summarize` | 批量复习 | Viewer+（只读产出） |
| `upload_document` | 创建上传意图 | Editor+ |
| `manage_acl` | 改权限 | Workspace Admin |
| `export_audit` | 导出审计 | Auditor/Admin |

约束：

- 最大工具步数、最大跨文档数、最大导出量
- 高危工具（删库、改 ACL、导出）需 step-up 确认或管理员角色
- 每次工具调用写入 `agent_runs` + `audit_events`

---

## 10. 可观测性与 SLO

| SLO | 目标（示例） |
|-----|--------------|
| API 可用性 | 99.9% |
| 上传受理延迟 | P99 < 2s（不含大文件传输） |
| 入库完成（≤20MB 文本 PDF） | P95 < 5 min |
| 问答首 token | P95 < 3s（不含冷启动） |
| 跨租户泄漏事件 | **0** |

指标：队列积压、Worker 失败率、embedding/LLM 错误与费用、检索空结果率、引用校验失败率。

细则见 [`ops-slo-dr.md`](./ops-slo-dr.md)（配额、容量、告警、RPO/RTO、Runbook）。

---

## 11. 分阶段实施（企业模型从 Day 1）

### M0 — 架构基线

- [x] 企业级架构文档
- [ ] 领域模型与 `tenant_id` 规范冻结
- [ ] 仓库骨架、Helm/Compose、配置 profile
- [ ] 错误码、request_id、审计事件字典

### M1 — 身份、空间、上传入库

- [ ] OIDC 登录（personal 可用本地 IdP）
- [ ] Tenant/Workspace/RBAC 最小集
- [ ] 预签名上传 + Parse/Embed Worker
- [ ] Postgres + S3 + Qdrant（payload 带租户字段）
- [ ] 文档 ACL 最小实现（workspace_all / owner）

**验收**：两租户同名文档互不可见；越权问答返回空/拒绝。

### M2 — 学习总结 + 安全问答

- [ ] Learning Worker + draft/publish
- [ ] 知识卡片向量化
- [ ] ACL 过滤混合检索 + 引用
- [ ] LLM Gateway 初版（路由/计量）
- [ ] Next.js：上传、报告、对话

**验收**：学习报告审批流可关可开；引用不出权。

### M3 — Agent 编排与治理

- [ ] 工具白名单 + 鉴权
- [ ] 复习总结 / 对比等复合任务
- [ ] 配额与 usage_ledger
- [ ] 管理台：成员、配额、失败任务

### M4 — 企业加固

- [ ] 审批流、敏感分级、私有模型路由
- [ ] 连接器（至少 1 个企业网盘）
- [ ] OpenSearch（如需要）、审计导出、备份演练
- [ ] 渗透与租户隔离测试报告

### M5 — 规模与智能增强

- [ ] 多区域 / 只读副本
- [ ] 知识图谱、多模态
- [ ] 质量评测门禁接入 CI
- [ ] 成本优化（小模型摘要、缓存、批处理）

---

## 12. 从个人版平滑到企业版

| 能力 | 做法 |
|------|------|
| 单人使用 | `profile=personal`，`tenant_id=default`，隐藏空间切换 |
| 升级团队 | 启用多 workspace + 邀请成员 |
| 升级企业 | 接 SSO、KMS、审批、配额、连接器 |
| 数据迁移 | 对象键与向量 payload 已含租户，迁移主要是 IdP 与密钥 |

**禁止路径**：先做无租户 SQLite 个人版，再「加租户字段」——成本远高于 Day 1 就带 `tenant_id`。

---

## 13. 质量保障

| 类型 | 内容 |
|------|------|
| 单元 | ACL 判定、过滤器构造、学习 JSON schema |
| 集成 | 双租户隔离、上传→学习→问答 |
| 安全 | 越权用例集、提示词注入、导出边界 |
| 性能 | 检索 P95、队列积压下的背压 |
| 评测 | 学习忠实度、Recall@K、引用正确率 |

---

## 14. 风险与对策

| 风险 | 对策 |
|------|------|
| 权限漏过滤导致串租 | 向量侧强制 filter；集成测试红线；代码审查清单 |
| LLM 成本失控 | 配额、路由小模型、缓存学习产物、异步限流 |
| 大文件/坏 PDF 拖垮 Worker | 超时、隔离队列、熔断、毒消息进 DLQ |
| 审批降低体验 | 空间级策略：个人空间 auto，合规空间 approval |
| 供应商锁定 | Provider 接口 + 评价集回归 |

---

## 15. 近期行动清单

1. 冻结组织模型：Tenant / Workspace / ACL
2. 选定 IdP 与对象存储（开发用 Keycloak + MinIO 即可）
3. 落地 Postgres schema（全表 `tenant_id`）
4. 竖切：**租户 A 上传 → 学习 → 问答**；租户 B 不可见
5. 再补审批、配额、连接器与管理台

---

## 16. 开放决策

| 决策项 | 选项 | 默认建议 |
|--------|------|----------|
| API 语言 | Python FastAPI / Node Nest | **Python FastAPI**（RAG 生态） |
| 前端 | Next.js | **Next.js**（企业默认，不再以 Streamlit 为主） |
| 多租户模式 | 库隔离 / Schema 隔离 / 行级隔离 | **行级隔离 + 向量 payload 过滤**（起步）；高安全租户可独立 collection |
| 发布策略 | 自动 / 审批 | **空间可配置，默认 auto，合规空间 approval** |
| 向量 | Qdrant / pgvector | **Qdrant** |
| 队列 | Redis / NATS / RabbitMQ | **Redis Streams 或 NATS** |
| 首发形态 | 私有化 / 专有云 / 多租户 SaaS | **先私有化/专有云，模型预留 SaaS** |

---

## 17. 术语

| 术语 | 含义 |
|------|------|
| Tenant | 租户，最顶层隔离单位 |
| Workspace | 租户内空间/知识域 |
| ACL | 文档访问控制列表 |
| LLM Gateway | 模型路由、预算、审计入口 |
| LearningArtifact | 学习总结产物（可草稿/发布） |
| KnowledgeCard | 可检索知识卡片 |
| Profile | personal/team/enterprise 部署配置 |

---

## 18. 设计审阅：遗漏与待补清单

> 审阅结论：企业主干（多租户、异步、ACL、学习、治理）方向正确，可指导立项；但若直接开工 M1，以下缺口会导致实现口径不一致或后期返工。按优先级排列。

### 18.1 P0 — 开工前必须补清

| # | 遗漏项 | 状态 | 落点 |
|---|--------|------|------|
| 1 | **完整 API 契约** | 已补草案 | [`api-contracts.md`](./api-contracts.md) |
| 2 | **完整 Schema / ER** | 已补草案 | [`data-model.md`](./data-model.md) |
| 3 | **ACL 变更如何同步向量** | 已定策略 | `data-model.md` §4 |
| 4 | **文档版本与重传** | 已定 | `data-model.md` §3 / §9 |
| 5 | **事件与队列语义** | 已定 Outbox | `data-model.md` §8；`api-contracts.md` §10 |
| 6 | **切块与超长文档学习** | 已定 | `data-model.md` §3 / §6 |
| 7 | **幂等与去重** | 已定 | `data-model.md` §5 / §14；上传 API Idempotency-Key |
| 8 | **Embedding 模型升级** | 已定字段与重建 | `data-model.md` §3 / §10 |

> 仍待实现阶段产出：可运行 OpenAPI YAML、Alembic migration、契约测试。

### 18.2 P1 — M2/M3 前应补

| # | 遗漏项 | 状态 | 说明 / 落点 |
|---|--------|------|-------------|
| 9 | **用户组 / SCIM** | 已补 | [`connectors-and-scim.md`](./connectors-and-scim.md) §2.1、§3 |
| 10 | **服务账号与 API Key** | 已补 | `connectors-and-scim.md` §2.2、§8 |
| 11 | **通知渠道** | 待补 | 学习完成/审批待办/任务失败：站内信、邮件、Webhook/Slack 未设计 |
| 12 | **会话与记忆策略** | 待补 | 对话保留多久、可否跨会话记忆、敏感会话加密与清理 |
| 13 | **引用深链** | 待补 | 点回 PDF 页码/段落锚点；仅有 chunk 不够产品化 |
| 14 | **反馈闭环** | 待补 | 点赞/点踩、错误引用举报 → 进入评测集与重排特征 |
| 15 | **配额细化** | 已补 | [`ops-slo-dr.md`](./ops-slo-dr.md) §3 |
| 16 | **审批流引擎边界** | 待补 | 「approval」是内置简单状态机还是对接企业 BPM（飞书/钉钉/ServiceNow） |
| 17 | **连接器同步模型** | 已补 | `connectors-and-scim.md` §4–§7 |
| 18 | **多语言 / i18n** | 待补 | UI 与分词/嵌入对中英混合外的语言策略 |
| 19 | **Feature Flag** | 部分 | 连接器灰度见 `connectors-and-scim.md` §12；全局 FF 仍待专文 |

### 18.3 P2 — 企业加固期应补

| # | 遗漏项 | 状态 | 说明 / 落点 |
|---|--------|------|-------------|
| 20 | **DR：RPO/RTO** | 已补 | [`ops-slo-dr.md`](./ops-slo-dr.md) §7 |
| 21 | **容量模型** | 已补 | `ops-slo-dr.md` §4 |
| 22 | **网络隔离部署手册** | 待补 | 纯离线/专有云安装、证书、模型包导入 |
| 23 | **法务与分包清单** | 待补 | DPA、子处理方（LLM 厂商）、日志留存年限 |
| 24 | **Runbook** | 已补大纲 | `ops-slo-dr.md` §9 |
| 25 | **无障碍与设计系统** | 待补 | 企业采购常审 a11y；前端规范未写 |
| 26 | **SDK / 公开 API 版本策略** | 待补 | `/v1` 兼容、弃用窗口 |
| 27 | **计费** | 待补 | 有 usage_ledger，无账单/发票/套餐（若走 SaaS） |
| 28 | **搜索可配置性** | 待补 | 权重、过滤 DSL、同义词、租户级相关度调参 |
| 29 | **内容安全** | 待补 | 病毒扫描钩子有了，缺恶意宏/加密 PDF/密码文件处理策略 |
| 30 | **Collection 实体** | 待补 | 组织图提了 Collection，后文未展开与 Workspace/标签关系 |

### 18.4 已覆盖较好（无需重开题）

- 多租户与「禁止先检后滤」
- 上传 → 解析 → 学习 → 发布主路径
- LLM Gateway / 敏感级路由意识
- Profile 收缩（personal/team/enterprise）
- SLO 与审计方向
- Agent 工具权限分层

### 18.5 建议的文档补丁顺序

1. [x] `docs/api-contracts.md`
2. [x] `docs/data-model.md` + 主文档 §6.4 摘要
3. [x] `docs/ops-slo-dr.md`（配额细则、RPO/RTO、Runbook 大纲）
4. [x] `docs/connectors-and-scim.md`（SCIM、服务账号、连接器同步）
5. [ ] （可选）通知 / 会话记忆 / 审批 BPM 专文

---

## 19. 文档维护

- 企业架构变更需同步更新第 3/5/6/7/11 节
- 个人版体验变更不得破坏 `tenant_id` 与 ACL 不变量
- 关闭第 18 节某遗漏项时，应落到对应专题文档或主文档正文，并在清单中勾掉
