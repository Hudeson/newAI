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

  ask(token: string, question: string, limit = 5) {
    return apiFetch<AskResponse>("/v1/ask", {
      method: "POST",
      token,
      body: JSON.stringify({ question, limit }),
    });
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
