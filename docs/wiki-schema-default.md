# Atrium Wiki Schema（默认模板）

> 租户初始化时写入 `wiki_schemas.schema_md`。可与人共进化；勿静默大幅改写已发布页规范。

## 1. 页面类型

- `source`：一篇 Raw 的摘要与主张
- `entity`：人物、组织、产品、项目
- `concept`：概念、方法、框架
- `synthesis`：主题综述或归档问答
- `comparison`：多对象对照
- `overview`：全局活综述
- `index` / `log`：系统页（由服务维护）

## 2. Frontmatter

必填：`title`, `type`, `last_updated`  
建议：`tags`, `sources`, `related`, `contradictions`, `confidence`

## 3. 命名

- `source`：kebab-case，可含日期  
- `entity` / `concept`：稳定显示名；slug 小写连字符  
- 禁止无意义的 `page-1` 式命名

## 4. 交叉引用与矛盾

- 每页应有 `## Connections`，至少一条 `[[wikilink]]`  
- 新信息与旧主张冲突时：**不得静默覆盖**；写入 `## 矛盾与待核` 与 frontmatter `contradictions`

## 5. Ingest 工作流

1. 只读 Raw，不修改 Raw  
2. 创建/更新 `source`  
3. upsert 相关 `entity`/`concept`（同 type+规范名合并）  
4. 更新链接与 index  
5. 追加 log：`## [YYYY-MM-DD] ingest | {title}`  
6. 单源最多触达 `WIKI_MAX_PAGES_PER_INGEST` 页

## 6. Query 工作流

1. 先读 index / overview  
2. 下钻相关页；证据不足再回落 Raw chunks  
3. 回答须可追溯 sources  
4. 用户确认或高价值答案 → 归档为 `synthesis`/`comparison`

## 7. Lint 规则

检查：矛盾未归档、过期主张、孤儿页、悬空链接、提及未建页的概念、ACL 漂移风险。  
自动修复仅限「补链/改 index」类低风险项；内容改写需 supervised。
