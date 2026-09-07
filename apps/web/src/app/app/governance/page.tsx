"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  type AgentRun,
  type Connector,
  type Quota,
  type UsageMeter,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function GovernancePage() {
  const { token, me, workspaceId } = useAuth();
  const [meters, setMeters] = useState<UsageMeter[]>([]);
  const [quotas, setQuotas] = useState<Quota[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [goal, setGoal] = useState("Summarize ACL and quota policies");
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [connectorName, setConnectorName] = useState("Inbox S3");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const refresh = useCallback(async () => {
    if (!token) return;
    const [summary, conns] = await Promise.all([
      api.usageSummary(token),
      api.connectors(token, workspaceId || undefined),
    ]);
    setMeters(summary);
    setConnectors(conns);
    if (me?.role === "admin" || me?.role === "owner") {
      setQuotas(await api.quotas(token));
    }
  }, [token, workspaceId, me?.role]);

  useEffect(() => {
    refresh().catch((err) =>
      setError(err instanceof ApiError ? err.message : "Failed to load governance"),
    );
  }, [refresh]);

  async function saveQuotas() {
    if (!token) return;
    setBusy("quotas");
    setError("");
    try {
      const next = await api.updateQuotas(
        token,
        quotas.map((q) => ({ meter: q.meter, limit: q.limit, window: q.window })),
      );
      setQuotas(next);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Quota update failed");
    } finally {
      setBusy("");
    }
  }

  async function runAgent(dryRun: boolean) {
    if (!token || !workspaceId) return;
    setBusy(dryRun ? "dry" : "agent");
    setError("");
    try {
      const run = await api.agentRun(token, {
        workspace_id: workspaceId,
        goal,
        dry_run: dryRun,
        tool_allowlist: ["search_knowledge", "get_learning", "review_summarize"],
      });
      setAgentRun(run);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Agent run failed");
    } finally {
      setBusy("");
    }
  }

  async function createAndSync() {
    if (!token || !workspaceId) return;
    setBusy("connector");
    setError("");
    try {
      const created = await api.createConnector(token, {
        workspace_id: workspaceId,
        type: "s3",
        name: connectorName,
        config: { bucket: "kb-documents", prefix: "inbox/" },
      });
      await api.syncConnector(token, created.id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Connector sync failed");
    } finally {
      setBusy("");
    }
  }

  const isAdmin = me?.role === "admin" || me?.role === "owner";

  return (
    <div className="stack" style={{ gap: 22 }}>
      <section className="panel stack">
        <h1>Governance</h1>
        <p className="muted">
          Quotas, usage meters, agent tool runs, and the S3 connector stub (E7).
        </p>
        {error ? <div className="error">{error}</div> : null}
      </section>

      <section className="panel stack">
        <h2>Usage & quotas</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Meter</th>
              <th>Used</th>
              <th>Limit</th>
              <th>Remaining</th>
              <th>Window</th>
            </tr>
          </thead>
          <tbody>
            {meters.map((m) => (
              <tr key={m.meter}>
                <td>{m.meter}</td>
                <td>{m.used}</td>
                <td>{m.limit}</td>
                <td>{m.remaining}</td>
                <td>{m.window}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {isAdmin ? (
          <div className="stack">
            <p className="muted">Admin: edit daily/lifetime limits.</p>
            {quotas.map((q, idx) => (
              <label key={q.meter} className="field">
                {q.meter} ({q.window})
                <input
                  className="input"
                  type="number"
                  value={q.limit}
                  onChange={(e) => {
                    const next = [...quotas];
                    next[idx] = { ...q, limit: Number(e.target.value) };
                    setQuotas(next);
                  }}
                />
              </label>
            ))}
            <button className="btn accent" disabled={busy === "quotas"} onClick={saveQuotas} type="button">
              Save quotas
            </button>
          </div>
        ) : null}
      </section>

      <section className="panel stack">
        <h2>Agent tools</h2>
        <p className="muted">Whitelist-only tools with optional dry-run (no side effects).</p>
        <label className="field">
          Goal
          <textarea value={goal} onChange={(e) => setGoal(e.target.value)} />
        </label>
        <div className="row">
          <button className="btn" disabled={!!busy} onClick={() => runAgent(true)} type="button">
            Dry-run
          </button>
          <button className="btn accent" disabled={!!busy} onClick={() => runAgent(false)} type="button">
            Run agent
          </button>
        </div>
        {agentRun ? (
          <div className="stack">
            <div className="badge">{agentRun.status}{agentRun.dry_run ? " · dry-run" : ""}</div>
            <p>{agentRun.answer}</p>
            <table className="table">
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {agentRun.tool_calls.map((c) => (
                  <tr key={c.id}>
                    <td>{c.tool_name}</td>
                    <td>{c.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="panel stack">
        <h2>Connectors</h2>
        <p className="muted">S3 stub imports a sample object into the workspace library.</p>
        {isAdmin ? (
          <div className="row">
            <input
              className="input"
              value={connectorName}
              onChange={(e) => setConnectorName(e.target.value)}
              placeholder="Connector name"
            />
            <button className="btn accent" disabled={busy === "connector"} onClick={createAndSync} type="button">
              Create & sync S3
            </button>
          </div>
        ) : (
          <p className="muted">Admin role required to manage connectors.</p>
        )}
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {connectors.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.type}</td>
                <td>{c.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
