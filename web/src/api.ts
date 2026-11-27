// Thin API client. The session cookie is HttpOnly; every state-changing call sends X-CertiFlow: 1.
export type Role = "admin" | "certified_translator" | "reviewer";
export interface User { id: number; username: string; name: string; role: Role; ui_language: "en" | "ar" }
export interface Language { code: string; name: string; native: string; direction: "ltr" | "rtl" }
export interface StampOption { choice: "certified" | "office"; label: string; name?: string; available: boolean; image?: string; reason?: string }
export interface JobDoc { key: string; title: string; filename: string; source_language: string; target_language: string;
  stage?: string; blocks?: number; open_flags?: Record<string, number> }
export interface JobFile { name: string; size: number; kind: string }
export interface Job { id: string; title: string; created_at: string; status: string; stage: string;
  source_language: string; target_language: string; stamp: string; cost_usd: number; error: string | null;
  documents_count: number; documents?: JobDoc[]; files?: JobFile[]; approved_at?: string | null;
  page_order?: string; document_type?: string | null; notes?: string | null;
  cost_by_agent?: Record<string, { calls: number; cost_usd: number; input_tokens: number; output_tokens: number }> }
export interface GlossaryItem { source: string; target: string; kind: string; confirmed?: boolean }

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} as Record<string, string> };
  if (method !== "GET") (init.headers as Record<string, string>)["X-CertiFlow"] = "1";
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  me: () => req<User>("GET", "/api/me"),
  login: (username: string, password: string) => req<User>("POST", "/api/auth/login", { username, password }),
  logout: () => req("POST", "/api/auth/logout"),
  setLanguage: (ui_language: "en" | "ar") => req("POST", "/api/me/prefs", { ui_language }),
  languages: () => req<Language[]>("GET", "/api/languages"),
  stamps: () => req<StampOption[]>("GET", "/api/stamps"),
  recentPairs: () => req<{ source: string; target: string }[]>("GET", "/api/recent-pairs"),
  jobs: () => req<Job[]>("GET", "/api/jobs"),
  job: (id: string) => req<Job>("GET", `/api/jobs/${id}`),
  createJob: (fd: FormData) => req<{ id: string }>("POST", "/api/jobs", fd),
  glossary: (id: string) => req<{ confirmed: boolean; items: GlossaryItem[] }>("GET", `/api/jobs/${id}/glossary`),
  confirmGlossary: (id: string, items: GlossaryItem[]) => req("POST", `/api/jobs/${id}/glossary/confirm`, { items }),
  documentModel: (id: string, key: string) => req<{ stage: string; model: DocModel }>("GET", `/api/jobs/${id}/documents/${key}`),
  approve: (id: string, note?: string) => req("POST", `/api/jobs/${id}/approve`, { note }),
  retry: (id: string) => req("POST", `/api/jobs/${id}/retry`),
};

export interface DocBlock { id: string; type: string; source_page?: number; source_text?: string; translated_text?: string;
  label?: string; rows?: { cells: { source_text?: string; translated_text?: string }[] }[];
  flags?: { code: string; severity: string; message: string; resolved?: boolean }[]; status?: string }
export interface DocModel { title: string; source_language: string; target_language: string; blocks: DocBlock[] }
