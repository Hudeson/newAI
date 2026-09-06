# 连接器与 SCIM（Connectors & Directory Sync）

> 对应主设计 P1：用户组/SCIM、服务账号、连接器同步模型。  
> 配套：[`data-model.md`](./data-model.md)、[`api-contracts.md`](./api-contracts.md)、[`ops-slo-dr.md`](./ops-slo-dr.md)。

---

## 1. 目标

企业知识库不能只靠手工上传，还需要：

1. **目录同步（SCIM / JIT）**：用户、组从 IdP 进入本系统，驱动 ACL  
2. **内容连接器**：从 SharePoint、Google Drive、Confluence、S3 等增量拉取文档  
3. **非人身份**：连接器与 CI 使用服务账号 / API Key，权限可审计、可吊销

原则：

- 所有同步对象带 `tenant_id`；连接器实例绑定 `workspace_id`（可多实例）  
- **源站权限不自动等于本系统 ACL**，必须经显式映射策略  
- 同步失败可重试、可死信、可人工对账；禁止静默丢权限扩大可见性  

---

## 2. 领域模型扩展

### 2.1 组与成员

```
tenants
  └── groups
        ├── external_id          # IdP/SCIM id
        ├── source               # scim | local | connector
        └── group_members (user_id | nested_group_id?)
```

| 表 | 关键字段 |
|----|----------|
| groups | id, tenant_id, name, external_id, source, status, synced_at |
| group_members | group_id, user_id, added_by, created_at |

ACL `principal_type=group` 指向 `groups.id`。  
嵌套组：首期 **不展开递归**（扁平化由 IdP 推送成员）；若需嵌套，M4+ 再做闭包表。

### 2.2 服务账号与 API Key

| 表 | 字段 |
|----|------|
| service_accounts | id, tenant_id, name, status, created_by |
| api_keys | id, service_account_id 或 user_id, key_prefix, key_hash, scopes[], workspace_id?, expires_at, revoked_at, last_used_at |

Scopes 示例：`documents:read` `documents:write` `connectors:manage` `scim:provision` `audit:export`。  
连接器 Worker 使用租户内服务账号，**不得**使用个人用户长期 token。

### 2.3 连接器实例与同步状态

| 表 | 说明 |
|----|------|
| connector_defs | 类型元数据：sharepoint / gdrive / confluence / s3 / webdav… |
| connector_instances | 租户+空间下的一个配置实例 |
| connector_secrets | 密钥引用（Vault/KMS 路径），库中不存明文 |
| connector_sync_runs | 每次同步运行记录 |
| connector_cursors | 增量游标（per path / drive / space） |
| connector_item_map | 远端 item_id ↔ 本地 document_id / version_id |
| connector_dead_letters | 毒消息与人工处理 |

**connector_instances 关键列**

| 列 | 说明 |
|----|------|
| id, tenant_id, workspace_id | |
| type | sharepoint / gdrive / … |
| name | 展示名 |
| status | disabled / idle / syncing / error / needs_reauth |
| config jsonb | 站点/驱动器/路径/过滤器，无密钥 |
| schedule | cron 或 interval |
| sync_mode | full / incremental |
| permission_mode | 见 §5 |
| feature_flags | 灰度 |
| created_by, created_at, updated_at | |

---

## 3. SCIM 与登录供给

### 3.1 模式

| 模式 | 适用 | 说明 |
|------|------|------|
| **SCIM 2.0** | 企业默认 | IdP 推送 User/Group；本系统为 SCIM Service Provider |
| **OIDC JIT** | 小团队 | 首次登录创建用户；组需另配或手工 |
| **本地用户** | personal | 无 SCIM |

同一租户可：SSO 登录 + SCIM 供给并存；以 `idp_subject` / `external_id` 关联。

### 3.2 SCIM 端点（Service Provider）

Base：`/scim/v2`（租户通过鉴权上下文或路径 `/t/{tenant_slug}/scim/v2` 隔离）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /Users | 过滤/分页 |
| POST | /Users | 创建 |
| GET | /Users/{id} | |
| PUT/PATCH | /Users/{id} | 更新；`active=false` → 停用 |
| DELETE | /Users/{id} | 硬删少用；推荐 active=false |
| GET/POST | /Groups | |
| PATCH | /Groups/{id} | 成员增减 |
| GET | /ServiceProviderConfig | |
| GET | /Schemas | |
| GET | /ResourceTypes | |

认证：Bearer **SCIM token**（租户级服务账号，scope=`scim:provision`）或 IdP 配置的专用密钥。

### 3.3 属性映射（默认）

| SCIM | 本地 |
|------|------|
| userName / emails[primary] | email |
| externalId / id | external_id |
| name.formatted | display_name |
| active | status=active/disabled |
| groups | group_members |
| urn:...:role（可选扩展） | 租户角色建议值（需白名单） |

**禁止** SCIM 直接授予 Platform Admin。租户角色映射表由 Tenant Admin 配置。

### 3.4 停用与删除语义

| IdP 动作 | 本地效果 |
|----------|----------|
| active=false | 用户无法登录；ACL 保留但鉴权失败；会话吊销 |
| DELETE User | 默认等同停用 + 匿名化可选；文档所有权转 Workspace Admin |
| 移出组 | 去掉 group_members；触发 ACL 影响文档的 `acl_hash` 重算任务 |

### 3.5 对账 Job

每日：`scim_reconcile` 拉取 IdP 侧清单（若支持）或依赖 SCIM 事件；报告：孤儿用户、幽灵组成员、映射失败。  
指标：`scim_provision_total{result=}`、`scim_lag_seconds`。

---

## 4. 连接器总体架构

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ Admin UI/API │────▶│ Connector Mgmt  │────▶│ Secrets (Vault)  │
└──────────────┘     └────────┬────────┘     └──────────────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ Scheduler       │  cron / manual / webhook
                     └────────┬────────┘
                              │ enqueue sync_run
                              ▼
                     ┌─────────────────┐
                     │ Connector Worker│  per-type plugin
                     └────────┬────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
    List/Delta API      Download file      Map ACL (optional)
           │                  │                  │
           ▼                  ▼                  ▼
    connector_item_map   object store      document_acl patch
           │                  │
           └────────┬─────────┘
                    ▼
            现有 Ingest Pipeline（parse → embed → learn）
```

要点：

- 连接器 **只负责发现与搬原文 + 映射元数据**；解析/向量/学习复用主链路  
- 每个 `sync_run` 有 run_id，可取消、可看进度  
- 插件接口统一，便于加类型  

### 4.1 插件接口（逻辑）

```text
ConnectorPlugin:
  validate_config(config) -> errors
  test_connection(secrets) -> ok | error
  list_changes(cursor, config) -> (items[], next_cursor)
  fetch_content(item) -> (bytes | stream, content_type, checksum)
  fetch_remote_acl(item) -> remote_principals[]   # optional
  map_to_document(item) -> DocumentUpsertCommand
```

### 4.2 同步运行状态机

```
queued → running → succeeded
              ↘ partial_success
              ↘ failed → (retry) → dead
              ↘ cancelled
```

`partial_success`：部分 item 进 DLQ，其余完成；需告警。

---

## 5. 权限映射策略（permission_mode）

| 模式 | 行为 | 风险 |
|------|------|------|
| `workspace_default` | 新文档继承空间默认 ACL | 简单；可能宽于源站 |
| `owner_only` | 仅同步发起人/绑定服务账号可读写，再手工授权 | 最安全默认 |
| `mapped` | 远端用户/组 → 本地 user/group 映射表 | 最贴近企业；配置复杂 |
| `mirror_strict` | 尽量镜像源站 ACL；无法映射的 principal **拒绝扩大**（文档对未映射者不可见） | 推荐企业网盘 |

**硬规则**：无法解析的远端「全员可读」不得默认映射为 `workspace_all`，除非 Tenant Admin 显式确认开关 `allow_public_to_workspace_all=true`。

映射表 `connector_identity_map`：

| 列 | 说明 |
|----|------|
| connector_instance_id | |
| remote_type | user / group |
| remote_id / remote_email | |
| local_principal_type | user / group |
| local_principal_id | |
| status | active / unmatched |

未匹配：item 仍可按 `owner_only` 入库，并记 `needs_acl_review`。

---

## 6. 增量同步、冲突与背压

### 6.1 游标

`connector_cursors` 按 `(instance_id, scope_key)` 存：

- SharePoint：deltaLink  
- Google Drive：`pageToken` / `startPageToken` changes  
- Confluence：`next` URL 或 `updated_at` 水位  
- S3：`list` continuation 或 Event 通知游标  

全量：`sync_mode=full` 重建清单，与 `connector_item_map` diff。

### 6.2 变更类型处理

| 远端事件 | 本地动作 |
|----------|----------|
| created / updated | 下载 → checksum 比较 → 新 version 或幂等跳过 → ingest |
| deleted | 软删本地 document（策略可配：归档 / 软删）；向量 superseded |
| moved / renamed | 更新元数据路径；可不重嵌 |
| ACL changed | 仅跑 ACL 同步任务 + acl_hash 更新 |

### 6.3 冲突

| 冲突 | 策略（默认） |
|------|--------------|
| 本地有手工新版本，远端又更新 | **远端优先**出新 version，本地手工版保留为历史；或空间策略 `local_wins` |
| 同 checksum | 跳过内容管线，只更新元数据 |
| 本地删除，远端仍在 | 下次同步 **恢复** 或忽略（`tombstone_ttl` 内不恢复） |

### 6.4 背压与配额

- 单实例并发下载上限（默认 4）  
- 受租户日嵌入/存储配额约束：超额则 `sync_run=partial_success`，剩余延后  
- 大租户公平调度：连接器任务与手工上传共享队列权重  
- 速率限制命中源 API：指数退避，尊重 `Retry-After`  

### 6.5 Webhook vs 轮询

| 类型 | 机制 |
|------|------|
| 优先 | 源站 webhook/subscription → 轻量 enqueue |
| 兜底 | 定时 incremental（5–60min 可配） |
| 安全 | webhook 验签；仅入队 item_id，拉数仍走 Worker 出站 |

---

## 7. 各连接器要点（首期）

### 7.1 SharePoint Online / OneDrive

- Auth：OAuth2 应用权限或委派；密钥在 Vault  
- 范围：site + library + folder path  
- 增量：Graph delta  
- ACL：Graph permissions → mapped 模式  
- 注意：版本历史可选只拉最新；检出锁定文件跳过并重试  

### 7.2 Google Drive

- Auth：服务账号 + Shared Drive，或 OAuth 用户  
- 增量：Changes API  
- 捷径（shortcut）解析目标；循环检测  
- Google Docs 导出 MIME（docx/pdf/md）可配  

### 7.3 Confluence Cloud / Data Center

- Auth：API Token / OAuth  
- 范围：space key 列表  
- 页面 + 附件；页面转 storage/HTML → 文本管线  
- 增量：`updated_at` 或 CQL  
- 权限：space 角色映射到本地组  

### 7.4 S3 / OSS 兼容

- Auth：静态密钥或 IRSA/OIDC 角色  
- 范围：bucket + prefix；可选 SNS/EventBridge  
- 无原生用户 ACL 时用 `workspace_default` 或路径规则映射  
- 支持 SSE-KMS 下载角色  

### 7.5 后续（M4+）

Notion、飞书云文档、Git 仓库、企业邮箱投递箱、RSS（只读）。

---

## 8. API 草案（管理面）

前缀：`/api/v1/workspaces/{workspace_id}/connectors`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 列表 |
| POST | / | 创建实例（不含明文 secret，只收 secret_ref 或一次性 secret 转 Vault） |
| GET | /{id} | 详情（secrets 脱敏） |
| PATCH | /{id} | 更新 config/schedule/permission_mode |
| POST | /{id}/test | 测连 |
| POST | /{id}/sync | `{mode: incremental\|full}` 触发 |
| GET | /{id}/runs | 同步历史 |
| GET | /{id}/runs/{run_id} | 进度与错误摘要 |
| POST | /{id}/runs/{run_id}/cancel | 取消 |
| GET | /{id}/dead-letters | DLQ |
| POST | /{id}/dead-letters/{id}/retry | 重试 |
| GET/PUT | /{id}/identity-map | 身份映射 |
| DELETE | /{id} | 禁用并停调度；可选清理已同步文档 |

SCIM 见 §3.2。  
服务账号：`/api/v1/service-accounts`、`/api/v1/api-keys`（Tenant Admin）。

错误码复用主契约；连接器专用：`connector_reauth_required` `connector_rate_limited` `connector_partial_success`。

---

## 9. 安全与合规

1. 密钥只进 Vault/KMS；轮转 Runbook 与 `ops-slo-dr` 对齐  
2. 出站连接器走企业代理 / Egress allowlist  
3. 同步审计：`connector.sync.started/completed`、`document.imported_from_connector`  
4. 敏感级：远端元数据可带标签 → 本地 `sensitivity`；L3+ 强制私有模型路由  
5. 删除权：源站删除后本地 GC 遵循租户 TTL  
6. 最小权限：Graph/Drive 范围只授需要的 site/drive  
7. Feature Flag：`connectors.enabled`、`connectors.sharepoint` 按租户灰度  

---

## 10. 可观测性

| 指标 | 说明 |
|------|------|
| `connector_sync_runs_total{type,result}` | 成功率 |
| `connector_sync_lag_seconds` | 游标落后真实时间 |
| `connector_items_total{action=upsert\|skip\|delete\|error}` | 吞吐 |
| `connector_dlq_depth` | 人工介入 |
| `scim_ops_total{resource,op,result}` | 供给 |
| `identity_map_unmatched_total` | 权限待审 |

告警：连续失败、reauth、DLQ 增长、lag > SLA（默认 2h）。

---

## 11. 与主摄入管线衔接

```
connector fetch
  → object_key 写入（同上传布局，source=connector）
  → documents.source = connector_instance_id + remote_item_id
  → upload_jobs / ingest_tasks 复用（type=connector_import）
  → parse → embed → learn（空间 publish_mode 仍生效）
```

幂等键：`tenant_id + connector_instance_id + remote_item_id + remote_version`。

---

## 12. Feature Flag 与发布阶段

| 阶段 | 范围 |
|------|------|
| M3 | 服务账号 + API Key；Group 实体；SCIM Users/Groups 最小集 |
| M3 | 连接器框架 + **S3 或 Confluence 择一** 打通竖切 |
| M4 | SharePoint / Google Drive；mapped ACL；Webhook |
| M5 | 更多源、嵌套组、双向（出站写回，默认关闭） |

个人 profile：连接器与 SCIM 默认编译可用但 UI 隐藏；或构建标签剔除。

---

## 13. 验收标准

**SCIM**

- [ ] IdP 创建用户 → 可登录对应租户  
- [ ] 停用用户 → 令牌失效且无法检索  
- [ ] 组增删成员 → 仅组 ACL 文档可见性变化；无串租  

**连接器**

- [ ] 配置测连成功；密钥不出现在日志/API 响应  
- [ ] 增量同步：远端更新产生新 version；删除触发本地软删  
- [ ] 配额打满时 partial_success + 可续跑  
- [ ] 双租户连接器数据互不可见  
- [ ] 人工上传与连接器导入文档在问答中统一带引用与来源标签  

---

## 14. 开放决策

| 项 | 默认建议 |
|----|----------|
| 首个内容连接器 | **S3**（实现简单）或客户指定网盘 |
| 默认 permission_mode | `owner_only`，企业网盘可升 `mirror_strict` |
| 远端与本地编辑冲突 | 远端优先保留历史 |
| SCIM 删除 | 软停用为主 |
| 双向同步写回源站 | 默认关闭（风险高） |

---

## 15. 主文档缺口映射

| 原 # | 项 | 本节 |
|------|----|------|
| 9 | 用户组 / SCIM | §2.1、§3 |
| 10 | 服务账号与 API Key | §2.2、§8 |
| 17 | 连接器同步模型 | §4–§7、§11 |
| 19 | Feature Flag（连接器部分） | §9、§12 |
