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
  const [goal, setGoal] = useState("总结 ACL 与配额策略");
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [connectorName, setConnectorName] = useState("收件箱 S3");
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
      setError(err instanceof ApiError ? err.message : "加载治理页失败"),
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
      setError(err instanceof ApiError ? err.message : "配额更新失败");
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
      setError(err instanceof ApiError ? err.message : "Agent 运行失败");
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
      setError(err instanceof ApiError ? err.message : "连接器同步失败");
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
      setError(err instanceof ApiError ? err.message : "发布模式更新失败");
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
      setError(err instanceof ApiError ? err.message : "模型策略更新失败");
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
      setExportMsg(`导出 ${exp.id}：${exp.event_count} 条事件`);
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
      setError(err instanceof ApiError ? err.message : "审计导出失败");
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
      setError(err instanceof ApiError ? err.message : "审批失败");
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
      setPingMsg("凭证已保存（密钥不会回显）。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存凭证失败");
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
      setPingMsg(`连通成功 · ${res.provider}/${res.model} · ${res.preview}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "连通测试失败");
    } finally {
      setBusy("");
    }
  }

  const isAdmin = me?.role === "admin" || me?.role === "owner";
  const publishModeLabel =
    currentWs?.publish_mode === "approval"
      ? "审批发布"
      : currentWs?.publish_mode === "auto"
        ? "自动发布"
        : currentWs?.publish_mode || "—";

  return (
    <div className="stack" style={{ gap: 22 }}>
      <section className="panel stack">
        <h1>治理</h1>
        <p className="muted">模型密钥、路由策略、审批、配额、Agent 工具与连接器。</p>
        {error ? <div className="error">{error}</div> : null}
      </section>

      {isAdmin ? (
        <section className="panel stack">
          <h2>模型与密钥（API Key）</h2>
          <p className="muted">
            配置 OpenAI 兼容端点（DeepSeek / OpenAI 等）或 Ollama。也可在服务器 `.env` 写入
            `LLM_API_KEY`。当前环境：
            {llmEnv
              ? ` provider=${llmEnv.llm_provider}，环境密钥=${llmEnv.llm_key_configured ? "已配置" : "未配置"}`
              : " —"}
          </p>
          <label className="field">
            提供商
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
            默认模型
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
              保存凭证
            </button>
            <button className="btn" type="button" disabled={busy === "ping"} onClick={pingLlm}>
              测试连接
            </button>
          </div>
          {pingMsg ? <p className="muted">{pingMsg}</p> : null}
          {creds.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>提供商</th>
                  <th>模型</th>
                  <th>密钥</th>
                </tr>
              </thead>
              <tbody>
                {creds.map((c) => (
                  <tr key={c.provider}>
                    <td>{c.provider}</td>
                    <td>{c.default_model || "—"}</td>
                    <td>{c.key_configured ? c.key_prefix : "未设置"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>工作区发布模式</h2>
          <p className="muted">
            当前：<span className="badge">{publishModeLabel}</span>
          </p>
          <button className="btn accent" disabled={busy === "publish"} onClick={togglePublishMode} type="button">
            切换为 {currentWs?.publish_mode === "approval" ? "自动发布" : "审批发布"}
          </button>
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>待审批</h2>
          {pending.length === 0 ? <p className="muted">审批模式下暂无草稿报告。</p> : null}
          <table className="table">
            <thead>
              <tr>
                <th>标题</th>
                <th>摘要</th>
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
                      通过
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
          <h2>按敏感级路由模型</h2>
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
            保存模型策略
          </button>
        </section>
      ) : null}

      {isAdmin ? (
        <section className="panel stack">
          <h2>审计导出</h2>
          <button className="btn accent" disabled={busy === "export"} onClick={exportAudit} type="button">
            导出审计 JSON
          </button>
          {exportMsg ? <p className="muted">{exportMsg}</p> : null}
        </section>
      ) : null}

      <section className="panel stack">
        <h2>用量与配额</h2>
        <table className="table">
          <thead>
            <tr>
              <th>指标</th>
              <th>已用</th>
              <th>上限</th>
              <th>剩余</th>
              <th>窗口</th>
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
                {q.meter}（{q.window}）
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
              保存配额
            </button>
          </div>
        ) : null}
      </section>

      <section className="panel stack">
        <h2>Agent 工具</h2>
        <label className="field">
          目标
          <textarea value={goal} onChange={(e) => setGoal(e.target.value)} />
        </label>
        <div className="row">
          <button className="btn" disabled={!!busy} onClick={() => runAgent(true)} type="button">
            干跑
          </button>
          <button className="btn accent" disabled={!!busy} onClick={() => runAgent(false)} type="button">
            运行 Agent
          </button>
        </div>
        {agentRun ? (
          <div className="stack">
            <div className="badge">
              {agentRun.status}
              {agentRun.dry_run ? " · 干跑" : ""}
            </div>
            <p>{agentRun.answer}</p>
          </div>
        ) : null}
      </section>

      <section className="panel stack">
        <h2>连接器</h2>
        {isAdmin ? (
          <div className="row">
            <input
              className="input"
              value={connectorName}
              onChange={(e) => setConnectorName(e.target.value)}
              placeholder="连接器名称"
            />
            <button className="btn accent" disabled={busy === "connector"} onClick={createAndSync} type="button">
              创建并同步 S3
            </button>
          </div>
        ) : null}
        <table className="table">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>状态</th>
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
