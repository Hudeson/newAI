"use client";

import { FormEvent, useState } from "react";
import { api, ApiError, type AskResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Turn = {
  question: string;
  result: AskResponse;
};

export default function AskPage() {
  const { token } = useAuth();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [active, setActive] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [graphAugment, setGraphAugment] = useState(false);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!token || !question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.ask(token, question.trim(), 5, graphAugment);
      setTurns((prev) => [...prev, { question: question.trim(), result }]);
      setActive(result);
      setQuestion("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "提问失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="split">
      <section className="panel stack">
        <div>
          <div className="page-kicker">问答</div>
          <h1>带着出处追问</h1>
          <p className="muted">回答仅基于当前租户 ACL 可见内容。点击回答可查看右侧引用。</p>
        </div>
        <div className="chat">
          {turns.map((t, idx) => (
            <div key={`${t.question}-${idx}`} className="stack">
              <div className="bubble user">{t.question}</div>
              <button
                type="button"
                className="bubble"
                onClick={() => setActive(t.result)}
                style={{ textAlign: "left" }}
              >
                {t.result.answer}
                <div className="muted" style={{ marginTop: 8 }}>
                  {t.result.citations.length} 条引用 — 点击查看
                  {t.result.graph_augmented ? " · 已启用图谱增强" : ""}
                </div>
              </button>
            </div>
          ))}
        </div>
        <form className="stack" onSubmit={onAsk}>
          <label className="field">
            问题
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="关于……我们得出了什么结论？"
              required
            />
          </label>
          <label className="row" style={{ gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={graphAugment}
              onChange={(e) => setGraphAugment(e.target.checked)}
            />
            <span>图谱增强（将实体邻域一并送入上下文）</span>
          </label>
          {error ? <div className="error">{error}</div> : null}
          <button className="btn accent" type="submit" disabled={busy}>
            {busy ? "思考中…" : "带引用提问"}
          </button>
        </form>
      </section>

      <aside className="panel drawer stack">
        <div>
          <div className="page-kicker">证据</div>
          <h2>引用</h2>
        </div>
        {!active || active.citations.length === 0 ? (
          <p className="muted">尚未选择引用。</p>
        ) : (
          active.citations.map((c) => (
            <div className="citation" key={c.chunk_id}>
              <div className="row">
                <span className="badge ok">#{c.ordinal}</span>
                <span className="muted">相关度 {c.score.toFixed(3)}</span>
              </div>
              <p>{c.snippet}</p>
              <small className="muted">文档 {c.document_id.slice(0, 8)}…</small>
            </div>
          ))
        )}
      </aside>
    </div>
  );
}
