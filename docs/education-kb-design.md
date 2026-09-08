# 教育智能知识库（K12 教材 · 题目）设计

> 状态：EDU.0 设计定稿 · EDU.1–3 试点已实现（packs/题库/讲题/学习页）  
> 范围：小学 → 初中（可扩展高中）；教材 + 题库 + 知识点 + 讲题/练习  
> 底座：Atrium KB（租户 / ACL / 文库 / Ask / Graph / Wiki / Gateway）  
> 关联：[`llm-wiki-design.md`](./llm-wiki-design.md)、[`knowledge-graph.md`](./knowledge-graph.md)、[`optimization-plan-full-pipeline.md`](./optimization-plan-full-pipeline.md)

---

## 0. 一句话

在 Atrium 上增加 **教育域**：把「教材章节」当作 Raw，把「题目」当作一等公民，把「课标知识点」当作 Wiki `concept` / KG 实体，支撑 **讲题、相似题、按知识点复习**，且全程租户隔离与版权可追溯。

---

## 1. 目标与非目标

### 1.1 目标

| 目标 | 说明 |
|------|------|
| 学段覆盖 | 小学、初中（年级 G1–G9）；学科可配置 |
| 教材 | 按版本/册次/单元/课入库，可引用到段落 |
| 题库 | 选择/填空/解答等；题干、答案、解析、难度、知识点 |
| 智能讲题 | Ask/练习：结合教材证据 + 解析；可出相似题 |
| 知识结构 | 知识点树/图；题–知识点–教材 多向关联 |
| 合规 | 内容包带授权声明；禁止默认「全网扒教辅」 |

### 1.2 非目标（首期）

- 直播课堂 / 完整 LMS（考勤、成绩单全套）  
- 未授权「全国所有出版社全部教材题」一键灌库  
- 替代教育部官方题库或考试系统  
- 自动搜题拍照 App（可后期接多模态）  

### 1.3 试点建议（EDU.1）

**初中数学 · 人教版（或选定一版）七年级上册 + 配套精选题 200～500 道**  
跑通后再扩学科/学段。

---

## 2. 为何能嵌进 Atrium

| 教育对象 | Atrium 映射 |
|----------|-------------|
| 教材 PDF/章节 | `Document` + 教育元数据（grade/subject/edition） |
| 课文段落 | `Chunk`（OPT 后真向量） |
| 知识点 | Wiki `concept` + KG `entity(type=concept)` |
| 题目 | **新表** `edu_questions`（勿当普通文档硬塞） |
| 讲题对话 | `Ask` + `retrieve=auto` + 题上下文 |
| 学校/机构 | `Tenant`；班级/年级 → `Workspace` 或 edu 分组 |
| 版权包 | `edu_content_packs` + license |

```text
授权内容包
  ├─ 教材 Document（Raw）──Ingest──▶ Wiki source / 知识点 concept
  ├─ 题目 Question ──────────────▶ 链知识点 + 可选教材锚点
  └─ 练习/讲题 Ask
        ├─ 读题 + 解析
        ├─ 拉教材 chunk / Wiki
        └─ 推荐相似题
```

---

## 3. 领域模型

### 3.1 学段与学科枚举（首期）

```text
stage: primary | junior
grade: 1..9
subject: chinese | math | english | physics | chemistry | biology
         | history | geography | politics | science | other
```

### 3.2 内容包（版权单元）

```sql
CREATE TABLE edu_content_packs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,              -- platform 级可用 tenant_id='*' 或单独 platform 表；首期租户自有包
  name TEXT NOT NULL,
  stage TEXT NOT NULL,
  subject TEXT NOT NULL,
  grade_min INTEGER,
  grade_max INTEGER,
  edition TEXT NOT NULL DEFAULT '',     -- 人教版/苏教版…
  license_type TEXT NOT NULL,          -- owned|licensed|open|demo
  license_note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);
```

### 3.3 教材元数据（扩展 Document）

不改崩现表时，用旁表：

```sql
CREATE TABLE edu_document_meta (
  document_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  pack_id TEXT,
  stage TEXT NOT NULL,
  subject TEXT NOT NULL,
  grade INTEGER NOT NULL,
  edition TEXT NOT NULL DEFAULT '',
  volume TEXT NOT NULL DEFAULT '',      -- 上册/下册
  unit_no TEXT NOT NULL DEFAULT '',
  lesson_title TEXT NOT NULL DEFAULT '',
  curriculum_code TEXT NOT NULL DEFAULT ''  -- 课标点可选
);
```

### 3.4 知识点

优先复用 Wiki/KG；教育侧加课标编码：

```sql
CREATE TABLE edu_knowledge_points (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  pack_id TEXT,
  code TEXT NOT NULL DEFAULT '',        -- 课标或内部编码
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  stage TEXT NOT NULL,
  grade INTEGER,
  parent_id TEXT,                       -- 树
  wiki_page_id TEXT,                    -- 可选链 Wiki concept
  entity_id TEXT,                       -- 可选链 KG
  UNIQUE(tenant_id, subject, code, name)
);
```

### 3.5 题目（一等公民）

```sql
CREATE TABLE edu_questions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  pack_id TEXT,
  stem_md TEXT NOT NULL,                -- 题干（可含 LaTeX）
  options_json TEXT NOT NULL DEFAULT '[]',  -- 选择题
  answer_md TEXT NOT NULL DEFAULT '',
  analysis_md TEXT NOT NULL DEFAULT '', -- 解析
  qtype TEXT NOT NULL,                 -- single|multi|fill|judge|essay|calc
  difficulty INTEGER NOT NULL DEFAULT 3, -- 1-5
  grade INTEGER,
  subject TEXT NOT NULL,
  stage TEXT NOT NULL,
  source_doc_id TEXT,                   -- 来自试卷文档时
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE edu_question_points (
  question_id TEXT NOT NULL,
  knowledge_point_id TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (question_id, knowledge_point_id)
);

CREATE TABLE edu_question_anchors (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  document_id TEXT NOT NULL,           -- 教材
  chunk_id TEXT,                        -- 段落锚点
  note TEXT NOT NULL DEFAULT ''
);
```

### 3.6 练习会话（最小）

```sql
CREATE TABLE edu_practice_sessions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  workspace_id TEXT,
  mode TEXT NOT NULL,                  -- drill|explain|exam
  filter_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE edu_practice_items (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  user_answer_md TEXT NOT NULL DEFAULT '',
  is_correct INTEGER,                   -- null=未判
  explain_ask_id TEXT,                  -- 可选关联 Ask 轨迹
  created_at TEXT NOT NULL
);
```

---

## 4. ACL 与版权

### 4.1 可见性

- 题目/知识点默认跟随 `pack` 授权范围 + 租户隔离。  
- 讲题引用教材 chunk 时，**二次校验** `can_read_document`（与 Ask 一致）。  
- 平台级共享包：通过「订阅」表授权给租户，禁止裸共享跨租户 ID。

### 4.2 版权闸门

| license_type | 行为 |
|--------------|------|
| `demo` | 仅内置样例，可公开演示 |
| `owned` | 租户自有讲义/校本 |
| `licensed` | 需填写授权方与期限；过期只读或下架 |
| `open` | 明确开源/公有协议链接 |

**入库 API 拒绝**无 `license_type` 的批量教材包。产品文案禁止宣传「已收录全国全部盗版教辅」。

---

## 5. 智能能力

### 5.1 讲题（Explain）

```text
输入：question_id 或粘贴题干
  → 取题目 + 知识点 + anchors
  → 检索教材 chunk / Wiki concept（ACL）
  → Gateway 讲解（步骤、易错、对应教材）
  → 引用：题解析 + 教材 chunk
  → 可选：归档 synthesis「本题讲解」
```

Ask 扩展：`POST /v1/ask` 增加 `edu_question_id`；或独立 `POST /v1/edu/explain`。

### 5.2 相似题 / 按点练习

- 向量：题干 embedding（依赖 OPT.1）  
- 结构：同 `knowledge_point_id` + 难度邻近  
- 融合排序后返回列表  

### 5.3 与 Wiki / Graph

| 动作 | 效果 |
|------|------|
| 教材 Ingest | Wiki `source` + 知识点 `concept` |
| 题目入库 | 链 `edu_knowledge_points`；可选写 entity 提及 |
| Lint | 孤儿知识点、无解析题、无教材锚点题 |

教育 Schema 追加页类型建议：`question_note`（可选，优质讲题归档）。

---

## 6. API 草案

| Method | Path | 说明 |
|--------|------|------|
| POST | `/v1/edu/packs` | 创建内容包（含 license） |
| GET | `/v1/edu/packs` | 列表 |
| POST | `/v1/edu/documents/{id}/meta` | 绑定教材元数据 |
| POST | `/v1/edu/points` | 知识点 upsert |
| GET | `/v1/edu/points` | 树/列表 |
| POST | `/v1/edu/questions` | 单题或批量导入 |
| GET | `/v1/edu/questions` | 筛选：学科/年级/知识点/难度 |
| GET | `/v1/edu/questions/{id}` | 详情 |
| POST | `/v1/edu/explain` | 讲题 |
| POST | `/v1/edu/practice` | 开练习会话 |
| POST | `/v1/edu/practice/{id}/answer` | 提交作答 |
| GET | `/v1/edu/similar` | `question_id` 相似题 |

---

## 7. 前端

| 入口 | 功能 |
|------|------|
| `/app/edu` | 学科导航、教材包、知识点树 |
| `/app/edu/questions` | 题库筛选 / 导入 |
| `/app/edu/practice` | 练习与讲题 |
| 文库 | 上传教材后补「教育元数据」 |
| 侧栏 | 「学习」或「题库」 |

首期可只做 **题库列表 + 讲题页**，练习会话其次。

---

## 8. 完整链路

```text
授权 Pack
  │
  ├─ 教材 PDF/MD → Document Meta(grade,subject,edition)
  │     → Parse/Chunk/(Embed) → Wiki/Graph 知识点
  │
  └─ 题目 JSON/表格导入 → edu_questions
        → 挂知识点 / 教材锚点
              │
              ▼
        学生/教师：练习 · 讲题 · Ask
              │
              ├─ 教材证据（ACL）
              ├─ 解析 + Gateway
              └─ 相似题 / 错题本（后期）
```

---

## 9. 分阶段计划（EDU.*）

| 阶段 | 内容 | 依赖 | 出口 |
|------|------|------|------|
| **EDU.0** | 本文设计 | — | 评审通过 |
| **EDU.1** | packs/meta/points/questions 表 + CRUD API | 现网 | **完成**（`0008`） |
| **EDU.2** | Explain 讲题 + 教材锚点引用 | EDU.1, Gateway | **完成** |
| **EDU.3** | `/app/edu` 题库+讲题 UI | EDU.2 | **完成** |
| **EDU.4** | 相似题 + 练习会话 | OPT.1 更佳 | 结构相似已有；向量待 OPT |
| **EDU.5** | Wiki/KG 知识点对齐 + Lint | WIKI.* | 待开工 |
| **EDU.6** | 多学科扩展与平台内容订阅 | EDU.5 | 待开工 |

**试点数据：** 初中数学一册 + 精选题集（`license=demo|owned`）。

---

## 10. 配置

| 变量 | 默认 | 说明 |
|------|------|------|
| `EDU_ENABLED` | `false` | 总开关 |
| `EDU_REQUIRE_LICENSE` | `true` | 强制内容包授权字段 |
| `EDU_DEFAULT_STAGE` | `junior` | |
| `EDU_SIMILAR_TOP_K` | `5` | |

---

## 11. 测试要点

- 跨租户题目不可见  
- 无教材读权限时讲题不得引用该 chunk  
- 无 license 的 pack 创建失败  
- 试点学科：导入 → 按知识点筛题 → explain 含引用  
- 回归：既有 Ask/Graph/文库不受影响（feature flag）  

---

## 12. 风险

| 风险 | 缓解 |
|------|------|
| 版权诉讼 | 授权包模型；不做非法全量采集 |
| 公式/排版 | stem 用 Markdown+LaTeX；渲染 KaTeX |
| 题海规模 | 先试点；向量与分页必备 |
| 与 Wiki 重复建设 | 知识点统一 concept；题仍独立表 |
| 幻觉讲题 | 强制附解析与教材引用；无证据则降级 |

---

## 13. 成功标准（试点）

1. 一套 `demo` 包可导入教材元数据 + ≥100 题。  
2. 按知识点筛题可用。  
3. Explain 返回步骤解析，且在有锚点时引用教材。  
4. ACL/租户隔离测试通过。  
5. `EDU_ENABLED` 默认关闭时主产品行为不变。  

---

## 14. 下一步

1. 确认试点：**学科 / 版本 / 题量 / 授权类型**。  
2. 分支建议：`cursor/edu-k12-design-4365`（本文）→ `cursor/edu-k12-pilot-4365`（EDU.1–3）。  
3. 与 OPT.1/OPT.3、WIKI.1 **并行**：教育试点可先用 MD 教材 + 本地 Gateway，再升级真向量与 PDF。
