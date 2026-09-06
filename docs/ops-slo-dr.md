# 运维、SLO 与灾备（Ops / SLO / DR）

> 对应主设计 P1/P2：配额细则、容量模型、RPO/RTO、Runbook、告警。  
> 与 [`personal-knowledge-base-agent.md`](./personal-knowledge-base-agent.md) §10、[`data-model.md`](./data-model.md)、[`api-contracts.md`](./api-contracts.md) 配套。

---

## 1. 目标与范围

本文件定义企业部署下的：

1. **服务等级**：SLI / SLO / 错误预算
2. **配额与限流**：租户 / 空间 / 用户级
3. **容量模型**：粗算公式与扩容触发点
4. **可观测性**：指标、日志、追踪、审计
5. **告警与值班**
6. **备份与灾备（DR）**：RPO/RTO、演练
7. **Runbook**：高频故障处置大纲

`profile=personal` 可关闭多副本与严格值班，但仍建议保留备份与基础健康检查。

---

## 2. SLI / SLO / 错误预算

### 2.1 核心 SLO（企业默认）

| 类别 | SLI | SLO（月度） | 说明 |
|------|-----|-------------|------|
| 可用性 | 成功请求比例（非 5xx、非依赖超时） | **99.9%** | 按网关成功计；不含客户端取消 |
| 上传受理 | `presign`/`complete` 延迟 | **P99 < 2s** | 不含浏览器直传对象存储时间 |
| 入库时效 | upload.complete → version.indexed | **P95 < 5min**（≤20MB 文本 PDF） | 扫描件/OCR 另册 |
| 学习时效 | indexed → learning.ready | **P95 < 10min**（≤5 万字） | 超长文档按章并行，另订预算 |
| 问答延迟 | 首 token 时间（TTFT） | **P95 < 3s** | 不含冷启动；依赖 LLM 单独拆分 |
| 问答成功率 | 有答案或明确「无权限/未找到」且 HTTP 非 5xx | **99.5%** | 「未找到」算成功 |
| 隔离正确性 | 跨租户可见事件 | **0** | 红线；任一事件烧光错误预算并升级 |
| 数据耐久 | 已确认上传对象丢失 | **0** | 与对象存储 SLA 对齐 |

### 2.2 依赖型 SLO（拆分记账）

| 依赖 | 记法 |
|------|------|
| 外部 LLM | 单独面板：可用性、TTFT、错误率、token 费用；**不计入**核心 API 99.9% 时需标记 `dependency_error` |
| IdP / OIDC | 登录成功率单独 SLO 99.9% |
| 对象存储 | 上传/下载错误率；走云厂商 SLA |

当 LLM 全挂时：问答返回可重试错误或降级「仅检索片段、不生成」——需产品开关 `degrade_mode=retrieve_only`。

### 2.3 错误预算

- 月可用性 99.9% ⇒ 允许约 **43 分钟**不可用 / 月
- 预算耗尽 → 冻结非紧急发布，优先稳定性
- **隔离事件不走错误预算谈判**，立即 Sev-1

### 2.4 按 Profile 收缩

| Profile | 可用性目标 | 值班 |
|---------|------------|------|
| personal | best-effort | 无 |
| team | 99.5% | 工作日 on-call |
| enterprise | 99.9% | 7×24 或合同约定 |

---

## 3. 配额与限流

### 3.1 租户默认配额（可配置）

| 配额项 | 默认 | 超限行为 |
|--------|------|----------|
| 存储（原文+派生） | 500 GB | `quota_exceeded`，拒绝新上传 |
| 单文件大小 | 50 MB | 413 |
| 单次批量文件数 | 20 | 400 |
| 日嵌入页/字符等价 | 10 万页或等价 token | 429，次日重置或排队低优先级 |
| 日 LLM tokens | 500 万 | 429；学习任务可延迟 |
| 并发 ingest worker 占用 | 按租户公平分享集群算力 | 排队 |
| 日 Agent runs | 1 000 | 429 |
| 审计导出 / 日 | 10 次 | 429 |
| API QPS / 用户 | 10 | 429 + Retry-After |
| API QPS / 租户 | 200 | 429 |
| 预签名有效期 | 15 min | URL 过期需重建 |
| 对话保留 | 90 天 | 到期冷存或删（租户策略） |

### 3.2 空间级配额（可选）

在租户额度内再切分：`workspace.storage_gb`、`workspace.daily_llm_tokens`，防止单一空间吃光租户预算。

### 3.3 限流算法建议

- 网关：token bucket（用户键 + 租户键）
- 队列：按 `tenant_id` 加权公平调度（避免大租户饿死小租户）
- LLM Gateway：租户令牌桶 + 模型级并发上限

### 3.4 计量来源

以 `usage_ledger` 为准；近实时 Redis 计数 + 定期对账 Postgres。  
配额检查点：presign、enqueue learn、agent run、audit export。

---

## 4. 容量模型（粗算）

### 4.1 变量

| 符号 | 含义 |
|------|------|
| D | 活跃文档数 |
| C | 平均每文档 chunk 数 |
| V | 向量维数（如 1024） |
| Q | 问答 QPS（峰值） |
| U | 日新增文档数 |
| L | 日学习任务数（≈U） |

### 4.2 经验公式

**向量存储（原始 float32，未量化）**

```
vector_bytes ≈ D * C * V * 4 * 1.3   # 1.3 含索引开销
```

例：10 万文档 × 40 chunk × 1024 维 ≈ 10e4 × 40 × 1024 × 4 × 1.3 ≈ **21 GB** 量级。

**元数据库**

```
postgres_bytes ≈ D * 5KB + D*C * 2KB + audit_days * events_per_day * 1KB
```

**对象存储**

```
s3_bytes ≈ 原文 * 1.2（含 derived） + 版本保留策略
```

**问答吞吐**

- 单副本 API 经验：CPU-bound 检索编排约 20–50 QPS（含 rerank/LLM 前）
- LLM 通常是瓶颈：按模型并发与 TTFT 反推

### 4.3 扩容触发点

| 信号 | 动作 |
|------|------|
| 队列积压 > 15min 的 P95 入库 SLA | +Worker 副本 / 提高并发 |
| Qdrant CPU > 70% 持续 15min | 分片/垂直扩容 |
| Postgres 连接或磁盘 > 80% | 扩盘 / 读写分离 |
| LLM 429 比例 > 2% | 降级、切备用模型、提配额 |
| 租户存储 > 85% 配额 | 通知管理员；可选只读 |

---

## 5. 可观测性

### 5.1 关联 ID

每请求：`request_id`（网关生成）→ 传入 Worker 为 `correlation_id`。  
审计、日志、追踪、Outbox 均带 `tenant_id` + `request_id`。

### 5.2 指标（Prometheus）

**红线**

- `http_requests_error_rate{status=~"5.."}`
- `cross_tenant_violation_total`（期望恒 0）
- `ingest_lag_seconds`（complete → indexed）
- `queue_depth{queue=parse|embed|learn}`
- `llm_error_rate` / `llm_ttft_seconds`

**业务**

- `uploads_total{status=}`
- `learning_artifacts_total{state=}`
- `search_empty_ratio`
- `citation_validation_fail_total`
- `quota_reject_total{meter=}`

**资源**

- Worker 副本数、重试率、DLQ 深度
- DB 连接池、Qdrant 集合大小、S3 错误率

### 5.3 日志

- 结构化 JSON；禁止记录原文全文与密钥
- 学习/问答可记 prompt hash、token、模型名
- 默认保留 30–90 天（合同可调）

### 5.4 追踪

OpenTelemetry：`upload.complete` → `parse` → `embed` → `learn` → `search` → `llm.complete`。

### 5.5 LLM 成本面板

按 tenant / model / operation（learn|chat|agent）聚合日费用；超预算告警。

---

## 6. 告警与事件等级

### 6.1 等级

| 等级 | 定义 | 响应 |
|------|------|------|
| Sev-1 | 全站不可用、疑似串租、数据丢失 | 立即叫人；15min 内响应 |
| Sev-2 | 核心路径严重降级（入库全面积压、问答大面积失败） | 30min |
| Sev-3 | 局部失败、单一租户配额打满、单 Worker 刷屏 | 工作日处理 |
| Sev-4 | 趋势预警 | 纳入迭代 |

### 6.2 必备告警规则（示例）

| 告警 | 条件 | 等级 |
|------|------|------|
| APIErrorBudgetBurn | 5xx 率 > 1% 持续 5min | Sev-2 |
| IngestLagHigh | P95 lag > 15min | Sev-2 |
| QueueDLQGrowing | DLQ 10min 增 > N | Sev-2 |
| CrossTenantViolation | 任何一次 | **Sev-1** |
| LLMOutage | 依赖错误率 > 50% 持续 5min | Sev-2（可降级） |
| DiskNearFull | > 85% | Sev-2 |
| BackupFailed | 备份 job 失败 | Sev-2 |
| CertificateExpiry | < 14 天 | Sev-3 |

---

## 7. 备份与灾备（DR）

### 7.1 数据分级

| 数据 | 组件 | 丢失影响 |
|------|------|----------|
| 原文与派生 | 对象存储 | 不可恢复的知识原文 |
| 元数据/ACL/审计 | PostgreSQL | 权限与审计丢失 |
| 向量 | Qdrant | 可从原文+chunks 重建（耗时长） |
| 队列 | Redis/NATS | 可丢未完成任务（需可重放 Outbox） |
| 密钥 | KMS/Vault | 恢复阻塞点 |

### 7.2 RPO / RTO 目标（企业默认）

| 场景 | RPO | RTO | 策略 |
|------|-----|-----|------|
| 同城单组件故障 | ≈0（多副本） | ≤15min | K8s 自动调度 / 多副本 |
| 可用区故障 | ≤5min | ≤1h | 多 AZ；DB 同步/半同步备 |
| 区域灾难 | ≤1h | ≤4–24h（合同） | 跨区备份；向量可重建 |
| 误删文档 | ≤15min（版本/回收站） | ≤1h | 软删 TTL + 对象版本控制 |

`personal`：RPO ≤24h（每日备份），RTO best-effort。

### 7.3 备份策略

| 组件 | 策略 |
|------|------|
| PostgreSQL | 连续 WAL 归档 + 每日全量；保留 30 天；定期 PITR 演练 |
| 对象存储 | 跨区复制或版本控制 + 生命周期；禁止无版本桶用于生产 |
| Qdrant | 每日快照到对象存储；**重建脚本**作为二选一恢复路径 |
| 配置/密钥 | IaC + Vault 快照；密钥轮转 runbook |
| Redis | 队列不作为唯一真相；Outbox 在 Postgres |

### 7.4 恢复优先级

1. 密钥与配置  
2. PostgreSQL（元数据/ACL）  
3. 对象存储挂载/复制  
4. 恢复 API/Web（只读模式可选）  
5. Qdrant 快照恢复 **或** 启动 rebuild_embeddings 任务  
6. Worker / 队列追平积压  

### 7.5 演练

| 演练 | 频率 |
|------|------|
| 备份可拉起（staging PITR） | 每月 |
| 区域切换桌面推演 | 每季 |
| 向量全量重建抽样 | 每季 |
| 串租/隔离回归 | 每发布 |

演练记录：时间、RPO/RTO 实测、缺陷、负责人。

---

## 8. 部署与环境

| 环境 | 用途 | 数据 |
|------|------|------|
| dev | 本地/共享开发 | 假数据 |
| staging | 预发、演练 | 脱敏拷贝 |
| prod | 生产 | 真实 |

规则：

- prod 变更走变更窗口 + 变更单（企业）
- 迁移（Alembic）先 staging  
- Feature flag 默认关，按租户灰度  

### 健康检查

- `/healthz`：进程存活  
- `/readyz`：Postgres + Redis + Qdrant +（可选）对象存储 head bucket  

未 ready 的 Pod 不得接流量。

---

## 9. Runbook 大纲

> 完整操作步骤在运维库维护；此处为必须覆盖的条目与原则。

### 9.1 疑似串租 / 数据泄漏（Sev-1）

1. 立即开启全局只读或切断问答/检索流量（保留审计）  
2. 保留现场：相关 `request_id`、检索日志、向量 filter 快照  
3. 核对：该请求的 `tenant_id`、ACL SQL、Qdrant filter  
4. 修复：缺陷补丁 + 全量 ACL/向量一致性校验任务  
5. 通知：受影响租户管理员（法务模板）  
6. 复盘：24h 内写出根因与回归用例  

### 9.2 入库全面积压

1. 看 `queue_depth`、Worker 日志、对象存储错误  
2. 区分：解析失败风暴 vs Worker 不足 vs 下游 LLM/embed 慢  
3. 动作：扩容 Worker；毒消息进 DLQ；对失败 MIME 熔断  
4. 对 SLA 已违约租户发状态页/通知  

### 9.3 问答大面积失败

1. 拆分：API 5xx vs LLM 超时 vs 检索空  
2. LLM 挂：开 `retrieve_only` 或切备用模型路由  
3. 检索异常：检查 Qdrant、filter、最近是否发布 embedding 新版本未双读  

### 9.4 单一租户配额打满

1. 确认计量是否漂移（对账）  
2. 临时提额或延后学习队列  
3. 通知租户管理员  

### 9.5 备份失败

1. 当天重跑；仍失败则 Sev-2  
2. 检查 WAL 上传权限、磁盘、网络  
3. 未解决前禁止可能丢数据的大变更  

### 9.6 密钥泄漏 / 轮转

1. 旋转 OIDC client secret、S3、LLM API Key  
2. 失效旧密钥；审计近 24h 调用  
3. 更新 Vault/K8s secret；滚动重启  

### 9.7 证书即将过期

提前 14/7/3 天告警；替换 Ingress/对象存储 TLS。

### 9.8 向量与 DB 不一致

跑 `reconcile_vectors`：按 `version_id` 对比 chunk 与 point；缺则补建，多余则删；ACL hash 漂移则 patch。

---

## 10. 安全运营

- 生产访问：SSO + MFA；临时 kubectl via JIT  
- 审计：管理操作 100% 入库  
- 漏洞：依赖扫描门槛；高危 7 日内修复（合同可调）  
- 渗透与隔离测试：上线前 + 每年  

---

## 11. 状态页与沟通

| 事件 | 沟通 |
|------|------|
| Sev-1/2 | 状态页 + 租户管理员邮件/Webhook |
| 计划内维护 | 提前 ≥72h（企业合同可调） |
| 降级模式 | 明确告知「仅检索不生成」等 |

---

## 12. 验收清单（Ops 就绪）

- [ ] 核心 SLO 仪表盘上线  
- [ ] Sev-1/2 告警路由到值班  
- [ ] Postgres PITR 演练通过（附报告）  
- [ ] 对象存储版本控制已开  
- [ ] Qdrant 快照或重建脚本验证  
- [ ] Runbook 9.1–9.8 有可执行版  
- [ ] `/readyz` 接入就绪探针  
- [ ] 配额拒绝可观测（`quota_reject_total`）  
- [ ] 串租检测用例在 CI  

---

## 13. 与主文档缺口映射

| 原遗漏 | 本节 |
|--------|------|
| 配额细化 | §3 |
| 容量模型 | §4 |
| DR RPO/RTO | §7 |
| Runbook | §9 |
| 可观测/告警 | §5–§6 |

仍属其它文档：SCIM/连接器 → `connectors-and-scim.md`；法务 DPA → 商务/合规册。
