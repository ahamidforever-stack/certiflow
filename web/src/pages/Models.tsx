import { useEffect, useState } from "react";
import { api, type AgentConf, type ModelSettings } from "../api";
import { useI18n } from "../i18n";

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
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="font-medium text-slate-900">{t(`agent_${name}`)}</h3>
        <span className="font-mono text-xs text-slate-400" dir="ltr">{name}</span>
        {a.overridden.length > 0
          ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">{t("moChanged")}</span>
          : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{t("moDefault")}</span>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <label className="label" htmlFor={id + "-model"}>{t("moModel")}</label>
          <select id={id + "-model"} className="input font-mono" dir="ltr" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })}>
            {data.models.map((m) => <option key={m.model} value={m.model}>{m.model}</option>)}
          </select>
          {price && <p className="mt-1 text-xs text-slate-500">{t("moPrice", { in: price.input, out: price.output })}</p>}
        </div>
        <div>
          <label className="label" htmlFor={id + "-effort"}>{t("moEffort")}</label>
          <select id={id + "-effort"} className="input" value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>
            {data.efforts.map((x) => <option key={x} value={x}>{t(`effort_${x}`)}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor={id + "-prompt"}>{t("moPrompt")}</label>
          <select id={id + "-prompt"} className="input font-mono" dir="ltr" value={f.prompt_version} onChange={(e) => setF({ ...f, prompt_version: e.target.value })}>
            {a.prompt_versions.map((v) => <option key={v} value={v}>{v}{v === a.default.prompt_version ? ` (${t("moDefault")})` : ""}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor={id + "-tok"}>{t("moMaxTokens")}</label>
          <input id={id + "-tok"} type="number" min={1000} max={128000} step={1000} className="input" dir="ltr"
            value={f.max_tokens} onChange={(e) => setF({ ...f, max_tokens: Number(e.target.value) })} />
        </div>
      </div>
      {f.prompt_version !== a.default.prompt_version && <p className="mt-2 text-xs text-amber-800">⚠ {t("moPromptWarn")}</p>}
      {err && <div role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-primary" disabled={!dirty || busy} onClick={() => run(() => api.adminSetAgent(name, f), t("moSaved"))}>{t("moSave")}</button>
        {a.overridden.length > 0 && (
          <button className="btn-ghost" disabled={busy} onClick={() => run(() => api.adminResetAgent(name), t("moSaved"))}>
            {t("moReset")} <span className="font-mono text-xs text-slate-500" dir="ltr">({a.default.model}, {a.default.prompt_version})</span>
          </button>
        )}
      </div>
    </div>
  );
}

export default function Models() {
  const { t } = useI18n();
  const [data, setData] = useState<ModelSettings | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [pipe, setPipe] = useState<Record<string, number>>({});
  const load = () => { setErr(""); api.adminSettings().then((d) => { setData(d); setPipe(d.pipeline); }).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const saved = (d: ModelSettings, m: string) => { setData(d); setPipe(d.pipeline); setMsg(m); };
  const pipeDirty = data && Object.keys(pipe).some((k) => pipe[k] !== data.pipeline[k]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{t("moTitle")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("moHint")}</p>
      </div>
      <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">{t("moCostWarn")}</div>
      {msg && <div role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg}</div>}
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>}
      {!data && !err && <div className="card p-5 text-sm text-slate-500">…</div>}
      {data && (
        <>
          <section className="card space-y-3 p-5">
            {Object.entries(data.agents).map(([name, a]) => <AgentRow key={name} name={name} a={a} data={data} onSaved={saved} />)}
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
