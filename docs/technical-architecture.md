# 完整技术架构

> 企业级知识库 Agent 平台的技术架构总览（汇总版）。  
> 细则见：[`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md)、[`data-model.md`](./data-model.md)、[`api-contracts.md`](./api-contracts.md)、[`ops-slo-dr.md`](./ops-slo-dr.md)、[`connectors-and-scim.md`](./connectors-and-scim.md)。

---

## 1. 架构愿景

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        企业级知识库 Agent 平台                            │
│                                                                         │
│   多租户文档中台  ×  权限可控 RAG  ×  自动学习总结  ×  可审计 Agent      │
└─────────────────────────────────────────────────────────────────────────┘
```

**一句话**：在租户与 ACL 边界内，完成「上传/同步 → 解析索引 → 学习总结 → 带引用问答 / Agent 编排」，并具备企业治理（SSO、配额、审计、连接器、DR）。

**部署剖面（同一代码）**

| Profile | 形态 |
|---------|------|
| `personal` | 单租户、可本地账号、单机 Compose |
| `team` | 多空间、基础 RBAC、单集群 |
| `enterprise` | SSO/SCIM、多副本、KMS、审批、连接器、专有网络 |

---

## 2. 系统上下文（C4 L1）

```
                 ┌──────────────┐
                 │ 企业 IdP     │  OIDC / SAML / SCIM
                 │ (Keycloak/   │
                 │  Entra/Okta) │
                 └──────┬───────┘
                        │
 ┌──────────┐    ┌──────▼───────┐    ┌─────────────────┐
 │ 终端用户  │───▶│ 本平台       │───▶│ LLM 供应商       │
 │ 管理员    │    │ KB Agent    │    │ (云/私有均可)    │
 │ 集成方    │    └──────┬───────┘    └─────────────────┘
 └──────────┘           │
                        ├──────────▶ 对象存储 (S3/MinIO/OSS)
                        ├──────────▶ 企业内容源 (SharePoint/Drive/…)
                        └──────────▶ 通知渠道 (邮件/Webhook，可选)
```

**信任边界**：浏览器/ SDK → TLS → 边缘网关；出站 LLM/连接器经代理与密钥托管；租户数据按 `tenant_id` 隔离。

---

## 3. 逻辑架构（C4 L2）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 体验层                                                                    │
│  Next.js Web（知识库/上传/学习报告/对话） · Admin Console · API SDK      │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │ HTTPS / SSE
┌───────────────────────────────────▼──────────────────────────────────────┐
│ 边缘层                                                                    │
│  Ingress · WAF · API Gateway（TLS、JWT/OIDC、限流、路由）                  │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────┐
│ 应用服务层（无状态，可水平扩展）                                           │
│                                                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
│  │ Identity    │ │ Ingest API  │ │ Retrieval   │ │ Agent       │        │
│  │ & Access    │ │ Upload/     │ │ Search/RAG  │ │ Orchestrator│        │
│  │ RBAC·ACL    │ │ Complete    │ │ Chat/SSE    │ │ Tools       │        │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
│  │ Learning    │ │ Policy      │ │ Admin/      │ │ Connector   │        │
│  │ Query API   │ │ Engine      │ │ Audit API   │ │ Mgmt API    │        │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘        │
│  ┌─────────────────────────────────────────────────────────────┐        │
│  │ LLM Gateway（路由 · 预算 · 降级 · 审计）                      │        │
│  └─────────────────────────────────────────────────────────────┘        │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │ 任务投递 / 事件
┌───────────────────────────────────▼──────────────────────────────────────┐
│ 异步执行层                                                                │
│  Queue（Redis Streams / NATS / RabbitMQ）                                 │
│  Workers: Parse · Embed · Learn · ACL-Sync · Notify · Connector · GC     │
│  Outbox Publisher（与 DB 同事务可靠投递）                                  │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────┐
│ 数据层                                                                    │
│  PostgreSQL（元数据/ACL/审计/任务）                                        │
│  Object Store（原文/派生）                                                 │
│  Qdrant（chunk/卡片向量，payload 含租户与 ACL 指纹）                       │
│  Redis（会话/限流/缓存） · OpenSearch（可选关键词）                         │
│  Vault/KMS（密钥）                                                         │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 技术栈

| 层 | 企业默认 | 说明 |
|----|----------|------|
| 前端 | **Next.js** | 用户端 + 管理台（可同仓分路由） |
| API | **FastAPI**（Python） | RAG 生态；亦可 Nest 但对齐契约 |
| 认证 | **OIDC** + **SCIM 2.0** | Keycloak / 云 IdP |
| 元数据 | **PostgreSQL** | 全表 `tenant_id` |
| 对象存储 | **S3 兼容** | MinIO / OSS / AWS S3 |
| 向量 | **Qdrant** | 强制 payload filter |
| 关键词 | Postgres FTS 或 OpenSearch | 混合检索 |
| 队列 | Redis Streams / NATS | 可重试、DLQ |
| 缓存 | Redis | 会话、限流、热点 ACL |
| LLM | OpenAI 兼容 API + Ollama | 经 LLM Gateway |
| Embedding | bge-m3 等 | 版本化字段 |
| 观测 | OTel + Prometheus + Grafana + Loki | Langfuse 可选 |
| 部署 | Compose（dev）/ **Helm + K8s**（企业） | |

---

## 5. 核心数据流

### 5.1 上传入库 + 学习

```
Client                API                 Object Store        Queue/Workers           PG / Qdrant
  │  presign            │                      │                    │                    │
  │────────────────────▶│ 校验配额/MIME/ACL     │                    │                    │
  │◀──── URL/job_id ────│                      │                    │                    │
  │  PUT 文件 ─────────────────────────────────▶│                    │                    │
  │  complete           │                      │                    │                    │
  │────────────────────▶│── enqueue parse ─────────────────────────▶│                    │
  │                     │                      │   parse            │── meta/chunks ────▶│
  │                     │                      │   embed            │── vectors ────────▶│
  │                     │                      │   learn            │── artifacts ──────▶│
  │  GET job/status     │◀────────── 进度/事件 ─┴────────────────────┘                    │
```

状态概要：`created → uploaded → parsing → embedding → learning → ready`（学习失败可 `ready_degraded`）。

### 5.2 安全问答（强制先鉴权）

```
问题 → AuthContext(tenant,user,roles,workspaces)
     → Policy：可得 document 集合 / ACL filter
     → Hybrid Search(向量 ∩ 关键词 ∩ filter)
     → 应用层 ACL 二次校验
     → Rerank → Prompt(证据) → LLM Gateway
     → 引用校验 → 审计 → SSE 流式返回
```

**禁止**无租户 filter 的全局检索后再丢弃。

### 5.3 连接器导入

```
Scheduler/Webhook → Connector Worker
  → list_changes(cursor) → fetch → 写入对象存储
  → 映射 ACL（owner_only / mapped / mirror_strict）
  → 进入与上传相同的 Ingest Pipeline
```

### 5.4 SCIM 供给

```
IdP ──SCIM──▶ /scim/v2/Users|Groups
              → users / groups / group_members
              → 停用即吊销会话；组变更触发 ACL 影响面重算
```

---

## 6. 领域与数据架构（摘要）

### 6.1 组织与权限

```
Tenant → Workspace → Document → DocumentVersion → Chunk
                 ↘ DocumentACL (user|group|role|workspace_all)
User / Group / Membership / Role
ServiceAccount / ApiKey
```

### 6.2 知识与任务

```
UploadJob → IngestTask(parse|embed|learn|acl_sync)
LearningArtifact (draft|approved|published|rejected)
KnowledgeCard → 向量
Conversation → Message → Citation
AgentRun → ToolCall
OutboxEvent / AuditEvent / UsageLedger
ConnectorInstance → SyncRun → ItemMap / DeadLetter
```

### 6.3 向量 Payload（强制）

```json
{
  "tenant_id": "...",
  "workspace_id": "...",
  "document_id": "...",
  "version_id": "...",
  "chunk_id": "...",
  "acl_hash": "...",
  "sensitivity": "L2",
  "status": "active",
  "embedding_version": "bge-m3@1",
  "point_type": "chunk"
}
```

ACL 变更：异步 patch `acl_hash` + **检索二次校验**。

### 6.4 对象键

```
{tenant}/{workspace}/{document}/v{n}/raw/...
{tenant}/{workspace}/{document}/v{n}/derived/...
```

完整 ER/状态机 → [`data-model.md`](./data-model.md)。

---

## 7. 服务组件职责

| 组件 | 职责 |
|------|------|
| **Identity & Access** | OIDC 回调、会话、RBAC、文档 ACL 判定、SCIM |
| **Ingest API** | 预签名上传、complete、任务查询、版本升版 |
| **Parse Worker** | PDF/DOCX/MD/HTML→文本；切块 |
| **Embed Worker** | Embedding 写入 Qdrant；模型版本标记 |
| **Learn Worker** | 摘要/大纲/要点/标签/卡片；超长 map-reduce |
| **Retrieval/RAG** | 混合检索、重排、提示组装、引用校验、SSE |
| **Agent Orchestrator** | 工具白名单、步数限制、二次授权、轨迹落库 |
| **LLM Gateway** | 按敏感级/租户路由、预算、降级、用量 |
| **Policy Engine** | 配额、发布模式、模型策略、数据驻留 |
| **Connector Mgmt/Worker** | 源站同步、游标、DLQ、身份映射 |
| **Admin/Audit** | 成员、配额、审计导出、失败任务 |
| **GC/Reconcile** | 软删清理、向量与 DB 对账 |

---

## 8. API 面（逻辑分组）

| 分组 | 示例 |
|------|------|
| 身份 | `GET /me`，workspaces，members |
| 上传 | `POST .../uploads/presign`，`complete`，`GET /upload-jobs/{id}` |
| 文档 | CRUD、versions、chunks、ACL |
| 学习 | GET/PATCH learning，publish/reject，relearn，review |
| 检索对话 | `POST /search`，conversations，SSE messages |
| Agent | `POST /agent/runs` |
| 管理 | usage、quotas、audit、jobs |
| SCIM | `/scim/v2/Users|Groups` |
| 连接器 | connectors CRUD、sync、runs、dead-letters |

完整契约 → [`api-contracts.md`](./api-contracts.md)。

---

## 9. 安全架构

```
┌─────────────┐   OIDC    ┌─────────────┐
│ IdP         │──────────▶│ API Gateway │── JWT 校验 / 限流
└─────────────┘           └──────┬──────┘
                                 │
                    AuthContext(tenant,user,roles,scopes)
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
         RBAC 角色          文档 ACL           工具二次授权
              │                  │                  │
              └──────────┬───────┴──────────────────┘
                         ▼
              Policy：配额 · 敏感级 · 模型路由 · 驻留
```

要点：

- 行级多租户 + 向量 payload 过滤  
- 密钥进 Vault/KMS；对象 SSE-KMS  
- DLP 钩子（上传/提示词）  
- 审计只追加；串租事件 = Sev-1  
- Agent 高危工具 step-up  

---

## 10. 部署架构

### 10.1 企业（Kubernetes）

```
                    Internet / 专线
                          │
                     Ingress/WAF
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
         web (Next)              api (FastAPI)×N
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
               workers×N          redis/nats         llm-gateway
                    │                 │
     ┌──────────────┼─────────────────┤
     ▼              ▼                 ▼
  PostgreSQL     Qdrant            S3/MinIO
  (主从/PITR)    (集群)            (+ 版本控制)
                     Vault/KMS
```

### 10.2 个人/团队

Docker Compose：`api + worker + web + postgres + qdrant + redis + minio`（+ 可选 keycloak）。

### 10.3 配置

`profile` + 环境变量 / Helm values：DB、S3、Qdrant、OIDC、LLM routes、配额、learning.publish_mode。

---

## 11. 可观测与 SLO（摘要）

| SLO | 目标 |
|-----|------|
| API 可用性 | 99.9% |
| 上传受理 P99 | < 2s |
| ≤20MB 入库 P95 | < 5min |
| 问答首 token P95 | < 3s |
| 跨租户泄漏 | **0** |

指标：队列积压、Worker 失败、LLM 错误/费用、空结果率、引用失败、配额拒绝、连接器 lag/DLQ。  
详册 → [`ops-slo-dr.md`](./ops-slo-dr.md)。

---

## 12. 灾备（摘要）

| 数据 | 策略 |
|------|------|
| Postgres | WAL + 日全量，PITR |
| 对象存储 | 版本控制 / 跨区复制 |
| Qdrant | 快照；可从原文重建 |
| 队列 | 非唯一真相；Outbox 在 DB |

企业默认：同城故障 RTO ≤15min；区域灾难 RPO ≤1h（合同可调）。

---

## 13. 集成架构

| 集成 | 协议 | 方向 |
|------|------|------|
| IdP | OIDC/SAML | 登录 |
| IdP | SCIM 2.0 | 用户/组供给 |
| LLM | OpenAI 兼容 HTTP | 出站 |
| Embedding | HTTP/本地 | 出站或侧车 |
| SharePoint/Drive/Confluence/S3 | 各厂商 API | 入站同步 |
| Webhook 通知 | HTTPS 签名 | 出站（P1） |

连接器与 SCIM → [`connectors-and-scim.md`](./connectors-and-scim.md)。

---

## 14. 仓库与模块边界

```
/
├── apps/
│   ├── web/              # Next.js
│   ├── api/              # FastAPI BFF/API
│   └── workers/          # 异步消费者
├── packages/ 或 services/
│   ├── identity/ · ingest/ · learning/ · retrieval/
│   ├── agent/ · policy/ · audit/ · connectors/ · llm/
│   └── shared/ domain · storage · observability
├── deploy/ compose/ · helm/ · terraform/
├── docs/                 # 本架构与专题
└── data/                 # 仅 local
```

---

## 15. 质量与隔离红线

| 红线 | 验证 |
|------|------|
| 双租户同名文档互不可见 | 自动化集成测试 |
| 越权问答为空/拒绝 | ACL 用例集 |
| 引用可回溯真实 chunk | 契约 + 评测 |
| 无 filter 检索不得合并上线 | Code review 清单 |
| SCIM 停用立即失效 | 供给测试 |

---

## 16. 演进路线（与里程碑对齐）

| 阶段 | 架构交付 |
|------|----------|
| M0 | 本文档体系、租户模型冻结 |
| M1 | 身份 + 上传入库 + 双租户隔离竖切 |
| M2 | 学习总结 + 安全问答 + LLM Gateway |
| M3 | Agent、配额、管理台、SCIM/服务账号、首个连接器 |
| M4 | 审批、敏感路由、更多连接器、DR 演练 |
| M5 | 多区域、图谱/多模态、成本优化 |

---

## 17. 文档索引

| 文档 | 内容 |
|------|------|
| [`technical-architecture.md`](./technical-architecture.md) | **本文件：完整技术架构总览** |
| [`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md) | 愿景、原则、计划、遗漏清单 |
| [`data-model.md`](./data-model.md) | ER、状态机、切块、ACL↔向量 |
| [`api-contracts.md`](./api-contracts.md) | API 契约、错误码、权限矩阵 |
| [`ops-slo-dr.md`](./ops-slo-dr.md) | 配额、SLO、告警、DR、Runbook |
| [`connectors-and-scim.md`](./connectors-and-scim.md) | SCIM、服务账号、连接器 |
| [`enterprise-vs-personal.md`](./enterprise-vs-personal.md) | 剖面对照 |
| [`checklist.md`](./checklist.md) | 实施勾选 |

---

## 18. 架构决策记录（ADR 摘要）

| 决策 | 选择 | 理由 |
|------|------|------|
| 多租户起步模式 | 行级隔离 + 向量 payload | 实现快；高安全租户可升独立 collection |
| 元数据库 | PostgreSQL 非 SQLite | 企业并发与 PITR |
| 前端 | Next.js 非 Streamlit 为主 | 权限/管理台/企业体验 |
| 检索鉴权 | Filter 先行 + 二次校验 | 防漏权与侧信道 |
| 学习与索引解耦 | 索引成功可检索，学习可失败重试 | 可用性 |
| 连接器默认 ACL | owner_only | 避免源站「公开」被放大成空间全员 |
| 个人版 | 同一模型 + profile 收缩 | 避免二次重构 |
