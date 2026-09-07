"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, type KbDocument, type LearningReport } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LearnPage() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;
  const { token, me } = useAuth();
  const [doc, setDoc] = useState<KbDocument | null>(null);
  const [report, setReport] = useState<LearningReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token || !documentId) return;
    Promise.all([api.document(token, documentId), api.learning(token, documentId)])
      .then(([d, r]) => {
        setDoc(d);
        setReport(r);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Failed to load learning report"),
      );
  }, [token, documentId]);

  async function relearn() {
    if (!token || !documentId) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.relearn(token, documentId);
      setReport(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Re-learn failed");
    } finally {
      setBusy(false);
    }
  }

  async function publish(status: "draft" | "published") {
    if (!token || !documentId) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.publishLearning(token, documentId, status);
      setReport(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Publish failed");
    } finally {
      setBusy(false);
    }
  }

  async function setSensitivity(level: string) {
    if (!token || !documentId) return;
    try {
      const d = await api.setSensitivity(token, documentId, level);
      setDoc(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sensitivity update failed");
    }
  }

  const isAdmin = me?.role === "admin" || me?.role === "owner";

  return (
    <div className="stack">
      <div className="row">
        <Link href="/app" className="muted">
          ← Library
        </Link>
      </div>
      <section className="panel">
        <h1>{doc?.title || "Learning report"}</h1>
        <p className="muted">
          Status: {report?.status || "—"} · Provider: {report?.provider || "—"} · Sensitivity:{" "}
          {doc?.sensitivity || "L2"}
        </p>
        <div className="row">
          <button className="btn" type="button" disabled={busy} onClick={relearn}>
            {busy ? "Working…" : "Re-run learn"}
          </button>
          {report?.status === "draft" ? (
            <button className="btn accent" type="button" disabled={busy} onClick={() => publish("published")}>
              Approve & publish
            </button>
          ) : null}
          {report?.status === "published" ? (
            <button className="btn" type="button" disabled={busy} onClick={() => publish("draft")}>
              Revert to draft
            </button>
          ) : null}
        </div>
        {isAdmin ? (
          <label className="field" style={{ marginTop: 12, maxWidth: 220 }}>
            Sensitivity
            <select
              className="select"
              value={doc?.sensitivity || "L2"}
              onChange={(e) => setSensitivity(e.target.value)}
            >
              {["L1", "L2", "L3", "L4"].map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {error ? <div className="error">{error}</div> : null}
      </section>

      {report ? (
        <div className="split">
          <section className="panel stack">
            <h2>Summary</h2>
            <p>{report.summary || "No summary yet."}</p>
            <h2>Key points</h2>
            <ul>
              {report.key_points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </section>
          <section className="panel stack">
            <h2>Outline</h2>
            <ol>
              {report.outline.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ol>
          </section>
        </div>
      ) : null}
    </div>
  );
}
