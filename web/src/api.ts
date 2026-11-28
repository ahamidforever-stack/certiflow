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
  documents_count: number; client?: string | null; documents?: JobDoc[]; files?: JobFile[]; approved_at?: string | null;
  page_order?: string; document_type?: string | null; notes?: string | null;
  cost_by_agent?: Record<string, { calls: number; cost_usd: number; input_tokens: number; output_tokens: number }> }
export interface GlossaryItem { source: string; target: string; kind: string; confirmed?: boolean; remembered?: boolean }
export interface MemoryClient { client: string; terms: number; updated_at: string | null; pairs: { source: string; target: string; terms: number }[] }
export interface MemoryTerm { id: number; client: string; source_language: string; target_language: string; source: string; target: string;
  kind: string; updated_at: string; updated_by: string; job_id: string | null; uses: number }

export interface AdminUser extends User { active: boolean; created_at: string; last_login_at: string | null;
  devices: number; locked: boolean; certified_stamp: boolean }
export interface AdminEvent { at: string; actor: string; action: string; target: string; data: Record<string, unknown> }
export type AssetType = "template" | "stamp_certified" | "stamp_office" | "signature";
export interface AssetInfo { id: string; name: string; type: AssetType; active: boolean; owner_user?: string | null;
  owner_company?: string | null; width_mm?: number | null; language?: string | null; pair?: string | null;
  file: string; size: number | null; seal_from_template: boolean; source_layout: boolean; margins_mm?: Record<string, number> | null }
export interface AssetListing { company: string; editable: boolean; assets: AssetInfo[];
  users: { id: string; name: string; role: string }[]; accounts: { username: string; name: string; role: string }[] }
export interface AgentConf { model: string; effort: string; max_tokens: number; prompt_version: string }
export interface ModelSettings { agents: Record<string, AgentConf & { default: AgentConf; overridden: string[]; prompt_versions: string[] }>;
  efforts: string[]; models: { model: string; input: number; output: number; cache_read: number; cache_write: number }[];
  pipeline: Record<string, number>; pipeline_default: Record<string, number>; pipeline_overridden: string[] }
export interface LangAdmin { code: string; display_name: string; native_name: string; direction: "ltr" | "rtl"; script: string;
  ocr_pack: string; values: Record<string, unknown>; default: Record<string, unknown>; overridden: string[];
  pdf_font_installed: boolean; fallback_installed: boolean }
export interface PairAdmin { source: string; target: string; template_id: string | null; conventions: string;
  no_foreign_script: boolean | null; transliteration_standard: string | null; in_defaults: boolean; overridden: boolean }
export interface LanguageAdmin { languages: LangAdmin[]; pairs: PairAdmin[]; editable: string[]; text_fields: string[];
  templates: { id: string; name: string; language: string | null; pair: string | null }[] }
export interface UsageAgent { agent: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number; cache_read_tokens: number }
export interface Usage { days: number; timezone: string; from: string; to: string;
  tiles: { today: number; week: number; month: number };
  total: { cost_usd: number; calls: number; jobs: number; input_tokens: number; output_tokens: number; cache_read_tokens: number };
  per_page_usd: number | null; pages: number;
  by_day: { day: string; cost_usd: number; calls: number }[]; by_agent: UsageAgent[];
  by_model: { model: string; calls: number; cost_usd: number }[];
  by_user: { username: string; name: string; jobs: number; cost_usd: number }[];
  top_jobs: { id: string; title: string; status: string; pages: number | null; by: string; cost_usd: number; calls: number }[] }
export interface SessionInfo { id: string; created_at: string; last_seen_at: string; ip: string; user_agent: string; current: boolean }

export class ApiError extends Error {
  constructor(public status: number, message: string, public retryAfter?: number) { super(message); }
}

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
    const ra = Number(r.headers.get("Retry-After"));
    throw new ApiError(r.status, msg, Number.isFinite(ra) && ra > 0 ? ra : undefined);
  }
  return r.json() as Promise<T>;
}

export const api = {
  me: () => req<User>("GET", "/api/me"),
  login: (username: string, password: string) => req<User>("POST", "/api/auth/login", { username, password }),
  logout: () => req("POST", "/api/auth/logout"),
  // admin (Phase 5)
  adminUsers: () => req<AdminUser[]>("GET", "/api/admin/users"),
  adminCreateUser: (body: { username: string; name: string; role: Role; password: string }) => req<AdminUser>("POST", "/api/admin/users", body),
  adminUpdateUser: (id: number, body: { name?: string; role?: Role; active?: boolean }) => req<AdminUser>("PATCH", `/api/admin/users/${id}`, body),
  adminSetPassword: (id: number, password: string) => req<AdminUser>("POST", `/api/admin/users/${id}/password`, { password }),
  adminUnlock: (id: number) => req<AdminUser>("POST", `/api/admin/users/${id}/unlock`),
  adminSignOut: (id: number) => req<AdminUser>("POST", `/api/admin/users/${id}/sessions/revoke`),
  adminAssets: () => req<AssetListing>("GET", "/api/admin/assets"),
  adminAddImage: (fd: FormData) => req<AssetInfo>("POST", "/api/admin/assets/image", fd),
  adminAddTemplate: (fd: FormData) => req<AssetInfo>("POST", "/api/admin/assets/template", fd),
  adminUpdateAsset: (id: string, body: { active?: boolean; name?: string; width_mm?: number }) =>
    req<AssetInfo>("PATCH", `/api/admin/assets/${encodeURIComponent(id)}`, body),
  assetFile: (id: string) => `/api/admin/assets/${encodeURIComponent(id)}/file`,
  adminSettings: () => req<ModelSettings>("GET", "/api/admin/settings"),
  adminSetAgent: (name: string, body: { model: string; effort: string; prompt_version: string; max_tokens: number }) =>
    req<ModelSettings>("PUT", `/api/admin/settings/agents/${name}`, body),
  adminResetAgent: (name: string) => req<ModelSettings>("DELETE", `/api/admin/settings/agents/${name}`),
  adminSetPipeline: (body: Record<string, number>) => req<ModelSettings>("PUT", "/api/admin/settings/pipeline", body),
  adminLanguages: () => req<LanguageAdmin>("GET", "/api/admin/languages"),
  adminSetLanguage: (code: string, body: Record<string, unknown>) => req<LanguageAdmin>("PUT", `/api/admin/languages/${code}`, body),
  adminResetLanguage: (code: string) => req<LanguageAdmin>("DELETE", `/api/admin/languages/${code}`),
  adminSetPair: (s: string, tg: string, body: Record<string, unknown>) => req<LanguageAdmin>("PUT", `/api/admin/pairs/${s}/${tg}`, body),
  adminResetPair: (s: string, tg: string) => req<LanguageAdmin>("DELETE", `/api/admin/pairs/${s}/${tg}`),
  adminUsage: (days: number) => req<Usage>("GET", `/api/admin/usage?days=${days}`),
  adminEvents: () => req<AdminEvent[]>("GET", "/api/admin/events"),
  sessions: () => req<SessionInfo[]>("GET", "/api/me/sessions"),
  revokeOtherSessions: () => req<{ revoked: number }>("POST", "/api/me/sessions/revoke-others"),
  setLanguage: (ui_language: "en" | "ar") => req("POST", "/api/me/prefs", { ui_language }),
  languages: () => req<Language[]>("GET", "/api/languages"),
  stamps: () => req<StampOption[]>("GET", "/api/stamps"),
  recentPairs: () => req<{ source: string; target: string }[]>("GET", "/api/recent-pairs"),
  jobs: () => req<Job[]>("GET", "/api/jobs"),
  job: (id: string) => req<Job>("GET", `/api/jobs/${id}`),
  createJob: (fd: FormData) => req<{ id: string }>("POST", "/api/jobs", fd),
  glossary: (id: string) => req<{ confirmed: boolean; items: GlossaryItem[] }>("GET", `/api/jobs/${id}/glossary`),
  clients: () => req<string[]>("GET", "/api/clients"),
  memory: () => req<MemoryClient[]>("GET", "/api/glossary-memory"),
  memoryTerms: (client: string, source?: string, target?: string) =>
    req<MemoryTerm[]>("GET", `/api/glossary-memory/terms?${new URLSearchParams({ client, ...(source ? { source } : {}), ...(target ? { target } : {}) })}`),
  memoryUpdate: (id: number, target: string, kind: string) => req<MemoryTerm>("PUT", `/api/glossary-memory/terms/${id}`, { target, kind }),
  memoryDelete: (id: number) => req<{ ok: boolean }>("DELETE", `/api/glossary-memory/terms/${id}`),
  confirmGlossary: (id: string, items: GlossaryItem[]) => req("POST", `/api/jobs/${id}/glossary/confirm`, { items }),
  documentModel: (id: string, key: string) => req<{ stage: string; model: DocModel }>("GET", `/api/jobs/${id}/documents/${key}`),
  approve: (id: string, note?: string) => req("POST", `/api/jobs/${id}/approve`, { note }),
  retry: (id: string) => req("POST", `/api/jobs/${id}/retry`),
  // review editor (Phase 4)
  editBlock: (id: string, key: string, block: string, body: { text?: string; cells?: { row: number; col: number; text: string }[]; reason?: string }) =>
    req<ReviewResult>("PUT", `/api/jobs/${id}/documents/${key}/blocks/${encodeURIComponent(block)}`, body),
  decideChange: (id: string, key: string, block: string, index: number, decision: "accept" | "reject") =>
    req<ReviewResult>("POST", `/api/jobs/${id}/documents/${key}/blocks/${encodeURIComponent(block)}/changes/${index}/${decision}`),
  resolveFlag: (id: string, key: string, block: string, index: number, comment: string) =>
    req<ReviewResult>("POST", `/api/jobs/${id}/documents/${key}/blocks/${encodeURIComponent(block)}/flags/${index}/resolve`, { comment }),
  rerun: (id: string, key: string, agent: string, blocks: string[], instruction: string) =>
    req<{ ok: boolean }>("POST", `/api/jobs/${id}/documents/${key}/rerun`, { agent, blocks, instruction }),
  audit: (id: string) => req<{ records: AuditRecord[]; truncated: boolean }>("GET", `/api/jobs/${id}/audit`),
  pageImage: (id: string, key: string, n: number) => `/api/jobs/${id}/documents/${key}/pages/${n}.png`,
};

export interface DocFlag { code: string; severity: string; message?: string; agent?: string; resolved?: boolean;
  resolved_by?: string; resolution?: string }
export interface DocHistory { at?: string; actor: string; field?: string; old?: string | null; new?: string | null; reason?: string;
  review?: "accepted" | "rejected" | null; reviewed_by?: string }
export interface DocCell { source_text?: string; translated_text?: string; header?: boolean; colspan?: number; blocks?: unknown[] }
export interface DocBlock { id: string; type: string; source_page?: number; bbox?: number[]; source_text?: string; translated_text?: string;
  label?: string; level?: number; rows?: { cells: DocCell[]; header?: boolean }[]; direction?: string;
  flags?: DocFlag[]; history?: DocHistory[]; status?: string; multilingual_duplicate?: boolean }
export interface DocModel { title: string; source_language: string; target_language: string; blocks: DocBlock[];
  pages?: { number: number }[] }
export interface ReviewResult { stage: string; model: DocModel; open_blockers: string[] }
export interface AuditRecord { kind: string; at?: string; by?: string | null; agent?: string; stage?: string; status?: string;
  document?: string; block?: string; blocks?: string[] | number; action?: string; model?: string; prompt_version?: string;
  usage?: { input_tokens?: number; output_tokens?: number }; cost_usd?: number; latency_s?: number; error?: string | null;
  note?: string | null; pdf?: string }
