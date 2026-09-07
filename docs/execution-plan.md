# 执行计划（从设计到可运行竖切）

> 状态：E0–E7、M4、Real-LLM 已落地；**M5 知识图谱处于 KG.0（设计定稿）**，实现见 [`milestones/M5-kg-plan.md`](./milestones/M5-kg-plan.md)。  
> 依据：[`technical-architecture.md`](./technical-architecture.md)、[`checklist.md`](./checklist.md)、[`data-model.md`](./data-model.md)、[`api-contracts.md`](./api-contracts.md)、[`knowledge-graph.md`](./knowledge-graph.md)。

---

## 0. 目标与原则

### 0.1 近期目标（第一交付）

打通 **M1 竖切**：

```
租户 A 上传文档 → 解析 → 向量入库 →（可查询状态）
租户 B 同名/同内容文档互不可见；越权检索为空/拒绝
```

不在第一交付内：完整学习总结 UI、Agent、SCIM、连接器、审批流。

### 0.2 执行原则

| 原则 | 做法 |
|------|------|
| 企业模型 Day 1 | 全表 `tenant_id`；向量 payload 必带租户字段 |
| 先竖切后长尾 | 一条路径跑通再扩格式/UI |
| 可测红线 | 双租户隔离自动化测试必须绿 |
| 配置分 profile | `personal` 可本地账号；结构仍按企业 |
| 小步提交 | 每完成一个可验证里程碑即提交 |
| **里程碑门禁** | **每个 E*/M* 完成后必须：整体 review + 回归测试通过，方可进入下一阶段** |

### 0.3 里程碑完成门禁（强制）

每个执行阶段（E0–E7）及项目里程碑（M1–M5）结束时，必须完成：

1. **整体 Review**
   - 对照本阶段任务清单与出口标准逐项核对
   - 代码/配置/文档一致性检查
   - 安全红线抽查（tenant_id、无裸检索等）
2. **回归验证**
   - 运行本阶段及之前全部自动化测试
   - 记录命令、结果、失败项与修复
   - 产出简短 `docs/milestones/Ex-review.md`（或追加 execution-log）
3. **签字放行**
   - checklist 勾选本阶段出口
   - 未通过不得开始下一阶段主开发

---

## 1. 阶段总览

| 阶段 | 名称 | 产出 | 依赖 |
|------|------|------|------|
| E0 | 冻结与骨架 | 仓库结构、Compose、配置、错误码 | 无 |
| E1 | 身份与租户 | 登录、Tenant/Workspace/RBAC | E0 |
| E2 | 上传与对象存储 | 预签名上传、UploadJob | E1 |
| E3 | 解析与向量 | Parse/Embed Worker、Qdrant | E2 |
| E4 | ACL 与隔离验收 | 文档 ACL、双租户测试 | E3 |
| E5 | M2 竖切预备 | 学习 Worker + 问答 API 最小版 | E4 |
| E6 | 前端可用 | Next.js 上传/状态/简单问答 | E5 |
| E7 | 治理与企业件 | 配额、Agent、SCIM、连接器… | E6 |

**当前执行焦点：M5 知识图谱 KG.1（存储 + 抽取）**；设计见 [`knowledge-graph.md`](./knowledge-graph.md)。

---

## 2. E0 — 冻结与骨架

### 2.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| E0.1 | 评审并冻结 `data-model.md` 中 Tenant/Workspace/ACL/UploadJob/Document/Chunk 字段 | 评审记录或 checklist 勾选「字段级冻结」 |
| E0.2 | 初始化 monorepo 目录：`apps/api`、`apps/workers`、`apps/web`、`packages/shared`、`deploy/compose` | 目录存在；README 指向启动方式 |
| E0.3 | Python 工具链：`pyproject.toml` / uv 或 poetry；ruff + pytest | `pytest` 可跑空测试 |
| E0.4 | 配置体系：`PROFILE=personal\|team\|enterprise` + `.env.example` | 切换 profile 不改代码路径 |
| E0.5 | `docker-compose.yml`：Postgres、Redis、Qdrant、MinIO（+ 可选 Keycloak） | `compose up` 健康检查通过 |
| E0.6 | 错误码字典、`request_id` 中间件、结构化日志骨架 | 任意 API 响应带 `request_id` |
| E0.7 | Alembic 初始化；首迁：tenants/users/workspaces 空表可演进 | `alembic upgrade head` 成功 |
| E0.8 | CI 草图：lint + test（可先 GitHub Actions 最小） | PR 可跑通 |

### 2.2 建议目录

```
apps/api/           # FastAPI
apps/workers/       # 队列消费者
apps/web/           # Next.js（E6 再充实）
packages/shared/    # 配置、错误码、DB models 公共部分
deploy/compose/     # 本地依赖
docs/               # 已有设计
```

### 2.3 出口标准

- [ ] 一键拉起依赖
- [ ] API `GET /healthz`、`GET /readyz` 可用
- [ ] 迁移可重复执行

---

## 3. E1 — 身份与租户

### 3.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| E1.1 | 表：tenants、users、memberships、workspaces、workspace_members | 迁移 + CRUD 仓储 |
| E1.2 | `personal`：本地注册/登录或固定 bootstrap admin | 能拿到 JWT/session |
| E1.3 | `enterprise` 路径预留 OIDC（可先 mock IdP） | 配置项齐全；未启用时不影响 personal |
| E1.4 | AuthContext 中间件：解析 `tenant_id`、`user_id`、roles | 下游强制依赖上下文 |
| E1.5 | API：`GET /me`、`GET/POST /workspaces` | 契约与 `api-contracts` 对齐（可子集） |
| E1.6 | 种子脚本：Tenant A / Tenant B 各一管理员 | 测试可复用 |

### 3.2 出口标准

- [ ] 两租户用户登录后 `tenant_id` 不同且不可伪造覆盖
- [ ] 无 Token 访问业务 API → 401

---

## 4. E2 — 上传与对象存储

### 4.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| E2.1 | MinIO bucket 初始化；存储抽象 `StorageProvider` | 本地可 PUT/GET |
| E2.2 | 表：upload_jobs、documents、document_versions | 状态机按 data-model |
| E2.3 | `POST .../uploads/presign`（Idempotency-Key） | 重放返回同一 job |
| E2.4 | 客户端直传（或集成测试模拟 PUT） | 对象键含 tenant/workspace/document |
| E2.5 | `POST .../complete` → 状态 uploaded + 入队 parse | Redis 可见消息 |
| E2.6 | `GET /upload-jobs/{id}` 进度查询 | 状态字段正确 |
| E2.7 | 配额钩子（可先硬编码限额） | 超限 429/`quota_exceeded` |

### 4.2 出口标准

- [ ] 集成测试：presign → put → complete → job=uploaded
- [ ] 对象路径无法跨租户猜测访问（无签名拒绝）

---

## 5. E3 — 解析与向量

### 5.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| E3.1 | Worker 框架：认领任务、重试、DLQ | 失败 3 次进 DLQ |
| E3.2 | Parser：至少 **md/txt + pdf**（docx 可紧随） | 文本落入 derived |
| E3.3 | Chunker：默认 size/overlap 可配置 | chunks 表有序写入 |
| E3.4 | Embedding Provider 接口；dev 可用假向量或小模型 | 点写入 Qdrant |
| E3.5 | Qdrant collection：payload 强制字段 | filter 含 tenant_id |
| E3.6 | 任务链：parse → embed → job=indexed/ready（学习先跳过） | 状态可查询 |
| E3.7 | 幂等：同 checksum 策略（跳过或返回已有） | 单测覆盖 |

### 5.2 出口标准

- [ ] 上传一份 Markdown，job 到 `indexed`/`ready`
- [ ] Qdrant 中点的 `tenant_id` 正确

---

## 6. E4 — ACL 与隔离验收（M1 关门）

### 6.1 任务清单

| # | 任务 | 验收 |
|---|------|------|
| E4.1 | document_acl 最小：owner + workspace_all | 授权判定函数单测 |
| E4.2 | 内部检索 API 或调试 search：强制 tenant + ACL filter | 无 filter 代码路径不存在 |
| E4.3 | 自动化：**双租户隔离套件** | 见下方用例 |
| E4.4 | 审计事件：upload.completed、document.indexed | 可查 audit 表 |
| E4.5 | 更新 checklist M1 全勾；打 tag `m1-slice` | 发布说明一页 |

### 6.2 必须通过的测试用例

| ID | 用例 | 期望 |
|----|------|------|
| T1 | 租户 A 上传 docX | job ready |
| T2 | 租户 B search「docX 独有句」 | 0 hit |
| T3 | 租户 B 直接 GET A 的 document_id | 404 |
| T4 | 租户 A 成员 Viewer 可读；无成员 404 | 按 ACL |
| T5 | 伪造 JWT tenant 为 A 访问 B 资源 | 拒绝 |
| T6 | Qdrant scroll 不带 filter 的生产代码路径 | 静态检查/禁止 |

### 6.3 M1 出口标准（第一交付完成定义）

- [ ] T1–T6 全绿
- [ ] Compose 文档可让新人 30 分钟内复现
- [ ] 已知限制清单写明（无学习、无 UI 或仅最小 API）

---

## 7. E5 — M2 最小智能（计划预告）

在 E4 完成后再启动，不并行抢主路径：

| # | 任务 | 验收 |
|---|------|------|
| E5.1 | Learn Worker：summary/outline/key_points JSON | 学习报告 API 可读 |
| E5.2 | 发布状态 draft/published（personal 默认 auto） | |
| E5.3 | `POST /search` + `POST /ask` 流式/非流式 | 带 citations |
| E5.4 | 引用校验：chunk 必须属于授权文档 | 单测 |
| E5.5 | LLM Gateway 初版（单 provider + 计量） | usage_ledger 有记录 |

**M2 出口**：上传后自动出学习报告；带引用问答；隔离测试仍绿。

---

## 8. E6 — 前端

| # | 任务 | 验收 |
|---|------|------|
| E6.1 | 登录 + 空间切换 | |
| E6.2 | 上传区 + 任务进度 | |
| E6.3 | 学习报告页 | |
| E6.4 | 对话页 + 引用抽屉 | |
| E6.5 | 管理：成员列表（只读先行） | |

可与 E5 后半并行，但不得阻塞隔离测试。

---

## 9. E7 — 企业件（M3+ 排期）

按优先级（完成 E5/E6 后）：

1. 配额与 usage 面板  
2. Agent 工具白名单（search/learn/review）  
3. SCIM + Group ACL  
4. 首个连接器（建议 S3）  
5. 审批发布模式、敏感级模型路由  
6. 备份演练按 `ops-slo-dr.md`

---

## 10. 人员与分工建议（单人/小团队）

| 角色 | 聚焦 |
|------|------|
| 后端 | E0–E5 API/Worker/DB |
| 前端 | E6（E4 后介入） |
| 全栈单人 | 严格按 E0→E4 顺序，E6 用最简页面或先用 API/httpie |

---

## 11. 风险与缓冲

| 风险 | 缓解 |
|------|------|
| PDF 解析质量差 | E3 先保 md/txt；PDF 文本型优先 |
| Embedding 环境重 | dev 用 mock embedding，CI 不下载大模型 |
| OIDC 耗时 | personal 本地登录先行；OIDC 接口预留 |
| 范围膨胀 | 任何「顺便做学习/Agent」拖过 E4 一律排到 E5+ |

---

## 12. 近两周执行日历（建议）

> 按工作日强度假设；可按人力压缩/拉长。

| 日序 | 焦点 |
|------|------|
| D1–D2 | E0 骨架 + Compose + 迁移 + health |
| D3–D4 | E1 身份与双租户种子 |
| D5–D7 | E2 上传全链路 |
| D8–D10 | E3 parse/embed/worker |
| D11–D12 | E4 ACL + T1–T6 |
| D13 | 文档/演示/tag `m1-slice` |
| D14+ | 启动 E5（学习+问答） |

---

## 13. 即时下一步（开工命令序）

1. **确认本计划**（本文）作为执行基线  
2. 执行 **E0.1–E0.5**：字段冻结声明 + 建仓骨架 + Compose  
3. 提交：`chore: scaffold monorepo and local dependencies`  
4. 进入 E1，不再回头扩文档专题（除非实现打脸）

---

## 14. 跟踪方式

- 勾选 [`checklist.md`](./checklist.md) M0/M1  
- 每阶段结束更新本文「出口标准」复选框  
- 阻塞记入 `docs/execution-log.md`（实现时按需建）

---

## 15. 明确不做（本执行窗口）

- 连接器 / SCIM 实现  
- 完整 Agent  
- 多区域 DR 落地  
- 计费/发票  
- 替换主文档已定技术栈（除非 E0 评审改 ADR）

---

## 16. M5 知识图谱进度

| 阶段 | 状态 | 文档 |
|------|------|------|
| KG.0 详细设计与计划 | **完成** | [`knowledge-graph.md`](./knowledge-graph.md)、[`milestones/M5-kg-plan.md`](./milestones/M5-kg-plan.md) |
| KG.1 存储 + 抽取 | 待开工 | 实现分支建议 `cursor/m5-knowledge-graph-4365` |
| KG.2 查询 + ACL | 待开工 | |
| KG.3 Ask 增强 | 待开工 | |
| KG.4 前端 | 待开工 | |
| KG.5 门禁 | 待开工 | `M5-kg-review.md` |

**设计锁定**：SQL 邻接表优先、列表 UI 优先、图谱作为 RAG 增强（默认关闭）、租户/ACL 强制、抽取复用 Real-LLM Gateway；Neo4j/大画布/多模态实体不在本里程碑。
