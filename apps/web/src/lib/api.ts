export type TokenResponse = {
  access_token: string;
  token_type: string;
  tenant_id: string;
  user_id: string;
};

export type Me = {
  user_id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  role: string;
};

export type Workspace = {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  publish_mode: string;
  status: string;
};

export type KbDocument = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  title: string;
  status: string;
  sensitivity?: string;
  created_by: string;
  chunk_count: number;
};

export type UploadJob = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  document_id: string;
  version_id: string;
  filename: string;
  status: string;
  object_key: string;
  size_bytes: number;
  error_message: string;
};

export type LearningReport = {
  id: string;
  document_id: string;
  version_id: string;
  workspace_id: string;
  status: string;
  summary: string;
  outline: string[];
  key_points: string[];
  provider: string;
};

export type Citation = {
  chunk_id: string;
  document_id: string;
  version_id: string;
  workspace_id: string;
  ordinal: number;
  score: number;
  snippet: string;
};

export type AskResponse = {
  answer: string;
  citations: Citation[];
};

export type UserOut = {
  user_id: string;
  email: string;
  display_name: string;
  role: string;
  status: string;
};

export type UsageMeter = {
  meter: string;
  limit: number;
  used: number;
  remaining: number;
  window: string;
};

export type Quota = {
  meter: string;
  limit: number;
  window: string;
};

export type AgentToolCall = {
  id: string;
  tool_name: string;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
};

export type AgentRun = {
  id: string;
  workspace_id: string;
  goal: string;
  status: string;
  dry_run: boolean;
  allowlist: string[];
  answer: string;
  tool_calls: AgentToolCall[];
};

export type Connector = {
  id: string;
  workspace_id: string;
  type: string;
  name: string;
  status: string;
  config: Record<string, unknown>;
  permission_mode: string;
};

export type ModelPolicy = {
  sensitivity: string;
  provider: string;
  model: string;
};

export type PendingApproval = {
  report_id: string;
  document_id: string;
  workspace_id: string;
  title: string;
  status: string;
  summary: string;
};

export type AuditExport = {
  id: string;
  status: string;
  event_count: number;
  object_key: string;
  download_url: string;
};

export type LlmCredential = {
  provider: string;
  base_url: string;
  default_model: string;
  key_configured: boolean;
  key_prefix: string;
};

export type LlmEnvStatus = {
  llm_provider: string;
  llm_base_url: string;
  llm_model: string;
  llm_key_configured: boolean;
  ollama_base_url: string;
  ollama_model: string;
};

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export function getApiBase() {
  return API_BASE.replace(/\/$/, "");
}

async function parseError(res: Response): Promise<never> {
  let code = "http_error";
  let message = res.statusText || "request failed";
  try {
    const body = await res.json();
    if (body?.error) {
      code = body.error.code || code;
      message = body.error.message || message;
    }
  } catch {
    // ignore
  }
  throw new ApiError(res.status, code, message);
}

export async function apiFetch<T>(
  path: string,
  opts: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const headers = new Headers(opts.headers || {});
  if (opts.token) headers.set("Authorization", `Bearer ${opts.token}`);
  if (opts.body && !(opts.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${getApiBase()}${path}`, { ...opts, headers });
  if (!res.ok) await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  register(body: {
    tenant_name: string;
    tenant_slug: string;
    email: string;
    password: string;
    display_name?: string;
  }) {
    return apiFetch<TokenResponse>("/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  login(body: { tenant_slug: string; email: string; password: string }) {
    return apiFetch<TokenResponse>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  me(token: string) {
    return apiFetch<Me>("/v1/me", { token });
  },

  workspaces(token: string) {
    return apiFetch<Workspace[]>("/v1/workspaces", { token });
  },

  users(token: string) {
    return apiFetch<UserOut[]>("/v1/users", { token });
  },

  documents(token: string, workspaceId?: string) {
    const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return apiFetch<KbDocument[]>(`/v1/documents${q}`, { token });
  },

  document(token: string, documentId: string) {
    return apiFetch<KbDocument>(`/v1/documents/${documentId}`, { token });
  },

  learning(token: string, documentId: string) {
    return apiFetch<LearningReport>(`/v1/documents/${documentId}/learning`, { token });
  },

  relearn(token: string, documentId: string) {
    return apiFetch<LearningReport>(`/v1/documents/${documentId}/learn`, {
      method: "POST",
      token,
    });
  },

  publishLearning(token: string, documentId: string, status: "draft" | "published") {
    return apiFetch<LearningReport>(`/v1/documents/${documentId}/learning/publish`, {
      method: "POST",
      token,
      body: JSON.stringify({ status }),
    });
  },

  updateWorkspace(token: string, workspaceId: string, publishMode: "auto" | "approval") {
    return apiFetch<Workspace>(`/v1/workspaces/${workspaceId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify({ publish_mode: publishMode }),
    });
  },

  pendingApprovals(token: string) {
    return apiFetch<PendingApproval[]>("/v1/admin/approvals/pending", { token });
  },

  modelPolicy(token: string) {
    return apiFetch<ModelPolicy[]>("/v1/admin/models/policy", { token });
  },

  updateModelPolicy(token: string, body: ModelPolicy[]) {
    return apiFetch<ModelPolicy[]>("/v1/admin/models/policy", {
      method: "PUT",
      token,
      body: JSON.stringify(body),
    });
  },

  setSensitivity(token: string, documentId: string, sensitivity: string) {
    return apiFetch<KbDocument>(`/v1/documents/${documentId}/sensitivity`, {
      method: "PATCH",
      token,
      body: JSON.stringify({ sensitivity }),
    });
  },

  createAuditExport(token: string) {
    return apiFetch<AuditExport>("/v1/admin/audit-exports", { method: "POST", token });
  },

  llmCredentials(token: string) {
    return apiFetch<LlmCredential[]>("/v1/admin/llm/credentials", { token });
  },

  saveLlmCredential(
    token: string,
    body: {
      provider: string;
      api_key?: string;
      base_url?: string;
      default_model?: string;
      clear_key?: boolean;
    },
  ) {
    return apiFetch<LlmCredential>("/v1/admin/llm/credentials", {
      method: "PUT",
      token,
      body: JSON.stringify(body),
    });
  },

  llmEnv(token: string) {
    return apiFetch<LlmEnvStatus>("/v1/admin/llm/env", { token });
  },

  llmPing(
    token: string,
    body: { provider: string; model?: string; base_url?: string; api_key?: string },
  ) {
    return apiFetch<{ ok: boolean; provider: string; model: string; preview: string }>(
      "/v1/admin/llm/ping",
      { method: "POST", token, body: JSON.stringify(body) },
    );
  },

  ask(token: string, question: string, limit = 5) {
    return apiFetch<AskResponse>("/v1/ask", {
      method: "POST",
      token,
      body: JSON.stringify({ question, limit }),
    });
  },

  usageSummary(token: string) {
    return apiFetch<UsageMeter[]>("/v1/usage/summary", { token });
  },

  quotas(token: string) {
    return apiFetch<Quota[]>("/v1/admin/quotas", { token });
  },

  updateQuotas(token: string, body: { meter: string; limit: number; window?: string }[]) {
    return apiFetch<Quota[]>("/v1/admin/quotas", {
      method: "PUT",
      token,
      body: JSON.stringify(body),
    });
  },

  agentRun(
    token: string,
    body: {
      workspace_id: string;
      goal: string;
      tool_allowlist?: string[];
      dry_run?: boolean;
      max_steps?: number;
    },
  ) {
    return apiFetch<AgentRun>("/v1/agent/runs", {
      method: "POST",
      token,
      body: JSON.stringify(body),
    });
  },

  connectors(token: string, workspaceId?: string) {
    const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return apiFetch<Connector[]>(`/v1/connectors${q}`, { token });
  },

  createConnector(
    token: string,
    body: { workspace_id: string; type: string; name: string; config?: Record<string, unknown> },
  ) {
    return apiFetch<Connector>("/v1/connectors", {
      method: "POST",
      token,
      body: JSON.stringify(body),
    });
  },

  syncConnector(token: string, connectorId: string) {
    return apiFetch<{ id: string; status: string; items_imported: number }>(
      `/v1/connectors/${connectorId}/sync`,
      { method: "POST", token },
    );
  },

  async uploadFile(token: string, workspaceId: string, file: File): Promise<UploadJob> {
    const presign = await apiFetch<{
      upload_job_id: string;
      document_id: string;
      version_id: string;
      upload_url: string;
    }>("/v1/uploads/presign", {
      method: "POST",
      token,
      body: JSON.stringify({
        workspace_id: workspaceId,
        filename: file.name,
        content_type: file.type || "text/plain",
        size_bytes: file.size,
      }),
    });

    const form = new FormData();
    form.append("file", file, file.name);
    const put = await fetch(`${getApiBase()}${presign.upload_url}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    if (!put.ok) await parseError(put);

    return apiFetch<UploadJob>(`/v1/upload-jobs/${presign.upload_job_id}/complete`, {
      method: "POST",
      token,
    });
  },
};
