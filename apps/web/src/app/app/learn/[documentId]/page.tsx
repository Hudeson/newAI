"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, type KbDocument, type LearningReport } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const REPORT_STATUS: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
};

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
        setError(err instanceof ApiError ? err.message : "加载学习报告失败"),
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
      setError(err instanceof ApiError ? err.message : "重新学习失败");
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
      setError(err instanceof ApiError ? err.message : "发布失败");
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
      setError(err instanceof ApiError ? err.message : "敏感级更新失败");
    }
  }

  const isAdmin = me?.role === "admin" || me?.role === "owner";

  return (
    <div className="stack">
      <div className="row">
        <Link href="/app" className="muted">
          ← 返回文库
        </Link>
      </div>
      <section className="panel">
        <div className="page-kicker">学习</div>
        <h1>{doc?.title || "学习报告"}</h1>
        <p className="muted">
          状态：{REPORT_STATUS[report?.status || ""] || report?.status || "—"} · 模型：
          {report?.provider || "—"} · 敏感级：{doc?.sensitivity || "L2"}
        </p>
        <div className="row">
          <button className="btn" type="button" disabled={busy} onClick={relearn}>
            {busy ? "处理中…" : "重新学习"}
          </button>
          {report?.status === "draft" ? (
            <button className="btn accent" type="button" disabled={busy} onClick={() => publish("published")}>
              审批并发布
            </button>
          ) : null}
          {report?.status === "published" ? (
            <button className="btn" type="button" disabled={busy} onClick={() => publish("draft")}>
              退回草稿
            </button>
          ) : null}
        </div>
        {isAdmin ? (
          <label className="field" style={{ marginTop: 12, maxWidth: 220 }}>
            敏感级
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
            <h2>摘要</h2>
            <p>{report.summary || "暂无摘要。"}</p>
            <h2>要点</h2>
            <ul>
              {report.key_points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </section>
          <section className="panel stack">
            <h2>大纲</h2>
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
