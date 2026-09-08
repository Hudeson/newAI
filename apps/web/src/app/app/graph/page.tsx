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

const STATUS_LABEL: Record<string, string> = {
  published: "已发布",
  draft: "草稿",
  indexed: "已入库",
  ready: "就绪",
};

const JOB_STATUS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已成功",
  failed: "失败",
  cancelled: "已取消",
};

const TYPE_LABEL: Record<string, string> = {
  person: "人物",
  organization: "组织",
  product: "产品",
  concept: "概念",
  location: "地点",
  event: "事件",
  document_ref: "文档",
  other: "其他",
};

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
      setError(err instanceof ApiError ? err.message : "加载图谱失败"),
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
      setError(err instanceof ApiError ? err.message : "抽取失败");
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
      setError(err instanceof ApiError ? err.message : "加载实体失败");
    }
  }

  async function onSearch(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    try {
      setEntities(await api.graphEntities(token, query.trim() || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "搜索失败");
    }
  }

  return (
    <div className="split">
      <section className="panel stack">
        <div>
          <div className="page-kicker">图谱</div>
          <h1>知识图谱</h1>
          <p className="muted">
            从已入库文档抽取实体与关系。可见性遵循文档 ACL。
          </p>
        </div>
        {stats ? (
          <div className="stat-row">
            <span className="badge ok">{stats.entities} 个实体</span>
            <span className="badge ok">{stats.relations} 条关系</span>
            <span className="badge ok">{stats.documents_covered} 篇文档</span>
          </div>
        ) : null}

        <form className="stack" onSubmit={onExtract}>
          <label className="field">
            文档
            <select
              className="select"
              value={documentId}
              onChange={(ev) => setDocumentId(ev.target.value)}
            >
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.title || d.id.slice(0, 8)}（{STATUS_LABEL[d.status] || d.status}）
                </option>
              ))}
            </select>
          </label>
          <button className="btn accent" type="submit" disabled={busy || !documentId}>
            {busy ? "抽取中…" : "抽取图谱"}
          </button>
          {job ? (
            <p className="muted">
              任务{JOB_STATUS[job.status] || job.status}：{job.entities_created} 个实体 /{" "}
              {job.relations_created} 条关系（{job.chunks_done}/{job.chunks_total} 分块）
            </p>
          ) : null}
        </form>

        <form className="row" onSubmit={onSearch} style={{ gap: 8 }}>
          <input
            className="select"
            style={{ flex: 1 }}
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            placeholder="搜索实体"
          />
          <button className="btn" type="submit">
            搜索
          </button>
        </form>

        {error ? <div className="error">{error}</div> : null}

        <div className="stack">
          {entities.length === 0 ? (
            <p className="muted">暂无可见实体。请先对文档执行抽取。</p>
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
                  {TYPE_LABEL[ent.type] || ent.type} · {ent.mention_count} 次提及
                </div>
              </button>
            ))
          )}
        </div>
      </section>

      <aside className="panel drawer stack">
        <div>
          <div className="page-kicker">详情</div>
          <h2>实体</h2>
        </div>
        {!selected ? (
          <p className="muted">选择实体以查看别名、证据与邻接关系。</p>
        ) : (
          <>
            <div>
              <h3 style={{ margin: 0 }}>{selected.name}</h3>
              <p className="muted">
                {TYPE_LABEL[selected.type] || selected.type}
                {selected.aliases.length ? ` · 别名：${selected.aliases.join("、")}` : ""}
              </p>
            </div>
            <div>
              <h3>提及</h3>
              {selected.mentions.length === 0 ? (
                <p className="muted">暂无提及</p>
              ) : (
                selected.mentions.map((m) => (
                  <div className="citation" key={m.id}>
                    <p>{m.mention_text}</p>
                    <small className="muted">文档 {m.document_id.slice(0, 8)}…</small>
                  </div>
                ))
              )}
            </div>
            <div>
              <h3>邻接关系</h3>
              {!neighbors || neighbors.edges.length === 0 ? (
                <p className="muted">当前 ACL 范围内无关系。</p>
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
