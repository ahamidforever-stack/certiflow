import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Cpu, RotateCw, Sparkles, UserRound } from "lucide-react";
import { api, type AuditRecord } from "../api";
import { useI18n } from "../i18n";
import { STEPS } from "../lib/jobs";
import { cn } from "../lib/cn";

// Audit log of one job as a timeline, grouped by the step it belongs to. Never shows document text.

type Filter = "all" | "people" | "agents";
const isPerson = (r: AuditRecord) => !!r.by && r.kind !== "llm_call";

const AGENT_STEP: Record<string, number> = { intake: 0, intake_zoom: 0, glossary: 1, translator: 2, proofreader: 3, qa: 4, formatter: 4 };
const STAGE_STEP: Record<string, number> = { intake: 0, translate: 2, translated: 2, proofread: 3, qa_format: 4, qa: 4, formatted: 4 };

/** Walk the records in order and give each the journey step it happened in. After review starts, agent re-runs stay in Review. */
function withSteps(recs: AuditRecord[]) {
  let step = 0, reviewing = false;
  return recs.map((r) => {
    if (r.kind === "status") {
      if (r.status === "waiting_glossary") step = 1;
      else if (r.status === "waiting_review") { step = 5; reviewing = true; }
      else if (r.status === "releasing" || r.status === "released") step = 6;
    } else if (r.kind === "approved" || r.kind === "released") step = 6;
    else if (r.kind === "glossary_confirmed" || r.kind === "glossary_memory") step = 1;
    else if (["review_edit", "review_change", "review_flag", "rerun_started", "rerun_done", "preview_built", "assist"].includes(r.kind)) { step = 5; reviewing = true; }
    else if (!reviewing && (r.kind === "llm_call" || r.kind === "llm_error") && r.agent && AGENT_STEP[r.agent] != null) step = AGENT_STEP[r.agent];
    else if (!reviewing && r.kind === "stage_done" && r.stage && STAGE_STEP[r.stage] != null) step = STAGE_STEP[r.stage];
    else if (!reviewing && r.kind === "qa_loop") step = 4;
    return { r, step };
  });
}

export default function Audit() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const [recs, setRecs] = useState<AuditRecord[] | null>(null);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const load = () => { setErr(""); api.audit(id).then((r) => setRecs(r.records)).catch((e) => setErr(e.message)); };
  useEffect(load, [id]);

  const groups = useMemo(() => {
    const out: { step: number; items: AuditRecord[]; all: AuditRecord[] }[] = [];
    for (const { r, step } of withSteps(recs ?? [])) {
      let g = out[out.length - 1];
      if (!g || g.step !== step) { g = { step, items: [], all: [] }; out.push(g); }
      g.all.push(r);
      if (filter === "all" || (filter === "people" ? isPerson(r) : !isPerson(r))) g.items.push(r);
    }
    return out.filter((g) => g.items.length);
  }, [recs, filter]);
  const calls = (recs ?? []).filter((r) => r.kind === "llm_call");
  const cost = calls.reduce((a, r) => a + (r.cost_usd ?? 0), 0);
  // one numeric format in both languages, so Arabic layout cannot scramble it
  const time = (at?: string) => (at ? new Date(at).toLocaleTimeString("en-GB", { hour12: false }) : "");
  const day = (at?: string) => (at ? new Date(at).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");

  const what = (r: AuditRecord) => {
    const v: Record<string, string | number> = {
      agent: r.agent ? t(`agent_${r.agent}`) : "", stage: r.stage ? t(`sd_${r.stage}`) : "", status: r.status ? t(`st_${r.status}`) : "",
      n: Array.isArray(r.blocks) ? r.blocks.length : (r.blocks ?? 0), action: r.action ? t(`au_act_${r.action}`) : "",
    };
    return t(`au_${r.kind}`, v);
  };

  return (
    <div className="mx-auto max-w-4xl animate-fade-in">
      <Link to={`/jobs/${id}`} className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4 rtl:-scale-x-100" />{t("rvBackToJob")}
      </Link>
      <header className="mb-6">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="page-title">{t("auTitle")}</h1>
          <span className="font-mono text-xs text-slate-500" dir="ltr">{id}</span>
        </div>
        <p className="mt-1.5 text-sm text-slate-500">{t("auHint")}</p>
      </header>

      {err && (
        <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span className="flex-1">{t("auLoadError")}</span><button className="btn-ghost btn-sm" onClick={load}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button>
        </div>
      )}
      {!recs && !err && <div className="space-y-3" aria-hidden>{[0, 1, 2].map((i) => <div key={i} className="skeleton h-24 rounded-xl" />)}</div>}
      {recs && (
        <>
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <div className="flex gap-0.5 rounded-lg bg-slate-200/60 p-0.5" role="group">
              {(["all", "people", "agents"] as Filter[]).map((f) => (
                <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
                  className={cn("rounded-md px-3 py-1 text-sm transition", filter === f ? "bg-surface font-medium text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900")}>{t(`auF_${f}`)}</button>
              ))}
            </div>
            <span className="ms-auto flex items-center gap-1.5 text-sm text-slate-600">
              <Cpu className="h-4 w-4 text-slate-400" />{t("auCalls", { n: calls.length })} · <span className="font-mono" dir="ltr">${cost.toFixed(3)}</span>
            </span>
          </div>

          {groups.length === 0 ? <p className="card p-6 text-sm text-slate-500">{t("auEmpty")}</p> : (
            <ol className="space-y-4">
              {groups.map((g, gi) => {
                const gCalls = g.all.filter((r) => r.kind === "llm_call");
                const gCost = gCalls.reduce((a, r) => a + (r.cost_usd ?? 0), 0);
                const first = g.all[0]?.at, last = g.all[g.all.length - 1]?.at;
                return (
                  <li key={gi} className="card overflow-hidden">
                    <div className="flex flex-wrap items-center gap-3 border-b border-slate-200/70 bg-slate-50/70 px-4 py-2.5">
                      <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold text-white", g.step === 6 ? "bg-seal-500" : "bg-brand-600 dark:bg-brand-500")}>{g.step + 1}</span>
                      <h2 className="text-sm font-medium text-slate-900">{t(STEPS[g.step])}</h2>
                      <span className="font-mono text-[11px] text-slate-500" dir="ltr">{day(first)} {time(first)}{last && last !== first ? ` – ${time(last)}` : ""}</span>
                      {gCalls.length > 0 && <span className="ms-auto text-xs text-slate-500">{t("auCalls", { n: gCalls.length })} · <span className="font-mono" dir="ltr">${gCost.toFixed(3)}</span></span>}
                    </div>
                    <ol className="relative px-4 py-2">
                      {g.items.map((r, i) => <Entry key={i} r={r} what={what(r)} time={time(r.at)} />)}
                    </ol>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

function Entry({ r, what, time }: { r: AuditRecord; what: string; time: string }) {
  const { t } = useI18n();
  const person = isPerson(r);
  const agent = !person && !!r.agent;
  const bad = r.kind === "llm_error" || (r.kind === "status" && (r.status === "failed" || !!r.error));
  const certify = r.kind === "approved" || r.kind === "released";
  return (
    <li className="group relative flex gap-3 py-2">
      <span className="absolute bottom-0 start-[13px] top-0 w-px bg-slate-200 group-first:top-4 group-last:bottom-auto group-last:h-4" aria-hidden />
      <span className={cn("relative z-[1] mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-4 ring-surface",
        bad ? "bg-red-100 text-red-600" : certify ? "bg-seal-100 text-seal-700" : person ? "bg-brand-600 text-white" : agent ? "bg-brand-50 text-brand-600" : "bg-slate-100 text-slate-400")}>
        {person ? <UserRound className="h-3.5 w-3.5" /> : agent ? <Sparkles className="h-3.5 w-3.5" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className={cn("text-sm", bad ? "text-red-800" : certify ? "font-medium text-slate-900" : person ? "text-slate-900" : "text-slate-600")}>{what}</span>
          <span className="text-xs text-slate-500">{person ? <bdi className="font-medium text-brand-600">{r.by}</bdi> : agent ? t(`agent_${r.agent}`) : t("auSystem")}</span>
          <span className="ms-auto font-mono text-[11px] tabular-nums text-slate-400" dir="ltr">{time}</span>
        </div>
        {(r.document || r.block || r.model || r.usage || r.pdf || (Array.isArray(r.blocks) && r.blocks.length)) && (
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500" dir="ltr">
            {r.document && <span className="font-mono">{r.document}</span>}
            {r.block && <span className="font-mono">{r.block}</span>}
            {Array.isArray(r.blocks) && r.blocks.length > 0 && r.blocks.length <= 6 && <span className="font-mono">{r.blocks.join(", ")}</span>}
            {r.model && <span>{r.model}{r.prompt_version ? ` · ${r.prompt_version}` : ""}</span>}
            {r.usage && <span>{(r.usage.input_tokens ?? 0).toLocaleString("en")} → {(r.usage.output_tokens ?? 0).toLocaleString("en")} tok</span>}
            {r.cost_usd != null && r.kind === "llm_call" && <span>${r.cost_usd.toFixed(4)}</span>}
            {r.latency_s != null && <span>{r.latency_s}s</span>}
            {r.pdf && <span>{r.pdf}</span>}
          </div>
        )}
        {r.error && <p className="mt-1 text-xs text-red-700" dir="auto">{r.error}</p>}
        {r.note && <p className="mt-1 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700" dir="auto">{r.note}</p>}
      </div>
    </li>
  );
}
