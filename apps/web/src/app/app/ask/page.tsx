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
      setError(err instanceof ApiError ? err.message : "Ask failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="split">
      <section className="panel stack">
        <h1>Ask</h1>
        <p className="muted">Answers stay inside your tenant ACL. Citations open on the right.</p>
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
                  {t.result.citations.length} citation(s) — click to inspect
                </div>
              </button>
            </div>
          ))}
        </div>
        <form className="stack" onSubmit={onAsk}>
          <label className="field">
            Question
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What did we conclude about …?"
              required
            />
          </label>
          <label className="row" style={{ gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={graphAugment}
              onChange={(e) => setGraphAugment(e.target.checked)}
            />
            <span>Graph augment (include entity neighborhood in context)</span>
          </label>
          {error ? <div className="error">{error}</div> : null}
          <button className="btn accent" type="submit" disabled={busy}>
            {busy ? "Thinking…" : "Ask with citations"}
          </button>
        </form>
      </section>

      <aside className="panel drawer">
        <h2>Citations</h2>
        {!active || active.citations.length === 0 ? (
          <p className="muted">No citations selected.</p>
        ) : (
          active.citations.map((c) => (
            <div className="citation" key={c.chunk_id}>
              <div className="row">
                <span className="badge ok">#{c.ordinal}</span>
                <span className="muted">score {c.score.toFixed(3)}</span>
              </div>
              <p>{c.snippet}</p>
              <small className="muted">doc {c.document_id.slice(0, 8)}…</small>
            </div>
          ))
        )}
      </aside>
    </div>
  );
}
