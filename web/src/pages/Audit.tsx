import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AuditRecord } from "../api";
import { useI18n } from "../i18n";

// Audit log of one job: who (person or agent) did what, when. Never shows document text.

type Filter = "all" | "people" | "agents";
const isPerson = (r: AuditRecord) => !!r.by && r.kind !== "llm_call";

export default function Audit() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const [recs, setRecs] = useState<AuditRecord[] | null>(null);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const load = () => { setErr(""); api.audit(id).then((r) => setRecs(r.records)).catch((e) => setErr(e.message)); };
  useEffect(load, [id]);

  const shown = useMemo(() => (recs ?? []).filter((r) =>
    filter === "all" ? true : filter === "people" ? isPerson(r) : !isPerson(r)), [recs, filter]);
  const calls = (recs ?? []).filter((r) => r.kind === "llm_call");
  const cost = calls.reduce((a, r) => a + (r.cost_usd ?? 0), 0);
  // one numeric format in both languages (inside an LTR cell), so Arabic layout cannot scramble it
  const fmt = (at?: string) => (at ? new Date(at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "medium", hour12: false }) : "");

  const what = (r: AuditRecord) => {
    const v: Record<string, string | number> = {
      agent: r.agent ? t(`agent_${r.agent}`) : "", stage: r.stage ? t(`sd_${r.stage}`) : "", status: r.status ? t(`st_${r.status}`) : "",
      n: Array.isArray(r.blocks) ? r.blocks.length : (r.blocks ?? 0), action: r.action ? t(`au_act_${r.action}`) : "",
    };
    return t(`au_${r.kind}`, v);
  };

  return (
    <div className="space-y-4">
      <Link to={`/jobs/${id}`} className="text-sm text-brand-500 hover:underline"><span className="inline-block rtl:rotate-180">←</span> {t("rvBackToJob")}</Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900">{t("auTitle")}</h1>
        <span className="font-mono text-xs text-slate-500" dir="ltr">{id}</span>
      </div>
      <p className="text-sm text-slate-600">{t("auHint")}</p>

      {err && (
        <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span className="flex-1">{t("auLoadError")}</span><button className="btn-ghost" onClick={load}>{t("retry")}</button>
        </div>
      )}
      {!recs && !err && <div className="text-slate-500">…</div>}
      {recs && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {(["all", "people", "agents"] as Filter[]).map((f) => (
              <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
                className={`rounded-full px-3 py-1 text-sm ${filter === f ? "bg-brand-600 text-white" : "bg-surface text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50"}`}>{t(`auF_${f}`)}</button>
            ))}
            <span className="ms-auto text-sm text-slate-600">
              {t("auCalls", { n: calls.length })} · <span className="font-mono" dir="ltr">${cost.toFixed(3)}</span>
            </span>
          </div>
          {shown.length === 0 ? <p className="card p-5 text-sm text-slate-500">{t("auEmpty")}</p> : (
            <div className="card overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-600">
                  <tr>
                    <th className="px-3 py-2 text-start font-medium">{t("auWhen")}</th>
                    <th className="px-3 py-2 text-start font-medium">{t("auWho")}</th>
                    <th className="px-3 py-2 text-start font-medium">{t("auWhat")}</th>
                    <th className="px-3 py-2 text-start font-medium">{t("auDetails")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {shown.map((r, i) => {
                    const person = isPerson(r);
                    const bad = r.kind === "llm_error" || (r.kind === "status" && (r.status === "failed" || r.error));
                    return (
                      <tr key={i} className={bad ? "bg-red-50" : ""}>
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-600" dir="ltr">{fmt(r.at)}</td>
                        <td className="whitespace-nowrap px-3 py-2">
                          <span className={`rounded px-1.5 py-0.5 text-xs ${person ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-700"}`}>
                            {person ? <bdi>{r.by}</bdi> : r.agent ? t(`agent_${r.agent}`) : t("auSystem")}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-slate-900">{what(r)}</td>
                        <td className="px-3 py-2 text-xs text-slate-600">
                          <span className="flex flex-wrap gap-x-3 gap-y-0.5" dir="ltr">
                            {r.document && <span className="font-mono">{r.document}</span>}
                            {r.block && <span className="font-mono">{r.block}</span>}
                            {Array.isArray(r.blocks) && r.blocks.length > 0 && r.blocks.length <= 6 && <span className="font-mono">{r.blocks.join(", ")}</span>}
                            {r.model && <span>{r.model}{r.prompt_version ? ` · ${r.prompt_version}` : ""}</span>}
                            {r.usage && <span>{(r.usage.input_tokens ?? 0).toLocaleString("en")} → {(r.usage.output_tokens ?? 0).toLocaleString("en")} tok</span>}
                            {r.cost_usd != null && r.kind === "llm_call" && <span>${r.cost_usd.toFixed(4)}</span>}
                            {r.latency_s != null && <span>{r.latency_s}s</span>}
                            {r.pdf && <span>{r.pdf}</span>}
                          </span>
                          {r.error && <span className="mt-1 block text-red-700" dir="auto">{r.error}</span>}
                          {r.note && <span className="mt-1 block" dir="auto">{r.note}</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
