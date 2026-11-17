import type { components } from './openapi';

// The native check route parses its body manually (it also accepts multipart), so
// FastAPI inlines this schema in the OpenAPI path rather than registering a component.
export interface CheckInput {
  type: 'text' | 'url' | 'file' | 'image';
  text?: string | null;
  url?: string | null;
  language?: string | null;
}

export interface CheckRequest {
  input: CheckInput;
  persona_id?: string | null;
  response_language?: string | null;
  mode?: 'async' | 'sync';
  fast?: boolean;
}

export type CheckResponse = components['schemas']['CheckResponse'];
export type FactCheckResult = components['schemas']['FactCheckResult'];
export type JobEnvelope = components['schemas']['JobEnvelope'];
export type Job = components['schemas']['Job'];

export interface SessionInfo {
  user: { id: string; email: string; display_name: string; permissions: string[] };
  csrf_token: string;
  totp_setup_required: boolean;
}

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.status = status;
    this.code = code;
  }
}

let csrfToken = '';
export function setCsrf(token: string): void {
  csrfToken = token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const body = init.body;
  if (body !== undefined && body !== null && !(body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (csrfToken && (init.method ?? 'GET') !== 'GET') {
    headers.set('X-CSRF-Token', csrfToken);
  }
  const response = await fetch(path, { ...init, headers, credentials: 'include' });
  if (!response.ok) {
    let code = 'http_error';
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const error = payload.error as Record<string, unknown> | undefined;
      code = String(error?.code ?? payload.code ?? code);
      detail = String(error?.message ?? payload.detail ?? detail);
    } catch {
      /* HTML error page or empty body */
    }
    throw new ApiError(response.status, code, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function getSession(): Promise<SessionInfo | null> {
  const response = await fetch('/api/auth/session', { credentials: 'include' });
  if (response.status === 401) return null;
  if (!response.ok) throw new ApiError(response.status, 'session_failed', 'Session failed.');
  const session = (await response.json()) as SessionInfo;
  setCsrf(session.csrf_token);
  return session;
}

export async function login(
  email: string,
  password: string,
  totp?: string,
): Promise<SessionInfo> {
  const session = await request<SessionInfo>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, totp_code: totp || undefined }),
  });
  setCsrf(session.csrf_token);
  return session;
}

export async function logout(): Promise<void> {
  await request<void>('/api/auth/logout', { method: 'POST' });
  setCsrf('');
}

export async function createCheck(
  body: CheckRequest,
  file?: File | null,
): Promise<{ status: number; job: Job }> {
  if (file) {
    const form = new FormData();
    form.set('payload', JSON.stringify(body));
    form.set('file', file);
    const response = await fetch('/v1/factcheck', {
      method: 'POST',
      body: form,
      credentials: 'include',
      headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
    });
    if (!response.ok) throw await errorFrom(response);
    const payload = (await response.json()) as { job: Job };
    return { status: response.status, job: payload.job };
  }
  const accepted = await request<{ job: Job }>('/v1/factcheck', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return { status: 202, job: accepted.job };
}

export async function getJob(jobId: string): Promise<JobEnvelope> {
  return request<JobEnvelope>(`/v1/factcheck/${encodeURIComponent(jobId)}`);
}

export async function getClaim(resultId: string): Promise<{
  result: CheckResponse;
  versions: { result_id: string; version: number; created_at: string; current: boolean }[];
  feedback: { helpful: number; unhelpful: number; incorrect: number; my_feedback: string | null };
}> {
  return request(`/v1/claims/${encodeURIComponent(resultId)}`);
}

export async function listClaims(params: {
  query?: string;
  mine?: boolean;
  verdict?: string;
}): Promise<{
  data: {
    result_id: string;
    claim_text: string;
    language: string;
    overall_verdict: string | null;
    topics: string[];
    domain_tags: string[];
    created_at: string;
    preliminary: boolean;
    has_contradiction: boolean;
  }[];
  next_cursor: string | null;
}> {
  const search = new URLSearchParams();
  if (params.query) search.set('query', params.query);
  if (params.mine) search.set('mine', 'true');
  if (params.verdict) search.set('verdict', params.verdict);
  return request(`/v1/claims?${search.toString()}`);
}

export async function sendFeedback(resultId: string, kind: string): Promise<void> {
  await request<void>(`/v1/claims/${encodeURIComponent(resultId)}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ kind }),
  });
}

export async function listPersonas(): Promise<
  { id: string; label: string; output_formats: string[] }[]
> {
  const payload = await request<{
    data: { id: string; factcheck?: { persona_id?: string | null } }[];
  }>('/v1/models');
  // ``factcheck`` is the default alias of the same persona as ``factcheck:analyst``;
  // listing both would show the same persona twice.
  return payload.data
    .filter((model) => model.factcheck?.persona_id && model.id !== 'factcheck')
    .map((model) => ({
      id: model.id,
      label: (model.factcheck?.persona_id ?? model.id)
        .split(/[-_]/)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' '),
      output_formats: ['substance', 'persona'],
    }));
}

async function errorFrom(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let detail = response.statusText;
  try {
    const payload = (await response.json()) as Record<string, unknown>;
    code = String(payload.code ?? code);
    detail = String(payload.detail ?? detail);
  } catch {
    /* ignore */
  }
  return new ApiError(response.status, code, detail);
}

export interface ChatStreamResult {
  jobId: string | null;
}

export async function chatStream(
  model: string,
  messages: { role: string; content: string }[],
  onChunk: (text: string) => void,
): Promise<ChatStreamResult> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch('/v1/chat/completions', {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify({ model, messages, stream: true }),
  });
  if (!response.ok || !response.body) throw await errorFrom(response);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let jobId: string | null = null;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const line = part
        .split('\n')
        .find((entry) => entry.startsWith('data:'));
      if (!line) continue;
      const payload = line.slice('data:'.length).trim();
      if (!payload || payload === '[DONE]') continue;
      try {
        const chunk = JSON.parse(payload) as {
          choices?: { delta?: { content?: string } }[];
          factcheck?: { job_id?: string };
        };
        if (chunk.factcheck?.job_id) jobId = chunk.factcheck.job_id;
        const text = chunk.choices?.[0]?.delta?.content;
        if (text) onChunk(text);
      } catch {
        /* keepalive or partial frame */
      }
    }
  }
  return { jobId };
}

export async function startTotpSetup(): Promise<{ secret: string; otpauth_uri: string }> {
  return request('/api/auth/totp/setup', { method: 'POST' });
}

export async function confirmTotp(
  code: string,
): Promise<{ enabled: boolean; recovery_codes: string[] }> {
  return request('/api/auth/totp/confirm', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

export type ProviderInfo = components['schemas']['ProviderInfo'];
export type ModelInfo = components['schemas']['ModelInfo'];
export type RoleInfo = components['schemas']['RoleInfo'];
export type UserInfo = components['schemas']['UserInfo'];
export type UsageSummary = components['schemas']['UsageSummary'];
export type DataFlowPolicy = components['schemas']['DataFlowPolicy'];
export type RoleBudgets = components['schemas']['RoleBudgets'];
export type ReindexAccepted = components['schemas']['ReindexAccepted'];

export async function listProviders(): Promise<ProviderInfo[]> {
  return request('/v1/config/providers');
}

export async function testProvider(id: string): Promise<{ models: string[]; latency_ms: number }> {
  return request(`/v1/config/providers/${encodeURIComponent(id)}/test`, { method: 'POST' });
}

export async function listModels(): Promise<ModelInfo[]> {
  return request('/v1/config/models');
}

export async function listRoles(): Promise<RoleInfo[]> {
  return request('/v1/config/roles');
}

export async function assignRole(alias: string, modelId: string): Promise<RoleInfo> {
  return request(`/v1/config/roles/${encodeURIComponent(alias)}`, {
    method: 'PUT',
    body: JSON.stringify({ model_id: modelId }),
  });
}

export async function listUsers(): Promise<{ data: UserInfo[] }> {
  return request('/v1/users');
}

export interface UserCreateInput {
  email: string;
  display_name: string;
  password: string;
  roles: string[];
}

export async function createUser(body: UserCreateInput): Promise<UserInfo> {
  return request('/v1/users', { method: 'POST', body: JSON.stringify(body) });
}

export async function updateUser(id: string, body: Record<string, unknown>): Promise<UserInfo> {
  return request(`/v1/users/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function usageSummary(from?: string, to?: string): Promise<UsageSummary> {
  const search = new URLSearchParams();
  if (from) search.set('from', from);
  if (to) search.set('to', to);
  return request(`/v1/usage/summary?${search.toString()}`);
}

export async function getDataFlow(): Promise<DataFlowPolicy> {
  return request('/v1/config/data-flow');
}

export async function setDataFlow(policy: DataFlowPolicy): Promise<DataFlowPolicy> {
  return request('/v1/config/data-flow', {
    method: 'PUT',
    body: JSON.stringify(policy),
  });
}

export async function getBudgets(): Promise<RoleBudgets> {
  return request('/v1/config/budgets');
}

export async function setBudgets(roles: Record<string, number>): Promise<RoleBudgets> {
  return request('/v1/config/budgets', {
    method: 'PUT',
    body: JSON.stringify({ roles }),
  });
}

export async function startReindex(): Promise<ReindexAccepted> {
  return request('/v1/config/reindex', {
    method: 'POST',
    body: JSON.stringify({ confirm: true, reason: 'operator UI' }),
  });
}

export async function getReindex(jobId: string): Promise<{
  job_id: string;
  state: string;
  progress: number;
  documents: number;
}> {
  return request(`/v1/config/reindex/${encodeURIComponent(jobId)}`);
}

export async function updateProvider(
  id: string,
  body: { api_key?: string; enabled?: boolean; base_url?: string; is_local?: boolean; name?: string },
): Promise<ProviderInfo> {
  return request(`/v1/config/providers/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

export async function probeModel(
  id: string,
  capabilities: string[] = [],
): Promise<{
  model_id: string;
  results: { capability: string; status: string; detail: string; latency_ms: number }[];
}> {
  return request(`/v1/config/models/${encodeURIComponent(id)}/probe`, {
    method: 'POST',
    body: JSON.stringify({ capabilities }),
  });
}
