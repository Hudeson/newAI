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
  graph_augmented?: boolean;
};

export type GraphStats = {
  entities: number;
  relations: number;
  documents_covered: number;
};

export type GraphEntity = {
  id: string;
  type: string;
  name: string;
  canonical_name: string;
  mention_count: number;
  description?: string;
};

export type GraphMention = {
  id: string;
  document_id: string;
  chunk_id: string;
  mention_text: string;
  confidence: number;
};

export type GraphEntityDetail = GraphEntity & {
  aliases: string[];
  mentions: GraphMention[];
};

export type GraphRelation = {
  id: string;
  subject_entity_id: string;
  predicate: string;
  object_entity_id: string;
  confidence: number;
  evidence_document_id: string | null;
  evidence_chunk_id: string | null;
};

export type GraphNeighbors = {
  center: GraphEntity;
  nodes: GraphEntity[];
  edges: GraphRelation[];
};

export type GraphJob = {
  id: string;
  document_id: string;
  status: string;
  chunks_total: number;
  chunks_done: number;
  entities_created: number;
  relations_created: number;
  error: string;
  trigger: string;
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

export type EduPack = {
  id: string;
  name: string;
  stage: string;
  subject: string;
  grade_min: number | null;
  grade_max: number | null;
  edition: string;
  license_type: string;
  license_note: string;
  status: string;
};

export type EduPoint = {
  id: string;
  name: string;
  code: string;
  subject: string;
  stage: string;
  grade: number | null;
  pack_id: string | null;
  parent_id: string | null;
};

export type EduQuestion = {
  id: string;
  stem_md: string;
  options: string[];
  answer_md: string;
  analysis_md: string;
  qtype: string;
  difficulty: number;
  grade: number | null;
  subject: string;
  stage: string;
  pack_id: string | null;
  knowledge_point_ids: string[];
  anchors?: { id: string; document_id: string; chunk_id: string | null; note: string }[];
};

export type EduExplain = {
  answer: string;
  question_id: string;
  citations: {
    chunk_id?: string | null;
    document_id?: string | null;
    snippet: string;
    source: string;
    score?: number | null;
  }[];
  knowledge_point_ids: string[];
};

export type EduPractice = {
  session_id: string;
  mode: string;
  questions: EduQuestion[];
};

export type EduPracticeAnswer = {
  id: string;
  session_id: string;
  question_id: string;
  user_answer_md: string;
  is_correct: number | null;
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

  ask(token: string, question: string, limit = 5, graphAugment = false) {
    return apiFetch<AskResponse>("/v1/ask", {
      method: "POST",
      token,
      body: JSON.stringify({ question, limit, graph_augment: graphAugment }),
    });
  },

  graphStats(token: string) {
    return apiFetch<GraphStats>("/v1/graph/stats", { token });
  },

  graphEntities(token: string, q?: string) {
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    return apiFetch<GraphEntity[]>(`/v1/graph/entities${qs}`, { token });
  },

  graphEntity(token: string, id: string) {
    return apiFetch<GraphEntityDetail>(`/v1/graph/entities/${id}`, { token });
  },

  graphNeighbors(token: string, id: string) {
    return apiFetch<GraphNeighbors>(`/v1/graph/entities/${id}/neighbors`, { token });
  },

  graphExtract(token: string, documentId: string, force = false) {
    return apiFetch<GraphJob>("/v1/graph/extract", {
      method: "POST",
      token,
      body: JSON.stringify({ document_id: documentId, force }),
    });
  },

  graphJob(token: string, jobId: string) {
    return apiFetch<GraphJob>(`/v1/graph/jobs/${jobId}`, { token });
  },

  eduPacks(token: string) {
    return apiFetch<EduPack[]>("/v1/edu/packs", { token });
  },

  eduSeedDemo(token: string) {
    return apiFetch<{ pack_id: string; created: boolean; points: number; questions: number }>(
      "/v1/edu/packs/seed-demo",
      { method: "POST", token },
    );
  },

  eduPoints(token: string, opts?: { subject?: string; pack_id?: string }) {
    const params = new URLSearchParams();
    if (opts?.subject) params.set("subject", opts.subject);
    if (opts?.pack_id) params.set("pack_id", opts.pack_id);
    const q = params.toString() ? `?${params}` : "";
    return apiFetch<EduPoint[]>(`/v1/edu/points${q}`, { token });
  },

  eduQuestions(
    token: string,
    opts?: {
      subject?: string;
      stage?: string;
      grade?: number;
      pack_id?: string;
      knowledge_point_id?: string;
      difficulty?: number;
      limit?: number;
    },
  ) {
    const params = new URLSearchParams();
    if (opts?.subject) params.set("subject", opts.subject);
    if (opts?.stage) params.set("stage", opts.stage);
    if (opts?.grade != null) params.set("grade", String(opts.grade));
    if (opts?.pack_id) params.set("pack_id", opts.pack_id);
    if (opts?.knowledge_point_id) params.set("knowledge_point_id", opts.knowledge_point_id);
    if (opts?.difficulty != null) params.set("difficulty", String(opts.difficulty));
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString() ? `?${params}` : "";
    return apiFetch<EduQuestion[]>(`/v1/edu/questions${q}`, { token });
  },

  eduQuestion(token: string, id: string) {
    return apiFetch<EduQuestion>(`/v1/edu/questions/${id}`, { token });
  },

  eduExplain(token: string, body: { question_id?: string; stem_md?: string; limit?: number }) {
    return apiFetch<EduExplain>("/v1/edu/explain", {
      method: "POST",
      token,
      body: JSON.stringify(body),
    });
  },

  eduSimilar(token: string, questionId: string, topK?: number) {
    const params = new URLSearchParams({ question_id: questionId });
    if (topK != null) params.set("top_k", String(topK));
    return apiFetch<EduQuestion[]>(`/v1/edu/similar?${params}`, { token });
  },

  eduPractice(
    token: string,
    body: {
      mode?: string;
      workspace_id?: string;
      filters?: Record<string, unknown>;
      question_ids?: string[];
      limit?: number;
    },
  ) {
    return apiFetch<EduPractice>("/v1/edu/practice", {
      method: "POST",
      token,
      body: JSON.stringify(body),
    });
  },

  eduPracticeAnswer(
    token: string,
    sessionId: string,
    body: { question_id: string; user_answer_md: string },
  ) {
    return apiFetch<EduPracticeAnswer>(`/v1/edu/practice/${sessionId}/answer`, {
      method: "POST",
      token,
      body: JSON.stringify(body),
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
