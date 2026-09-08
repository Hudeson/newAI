"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type KbDocument } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const STATUS_LABEL: Record<string, string> = {
  published: "已发布",
  draft: "草稿",
  indexed: "已入库",
  ready: "就绪",
  processing: "处理中",
};

export default function LibraryPage() {
  const { token, workspaceId, refresh } = useAuth();
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastJob, setLastJob] = useState("");

  const load = useCallback(async () => {
    if (!token || !workspaceId) return;
    const rows = await api.documents(token, workspaceId);
    setDocs(rows);
  }, [token, workspaceId]);

  useEffect(() => {
    load().catch((err) =>
      setError(err instanceof ApiError ? err.message : "加载文档失败"),
    );
  }, [load]);

  async function onUpload(file: File | null) {
    if (!file || !token || !workspaceId) return;
    setBusy(true);
    setError("");
    try {
      const job = await api.uploadFile(token, workspaceId, file);
      const status = STATUS_LABEL[job.status] || job.status;
      setLastJob(`${job.filename} → ${status}`);
      await refresh();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      <section className="panel hero">
        <div className="page-kicker">文库</div>
        <h1>把材料放进中庭</h1>
        <p className="muted" style={{ maxWidth: 42 + "rem" }}>
          支持 Markdown / 纯文本。个人版上传后自动入库并生成学习总结。
        </p>
        <div className="row" style={{ marginTop: 18 }}>
          <label className="btn accent">
            {busy ? "上传中…" : "上传文档"}
            <input
              type="file"
              accept=".md,.txt,text/plain,text/markdown"
              hidden
              disabled={busy || !workspaceId}
              onChange={(e) => onUpload(e.target.files?.[0] || null)}
            />
          </label>
          {lastJob ? <span className="badge ok">{lastJob}</span> : null}
          <Link className="btn" href="/app/ask" style={{ background: "transparent", color: "var(--ink)", border: "1px solid var(--line-strong)" }}>
            去问答
          </Link>
        </div>
        {error ? <div className="error" style={{ marginTop: 14 }}>{error}</div> : null}
      </section>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>文档列表</h2>
          <span className="muted">{docs.length} 篇</span>
        </div>
        {docs.length === 0 ? (
          <p className="muted">当前工作区还没有文档。上传第一份材料，知识链就会开始生长。</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>标题</th>
                <th>状态</th>
                <th>分块</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td style={{ fontWeight: 600 }}>{d.title}</td>
                  <td>
                    <span className={`badge ${d.status === "published" ? "ok" : "warn"}`}>
                      {STATUS_LABEL[d.status] || d.status}
                    </span>
                  </td>
                  <td>{d.chunk_count}</td>
                  <td>
                    <Link href={`/app/learn/${d.id}`} style={{ color: "var(--accent)", fontWeight: 600 }}>
                      学习报告 →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
