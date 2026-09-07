"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type GraphEntity,
  type GraphEntityDetail,
  type GraphJob,
  type GraphNeighbors,
  type GraphStats,
  type KbDocument,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function GraphPage() {
  const { token, workspaceId } = useAuth();
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<GraphEntityDetail | null>(null);
  const [neighbors, setNeighbors] = useState<GraphNeighbors | null>(null);
  const [job, setJob] = useState<GraphJob | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!token || !workspaceId) return;
    const [s, d, e] = await Promise.all([
      api.graphStats(token),
      api.documents(token, workspaceId),
      api.graphEntities(token, query.trim() || undefined),
    ]);
    setStats(s);
    setDocs(d);
    setEntities(e);
    if (!documentId && d[0]) setDocumentId(d[0].id);
  }, [token, workspaceId, query, documentId]);

  useEffect(() => {
    refresh().catch((err) =>
      setError(err instanceof ApiError ? err.message : "Failed to load graph"),
    );
  }, [refresh]);

  async function onExtract(e: FormEvent) {
    e.preventDefault();
    if (!token || !documentId) return;
    setBusy(true);
    setError("");
    try {
      const j = await api.graphExtract(token, documentId, true);
      setJob(j);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Extract failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSelect(id: string) {
    if (!token) return;
    setError("");
    try {
      const [detail, nb] = await Promise.all([
        api.graphEntity(token, id),
        api.graphNeighbors(token, id),
      ]);
      setSelected(detail);
      setNeighbors(nb);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load entity");
    }
  }

  async function onSearch(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    try {
      setEntities(await api.graphEntities(token, query.trim() || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed");
    }
  }

  return (
    <div className="split">
      <section className="panel stack">
        <h1>Graph</h1>
        <p className="muted">
          Extract entities and relations from indexed documents. Visibility follows document ACL.
        </p>
        {stats ? (
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            <span className="badge ok">{stats.entities} entities</span>
            <span className="badge ok">{stats.relations} relations</span>
            <span className="badge ok">{stats.documents_covered} docs</span>
          </div>
        ) : null}

        <form className="stack" onSubmit={onExtract}>
          <label className="field">
            Document
            <select
              className="select"
              value={documentId}
              onChange={(ev) => setDocumentId(ev.target.value)}
            >
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title || d.id.slice(0, 8)} ({d.status})
                </option>
              ))}
            </select>
          </label>
          <button className="btn accent" type="submit" disabled={busy || !documentId}>
            {busy ? "Extracting…" : "Extract graph"}
          </button>
          {job ? (
            <p className="muted">
              Job {job.status}: {job.entities_created} entities / {job.relations_created} relations
              ({job.chunks_done}/{job.chunks_total} chunks)
            </p>
          ) : null}
        </form>

        <form className="row" onSubmit={onSearch} style={{ gap: 8 }}>
          <input
            className="select"
            style={{ flex: 1 }}
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            placeholder="Search entities"
          />
          <button className="btn" type="submit">
            Search
          </button>
        </form>

        {error ? <div className="error">{error}</div> : null}

        <div className="stack">
          {entities.length === 0 ? (
            <p className="muted">No visible entities yet. Extract from a document first.</p>
          ) : (
            entities.map((ent) => (
              <button
                key={ent.id}
                type="button"
                className="bubble"
                style={{ textAlign: "left" }}
                onClick={() => onSelect(ent.id)}
              >
                <strong>{ent.name}</strong>
                <div className="muted">
                  {ent.type} · {ent.mention_count} mention(s)
                </div>
              </button>
            ))
          )}
        </div>
      </section>

      <aside className="panel drawer stack">
        <h2>Entity</h2>
        {!selected ? (
          <p className="muted">Select an entity to inspect aliases, evidence, and neighbors.</p>
        ) : (
          <>
            <div>
              <h3 style={{ margin: 0 }}>{selected.name}</h3>
              <p className="muted">
                {selected.type}
                {selected.aliases.length ? ` · aliases: ${selected.aliases.join(", ")}` : ""}
              </p>
            </div>
            <div>
              <h3>Mentions</h3>
              {selected.mentions.length === 0 ? (
                <p className="muted">No mentions</p>
              ) : (
                selected.mentions.map((m) => (
                  <div className="citation" key={m.id}>
                    <p>{m.mention_text}</p>
                    <small className="muted">doc {m.document_id.slice(0, 8)}…</small>
                  </div>
                ))
              )}
            </div>
            <div>
              <h3>Neighbors</h3>
              {!neighbors || neighbors.edges.length === 0 ? (
                <p className="muted">No relations in ACL scope.</p>
              ) : (
                neighbors.edges.map((e) => {
                  const nodes = [neighbors.center, ...neighbors.nodes];
                  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
                  const s = byId[e.subject_entity_id]?.name || e.subject_entity_id.slice(0, 6);
                  const o = byId[e.object_entity_id]?.name || e.object_entity_id.slice(0, 6);
                  return (
                    <div className="citation" key={e.id}>
                      <p>
                        {s} —<em>{e.predicate}</em>→ {o}
                      </p>
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
