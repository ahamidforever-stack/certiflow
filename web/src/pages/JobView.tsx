import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, ArrowRight, BookOpenText, Check, ChevronDown, Download, FileArchive, FileText, FileType2,
  History, Loader2, OctagonAlert, Plus, RotateCw, Search, ShieldCheck, Sparkles, Stamp, Trash2, X,
} from "lucide-react";
import { api, type DocModel, type GlossaryItem, type Job, type JobFile } from "../api";
import { useAuth } from "../App";
import { StatusChip } from "../components/Status";
import { SealRing } from "../components/Seal";
import { useI18n } from "../i18n";
import { useJobs } from "../lib/useJobs";
import { STEPS, progressOf } from "../lib/jobs";
import { cn } from "../lib/cn";

interface Ev { id: number; text: string; at?: string; tone?: "error" | "ok" }
const KINDS = ["name", "organisation", "place", "acronym", "term"];

export default function JobView() {
  const { id = "" } = useParams();
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const { refresh: refreshJobs } = useJobs();
  const loc = useLocation();
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState(false);
  const [events, setEvents] = useState<Ev[]>([]);
  const seq = useRef(0);

  const load = useCallback(() => api.job(id).then((j) => { setJob(j); setErr(false); }).catch(() => setErr(true)), [id]);
  useEffect(() => { setJob(null); setEvents([]); load(); }, [load]);
  const changed = () => { load(); refreshJobs(); };

  // live progress (server-sent events); reconnects automatically
  useEffect(() => {
    const es = new EventSource(`/api/jobs/${id}/events`);
    const push = (text: string, at?: string, tone?: Ev["tone"]) =>
      setEvents((e) => [...e.slice(-199), { id: ++seq.current, text, at, tone }]);
    es.addEventListener("progress", (m) => {
      const d = JSON.parse((m as MessageEvent).data);
      if (d.kind === "llm_call") push(t("ev_llm_call", { agent: t(`agent_${d.agent}`) }) + (d.document ? ` · ${d.document}` : ""), d.at);
      else if (d.kind === "llm_error") push(t("ev_llm_error", { agent: t(`agent_${d.agent}`) }), d.at, "error");
      else if (d.kind === "stage_done") push(t("ev_stage_done", { stage: t(`sd_${d.stage}`) }) + (d.document ? ` · ${d.document}` : ""), d.at);
      else if (d.kind === "qa_loop") push(t("ev_qa_loop", { n: (d.blocks || []).length }), d.at);
      else if (d.kind === "glossary_confirmed") push(t("ev_glossary_confirmed"), d.at, "ok");
      else if (d.kind === "approved") push(t("ev_approved", { by: d.by }), d.at, "ok");
      else if (d.kind === "released") push(t("ev_released", { pdf: d.pdf }), d.at, "ok");
    });
    es.addEventListener("status", () => changed());
    es.addEventListener("end", () => { changed(); es.close(); });
    return () => es.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, lang]);

  useEffect(() => {
    if (job && loc.hash === "#glossary") document.getElementById("glossary")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [job?.status, loc.hash]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err && !job) return (
    <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <span className="flex-1">{t("loadError")}</span><button className="btn-ghost btn-sm" onClick={load}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button>
    </div>
  );
  if (!job) return <JobSkeleton />;
  const isSigner = user?.role === "admin" || user?.role === "certified_translator";
  const p = progressOf(job);
  const running = ["queued", "running", "reworking", "releasing"].includes(job.status);

  return (
    <div className="animate-fade-in">
      <Link to="/jobs" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4 rtl:-scale-x-100" />{t("back")}
      </Link>
      <header className="mb-8 flex items-start gap-3 sm:gap-4">
        <SealRing progress={p} size={56} className="hidden sm:block" />
        <SealRing progress={p} size={40} className="sm:hidden" />
        <div className="min-w-0 flex-1">
          <h1 className="page-title break-words sm:truncate"><bdi>{job.title}</bdi></h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
            <StatusChip status={job.status} />
            {job.client && <bdi className="text-slate-700">{job.client}</bdi>}
            <bdi className="font-mono text-xs uppercase" dir="ltr">{job.source_language} → {job.target_language}</bdi>
          </div>
        </div>
        <Link to={`/jobs/${job.id}/audit`} className="btn-ghost btn-sm" aria-label={t("auOpen")} title={t("auOpen")}><History className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t("auOpen")}</span></Link>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-6">
          {job.error && (job.status === "failed" || job.status === "blocked") ? (
            <section className="card border-red-200 p-5">
              <div className="flex items-start gap-3">
                <OctagonAlert className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
                <div className="min-w-0 flex-1">
                  <h2 className="font-medium text-slate-900">{t(job.status === "blocked" ? "jvBlockedTitle" : "jvFailedTitle")}</h2>
                  <p className="mt-1 text-sm text-red-800" dir="auto">{job.error}</p>
                </div>
                {job.status === "failed" && <button className="btn-primary btn-sm" onClick={() => api.retry(job.id).then(changed)}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button>}
              </div>
            </section>
          ) : job.error ? (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" dir="auto">{job.error}</p>
          ) : null}

          {job.purged_at && (
            <p className="rounded-xl border border-slate-200 bg-slate-100 px-4 py-3 text-sm text-slate-700">
              {t("jbPurged", { date: new Date(job.purged_at).toLocaleDateString(lang === "ar" ? "ar-AE" : "en-GB", { day: "numeric", month: "short", year: "numeric" }) })}
            </p>
          )}

          {!job.purged_at && job.status === "waiting_glossary" && <GlossaryStep jobId={job.id} onDone={changed} />}
          {!job.purged_at && job.status === "waiting_review" && <ReviewStep job={job} canApprove={isSigner} onDone={changed} />}
          {running && <WorkingCard job={job} events={events} />}
          {job.status === "released" && <ReleasedCard job={job} />}
          {job.status !== "released" && job.files && job.files.length > 0 && <Files job={job} />}
        </div>

        <aside className="space-y-6 lg:sticky lg:top-8 lg:self-start">
          <Journey job={job} />
          <Details job={job} admin={user?.role === "admin"} onChange={changed} />
          {!running && <Activity events={events} />}
        </aside>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ journey rail */

function Journey({ job }: { job: Job }) {
  const { t } = useI18n();
  const p = progressOf(job);
  return (
    <section>
      <h2 className="eyebrow mb-3">{t("jvJourney")}</h2>
      <ol className="relative">
        {STEPS.map((s, i) => {
          const done = i < p.done;
          const active = p.active === i;
          const state = done ? "done" : active ? p.tone : "todo";
          return (
            <li key={s} className="relative flex gap-3 pb-4 last:pb-0">
              {i < STEPS.length - 1 && <span className={cn("absolute start-[11px] top-6 h-[calc(100%-1.25rem)] w-px", done ? "bg-brand-500" : "bg-slate-200")} aria-hidden />}
              <span className={cn("relative z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                state === "done" && (i === 6 ? "bg-seal-500 text-white" : "bg-brand-600 text-white dark:bg-brand-500"),
                state === "run" && "bg-brand-50 text-brand-600 ring-2 ring-brand-400",
                state === "you" && "bg-seal-50 text-seal-700 ring-2 ring-seal-400",
                state === "fail" && "bg-red-50 text-red-600 ring-2 ring-red-400",
                state === "todo" && "bg-surface text-slate-400 ring-1 ring-slate-200")}>
                {state === "done" ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : state === "run" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : state === "fail" ? "!" : i + 1}
              </span>
              <div className="min-w-0 pt-0.5">
                <div className={cn("text-sm", done ? "text-slate-600" : active ? "font-medium text-slate-900" : "text-slate-400")}>{t(s)}</div>
                {active && (
                  <div className={cn("text-xs", p.tone === "you" ? "text-seal-700" : p.tone === "fail" ? "text-red-700" : "text-brand-500")}>
                    {t(p.tone === "you" ? "jvStepWaiting" : p.tone === "fail" ? "jvStepFailed" : "jvStepWorking")}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Details({ job, admin, onChange }: { job: Job; admin: boolean; onChange: () => void }) {
  const { t, lang } = useI18n();
  const row = (k: string, v: React.ReactNode) => (
    <div className="flex items-baseline justify-between gap-3 py-1.5"><dt className="text-slate-500">{t(k)}</dt><dd className="min-w-0 truncate text-end text-slate-800">{v}</dd></div>
  );
  return (
    <section>
      <h2 className="eyebrow mb-2">{t("jvDetails")}</h2>
      <dl className="divide-y divide-slate-200/70 text-[13px]">
        {row("jvPair", <bdi className="font-mono text-xs uppercase" dir="ltr">{job.source_language} → {job.target_language}</bdi>)}
        {row("jvStamp", job.stamp === "certified" ? t("certified") : t("officeStamp"))}
        {job.document_type && row("jvDocType", <bdi>{job.document_type}</bdi>)}
        {row("jvCreated", new Date(job.created_at).toLocaleString(lang === "ar" ? "ar-AE" : "en-GB", { dateStyle: "medium", timeStyle: "short" }))}
        {row("jvCost", <span className="font-mono text-xs" dir="ltr">${job.cost_usd.toFixed(2)}</span>)}
        {row("jvJobId", <span className="font-mono text-xs" dir="ltr">{job.id}</span>)}
      </dl>
      {admin && !job.purged_at && (
        <label className="mt-3 flex items-start gap-2 rounded-lg bg-slate-100/70 px-3 py-2 text-xs text-slate-700">
          <input type="checkbox" className="mt-0.5 h-3.5 w-3.5 accent-brand-600" checked={!!job.keep}
            onChange={(e) => api.setKeep(job.id, e.target.checked).then(onChange)} />
          <span><span className="font-medium">{t("jbKeep")}</span><span className="block text-slate-500">{t("jbKeepHint")}</span></span>
        </label>
      )}
    </section>
  );
}

function Activity({ events, live }: { events: Ev[]; live?: boolean }) {
  const { t } = useI18n();
  const list = [...events].reverse();
  return (
    <section>
      <h2 className="eyebrow mb-2 flex items-center gap-2">{t("jvActivity")}
        {live && <span className="relative flex h-1.5 w-1.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-70" /><span className="relative h-1.5 w-1.5 rounded-full bg-brand-500" /></span>}
      </h2>
      {list.length === 0 ? <p className="text-xs text-slate-500">{t("jvNoActivity")}</p> : (
        <ol className="max-h-80 space-y-1.5 overflow-y-auto text-xs">
          {list.map((e, i) => (
            <li key={e.id} className={cn("flex gap-2.5", i === 0 && "animate-fade-in", e.tone === "error" ? "text-red-700" : e.tone === "ok" ? "text-emerald-700" : i === 0 ? "text-slate-900" : "text-slate-500")}>
              <span className="shrink-0 font-mono tabular-nums text-slate-400" dir="ltr">{e.at ? new Date(e.at).toLocaleTimeString("en-GB") : ""}</span>
              <span dir="auto">{e.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ step cards */

function StepCard({ tone, icon, title, hint, children, id }: { tone: "seal" | "brand" | "plain"; icon: React.ReactNode; title: string; hint?: string; children: React.ReactNode; id?: string }) {
  return (
    <section id={id} className={cn("card scroll-mt-6 overflow-hidden", tone === "seal" && "border-seal-300/80", tone === "brand" && "border-brand-200")}>
      <div className={cn("flex items-start gap-3 px-5 pb-4 pt-5", tone === "seal" && "bg-gradient-to-b from-seal-50 to-transparent", tone === "brand" && "bg-gradient-to-b from-brand-50 to-transparent")}>
        <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
          tone === "seal" ? "bg-seal-100 text-seal-700" : tone === "brand" ? "bg-brand-100 text-brand-600" : "bg-slate-100 text-slate-600")}>{icon}</span>
        <div className="min-w-0">
          <h2 className="font-serif text-lg text-slate-900">{title}</h2>
          {hint && <p className="mt-0.5 text-sm leading-relaxed text-slate-500">{hint}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

function WorkingCard({ job, events }: { job: Job; events: Ev[] }) {
  const { t } = useI18n();
  const p = progressOf(job);
  const latest = [...events].reverse().slice(0, 6);
  return (
    <StepCard tone="brand" icon={<Sparkles className="h-5 w-5" />} title={job.status === "releasing" ? t("st_releasing") : t("jvAgentsTitle")}
      hint={job.status === "releasing" ? t("jvReleasing") : t("jvAgentsHint")}>
      <div className="px-5 pb-5">
        <div className="mb-4 flex gap-1" aria-hidden>
          {STEPS.map((s, i) => <span key={s} className={cn("h-1.5 flex-1 rounded-full", i < p.done ? "bg-brand-600 dark:bg-brand-500" : i === p.active ? "animate-pulse bg-brand-300" : "bg-slate-200")} />)}
        </div>
        <div className="flex items-center gap-2.5 rounded-xl bg-slate-50 px-4 py-3">
          <Loader2 className="h-4 w-4 animate-spin text-brand-500" />
          <span className="text-sm font-medium text-slate-900">{t(STEPS[p.active ?? 0])}…</span>
          <span className="ms-auto font-mono text-xs tabular-nums text-slate-500" dir="ltr">{(p.active ?? 0) + 1} / {STEPS.length}</span>
        </div>
        {latest.length > 0 && (
          <ol className="mt-4 space-y-2 border-s-2 border-slate-200 ps-4" aria-live="polite">
            {latest.map((e, i) => (
              <li key={e.id} className={cn("relative text-sm", i === 0 ? "animate-fade-in text-slate-900" : "text-slate-500", e.tone === "error" && "text-red-700")}>
                <span className={cn("absolute -start-[21px] top-1.5 h-2 w-2 rounded-full ring-4 ring-surface", i === 0 ? "bg-brand-500" : "bg-slate-300")} />
                <span dir="auto">{e.text}</span>
                {e.at && <span className="ms-2 font-mono text-[11px] text-slate-400" dir="ltr">{new Date(e.at).toLocaleTimeString("en-GB")}</span>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </StepCard>
  );
}

function GlossaryStep({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const { t } = useI18n();
  const [items, setItems] = useState<GlossaryItem[] | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.glossary(jobId).then((g) => setItems(g.items)).catch(() => setItems([])); }, [jobId]);
  const set = (i: number, k: keyof GlossaryItem, v: string) => setItems((x) => x!.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const remembered = items?.filter((r) => r.remembered).length ?? 0;
  const visible = useMemo(() => (items ?? []).map((r, i) => ({ r, i })).filter(({ r }) => !q || `${r.source} ${r.target}`.toLowerCase().includes(q.toLowerCase())), [items, q]);
  const confirm = () => {
    setBusy(true);
    api.confirmGlossary(jobId, items!).then(() => { toast.success(t("ev_glossary_confirmed")); onDone(); })
      .catch((e) => toast.error(e.message)).finally(() => setBusy(false));
  };
  return (
    <StepCard id="glossary" tone="seal" icon={<BookOpenText className="h-5 w-5" />} title={t("waitingGlossary")} hint={t("glossaryHint")}>
      {items === null ? <div className="space-y-2 px-5 pb-5">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-10" />)}</div> : (
        <>
          <div className="flex flex-wrap items-center gap-3 border-y border-slate-200/70 bg-slate-50/60 px-5 py-2.5">
            <span className="text-sm font-medium text-slate-700">{t("jvTermsN", { n: items.length })}</span>
            {remembered > 0 && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">{t("jvFromMemoryN", { n: remembered })}</span>}
            {items.length > 8 && (
              <label className="relative ms-auto w-full sm:w-56">
                <Search className="pointer-events-none absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input className="input py-1.5 ps-8 text-[13px]" placeholder={t("jvFilterTerms")} value={q} onChange={(e) => setQ(e.target.value)} dir="auto" />
              </label>
            )}
          </div>
          {items.length === 0 && <p className="px-5 py-6 text-sm text-slate-500">{t("emptyGlossary")}</p>}
          {items.length > 0 && (
            <div className="divide-y divide-slate-100">
              <div className="hidden grid-cols-[1fr_1fr_8.5rem_2.25rem] gap-3 px-5 py-2 text-[11px] font-semibold text-slate-500 sm:grid">
                <span>{t("jvTermSource")}</span><span>{t("jvTermTarget")}</span><span>{t("jvTermKind")}</span><span />
              </div>
              {visible.map(({ r, i }) => (
                <div key={i} className="grid grid-cols-[1fr_auto] gap-2 px-5 py-2.5 sm:grid-cols-[1fr_1fr_8.5rem_2.25rem] sm:items-center sm:gap-3">
                  <input aria-label={t("jvTermSource")} className="input col-span-2 py-1.5 sm:col-span-1" dir="auto" value={r.source} onChange={(e) => set(i, "source", e.target.value)} />
                  <div className="relative col-span-2 sm:col-span-1">
                    <input aria-label={t("jvTermTarget")} className={cn("input py-1.5", r.remembered && "pe-8")} dir="auto" value={r.target} onChange={(e) => set(i, "target", e.target.value)} />
                    {r.remembered && <span title={t("fromMemory")} className="absolute end-2.5 top-1/2 -translate-y-1/2 text-emerald-600"><ShieldCheck className="h-4 w-4" /></span>}
                  </div>
                  <select aria-label={t("jvTermKind")} className="input py-1.5 text-[13px]" value={r.kind} onChange={(e) => set(i, "kind", e.target.value)}>
                    {KINDS.map((k) => <option key={k} value={k}>{t(`jk_${k}`)}</option>)}
                  </select>
                  <button className="icon-btn h-8 w-8 hover:bg-red-50 hover:text-red-600" aria-label={t("jvRemoveTerm")} title={t("jvRemoveTerm")}
                    onClick={() => setItems((x) => x!.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-200/70 bg-surface px-5 py-3">
            <button className="btn-quiet btn-sm" onClick={() => setItems((x) => [...x!, { source: "", target: "", kind: "name" }])}><Plus className="h-4 w-4" />{t("addRow")}</button>
            <button className="btn-primary ms-auto" disabled={busy} onClick={confirm}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}{t("confirmGlossary")}
            </button>
          </div>
        </>
      )}
    </StepCard>
  );
}

function ReviewStep({ job, canApprove, onDone }: { job: Job; canApprove: boolean; onDone: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const blockers = (job.documents ?? []).reduce((a, d) => a + (d.open_flags?.blocker ?? 0), 0);
  const stampName = job.stamp === "certified" ? t("certified") : t("officeStamp");
  const checks = [
    { ok: blockers === 0, label: blockers === 0 ? t("jvCheckBlockers") : t("rvApproveBlocked", { n: blockers }) },
    { ok: true, label: t("jvCheckStamp", { stamp: stampName }) },
    { ok: canApprove, label: canApprove ? t("jvCheckSigner") : t("onlySigner") },
  ];
  const ready = checks.every((c) => c.ok);
  return (
    <>
      <StepCard tone="seal" icon={<FileText className="h-5 w-5" />} title={t("jvReviewTitle")} hint={t("reviewHint")}>
        <ul className="divide-y divide-slate-100 border-t border-slate-200/70">
          {job.documents?.map((d) => {
            const flags = d.open_flags ?? {};
            const b = flags.blocker ?? 0;
            const other = Object.entries(flags).filter(([k]) => k !== "blocker").reduce((a, [, n]) => a + n, 0);
            return (
              <li key={d.key} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <span className="flex h-9 w-7 shrink-0 items-center justify-center rounded-[3px] bg-white font-mono text-[9px] text-slate-400 shadow-sm ring-1 ring-slate-200" dir="ltr">{d.key}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-900"><bdi>{d.title}</bdi></div>
                  <div className="mt-0.5 flex flex-wrap gap-1.5 text-xs">
                    {b > 0 && <span className="flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-red-700"><OctagonAlert className="h-3 w-3" />{t("jvBlockersN", { n: b })}</span>}
                    {other > 0 && <span className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-amber-800"><AlertTriangle className="h-3 w-3" />{t("jvWarningsN", { n: other })}</span>}
                    {b === 0 && other === 0 && <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700"><Check className="h-3 w-3" />{t("jvChecked")}</span>}
                  </div>
                </div>
                <Link to={`/jobs/${job.id}/review/${d.key}`} className={cn(b > 0 || other > 0 ? "btn-primary" : "btn-ghost", "btn-sm")}>
                  {t("rvOpenEditor")}<ArrowRight className="h-3.5 w-3.5 rtl:-scale-x-100" />
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="border-t border-slate-200/70 bg-slate-50/60 px-5 py-4">
          <h3 className="mb-2.5 flex items-center gap-2 text-sm font-medium text-slate-900"><Stamp className="h-4 w-4 text-seal-600" />{t("jvApproveTitle")}</h3>
          <ul className="mb-4 space-y-1.5">
            {checks.map((c, i) => (
              <li key={i} className={cn("flex items-center gap-2 text-[13px]", c.ok ? "text-slate-700" : "text-red-700")}>
                <span className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded-full", c.ok ? "bg-emerald-500 text-white" : "bg-red-100 text-red-600")}>
                  {c.ok ? <Check className="h-3 w-3" strokeWidth={3} /> : <X className="h-3 w-3" strokeWidth={3} />}
                </span>{c.label}
              </li>
            ))}
          </ul>
          <button className="btn-seal w-full sm:w-auto" disabled={!ready} onClick={() => setOpen(true)}><Stamp className="h-4 w-4" />{t("jvApproveBtn")}</button>
        </div>
        <details className="group border-t border-slate-200/70">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 text-sm text-slate-600 hover:text-slate-900">
            <ChevronDown className="h-4 w-4 transition group-open:rotate-180" />{t("jvPreviewTitle")}
          </summary>
          <div className="space-y-4 px-5 pb-5">{job.documents?.map((d) => <Preview key={d.key} jobId={job.id} docKey={d.key} title={d.title} />)}</div>
        </details>
      </StepCard>
      <ApproveDialog open={open} onOpenChange={setOpen} job={job} stampName={stampName} onDone={onDone} />
    </>
  );
}

function ApproveDialog({ open, onOpenChange, job, stampName, onDone }: { open: boolean; onOpenChange: (v: boolean) => void; job: Job; stampName: string; onDone: () => void }) {
  const { t, dir } = useI18n();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const approve = () => {
    setBusy(true);
    api.approve(job.id, note || undefined)
      .then(() => { onOpenChange(false); toast.success(t("st_releasing")); onDone(); })
      .catch((e) => toast.error(e.message)).finally(() => setBusy(false));
  };
  return (
    <Dialog.Root open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] animate-fade-in" />
        <Dialog.Content dir={dir} aria-describedby="apc-text"
          className="fixed inset-x-3 top-[10vh] z-50 mx-auto max-w-lg overflow-hidden rounded-2xl border border-seal-200 bg-raised shadow-float animate-fade-in focus:outline-none">
          <div className="flex flex-col items-center bg-gradient-to-b from-seal-50 to-transparent px-6 pb-2 pt-7 text-center">
            <SealRing progress={{ done: 7, active: null, tone: "done" }} size={64} label={false} />
            <Dialog.Title className="mt-4 font-serif text-xl text-slate-900">{t("apConfirmTitle")}</Dialog.Title>
          </div>
          <div className="space-y-4 px-6 pb-6 pt-3">
            <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200 text-sm">
              <div className="flex items-center gap-3 px-4 py-2.5"><dt className="w-24 shrink-0 text-slate-500">{t("stamp")}</dt><dd className="font-medium text-slate-900">{stampName}</dd></div>
              <div className="flex gap-3 px-4 py-2.5"><dt className="w-24 shrink-0 text-slate-500">{t("documents")}</dt>
                <dd className="min-w-0 flex-1 space-y-1">
                  {job.documents?.map((d) => (
                    <div key={d.key} className="flex items-center gap-2">
                      <bdi className="min-w-0 flex-1 truncate">{d.title}</bdi>
                      <a className="shrink-0 text-xs text-brand-500 hover:underline" href={`/api/jobs/${job.id}/documents/${d.key}/preview.pdf`} target="_blank" rel="noopener">{t("rvPreview")}</a>
                    </div>
                  ))}
                </dd>
              </div>
            </dl>
            <div>
              <label className="label" htmlFor="an">{t("approveNote")}</label>
              <input id="an" className="input" dir="auto" value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <p id="apc-text" className="rounded-lg bg-slate-100 px-3 py-2.5 text-[13px] leading-relaxed text-slate-700">{t("apConfirmText")}</p>
            <div className="flex justify-end gap-2">
              <Dialog.Close className="btn-quiet" disabled={busy}>{t("rvCancel")}</Dialog.Close>
              <button className="btn-seal" disabled={busy} onClick={approve}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Stamp className="h-4 w-4" />}{busy ? t("jvApproving") : t("jvApproveFinal")}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ReleasedCard({ job }: { job: Job }) {
  const { t, lang } = useI18n();
  const when = job.approved_at ? new Date(job.approved_at).toLocaleString(lang === "ar" ? "ar-AE" : "en-GB", { dateStyle: "long", timeStyle: "short" }) : "";
  return (
    <section className="card overflow-hidden border-seal-300/80">
      <div className="relative flex flex-col items-center bg-gradient-to-b from-seal-50 via-seal-50/40 to-transparent px-6 pb-6 pt-8 text-center">
        <SealRing progress={{ done: 7, active: null, tone: "done" }} size={76} label={false} className="drop-shadow-sm" />
        <h2 className="mt-4 font-serif text-2xl text-slate-900">{t("jvCertified")}</h2>
        {when && <p className="mt-1 text-sm text-slate-500">{t("jvReleasedOn", { date: when })}</p>}
      </div>
      {job.files && job.files.length > 0 && <div className="px-5 pb-5"><FileGrid job={job} /></div>}
    </section>
  );
}

function Files({ job }: { job: Job }) {
  const { t } = useI18n();
  return (
    <section className="card p-5">
      <h2 className="mb-3 font-medium text-slate-900">{t("jvDownloads")}</h2>
      <FileGrid job={job} />
    </section>
  );
}

const FILE_ICON: Record<string, [React.ReactNode, string, string]> = {
  pdf: [<FileText key="p" className="h-5 w-5" />, "bg-red-50 text-red-600", "jvKindPdf"],
  docx: [<FileType2 key="d" className="h-5 w-5" />, "bg-blue-50 text-blue-600", "jvKindDocx"],
  zip: [<FileArchive key="z" className="h-5 w-5" />, "bg-slate-100 text-slate-600", "jvKindZip"],
};
function FileGrid({ job }: { job: Job }) {
  const { t } = useI18n();
  const order = (f: JobFile) => ({ pdf: 0, docx: 1, zip: 2 } as Record<string, number>)[f.kind] ?? 3;
  return (
    <ul className="grid gap-2.5 sm:grid-cols-2">
      {[...job.files!].sort((a, b) => order(a) - order(b)).map((f) => {
        const [icon, tone, label] = FILE_ICON[f.kind] ?? [<FileText key="o" className="h-5 w-5" />, "bg-slate-100 text-slate-500", "jvKindTxt"];
        return (
          <li key={f.name}>
            <a href={`/api/jobs/${job.id}/files/${encodeURIComponent(f.name)}`} download
              className="group flex items-center gap-3 rounded-xl border border-slate-200 bg-surface p-3 transition hover:border-brand-300 hover:shadow-paper">
              <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", tone)}>{icon}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-slate-900">{f.name === "disclosures.txt" ? t("disclosures") : t(label)}</span>
                <span className="block truncate text-xs text-slate-500" dir="ltr">{f.name} · {(f.size / 1024).toFixed(0)} KB</span>
              </span>
              <Download className="h-4 w-4 shrink-0 text-slate-400 transition group-hover:text-brand-500" aria-label={t("jvDownload")} />
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function Preview({ jobId, docKey, title }: { jobId: string; docKey: string; title: string }) {
  const { t } = useI18n();
  const [model, setModel] = useState<DocModel | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => { api.documentModel(jobId, docKey).then((m) => setModel(m.model)).catch(() => {}); }, [jobId, docKey]);
  if (!model) return <div className="skeleton h-24" />;
  const rtl = ["ar", "fa", "ur", "he"].includes(model.target_language);
  const blocks = all ? model.blocks : model.blocks.slice(0, 12);
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white text-slate-900 shadow-paper dark:bg-slate-100">
      <div className="border-b border-slate-200 px-4 py-2 text-xs text-slate-500"><span className="font-mono" dir="ltr">{docKey}</span> · <bdi>{title}</bdi></div>
      <div className="space-y-2 px-6 py-5 text-sm leading-relaxed" dir={rtl ? "rtl" : "ltr"}>
        {blocks.map((b) => {
          const open = (b.flags || []).filter((f) => !f.resolved);
          const blocker = open.some((f) => f.severity === "blocker");
          const text = b.rows?.length ? b.rows.map((r) => r.cells.map((c) => c.translated_text).join(" | ")).join("\n")
            : b.type === "note" ? `// ${b.translated_text} //` : `${b.label ? b.label + " " : ""}${b.translated_text ?? ""}`;
          return (
            <div key={b.id} className={cn("whitespace-pre-wrap rounded px-2 py-1", blocker ? "bg-red-50 ring-1 ring-red-200" : open.length ? "bg-amber-50" : "", b.type === "heading" && "font-semibold", b.type === "note" && "italic text-brand-600")}
              title={open.map((f) => `${f.severity}: ${f.message}`).join("\n")}>{text}</div>
          );
        })}
      </div>
      {model.blocks.length > 12 && <button className="w-full border-t border-slate-200 py-1.5 text-xs text-brand-500 hover:bg-slate-50" onClick={() => setAll(!all)}>{all ? t("showLess") : `${t("showMore")} (${model.blocks.length})`}</button>}
    </div>
  );
}

function JobSkeleton() {
  return (
    <div aria-hidden>
      <div className="skeleton mb-6 h-4 w-20" />
      <div className="mb-8 flex items-center gap-4"><div className="skeleton h-14 w-14 rounded-full" /><div className="space-y-2"><div className="skeleton h-6 w-64" /><div className="skeleton h-4 w-40" /></div></div>
      <div className="grid gap-8 lg:grid-cols-[1fr_18rem]"><div className="skeleton h-72 rounded-xl" /><div className="space-y-3">{[0, 1, 2, 3, 4, 5, 6].map((i) => <div key={i} className="skeleton h-5" />)}</div></div>
    </div>
  );
}
