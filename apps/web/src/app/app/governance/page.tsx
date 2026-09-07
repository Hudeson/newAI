"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  getApiBase,
  type AgentRun,
  type Connector,
  type LlmCredential,
  type LlmEnvStatus,
  type ModelPolicy,
  type PendingApproval,
  type Quota,
  type UsageMeter,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function GovernancePage() {
  const { token, me, workspaceId, workspaces, refresh: refreshAuth } = useAuth();
  const [meters, setMeters] = useState<UsageMeter[]>([]);
  const [quotas, setQuotas] = useState<Quota[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [policies, setPolicies] = useState<ModelPolicy[]>([]);
  const [pending, setPending] = useState<PendingApproval[]>([]);
  const [llmEnv, setLlmEnv] = useState<LlmEnvStatus | null>(null);
  const [creds, setCreds] = useState<LlmCredential[]>([]);
  const [keyDraft, setKeyDraft] = useState("");
  const [baseUrlDraft, setBaseUrlDraft] = useState("https://api.deepseek.com/v1");
  const [modelDraft, setModelDraft] = useState("deepseek-chat");
  const [providerDraft, setProviderDraft] = useState("openai_compatible");
  const [pingMsg, setPingMsg] = useState("");
  const [goal, setGoal] = useState("Summarize ACL and quota policies");
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [connectorName, setConnectorName] = useState("Inbox S3");
  const [exportMsg, setExportMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const currentWs = workspaces.find((w) => w.id === workspaceId);

  const refresh = useCallback(async () => {
    if (!token) return;
    const [summary, conns] = await Promise.all([
      api.usageSummary(token),
      api.connectors(token, workspaceId || undefined),
    ]);
    setMeters(summary);
    setConnectors(conns);
    if (me?.role === "admin" || me?.role === "owner") {
      const [q, p, a, c, e] = await Promise.all([
        api.quotas(token),
        api.modelPolicy(token),
        api.pendingApprovals(token),
        api.llmCredentials(token),
        api.llmEnv(token),
      ]);
      setQuotas(q);
      setPolicies(p);
      setPending(a);
      setCreds(c);
      setLlmEnv(e);
      const existing = c.find((x) => x.provider === "openai_compatible");
      if (existing?.base_url) setBaseUrlDraft(existing.base_url);
      if (existing?.default_model) setModelDraft(existing.default_model);
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

  async function togglePublishMode() {
    if (!token || !workspaceId || !currentWs) return;
    setBusy("publish");
    setError("");
    try {
      const next = currentWs.publish_mode === "approval" ? "auto" : "approval";
      await api.updateWorkspace(token, workspaceId, next);
      await refreshAuth();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Publish mode update failed");
    } finally {
      setBusy("");
    }
  }

  async function savePolicies() {
    if (!token) return;
    setBusy("policy");
    setError("");
    try {
      setPolicies(await api.updateModelPolicy(token, policies));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Model policy update failed");
    } finally {
      setBusy("");
    }
  }

  async function exportAudit() {
    if (!token) return;
    setBusy("export");
    setError("");
    try {
      const exp = await api.createAuditExport(token);
      setExportMsg(`Export ${exp.id}: ${exp.event_count} events`);
      const res = await fetch(`${getApiBase()}${exp.download_url}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-${exp.id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Audit export failed");
    } finally {
      setBusy("");
    }
  }

  async function approve(documentId: string) {
    if (!token) return;
    setBusy("approve");
    try {
      await api.publishLearning(token, documentId, "published");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Approve failed");
    } finally {
      setBusy("");
    }
  }

  async function saveCredential() {
    if (!token) return;
    setBusy("llm");
    setError("");
    try {
      await api.saveLlmCredential(token, {
        provider: providerDraft,
        api_key: keyDraft || undefined,
        base_url: baseUrlDraft,
        default_model: modelDraft,
      });
      setKeyDraft("");
      await refresh();
      setPingMsg("Credential saved (key never re-displayed).");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save credential failed");
    } finally {
      setBusy("");
    }
  }

  async function pingLlm() {
    if (!token) return;
    setBusy("ping");
    setError("");
    try {
      const res = await api.llmPing(token, {
        provider: providerDraft,
        model: modelDraft,
        base_url: baseUrlDraft,
        api_key: keyDraft || undefined,
      });
      setPingMsg(`Ping ok · ${res.provider}/${res.model} · ${res.preview}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Ping failed");
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
          Model keys, routing, approvals, quotas, agent tools, and connectors.
        </p>
        {error ? <div className="error">{error}</div> : null}
      </section>

      {isAdmin ? (
        <section className="panel stack">
          <h2>模型与密钥（API Key）</h2>
          <p className="muted">
            配置 OpenAI 兼容端点（DeepSeek / OpenAI 等）或 Ollama。也可在服务器 `.env` 写
            `LLM_API_KEY`。环境：
            {llmEnv
              ? ` provider=${llmEnv.llm_provider}, env_key=${llmEnv.llm_key_configured ? "yes" : "no"}`
              : " —"}
          </p>
          <label className="field">
            Provider
            <select
              className="select"
              value={providerDraft}
              onChange={(e) => setProviderDraft(e.target.value)}
            >
              <option value="openai_compatible">openai_compatible</option>
              <option value="ollama">ollama</option>
              <option value="local">local</option>
            </select>
          </label>
          <label className="field">
            Base URL
            <input
              className="input"
              value={baseUrlDraft}
              onChange={(e) => setBaseUrlDraft(e.target.value)}
              placeholder="https://api.deepseek.com/v1"
            />
          </label>
          <label className="field">
            Default model
            <input
              className="input"
              value={modelDraft}
              onChange={(e) => setModelDraft(e.target.value)}
            />
          </label>
          <label className="field">
            API Key（只写不回显）
            <input
              className="input"
              type="password"
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.target.value)}
              placeholder={creds.find((c) => c.provider === providerDraft)?.key_prefix || "sk-..."}
            />
          </label>
          <div className="row">
            <button className="btn accent" type="button" disabled={busy === "llm"} onClick={saveCredential}>
              Save credential
            </button>
            <button className="btn" type="button" disabled={busy === "ping"} onClick={pingLlm}>
              Test connection
            </button>
          </div>
          {pingMsg ? <p className="muted">{pingMsg}</p> : null}
          {creds.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Key</th>
                </tr>
              </thead>
              <tbody>
                {creds.map((c) => (
                  <tr key={c.provider}>
                    <td>{c.provider}</td>
                    <td>{c.default_model || "—"}</td>
                    <td>{c.key_configured ? c.key_prefix : "not set"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>Workspace publish mode</h2>
          <p className="muted">
            Current: <span className="badge">{currentWs?.publish_mode || "—"}</span>
          </p>
          <button className="btn accent" disabled={busy === "publish"} onClick={togglePublishMode} type="button">
            Switch to {currentWs?.publish_mode === "approval" ? "auto" : "approval"}
          </button>
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>Pending approvals</h2>
          {pending.length === 0 ? <p className="muted">No draft reports in approval workspaces.</p> : null}
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Summary</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p) => (
                <tr key={p.report_id}>
                  <td>{p.title}</td>
                  <td>{p.summary}</td>
                  <td>
                    <button className="btn accent" type="button" onClick={() => approve(p.document_id)}>
                      Approve
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>Model routing by sensitivity</h2>
          {policies.map((p, idx) => (
            <div key={p.sensitivity} className="row">
              <span className="badge">{p.sensitivity}</span>
              <input
                className="input"
                value={p.provider}
                onChange={(e) => {
                  const next = [...policies];
                  next[idx] = { ...p, provider: e.target.value };
                  setPolicies(next);
                }}
              />
              <input
                className="input"
                value={p.model}
                onChange={(e) => {
                  const next = [...policies];
                  next[idx] = { ...p, model: e.target.value };
                  setPolicies(next);
                }}
              />
            </div>
          ))}
          <button className="btn accent" disabled={busy === "policy"} onClick={savePolicies} type="button">
            Save model policy
          </button>
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>Audit export</h2>
          <button className="btn accent" disabled={busy === "export"} onClick={exportAudit} type="button">
            Export audit JSON
          </button>
          {exportMsg ? <p className="muted">{exportMsg}</p> : null}
        </section>
      ) : null}

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
          </div>
        ) : null}
      </section>

      <section className="panel stack">
        <h2>Connectors</h2>
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
        ) : null}
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
