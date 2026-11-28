import { useEffect, useState } from "react";
import { api, type AgentConf, type ModelSettings } from "../api";
import { useI18n } from "../i18n";
import { Sym } from "../components/Sym";
import { Check, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { cn } from "../lib/cn";

// Admin: model, effort and prompt version per pipeline step (overlay on config/agents.json), plus two pipeline knobs.

function AgentRow({ name, a, data, onSaved }: { name: string; a: ModelSettings["agents"][string]; data: ModelSettings;
  onSaved: (d: ModelSettings, msg: string) => void }) {
  const { t } = useI18n();
  const [f, setF] = useState<AgentConf>({ model: a.model, effort: a.effort, prompt_version: a.prompt_version, max_tokens: a.max_tokens });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => setF({ model: a.model, effort: a.effort, prompt_version: a.prompt_version, max_tokens: a.max_tokens }), [a]);
  const dirty = f.model !== a.model || f.effort !== a.effort || f.prompt_version !== a.prompt_version || f.max_tokens !== a.max_tokens;
  const price = data.models.find((m) => m.model === f.model);
  const run = async (fn: () => Promise<ModelSettings>, msg: string) => {
    setBusy(true); setErr("");
    try { onSaved(await fn(), msg); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const id = `m-${name}`;
  const lab = "mb-1 block text-[11px] font-medium text-slate-500 lg:sr-only";
  return (
    <li className={cn("px-4 py-3 transition", dirty && "bg-seal-50/60")}>
      <div className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,13rem)_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_6.5rem_auto]">
        <div className="min-w-0 sm:col-span-2 lg:col-span-1 lg:pt-1.5">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-slate-900">{t(`agent_${name}`)}</span>
            {a.overridden.length > 0 && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-seal-500" title={t("moChanged")} />}
          </div>
          <span className="font-mono text-[11px] text-slate-400" dir="ltr">{name}</span>
        </div>
        <div>
          <label className={lab} htmlFor={id + "-model"}>{t("moModel")}</label>
          <select id={id + "-model"} className="input py-1.5 text-[13px]" dir="ltr" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })}>
            {data.models.map((m) => <option key={m.model} value={m.model}>{m.model}</option>)}
          </select>
          {price && <p className="mt-1 text-[11px] text-slate-500">{t("moPrice", { in: price.input, out: price.output })}</p>}
        </div>
        <div>
          <label className={lab} htmlFor={id + "-effort"}>{t("moEffort")}</label>
          <select id={id + "-effort"} className="input py-1.5 text-[13px]" value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>
            {data.efforts.map((x) => <option key={x} value={x}>{t(`effort_${x}`)}</option>)}
          </select>
        </div>
        <div>
          <label className={lab} htmlFor={id + "-prompt"}>{t("moPrompt")}</label>
          <select id={id + "-prompt"} className="input py-1.5 text-[13px]" dir="ltr" value={f.prompt_version} onChange={(e) => setF({ ...f, prompt_version: e.target.value })}>
            {a.prompt_versions.map((v) => <option key={v} value={v}>{v}{v === a.default.prompt_version ? ` (${t("moDefault")})` : ""}</option>)}
          </select>
        </div>
        <div>
          <label className={lab} htmlFor={id + "-tok"}>{t("moMaxTokens")}</label>
          <input id={id + "-tok"} type="number" min={1000} max={128000} step={1000} className="input py-1.5 text-[13px]" dir="ltr"
            value={f.max_tokens} onChange={(e) => setF({ ...f, max_tokens: Number(e.target.value) })} />
        </div>
        <div className="flex items-center gap-1 sm:col-span-2 lg:col-span-1 lg:justify-end">
          {dirty && <button className="btn-primary btn-sm" disabled={busy} onClick={() => run(() => api.adminSetAgent(name, f), t("moSaved"))}><Check className="h-3.5 w-3.5" />{t("moSave")}</button>}
          {a.overridden.length > 0 && (
            <button className="icon-btn h-8 w-8" disabled={busy} onClick={() => run(() => api.adminResetAgent(name), t("moSaved"))}
              title={`${t("moReset")} (${a.default.model}, ${a.default.prompt_version})`} aria-label={t("moReset")}><RotateCcw className="h-4 w-4" /></button>
          )}
        </div>
      </div>
      {f.prompt_version !== a.default.prompt_version && <p className="mt-2 text-xs text-amber-800"><Sym k="warn" />{t("moPromptWarn")}</p>}
      {err && <div role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
    </li>
  );
}

export default function Models() {
  const { t } = useI18n();
  const [data, setData] = useState<ModelSettings | null>(null);
  const [err, setErr] = useState("");
  const [pipe, setPipe] = useState<Record<string, number>>({});
  const load = () => { setErr(""); api.adminSettings().then((d) => { setData(d); setPipe(d.pipeline); }).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const saved = (d: ModelSettings, m: string) => { setData(d); setPipe(d.pipeline); toast.success(m); };
  const pipeDirty = data && Object.keys(pipe).some((k) => pipe[k] !== data.pipeline[k]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-serif text-xl font-medium text-slate-900">{t("moTitle")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("moHint")}</p>
      </div>
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"><Sym k="warn" />{t("moCostWarn")}</div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>}
      {!data && !err && <div className="space-y-2" aria-hidden>{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-14 rounded-xl" />)}</div>}
      {data && (
        <>
          <section className="card overflow-hidden">
            <div className="hidden grid-cols-[minmax(0,13rem)_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_6.5rem_auto] gap-3 border-b border-slate-200/80 bg-slate-50/70 px-4 py-2 text-[11px] font-semibold text-slate-500 lg:grid">
              <span>{t("coAgent")}</span><span>{t("moModel")}</span><span>{t("moEffort")}</span><span>{t("moPrompt")}</span><span>{t("moMaxTokens")}</span><span className="w-8" />
            </div>
            <ul className="divide-y divide-slate-100">
              {Object.entries(data.agents).map(([name, a]) => <AgentRow key={name} name={name} a={a} data={data} onSaved={saved} />)}
            </ul>
          </section>
          <section className="card p-5">
            <h2 className="font-semibold text-slate-900">{t("moPipeline")}</h2>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              {([["qa_max_loops", "moQaLoops", "moQaLoopsHint", 0, 5], ["max_parallel_documents", "moParallel", "moParallelHint", 1, 8]] as const).map(([k, label, hint, lo, hi]) => (
                <div key={k}>
                  <label className="label" htmlFor={`p-${k}`}>{t(label)} {data.pipeline_overridden.includes(k) && <span className="ms-1 text-xs font-normal text-amber-800">({t("moChanged")}; {t("moDefault")} {data.pipeline_default[k]})</span>}</label>
                  <input id={`p-${k}`} type="number" min={lo} max={hi} className="input max-w-[8rem]" dir="ltr" value={pipe[k] ?? ""}
                    onChange={(e) => setPipe({ ...pipe, [k]: Number(e.target.value) })} />
                  <p className="mt-1 text-xs text-slate-500">{t(hint)}</p>
                </div>
              ))}
            </div>
            <button className="btn-primary mt-4" disabled={!pipeDirty}
              onClick={() => api.adminSetPipeline(pipe).then((d) => saved(d, t("moSaved"))).catch((e) => setErr(e.message))}>{t("moSave")}</button>
          </section>
        </>
      )}
    </div>
  );
}
