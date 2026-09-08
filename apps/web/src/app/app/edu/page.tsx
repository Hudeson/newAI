"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type EduExplain,
  type EduOfficialSource,
  type EduOfficialSyncResult,
  type EduPack,
  type EduPoint,
  type EduPractice,
  type EduQuestion,
  type EduWebSearchResult,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

const SUBJECT_LABEL: Record<string, string> = {
  math: "数学",
  chinese: "语文",
  english: "英语",
  physics: "物理",
  chemistry: "化学",
  biology: "生物",
  history: "历史",
  geography: "地理",
  politics: "政治",
  science: "科学",
  other: "其他",
};

const STAGE_LABEL: Record<string, string> = {
  primary: "小学",
  junior: "初中",
};

const QTYPE_LABEL: Record<string, string> = {
  single: "单选",
  multi: "多选",
  fill: "填空",
  judge: "判断",
  essay: "解答",
  calc: "计算",
};

const LICENSE_LABEL: Record<string, string> = {
  demo: "演示",
  owned: "自有",
  licensed: "授权",
  open: "开放",
};

export default function EduPage() {
  const { token, workspaceId } = useAuth();
  const [packs, setPacks] = useState<EduPack[]>([]);
  const [points, setPoints] = useState<EduPoint[]>([]);
  const [questions, setQuestions] = useState<EduQuestion[]>([]);
  const [pointFilter, setPointFilter] = useState("");
  const [selected, setSelected] = useState<EduQuestion | null>(null);
  const [explain, setExplain] = useState<EduExplain | null>(null);
  const [similar, setSimilar] = useState<EduQuestion[]>([]);
  const [practice, setPractice] = useState<EduPractice | null>(null);
  const [answerDraft, setAnswerDraft] = useState("");
  const [gradeMsg, setGradeMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [officialSources, setOfficialSources] = useState<EduOfficialSource[]>([]);
  const [officialSourceId, setOfficialSourceId] = useState("fixture-moe-math-g7");
  const [customFeedUrl, setCustomFeedUrl] = useState("");
  const [acceptLicense, setAcceptLicense] = useState(false);
  const [syncResult, setSyncResult] = useState<EduOfficialSyncResult | null>(null);
  const [webQuery, setWebQuery] = useState("七年级有理数 教程 试题");
  const [webAutoImport, setWebAutoImport] = useState(true);
  const [webResult, setWebResult] = useState<EduWebSearchResult | null>(null);

  const pointName = useMemo(() => {
    const map = new Map(points.map((p) => [p.id, p.name]));
    return (id: string) => map.get(id) || id.slice(0, 8);
  }, [points]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const [p, pt, qs, sources] = await Promise.all([
      api.eduPacks(token),
      api.eduPoints(token),
      api.eduQuestions(token, {
        knowledge_point_id: pointFilter || undefined,
        limit: 50,
      }),
      api.eduOfficialSources(token),
    ]);
    setPacks(p);
    setPoints(pt);
    setQuestions(qs);
    setOfficialSources(sources);
    if (!officialSourceId && sources[0]) setOfficialSourceId(sources[0].id);
  }, [token, pointFilter, officialSourceId]);

  useEffect(() => {
    refresh().catch((err) =>
      setError(err instanceof ApiError ? err.message : "加载学习模块失败"),
    );
  }, [refresh]);

  async function onSeed() {
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      await api.eduSeedDemo(token);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "导入演示包失败");
    } finally {
      setBusy(false);
    }
  }

  async function onOfficialSync() {
    if (!token || !workspaceId) return;
    setBusy(true);
    setError("");
    setSyncResult(null);
    try {
      const res = await api.eduOfficialSync(token, {
        source_id: officialSourceId,
        workspace_id: workspaceId,
        accept_license: acceptLicense,
        feed_url: officialSourceId === "live-custom" ? customFeedUrl.trim() || undefined : undefined,
      });
      setSyncResult(res);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "官网同步失败");
    } finally {
      setBusy(false);
    }
  }

  async function onWebSearch() {
    if (!token || !workspaceId || !webQuery.trim()) return;
    setBusy(true);
    setError("");
    setWebResult(null);
    try {
      const res = await api.eduWebSearch(token, {
        query: webQuery.trim(),
        workspace_id: workspaceId,
        subject: "math",
        stage: "junior",
        grade: 7,
        limit: 5,
        auto_import: webAutoImport,
        accept_license: acceptLicense,
      });
      setWebResult(res);
      if (webAutoImport) await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "联网搜索失败");
    } finally {
      setBusy(false);
    }
  }

  async function onSelect(q: EduQuestion) {
    if (!token) return;
    setError("");
    setExplain(null);
    setGradeMsg("");
    setAnswerDraft("");
    try {
      const detail = await api.eduQuestion(token, q.id);
      setSelected(detail);
      const sim = await api.eduSimilar(token, q.id);
      setSimilar(sim);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载题目失败");
    }
  }

  async function onExplain(e: FormEvent) {
    e.preventDefault();
    if (!token || !selected) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.eduExplain(token, { question_id: selected.id, limit: 5 });
      setExplain(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "讲题失败");
    } finally {
      setBusy(false);
    }
  }

  async function onStartPractice() {
    if (!token) return;
    setBusy(true);
    setError("");
    setGradeMsg("");
    try {
      const session = await api.eduPractice(token, {
        mode: "drill",
        workspace_id: workspaceId || undefined,
        filters: pointFilter ? { knowledge_point_id: pointFilter } : { subject: "math" },
        limit: 3,
      });
      setPractice(session);
      if (session.questions[0]) await onSelect(session.questions[0]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "开始练习失败");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmitAnswer(e: FormEvent) {
    e.preventDefault();
    if (!token || !practice || !selected) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.eduPracticeAnswer(token, practice.session_id, {
        question_id: selected.id,
        user_answer_md: answerDraft,
      });
      if (res.is_correct === 1) setGradeMsg("回答正确");
      else if (res.is_correct === 0) setGradeMsg(`回答有误。参考：${selected.answer_md || "见解析"}`);
      else setGradeMsg("已提交（主观题待教师/模型批改）");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 28 }}>
      <header className="stack" style={{ gap: 8 }}>
        <div className="page-kicker">Education</div>
        <h1>学习</h1>
        <p className="muted">
          授权内容包 · 知识点 · 题库与讲题。试点：初中数学演示包（非全网盗版教辅）。
        </p>
      </header>

      {error ? <div className="error">{error}</div> : null}

      <section className="panel">
        <div>
          <h2>自动联网搜索</h2>
          <p className="muted">
            在教育官网白名单内检索教程/试题；可自动入库。默认 fixture
            演示；线上配置 WEB_SEARCH_MODE=live 与 Brave/Bing Key 或 duckduckgo。
          </p>
        </div>
        <div className="stack" style={{ gap: 12, marginTop: 12 }}>
          <label className="field">
            搜索词
            <input
              value={webQuery}
              onChange={(e) => setWebQuery(e.target.value)}
              placeholder="例如：七年级有理数 课标 试题"
            />
          </label>
          <label className="row" style={{ gap: 8 }}>
            <input
              type="checkbox"
              checked={acceptLicense}
              onChange={(e) => setAcceptLicense(e.target.checked)}
            />
            <span>我确认来源为官方公开或已获授权，同意按声明许可入库</span>
          </label>
          <label className="row" style={{ gap: 8 }}>
            <input
              type="checkbox"
              checked={webAutoImport}
              onChange={(e) => setWebAutoImport(e.target.checked)}
            />
            <span>搜索后自动导入白名单/结构化结果</span>
          </label>
          <button className="btn accent" type="button" disabled={busy} onClick={onWebSearch}>
            {busy ? "搜索中…" : "联网搜索并入库"}
          </button>
          {webResult ? (
            <div className="stack" style={{ gap: 8 }}>
              <p className="muted">
                查询：{webResult.query} · 提供方 {webResult.provider} · 命中{" "}
                {webResult.hits.length}
                {webResult.imports.length
                  ? ` · 已导入 ${webResult.imports.length} 批`
                  : ""}
              </p>
              <ul className="list-plain">
                {webResult.hits.map((h) => (
                  <li key={h.url}>
                    <strong>{h.title}</strong>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {h.snippet}
                    </div>
                    <small className="muted">
                      {h.url}
                      {h.allowlisted ? " · 白名单" : ""}
                    </small>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </section>

      <section className="panel">
        <div>
          <h2>官网自动同步</h2>
          <p className="muted">
            仅拉取白名单教育官网 / 授权 JSON 源。须勾选授权确认；默认 fixture
            模式可离线演示，线上设 EDU_OFFICIAL_MODE=live。
          </p>
        </div>
        <div className="stack" style={{ gap: 12, marginTop: 12 }}>
          <label className="field">
            官方源
            <select
              className="select"
              value={officialSourceId}
              onChange={(e) => setOfficialSourceId(e.target.value)}
            >
              {officialSources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}（{LICENSE_LABEL[s.license_type] || s.license_type}）
                </option>
              ))}
            </select>
          </label>
          {officialSourceId === "live-custom" ? (
            <label className="field">
              授权 Feed URL（白名单域名）
              <input
                value={customFeedUrl}
                onChange={(e) => setCustomFeedUrl(e.target.value)}
                placeholder="https://www.moe.gov.cn/.../feed.json"
              />
            </label>
          ) : null}
          <label className="row" style={{ gap: 8 }}>
            <input
              type="checkbox"
              checked={acceptLicense}
              onChange={(e) => setAcceptLicense(e.target.checked)}
            />
            <span>我确认该来源为官方公开或已获授权内容，同意按声明许可入库</span>
          </label>
          <div className="row">
            <button className="btn" type="button" disabled={busy} onClick={onOfficialSync}>
              {busy ? "同步中…" : "从官网同步教程与试题"}
            </button>
          </div>
          {syncResult ? (
            <p className="muted">
              同步{syncResult.status}：教程 {syncResult.tutorials_imported} · 知识点{" "}
              {syncResult.points_imported} · 试题 {syncResult.questions_imported}
            </p>
          ) : null}
          {officialSources.find((s) => s.id === officialSourceId)?.license_note ? (
            <p className="muted" style={{ fontSize: 13 }}>
              许可说明：{officialSources.find((s) => s.id === officialSourceId)?.license_note}
            </p>
          ) : null}
        </div>
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2>内容包</h2>
            <p className="muted">创建包需声明 license；可一键导入数学演示样例。</p>
          </div>
          <button className="btn" type="button" disabled={busy} onClick={onSeed}>
            {busy ? "处理中…" : "导入数学演示包"}
          </button>
        </div>
        {packs.length === 0 ? (
          <p className="muted">暂无内容包。点击上方导入演示数据。</p>
        ) : (
          <ul className="list-plain">
            {packs.map((p) => (
              <li key={p.id}>
                <strong>{p.name}</strong>
                <span className="muted">
                  {" "}
                  · {STAGE_LABEL[p.stage] || p.stage}
                  {" · "}
                  {SUBJECT_LABEL[p.subject] || p.subject}
                  {" · "}
                  {LICENSE_LABEL[p.license_type] || p.license_type}
                  {p.edition ? ` · ${p.edition}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h2>题库</h2>
            <p className="muted">按知识点筛选；选择题目后可讲题或练习。</p>
          </div>
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <select
              value={pointFilter}
              onChange={(e) => setPointFilter(e.target.value)}
              aria-label="知识点筛选"
            >
              <option value="">全部知识点</option>
              {points.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code ? `${p.code} ` : ""}
                  {p.name}
                </option>
              ))}
            </select>
            <button className="btn ghost" type="button" disabled={busy} onClick={onStartPractice}>
              开始练习
            </button>
          </div>
        </div>

        <div className="split" style={{ marginTop: 16 }}>
          <div>
            {questions.length === 0 ? (
              <p className="muted">暂无题目。</p>
            ) : (
              <ul className="list-plain selectable">
                {questions.map((q) => (
                  <li key={q.id}>
                    <button
                      type="button"
                      className={selected?.id === q.id ? "link-btn active" : "link-btn"}
                      onClick={() => onSelect(q)}
                    >
                      <span className="muted">
                        [{QTYPE_LABEL[q.qtype] || q.qtype} · 难度 {q.difficulty}]
                      </span>{" "}
                      {q.stem_md.slice(0, 80)}
                      {q.stem_md.length > 80 ? "…" : ""}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            {!selected ? (
              <p className="muted">选择一道题查看详情与讲题。</p>
            ) : (
              <div className="stack" style={{ gap: 16 }}>
                <div>
                  <h3>题目</h3>
                  <p style={{ whiteSpace: "pre-wrap" }}>{selected.stem_md}</p>
                  {selected.options.length > 0 ? (
                    <ol type="A">
                      {selected.options.map((opt, i) => (
                        <li key={i}>{opt}</li>
                      ))}
                    </ol>
                  ) : null}
                  <p className="muted">
                    知识点：
                    {selected.knowledge_point_ids.map(pointName).join("、") || "无"}
                  </p>
                </div>

                <form className="stack" style={{ gap: 10 }} onSubmit={onExplain}>
                  <button className="btn" type="submit" disabled={busy}>
                    智能讲题
                  </button>
                </form>

                {practice ? (
                  <form className="stack" style={{ gap: 10 }} onSubmit={onSubmitAnswer}>
                    <label>
                      练习作答
                      <input
                        value={answerDraft}
                        onChange={(e) => setAnswerDraft(e.target.value)}
                        placeholder="填写答案，如 4 或 B 或 对"
                      />
                    </label>
                    <button className="btn ghost" type="submit" disabled={busy}>
                      提交作答
                    </button>
                    {gradeMsg ? <p>{gradeMsg}</p> : null}
                  </form>
                ) : null}

                {explain ? (
                  <div>
                    <h3>讲解</h3>
                    <p style={{ whiteSpace: "pre-wrap" }}>{explain.answer}</p>
                    {explain.citations.length > 0 ? (
                      <div>
                        <h4>引用</h4>
                        <ul className="list-plain">
                          {explain.citations.map((c, i) => (
                            <li key={i} className="muted">
                              [{c.source}] {c.snippet}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {similar.length > 0 ? (
                  <div>
                    <h4>相似题</h4>
                    <ul className="list-plain">
                      {similar.map((q) => (
                        <li key={q.id}>
                          <button type="button" className="link-btn" onClick={() => onSelect(q)}>
                            {q.stem_md.slice(0, 60)}
                            {q.stem_md.length > 60 ? "…" : ""}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
