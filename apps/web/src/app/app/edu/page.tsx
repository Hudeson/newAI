"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  type EduExplain,
  type EduPack,
  type EduPoint,
  type EduPractice,
  type EduQuestion,
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

  const pointName = useMemo(() => {
    const map = new Map(points.map((p) => [p.id, p.name]));
    return (id: string) => map.get(id) || id.slice(0, 8);
  }, [points]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const [p, pt, qs] = await Promise.all([
      api.eduPacks(token),
      api.eduPoints(token),
      api.eduQuestions(token, {
        knowledge_point_id: pointFilter || undefined,
        limit: 50,
      }),
    ]);
    setPacks(p);
    setPoints(pt);
    setQuestions(qs);
  }, [token, pointFilter]);

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
