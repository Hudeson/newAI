# API 契约草案（OpenAPI 风格）

> 对应主文档 P0：完整 API 契约。  
> Base path：`/api/v1`  
> 认证：`Authorization: Bearer <OIDC access token>` 或 `X-API-Key`  
> 所有业务请求必须能解析出 `tenant_id`（来自 token claims 或密钥绑定）；禁止客户端传任意租户覆盖（除非平台超管接口）。

---

## 1. 约定

### 1.1 公共头

| Header | 说明 |
|--------|------|
| Authorization | Bearer JWT |
| X-Request-Id | 客户端可传；服务端必回 |
| Idempotency-Key | 写操作可选/上传必填建议 |
| X-Workspace-Id | 可选默认空间；多空间操作以 body 为准 |

### 1.2 公共错误体

```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "Daily LLM token quota exceeded",
    "details": { "meter": "llm_tokens", "limit": 5000000 },
    "request_id": "req_..."
  }
}
```

### 1.3 主要错误码

| code | HTTP | 说明 |
|------|------|------|
| unauthenticated | 401 | 未登录 |
| forbidden | 403 | 无权限（对外可映射为 not_found） |
| not_found | 404 | 资源不存在或无权限 |
| validation_error | 400 | 参数错误 |
| conflict | 409 | 幂等冲突/状态不允许 |
| unsupported_media | 415 | 文件类型不支持 |
| payload_too_large | 413 | 超过大小限制 |
| quota_exceeded | 429 | 配额 |
| rate_limited | 429 | QPS |
| job_failed | 422 | 任务终态失败（查询时） |
| internal_error | 500 | 内部错误 |

### 1.4 分页

`?cursor=...&limit=50` → `{ items, next_cursor }`

---

## 2. 身份与空间

### GET /me

返回当前用户、租户、角色、可访问 workspaces。

### GET /workspaces

列表当前租户下有权空间。

### POST /workspaces

Tenant Admin：创建空间。

```json
{ "name": "Research", "slug": "research", "publish_mode": "approval" }
```

### GET /workspaces/{workspace_id}/members

### PUT /workspaces/{workspace_id}/members/{user_id}

```json
{ "role": "editor" }
```

---

## 3. 上传与任务

### POST /workspaces/{workspace_id}/uploads/presign

申请预签名上传。

**Request**

```json
{
  "filename": "arch.pdf",
  "mime": "application/pdf",
  "size_bytes": 1048576,
  "checksum_sha256": "…",
  "idempotency_key": "client-ulid-…"
}
```

**Response 201**

```json
{
  "upload_job_id": "uj_...",
  "document_id": "d_...",
  "version_id": "v_...",
  "object_key": "t/w/d/v1/raw/arch.pdf",
  "upload": {
    "method": "PUT",
    "url": "https://minio/.../presigned",
    "headers": { "Content-Type": "application/pdf" },
    "expires_in": 900
  }
}
```

同 `idempotency_key` 重放：返回同一 job（200）。

### POST /workspaces/{workspace_id}/uploads/{upload_job_id}/complete

客户端直传完成后确认；服务端入队 `parse`。

**Response**

```json
{
  "upload_job_id": "uj_...",
  "status": "uploaded",
  "links": { "self": "/api/v1/upload-jobs/uj_..." }
}
```

### POST /workspaces/{workspace_id}/uploads（可选小文件）

`multipart/form-data` 直传网关；仅 `size <= threshold`（如 5MB）。大文件必须走预签名。

### GET /upload-jobs/{upload_job_id}

```json
{
  "id": "uj_...",
  "document_id": "d_...",
  "version_id": "v_...",
  "status": "embedding",
  "progress": 62,
  "stages": [
    { "name": "upload", "status": "succeeded" },
    { "name": "parse", "status": "succeeded" },
    { "name": "embed", "status": "running" },
    { "name": "learn", "status": "queued" }
  ],
  "error": null
}
```

状态：`created|uploaded|scanning|parsing|embedding|learning|ready|ready_degraded|failed|deleted`

### POST /upload-jobs/{upload_job_id}/retry

仅 `failed` 可重试；从失败 stage 恢复。

### GET /workspaces/{workspace_id}/upload-jobs

过滤：`status`, `created_by`, 时间范围。

---

## 4. 文档与 ACL

### GET /workspaces/{workspace_id}/documents

查询：`q`, `tag`, `status`, `sensitivity`

### GET /documents/{document_id}

含 current_version、学习状态摘要、调用者有效权限。

### POST /documents/{document_id}/versions/presign

上传新版本（内容变更）；body 同上传 presign。

### GET /documents/{document_id}/versions

### GET /documents/{document_id}/chunks

分页；Viewer+。调试/引用面板用。

### GET /documents/{document_id}/acl

### PUT /documents/{document_id}/acl

替换式或 patch（实现选一种，推荐 patch）。

```json
{
  "set": [
    { "principal_type": "group", "principal_id": "g_eng", "permission": "read" }
  ],
  "remove": [
    { "principal_type": "user", "principal_id": "u_1", "permission": "write" }
  ]
}
```

副作用：写审计 + 投递 `AclChanged` + 异步向量 payload 同步。

### DELETE /documents/{document_id}

软删；级联调度 GC。

---

## 5. 学习总结

### GET /documents/{document_id}/learning

当前学习报告。

```json
{
  "artifact_id": "la_...",
  "version_id": "v_...",
  "state": "draft",
  "summary": "…",
  "outline": [{ "title": "…", "children": [] }],
  "key_points": [
    { "point": "…", "evidence_chunk_ids": ["c1", "c2"] }
  ],
  "suggested_tags": ["rag", "acl"],
  "open_questions": ["…"],
  "model": "deepseek-chat",
  "updated_at": "…"
}
```

### POST /documents/{document_id}/learning/relearn

Editor+；可选 `{ "version_id": "v_..." }`；入队 learn 任务。

### PATCH /documents/{document_id}/learning

人工修订 draft 字段。

### POST /documents/{document_id}/learning/publish

`draft|approved` → `published`（视空间 `publish_mode`；approval 模式需审批权限）。

### POST /documents/{document_id}/learning/reject

```json
{ "reason": "要点缺少证据" }
```

### POST /workspaces/{workspace_id}/learning/review

批量复习总结（Agent/服务端任务）。

```json
{
  "document_ids": ["d1", "d2"],
  "or_filter": { "tags": ["rag"], "since": "2026-09-01" },
  "format": "markdown"
}
```

返回 `job_id`；完成后产出 review report 资源。

---

## 6. 检索与对话

### POST /search

```json
{
  "query": "如何做租户隔离？",
  "workspace_ids": ["w_..."],
  "top_k": 8,
  "filters": { "tags": ["security"], "sensitivity": ["L1", "L2"] }
}
```

**Response**

```json
{
  "hits": [
    {
      "chunk_id": "c_...",
      "document_id": "d_...",
      "score": 0.82,
      "snippet": "…",
      "page_from": 3,
      "heading_path": "安全/多租户"
    }
  ]
}
```

服务端强制 ACL filter；无权限命中不得返回。

### POST /conversations

```json
{ "workspace_ids": ["w_..."], "title": "可选" }
```

### POST /conversations/{conversation_id}/messages

```json
{
  "content": "总结本周上传的架构文档",
  "stream": true,
  "scope": { "document_ids": ["d_..."] }
}
```

- `stream=true`：`text/event-stream`  
  事件：`token` / `citation` / `tool_call` / `usage` / `done` / `error`
- 非流式：完整 message + citations

### GET /conversations/{conversation_id}

### GET /conversations/{conversation_id}/messages

### POST /ask（可选快捷接口）

无会话单次问答；内部仍写审计。

---

## 7. Agent

### POST /agent/runs

```json
{
  "conversation_id": "cv_...",
  "goal": "对比文档 A 与 B 中关于 ACL 的说法",
  "tool_allowlist": ["search_knowledge", "get_document", "review_summarize"],
  "max_steps": 8
}
```

### GET /agent/runs/{run_id}

含 steps、tool_calls、最终答案、引用。

高危工具（`manage_acl`、`export_audit`）若未在 allowlist 或角色不足 → 400/403。

---

## 8. 管理与审计

### GET /admin/usage

Tenant Admin：存储、embed、llm、job 计量；支持 `from`/`to`。

### GET /admin/quotas

### PUT /admin/quotas

### GET /admin/jobs?status=dead

失败/死信任务。

### POST /admin/jobs/{task_id}/requeue

### GET /admin/audit-events

过滤：actor、action、resource、时间。

### POST /admin/audit-exports

异步导出；返回 export job；下载链有过期时间。

### GET /admin/models/policy

### PUT /admin/models/policy

敏感级 → 模型路由。

---

## 9. Webhooks（P1）

### POST /admin/webhooks

```json
{
  "url": "https://example.com/hook",
  "events": ["learning.published", "upload.failed"],
  "secret": "…"
}
```

投递签名：`X-KB-Signature: sha256=...`

---

## 10. 事件类型（Outbox → 内部/Webhook）

| type | 何时 |
|------|------|
| upload.completed | 直传确认 |
| document.version.indexed | 向量写入完成 |
| learning.ready | 学习草稿生成 |
| learning.published | 发布 |
| acl.changed | ACL 变更 |
| upload.failed | 终态失败 |
| agent.run.completed | Agent 结束 |

事件信封：

```json
{
  "id": "evt_...",
  "type": "document.version.indexed",
  "tenant_id": "t_...",
  "occurred_at": "2026-09-06T12:00:00Z",
  "aggregate_type": "document_version",
  "aggregate_id": "v_...",
  "payload": { "document_id": "d_...", "workspace_id": "w_..." }
}
```

---

## 11. 流式 SSE 事件示例

```
event: token
data: {"text":"租户隔离"}

event: citation
data: {"index":1,"chunk_id":"c_...","document_id":"d_...","quote":"..."}

event: done
data: {"message_id":"m_...","usage":{"llm_tokens":1234}}
```

---

## 12. 权限矩阵（接口级摘要）

| 接口 | Viewer | Editor | WsAdmin | TenantAdmin |
|------|--------|--------|---------|-------------|
| search / ask / 读学习(published) | ✓ | ✓ | ✓ | ✓ |
| 上传 / relearn / 修订 draft | | ✓ | ✓ | ✓ |
| publish（auto 空间） | | ✓ | ✓ | ✓ |
| publish（approval 空间） | | | ✓* | ✓ |
| ACL 修改 | | | ✓ | ✓ |
| 配额/审计导出 | | | | ✓ |

\* 或独立 Approver 角色。

---

## 13. 限流与配额（默认建议）

| 维度 | 默认 |
|------|------|
| API QPS / user | 10 |
| 上传大小 | 50 MB / 文件 |
| 批量上传 | 20 文件 / 请求批次 |
| 预签名有效期 | 15 min |
| 日 llm_tokens / tenant | 可配 |
| Agent max_steps | 8（请求可更低，不可更高过租户上限） |

超限 → `429` + `Retry-After`。

---

## 14. 版本策略

- 当前前缀 `/api/v1`
- 破坏性变更走 `/v2`；`v1` 至少保留一个企业发布周期
- 弃用响应头：`Deprecation` / `Sunset`

---

## 15. 与数据模型对齐检查表

- [x] upload idempotency_key
- [x] document version 新传
- [x] learning draft/publish
- [x] ACL patch + 异步同步
- [x] search 强制租户与 ACL
- [x] audit/usage 管理接口
- [x] outbox 事件类型
- [x] SCIM 用户同步 API（P1）→ 见 [`connectors-and-scim.md`](./connectors-and-scim.md) §3、§8
- [x] 连接器 API（P1）→ 见 `connectors-and-scim.md` §8
- [ ] Webhooks 投递保证与重试细则（实现阶段）
