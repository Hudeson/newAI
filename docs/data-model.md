# 数据模型与状态机

> 对应主文档 P0：完整 Schema / ER、文档版本、ACL↔向量一致性、切块、幂等、Embedding 版本。  
> 约定：所有业务表（除平台级字典外）必须含 `tenant_id`；删除默认软删 + GC。

---

## 1. ER 总览

```
tenants ─┬─ workspaces ─┬─ documents ─┬─ document_versions ─┬─ chunks
         │              │             │                     └─ vector points (Qdrant)
         │              │             ├─ document_acl
         │              │             ├─ learning_artifacts ─┬─ knowledge_cards
         │              │             │                      └─ insights
         │              │             └─ upload_jobs ── ingest_tasks
         │              └─ workspace_members
         ├─ users ── memberships ── roles
         ├─ groups ── group_members
         ├─ api_keys
         ├─ conversations ── messages ── answer_citations
         ├─ agent_runs ── agent_tool_calls
         ├─ outbox_events
         ├─ audit_events
         └─ usage_ledger
```

ID 策略：应用层 UUID/ULID（字符串）；对外 API 不暴露自增整数。

---

## 2. 组织与身份

### tenants

| 列 | 类型 | 说明 |
|----|------|------|
| id | uuid pk | |
| name | text | |
| slug | text unique | |
| status | enum | active / suspended / deleted |
| region | text | 数据驻留 |
| settings | jsonb | 默认模型、发布策略等 |
| created_at | timestamptz | |

### users

| 列 | 类型 | 说明 |
|----|------|------|
| id | uuid pk | |
| tenant_id | uuid | 可空仅对平台超管；业务用户必填 |
| email | citext | 租户内唯一 |
| display_name | text | |
| status | enum | active / disabled |
| idp_subject | text | OIDC sub |
| created_at | timestamptz | |

唯一：`(tenant_id, email)`、`(tenant_id, idp_subject)`。

### memberships / roles

- `memberships(tenant_id, user_id, role)`：tenant_admin / member / auditor …
- 平台角色另表或 `users.platform_role`

### workspaces / workspace_members

| workspaces | 说明 |
|------------|------|
| id, tenant_id, name, slug | |
| publish_mode | auto / approval |
| default_sensitivity | L1–L4 |
| settings | jsonb |

`workspace_members(workspace_id, user_id, role)`：admin / editor / viewer。

### groups / group_members

企业目录组；ACL `principal_type=group` 指向 `groups.id`。  
后续 SCIM 写入本组。详见 [`connectors-and-scim.md`](./connectors-and-scim.md)。

### api_keys

| 列 | 说明 |
|----|------|
| id, tenant_id, name | |
| key_hash | 仅存哈希 |
| scopes | text[] |
| workspace_id | 可选收窄 |
| expires_at, revoked_at | |

---

## 3. 文档、版本、切块

### documents（逻辑文档头）

| 列 | 说明 |
|----|------|
| id, tenant_id, workspace_id | |
| title | |
| current_version_id | 指向最新版本 |
| sensitivity | L1–L4 |
| status | 见状态机 |
| checksum_current | 当前版本内容哈希 |
| created_by, created_at, updated_at | |
| deleted_at | 软删 |

唯一建议：`(tenant_id, workspace_id, checksum_current)` **可选**去重（策略可配：拒绝 / 复用 / 允许重复）。

### document_versions

| 列 | 说明 |
|----|------|
| id, tenant_id, document_id | |
| version_no | 从 1 递增 |
| object_key | raw 对象键 |
| mime, size_bytes, checksum | |
| parser | 解析器名/版本 |
| embedding_model | 本版使用的嵌入模型 |
| embedding_version | 如 `bge-m3@1` |
| status | pending / parsing / embedding / indexed / failed / superseded |
| error_code, error_message | |
| created_by, created_at | |

唯一：`(document_id, version_no)`。

### chunks

| 列 | 说明 |
|----|------|
| id, tenant_id, document_id, version_id | |
| ordinal | 顺序 |
| content | text |
| token_count | int |
| heading_path | text | 如 `第3章/3.2` |
| page_from, page_to | 可选，PDF 深链 |
| anchor | 可选段落锚 |
| content_hash | |
| vector_point_id | Qdrant point id |
| acl_hash | 写入时文档 ACL 指纹 |
| status | active / superseded / deleted |

索引：`(tenant_id, document_id, version_id, ordinal)`。

### 切块默认参数

| 参数 | 默认 | 说明 |
|------|------|------|
| chunk_size | 800 tokens | 中文可按字近似 |
| chunk_overlap | 120 | ~15% |
| split | 标题/段落优先，再硬切 | |
| 表格/代码 | 尽量整块保留 | |
| 超长学习 | 分章 map-reduce | 单章失败不阻断其它章 |

---

## 4. ACL 与向量一致性

### document_acl

| 列 | 说明 |
|----|------|
| id, tenant_id, document_id | |
| principal_type | user / group / role / workspace_all |
| principal_id | workspace_all 时可空或填 workspace_id |
| permission | read / write / admin |
| created_at | |

唯一：`(document_id, principal_type, principal_id, permission)`。

### acl_hash 计算

```
acl_hash = sha256( canonical_json( sorted ACL rows of document ) )
```

### 同步策略（强制）

1. **写入向量时**：payload 带 `tenant_id/workspace_id/document_id/version_id/acl_hash/status/sensitivity`
2. **ACL 变更时**：
   - 同步重算 `acl_hash`
   - 异步任务批量 patch Qdrant payload（或按 version 重建）
   - 任务完成前，检索路径：**向量召回后必须用 Postgres ACL 二次校验**（防窗口期串权）
3. **文档/版本 superseded**：chunk.status + 向量 payload.status 更新；检索默认 `status=active AND version_id=current`

**禁止**：无 filter 的全局 top-k 后再丢弃。

---

## 5. 上传与摄入任务

### upload_jobs

| 列 | 说明 |
|----|------|
| id, tenant_id, workspace_id | |
| document_id, version_id | 创建后回填 |
| filename, mime, size_bytes | |
| object_key | |
| checksum | 客户端或服务端计算 |
| status | 见状态机 |
| progress | 0–100 |
| idempotency_key | 客户端传入，租户内唯一 |
| error_code, error_message | |
| created_by, created_at, updated_at | |

唯一：`(tenant_id, idempotency_key)` WHERE key IS NOT NULL。

### ingest_tasks

| 列 | 说明 |
|----|------|
| id, tenant_id, upload_job_id, version_id | |
| type | parse / embed / learn / acl_sync / gc |
| status | queued / running / succeeded / failed / dead |
| attempt, max_attempts | |
| available_at | 延迟重试 |
| locked_by, locked_at | |
| input jsonb, result jsonb | |
| idempotency_key | 如 `embed:{version_id}` |

---

## 6. 学习产物

### learning_artifacts

| 列 | 说明 |
|----|------|
| id, tenant_id, document_id, version_id | |
| state | draft / approved / published / rejected |
| summary | text |
| outline | jsonb |
| key_points | jsonb | `[{point, evidence_chunk_ids[]}]` |
| suggested_tags | text[] |
| open_questions | jsonb |
| model, prompt_version | |
| created_at, published_at, published_by | |

同一 `version_id` 可有多轮学习；`is_current` 标记当前有效。

### knowledge_cards

| 列 | 说明 |
|----|------|
| id, tenant_id, document_id, artifact_id | |
| title, body | |
| tags | text[] |
| vector_point_id | |
| status | active / archived |

### insights（增量学习，P1）

新版本 vs 旧知识：`addition | conflict | merge_candidate` + 双方证据。

### 超长文档学习算法

```
for section in sections:
  partial = summarize(section)          # map
merge(partials) → learning_artifact     # reduce
key_points.evidence_chunk_ids 必须落在本 version 的 chunks 内
```

---

## 7. 对话与 Agent

### conversations / messages

- conversations: tenant, workspace_scope[], user_id, title, created_at
- messages: role, content, token_usage, created_at
- answer_citations: message_id, chunk_id, document_id, quote, page_from, score

### agent_runs / agent_tool_calls

| agent_runs | 说明 |
|------------|------|
| id, tenant_id, conversation_id, user_id | |
| status | running / succeeded / failed / cancelled |
| steps, model | |

| agent_tool_calls | 说明 |
|------------------|------|
| run_id, tool_name | |
| args jsonb, result jsonb | 脱敏后 |
| allowed | bool | 鉴权结果 |
| latency_ms | |

---

## 8. Outbox、审计、计量

### outbox_events

可靠事件投递（与业务同事务写入）：

| 列 | 说明 |
|----|------|
| id, tenant_id | |
| type | DocumentVersionIndexed / LearningReady / AclChanged / … |
| aggregate_type, aggregate_id | |
| payload jsonb | |
| status | pending / published / failed |
| created_at, published_at | |

消费者以 `(type, id)` 幂等处理。

### audit_events

只追加；见主文档字段。高敏 detail 可外置对象存储。

### usage_ledger

| 列 | 说明 |
|----|------|
| id, tenant_id, workspace_id | |
| meter | storage_bytes / embed_tokens / llm_tokens / job_count |
| quantity | numeric |
| period_start | 聚合桶 |
| labels jsonb | model, operation |

---

## 9. 状态机

### 9.1 upload_jobs

```
created → uploaded → scanning → parsing → embedding → learning → ready
                                              ↘ failed ↔ (retry) 
ready / failed 可 delete → deleted
```

说明：`learning` 失败时若索引已完成，可落 `ready_degraded`（可检索，学习待重试）——可选状态。

### 9.2 document_versions

```
pending → parsing → embedding → indexed
                      ↘ failed
indexed → superseded（被更新版本替换）
```

### 9.3 documents.status（聚合视图）

由 current_version + learning 状态推导或冗余缓存：

`draft | processing | indexed | published | archived | failed`

企业 `publish_mode=approval` 时：indexed 后学习 draft，审批通过才 `published`（可被默认检索）。

### 9.4 learning_artifacts.state

```
draft → approved → published
draft → rejected
published → (relearn 产生新 draft，旧版可 archive)
```

### 9.5 ingest_tasks

```
queued → running → succeeded
              ↘ failed → queued（退避）→ dead
```

---

## 10. 向量 Payload 规范

```json
{
  "tenant_id": "t_...",
  "workspace_id": "w_...",
  "document_id": "d_...",
  "version_id": "v_...",
  "chunk_id": "c_...",
  "acl_hash": "sha256:...",
  "sensitivity": "L2",
  "status": "active",
  "embedding_version": "bge-m3@1",
  "point_type": "chunk"
}
```

知识卡片：`point_type=card`，同样强制租户字段。

检索 filter 最小集：

```
tenant_id = $t
AND workspace_id IN $scopes
AND status = "active"
AND embedding_version = $current
AND sensitivity IN $allowed
```

再加应用层 ACL 二次校验。

---

## 11. 对象存储键

```
{tenant_id}/{workspace_id}/{document_id}/v{version_no}/raw/{filename}
{tenant_id}/{workspace_id}/{document_id}/v{version_no}/derived/text.json
{tenant_id}/{workspace_id}/{document_id}/v{version_no}/derived/learning.json
{tenant_id}/exports/{export_id}.zip
```

---

## 12. 索引与约束清单（实现时必建）

- 所有表：`(tenant_id)` 索引或复合前缀索引
- `upload_jobs(tenant_id, idempotency_key)` unique
- `document_versions(document_id, version_no)` unique
- `chunks(version_id, ordinal)` unique
- `document_acl(document_id, principal_type, principal_id, permission)` unique
- `outbox_events(status, created_at)` 供 publisher 扫描
- `ingest_tasks(status, available_at)` 供 worker 抢占

---

## 13. 迁移与种子

- 工具：Alembic（Python）或等效
- 禁止无租户迁移；新表评审检查表含 `tenant_id`
- `profile=personal` 种子：预置 `tenant=default`、`workspace=default`、owner membership

---

## 14. 开放策略默认值

| 策略 | 默认 |
|------|------|
| 同 checksum 再上传 | 返回已有 document（幂等），不建新版本 |
| 内容变化再上传 | 新 version_no，旧 version superseded |
| 学习失败 | 文档仍可按 indexed 检索；学习可重试 |
| ACL 变更 | 异步 patch 向量；窗口期二次校验 |
| 硬删 | 仅 GC Worker 在软删 TTL（默认 30 天）后执行 |
