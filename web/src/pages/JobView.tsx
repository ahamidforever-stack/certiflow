import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type DocModel, type GlossaryItem, type Job } from "../api";
import { useAuth } from "../App";
import { LangPair, StatusChip } from "../components/Status";
import { useI18n } from "../i18n";

const STAGES = ["intake", "translated", "proofread", "qa", "formatted"];
interface Ev { id: number; text: string; at?: string; tone?: "error" | "ok" }

export default function JobView() {
  const { id = "" } = useParams();
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const seq = useRef(0);

  const load = useCallback(() => api.job(id).then(setJob).catch(() => {}), [id]);
  useEffect(() => { load(); }, [load]);

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
    es.addEventListener("status", () => load());
    es.addEventListener("end", () => { load(); es.close(); });
    return () => es.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, lang]);

  if (!job) return <div className="text-slate-400">…</div>;
  const isSigner = user?.role === "admin" || user?.role === "certified_translator";

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-brand-500 hover:underline">← {t("back")}</Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900" dir="auto">{job.title}</h1>
          <StatusChip status={job.status} />
          <span className="font-mono text-xs text-slate-400" dir="ltr">{job.id}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-4 text-sm text-slate-600">
          <LangPair s={job.source_language} t={job.target_language} />
          <span>{job.stamp === "certified" ? t("certified") : t("officeStamp")}</span>
          {job.document_type && <span dir="auto">{job.document_type}</span>}
          <span className="font-mono text-xs" dir="ltr">${job.cost_usd.toFixed(2)}</span>
        </div>
      </div>

      {job.error && (
        <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span className="flex-1" dir="auto">{job.error}</span>
          {job.status === "failed" && <button className="btn-ghost" onClick={() => api.retry(job.id).then(load)}>{t("retry")}</button>}
        </div>
      )}

      {job.status === "waiting_glossary" && <GlossaryPanel jobId={job.id} onDone={load} />}
      {job.status === "waiting_review" && <ReviewPanel job={job} canApprove={isSigner} onDone={load} />}
      {job.files && job.files.length > 0 && <FilesPanel job={job} />}

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card p-5 lg:col-span-2">
          <h2 className="mb-3 font-semibold text-slate-900">{t("documents")}</h2>
          <ul className="space-y-4">
            {job.documents?.map((d) => {
              const at = STAGES.indexOf(d.stage ?? "");
              return (
                <li key={d.key}>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono text-xs text-slate-400">{d.key}</span>
                    <span className="font-medium text-slate-800" dir="auto">{d.title}</span>
                    <LangPair s={d.source_language} t={d.target_language} />
                    {d.open_flags && Object.keys(d.open_flags).length > 0 && (
                      <span className="ms-auto text-xs text-amber-700">
                        {Object.values(d.open_flags).reduce((a, b) => a + b, 0)} {t("openFlags")}
                        {d.open_flags.blocker ? ` · ${d.open_flags.blocker} ${t("blockers")}` : ""}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex gap-1">
                    {STAGES.map((s, i) => (
                      <div key={s} className="flex-1">
                        <div className={`h-1.5 rounded-full ${i <= at ? "bg-brand-500" : "bg-slate-200"}`} />
                        <div className={`mt-1 text-[11px] ${i <= at ? "text-brand-600" : "text-slate-400"}`}>{t(`stage_${s}`)}</div>
                      </div>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
          {job.cost_by_agent && Object.keys(job.cost_by_agent).length > 0 && (
            <div className="mt-6">
              <h3 className="mb-2 text-sm font-semibold text-slate-700">{t("costByAgent")}</h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {Object.entries(job.cost_by_agent).map(([a, c]) => (
                  <div key={a} className="rounded-lg bg-slate-50 px-3 py-2 text-xs">
                    <div className="text-slate-600">{t(`agent_${a}`)}</div>
                    <div className="font-mono text-slate-900" dir="ltr">${c.cost_usd.toFixed(3)} · {c.calls}×</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
        <section className="card p-5">
          <h2 className="mb-3 font-semibold text-slate-900">{t("progress")}</h2>
          <ol className="max-h-96 space-y-1.5 overflow-y-auto text-xs">
            {events.length === 0 && <li className="text-slate-400">…</li>}
            {[...events].reverse().map((e) => (
              <li key={e.id} className={`flex gap-2 ${e.tone === "error" ? "text-red-700" : e.tone === "ok" ? "text-emerald-700" : "text-slate-600"}`}>
                <span className="shrink-0 font-mono text-slate-400" dir="ltr">{e.at ? new Date(e.at).toLocaleTimeString("en-GB") : ""}</span>
                <span dir="auto">{e.text}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

function GlossaryPanel({ jobId, onDone }: { jobId: string; onDone: () => void }) {
  const { t } = useI18n();
  const [items, setItems] = useState<GlossaryItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.glossary(jobId).then((g) => setItems(g.items)); }, [jobId]);
  if (!items) return null;
  const set = (i: number, k: keyof GlossaryItem, v: string) => setItems((x) => x!.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <section className="card border-amber-300 p-5">
      <h2 className="font-semibold text-slate-900">{t("waitingGlossary")}</h2>
      <p className="mb-4 mt-1 text-sm text-slate-600">{t("glossaryHint")}</p>
      {items.length === 0 && <p className="mb-3 text-sm text-slate-500">{t("emptyGlossary")}</p>}
      {items.length > 0 && (
        <table className="mb-3 w-full text-sm">
          <thead className="text-xs uppercase text-slate-500"><tr><th className="py-1 text-start">{t("source")}</th><th className="py-1 text-start">{t("target")}</th><th className="py-1 text-start">{t("kind")}</th><th /></tr></thead>
          <tbody>
            {items.map((r, i) => (
              <tr key={i}>
                <td className="py-1 pe-2"><input className="input" dir="auto" value={r.source} onChange={(e) => set(i, "source", e.target.value)} /></td>
                <td className="py-1 pe-2"><input className="input" dir="auto" value={r.target} onChange={(e) => set(i, "target", e.target.value)} /></td>
                <td className="py-1 pe-2"><select className="input" value={r.kind} onChange={(e) => set(i, "kind", e.target.value)}>{["name", "organisation", "place", "acronym", "term"].map((k) => <option key={k}>{k}</option>)}</select></td>
                <td className="py-1"><button className="text-xs text-red-600 hover:underline" onClick={() => setItems((x) => x!.filter((_, j) => j !== i))}>{t("remove")}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex gap-2">
        <button className="btn-ghost" onClick={() => setItems((x) => [...x!, { source: "", target: "", kind: "name" }])}>+ {t("addRow")}</button>
        <button className="btn-primary ms-auto" disabled={busy} onClick={() => { setBusy(true); api.confirmGlossary(jobId, items).then(onDone).finally(() => setBusy(false)); }}>{t("confirmGlossary")}</button>
      </div>
    </section>
  );
}

function ReviewPanel({ job, canApprove, onDone }: { job: Job; canApprove: boolean; onDone: () => void }) {
  const { t } = useI18n();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  return (
    <section className="card border-violet-300 p-5">
      <h2 className="font-semibold text-slate-900">{t("waitingReview")}</h2>
      <p className="mb-4 mt-1 text-sm text-slate-600">{t("reviewHint")}</p>
      <div className="space-y-4">{job.documents?.map((d) => <Preview key={d.key} jobId={job.id} docKey={d.key} title={d.title} />)}</div>
      <p className="mt-3 text-xs text-slate-500">{t("editorSoon")}</p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1"><label className="label" htmlFor="an">{t("approveNote")}</label><input id="an" className="input" value={note} onChange={(e) => setNote(e.target.value)} /></div>
        <button className="btn-primary" disabled={!canApprove || busy}
          onClick={() => { setBusy(true); setErr(""); api.approve(job.id, note || undefined).then(onDone).catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>
          ✓ {t("approve")}
        </button>
      </div>
      {!canApprove && <p className="mt-2 text-xs text-slate-500">{t("onlySigner")}</p>}
      {err && <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</p>}
    </section>
  );
}

function Preview({ jobId, docKey, title }: { jobId: string; docKey: string; title: string }) {
  const { t } = useI18n();
  const [model, setModel] = useState<DocModel | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => { api.documentModel(jobId, docKey).then((m) => setModel(m.model)).catch(() => {}); }, [jobId, docKey]);
  if (!model) return <div className="text-sm text-slate-400">{t("noPreview")}</div>;
  const rtl = ["ar", "fa", "ur", "he"].includes(model.target_language);
  const blocks = all ? model.blocks : model.blocks.slice(0, 12);
  return (
    <div className="rounded-lg border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-700"><span className="font-mono text-xs text-slate-400">{docKey}</span> <span dir="auto">{title}</span> · {t("translation")}</div>
      <div className="space-y-2 px-4 py-3 text-sm leading-relaxed" dir={rtl ? "rtl" : "ltr"}>
        {blocks.map((b) => {
          const open = (b.flags || []).filter((f) => !f.resolved);
          const blocker = open.some((f) => f.severity === "blocker");
          const text = b.rows?.length ? b.rows.map((r) => r.cells.map((c) => c.translated_text).join(" | ")).join("\n")
            : b.type === "note" ? `// ${b.translated_text} //` : `${b.label ? b.label + " " : ""}${b.translated_text ?? ""}`;
          return (
            <div key={b.id} className={`whitespace-pre-wrap rounded px-2 py-1 ${blocker ? "bg-red-50 ring-1 ring-red-200" : open.length ? "bg-amber-50" : ""} ${b.type === "heading" ? "font-semibold" : ""} ${b.type === "note" ? "italic text-brand-600" : ""}`}
              title={open.map((f) => `${f.severity}: ${f.message}`).join("\n")}>
              {text}
            </div>
          );
        })}
      </div>
      {model.blocks.length > 12 && <button className="w-full border-t border-slate-200 py-1.5 text-xs text-brand-500 hover:bg-slate-50" onClick={() => setAll(!all)}>{all ? t("showLess") : `${t("showMore")} (${model.blocks.length})`}</button>}
    </div>
  );
}

function FilesPanel({ job }: { job: Job }) {
  const { t } = useI18n();
  return (
    <section className="card border-emerald-300 p-5">
      <h2 className="mb-3 font-semibold text-slate-900">{t("files")}</h2>
      <ul className="grid gap-2 sm:grid-cols-2">
        {job.files!.map((f) => (
          <li key={f.name}>
            <a href={`/api/jobs/${job.id}/files/${encodeURIComponent(f.name)}`} download
              className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:border-brand-500 hover:bg-brand-50">
              <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-white ${f.kind === "pdf" ? "bg-red-600" : f.kind === "docx" ? "bg-blue-600" : f.kind === "zip" ? "bg-slate-600" : "bg-slate-400"}`}>{f.kind}</span>
              <span className="truncate" dir="ltr">{f.name === "disclosures.txt" ? t("disclosures") : f.name}</span>
              <span className="ms-auto text-xs text-slate-400">{(f.size / 1024).toFixed(0)} KB</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
