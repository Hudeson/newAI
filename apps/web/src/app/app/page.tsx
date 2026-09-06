"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type KbDocument } from "@/lib/api";
import { useAuth } from "@/lib/auth";

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
      setError(err instanceof ApiError ? err.message : "Failed to load documents"),
    );
  }, [load]);

  async function onUpload(file: File | null) {
    if (!file || !token || !workspaceId) return;
    setBusy(true);
    setError("");
    try {
      const job = await api.uploadFile(token, workspaceId, file);
      setLastJob(`${job.filename} → ${job.status}`);
      await refresh();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="panel hero">
        <h1>Library</h1>
        <p className="muted">
          Drop markdown/text into the active workspace. Ingest + learn run automatically on
          personal profile.
        </p>
        <div className="row" style={{ marginTop: 16 }}>
          <label className="btn accent">
            {busy ? "Uploading…" : "Upload document"}
            <input
              type="file"
              accept=".md,.txt,text/plain,text/markdown"
              hidden
              disabled={busy || !workspaceId}
              onChange={(e) => onUpload(e.target.files?.[0] || null)}
            />
          </label>
          {lastJob ? <span className="badge ok">{lastJob}</span> : null}
        </div>
        {error ? <div className="error" style={{ marginTop: 12 }}>{error}</div> : null}
      </section>

      <section className="panel">
        <h2>Documents</h2>
        {docs.length === 0 ? (
          <p className="muted">No documents yet in this workspace.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Chunks</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td>
                    <span className={`badge ${d.status === "published" ? "ok" : "warn"}`}>
                      {d.status}
                    </span>
                  </td>
                  <td>{d.chunk_count}</td>
                  <td>
                    <Link href={`/app/learn/${d.id}`}>Learning →</Link>
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
