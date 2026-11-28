import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, RotateCw, Search, X } from "lucide-react";
import type { Job } from "../api";
import { StatusChip } from "../components/Status";
import { SealRing } from "../components/Seal";
import { useI18n } from "../i18n";
import { useJobs } from "../lib/useJobs";
import { bucketOf, jobTime, progressOf, type Bucket } from "../lib/jobs";
import { cn } from "../lib/cn";

// All jobs: search, filter by where the job is, newest first. Reads the shared, polled job list.
type Tab = "all" | Bucket;
const TABS: [Tab, string][] = [["all", "jobsFilterAll"], ["needs", "navNeedsYou"], ["progress", "navInProgress"], ["done", "jobsFilterDone"]];

export default function Jobs() {
  const { t, lang } = useI18n();
  const { jobs, error, refresh } = useJobs();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("f") as Tab) || "all";
  const q = params.get("q") ?? "";
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });

  const sorted = useMemo(() => [...(jobs ?? [])].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()), [jobs]);
  const counts = useMemo(() => {
    const c: Record<Tab, number> = { all: sorted.length, needs: 0, progress: 0, done: 0 };
    for (const j of sorted) c[bucketOf(j)]++;
    return c;
  }, [sorted]);
  const shown = useMemo(() => {
    const k = q.trim().toLocaleLowerCase();
    return sorted.filter((j) => (tab === "all" || bucketOf(j) === tab)
      && (!k || `${j.title} ${j.client ?? ""} ${j.id} ${j.document_type ?? ""}`.toLocaleLowerCase().includes(k)));
  }, [sorted, tab, q]);
  const date = (j: Job) => jobTime(j).toLocaleDateString(lang === "ar" ? "ar-AE" : "en-GB", { day: "numeric", month: "short", year: "numeric" });

  return (
    <div className="animate-fade-in">
      <header className="mb-6 flex flex-wrap items-end gap-3">
        <h1 className="page-title">{t("navAllJobs")}</h1>
        <Link to="/new" className="btn-primary btn-sm ms-auto"><Plus className="h-4 w-4" />{t("newJob")}</Link>
      </header>

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input className="input ps-9 pe-8" type="search" placeholder={t("jobsSearch")} aria-label={t("jobsSearch")} dir="auto"
            value={q} onChange={(e) => set("q", e.target.value)} />
          {q && <button className="absolute end-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:text-slate-700" aria-label={t("edClearSelection")} onClick={() => set("q", "")}><X className="h-3.5 w-3.5" /></button>}
        </label>
        <div className="-mx-4 flex gap-1 overflow-x-auto px-4 sm:mx-0 sm:ms-auto sm:px-0" role="tablist" aria-label={t("status")}>
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => set("f", k === "all" ? "" : k)}
              className={cn("flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition",
                tab === k ? "bg-surface font-medium text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-500 hover:bg-slate-200/50 hover:text-slate-800")}>
              {t(label)}
              <span className={cn("rounded-full px-1.5 text-[11px] tabular-nums", k === "needs" && counts.needs ? "bg-seal-100 text-seal-700" : "bg-slate-200/70 text-slate-600")}>{counts[k]}</span>
            </button>
          ))}
        </div>
      </div>

      {error && jobs === null ? (
        <div role="alert" className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {t("loadError")}<button className="btn-ghost btn-sm ms-auto" onClick={refresh}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button>
        </div>
      ) : jobs === null ? (
        <div className="space-y-2" aria-hidden>{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-14 rounded-xl" />)}</div>
      ) : jobs.length === 0 ? (
        <div className="card flex flex-col items-center px-6 py-14 text-center">
          <SealRing progress={{ done: 0, active: null, tone: "run" }} size={48} label={false} />
          <p className="mt-4 text-slate-600">{t("noJobs")}</p>
          <Link to="/new" className="btn-primary btn-sm mt-4"><Plus className="h-4 w-4" />{t("newJob")}</Link>
        </div>
      ) : shown.length === 0 ? (
        <p className="card px-6 py-10 text-center text-sm text-slate-500">{t("jobsNoMatch")}</p>
      ) : (
        <div className="card overflow-hidden">
          {/* header row (wide screens) */}
          <div className="hidden grid-cols-[minmax(0,1fr)_6rem_9rem_7.5rem_5rem] gap-4 border-b border-slate-200/80 bg-slate-50/70 px-4 py-2 text-[11px] font-semibold text-slate-500 md:grid">
            <span>{t("title")}</span><span>{t("pair")}</span><span>{t("status")}</span><span>{t("created")}</span><span className="text-end">{t("cost")}</span>
          </div>
          <ul className="divide-y divide-slate-100">
            {shown.map((j) => (
              <li key={j.id}>
                <Link to={`/jobs/${j.id}`}
                  className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-4 py-3 transition hover:bg-slate-50 md:grid-cols-[minmax(0,1fr)_6rem_9rem_7.5rem_5rem] md:gap-4">
                  <span className="flex min-w-0 items-center gap-3 max-md:contents">
                    <SealRing progress={progressOf(j)} size={28} />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-900"><bdi>{j.title}</bdi></span>
                      <span className="block truncate text-xs text-slate-500">
                        {j.client && <bdi>{j.client}</bdi>}<span className={cn(j.client && "max-md:hidden")}>{j.client && " · "}<bdi className="font-mono" dir="ltr">{j.id}</bdi></span>
                      </span>
                    </span>
                  </span>
                  <bdi className="hidden font-mono text-xs uppercase text-slate-600 md:block" dir="ltr">{j.source_language} → {j.target_language}</bdi>
                  <span className="max-md:col-start-3 max-md:row-start-1 md:block"><StatusChip status={j.status} /></span>
                  <span className="hidden text-xs text-slate-500 md:block">{date(j)}</span>
                  <span className="hidden text-end font-mono text-xs text-slate-600 md:block" dir="ltr">${j.cost_usd.toFixed(2)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
