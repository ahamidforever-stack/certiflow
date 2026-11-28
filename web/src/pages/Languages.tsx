import { useEffect, useState } from "react";
import { api, type LangAdmin, type LanguageAdmin, type PairAdmin } from "../api";
import { useI18n } from "../i18n";

// Admin: language profiles (fonts, sizes, translation rules) and per-pair rules, laid over the profile files.

const NUM: Record<string, [number, number, number]> = { body_size_pt: [8, 20, 0.5], heading_scale: [1, 2, 0.05], line_spacing: [0.8, 2, 0.05] };
const DIGITS = ["as_source", "western", "eastern_arabic", "persian"];

function Alert({ err, msg }: { err: string; msg: string }) {
  if (err) return <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>;
  if (msg) return <div role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg}</div>;
  return null;
}

function LanguageForm({ l, textFields, onSaved }: { l: LangAdmin; textFields: string[]; onSaved: (d: LanguageAdmin) => void }) {
  const { t } = useI18n();
  const [v, setV] = useState<Record<string, unknown>>(l.values);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const changed = Object.keys(v).filter((k) => JSON.stringify(v[k]) !== JSON.stringify(l.values[k]));
  const run = async (fn: () => Promise<LanguageAdmin>) => {
    setBusy(true); setErr(""); setMsg("");
    try { const d = await fn(); onSaved(d); setV(d.languages.find((x) => x.code === l.code)!.values); setMsg(t("laSaved")); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const id = (k: string) => `lf-${l.code}-${k}`;
  const qm = (v.quote_marks as string[]) ?? ["", ""];
  return (
    <div className="mt-3 space-y-4 border-t border-slate-100 pt-4">
      <h3 className="text-sm font-semibold text-slate-900">{t("laLayout")}</h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {["word_font", "pdf_font", "pdf_font_fallback"].map((k) => (
          <div key={k}>
            <label className="label" htmlFor={id(k)}>{t(`f_${k}`)}</label>
            <input id={id(k)} className="input" dir="ltr" value={(v[k] as string) ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
          </div>
        ))}
        {Object.entries(NUM).map(([k, [lo, hi, step]]) => (
          <div key={k}>
            <label className="label" htmlFor={id(k)}>{t(`f_${k}`)}</label>
            <input id={id(k)} type="number" min={lo} max={hi} step={step} className="input max-w-[8rem]" dir="ltr"
              value={v[k] as number} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} />
          </div>
        ))}
        <div>
          <label className="label" htmlFor={id("digit_style")}>{t("f_digit_style")}</label>
          <select id={id("digit_style")} className="input" value={v.digit_style as string} onChange={(e) => setV({ ...v, digit_style: e.target.value })}>
            {DIGITS.map((d) => <option key={d} value={d}>{t(`digit_${d}`)}</option>)}
          </select>
        </div>
        <div>
          <span className="label">{t("f_quote_marks")}</span>
          <div className="flex gap-2" dir="ltr">
            {[0, 1].map((i) => (
              <input key={i} aria-label={`${t("f_quote_marks")} ${i + 1}`} className="input w-16 text-center" maxLength={3} value={qm[i]}
                onChange={(e) => setV({ ...v, quote_marks: i ? [qm[0], e.target.value] : [e.target.value, qm[1]] })} />
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
          <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={!!v.justify} onChange={(e) => setV({ ...v, justify: e.target.checked })} />
          {t("f_justify")}
        </label>
      </div>

      <h3 className="text-sm font-semibold text-slate-900">{t("laRules")}</h3>
      <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">⚠ {t("laRulesWarn")}</p>
      {textFields.map((k) => (
        <div key={k}>
          <label className="label" htmlFor={id(k)}>{t(`f_${k}`)}</label>
          <textarea id={id(k)} dir="auto" rows={k === "style_guide" ? 6 : 2} className="input"
            value={(v[k] as string) ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
        </div>
      ))}
      <Alert err={err} msg={msg} />
      <div className="flex flex-wrap gap-2">
        <button className="btn-primary" disabled={busy || changed.length === 0}
          onClick={() => run(() => api.adminSetLanguage(l.code, Object.fromEntries(changed.map((k) => [k, v[k]]))))}>{t("laSave")}</button>
        {l.overridden.length > 0 && <button className="btn-ghost" disabled={busy} onClick={() => run(() => api.adminResetLanguage(l.code))}>{t("laReset")}</button>}
      </div>
    </div>
  );
}

function PairForm({ p, data, onSaved, onCancel }: { p: PairAdmin; data: LanguageAdmin; onSaved: (d: LanguageAdmin) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const isNew = !data.pairs.some((x) => x.source === p.source && x.target === p.target);
  const [f, setF] = useState({ ...p });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true); setErr("");
    try {
      onSaved(await api.adminSetPair(f.source, f.target, { conventions: f.conventions, template_id: f.template_id,
        no_foreign_script: f.no_foreign_script, transliteration_standard: f.transliteration_standard }));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const langSelect = (k: "source" | "target", label: string) => (
    <div>
      <label className="label" htmlFor={`pf-${k}`}>{label}</label>
      <select id={`pf-${k}`} className="input" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}>
        {data.languages.map((l) => <option key={l.code} value={l.code}>{l.display_name} · {l.native_name}</option>)}
      </select>
    </div>
  );
  return (
    <div className="mt-3 space-y-3 rounded-lg border border-brand-100 bg-brand-50/40 p-4">
      {isNew && <div className="grid gap-3 sm:grid-cols-2">{langSelect("source", t("laFrom"))}{langSelect("target", t("laTo"))}</div>}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="pf-tpl">{t("f_template_id")}</label>
          <select id="pf-tpl" className="input" value={f.template_id ?? ""} onChange={(e) => setF({ ...f, template_id: e.target.value || null })}>
            <option value="">{t("laTplAuto")}</option>
            {data.templates.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="pf-nfs">{t("f_no_foreign_script")}</label>
          <select id="pf-nfs" className="input" value={f.no_foreign_script === null ? "" : String(f.no_foreign_script)}
            onChange={(e) => setF({ ...f, no_foreign_script: e.target.value === "" ? null : e.target.value === "true" })}>
            <option value="">{t("laNfsDefault")}</option><option value="true">{t("laNfsForbid")}</option><option value="false">{t("laNfsAllow")}</option>
          </select>
        </div>
      </div>
      <div>
        <label className="label" htmlFor="pf-conv">{t("f_conventions")}</label>
        <textarea id="pf-conv" rows={3} dir="auto" className="input" value={f.conventions} onChange={(e) => setF({ ...f, conventions: e.target.value })} />
        <p className="mt-1 text-xs text-amber-800">⚠ {t("laRulesWarn")}</p>
      </div>
      <div>
        <label className="label" htmlFor="pf-tr">{t("f_transliteration_standard")}</label>
        <input id="pf-tr" dir="auto" className="input" value={f.transliteration_standard ?? ""} onChange={(e) => setF({ ...f, transliteration_standard: e.target.value || null })} />
      </div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={busy || f.source === f.target} onClick={save}>{t("laSave")}</button>
        <button className="btn-ghost" onClick={onCancel}>{t("usCancel")}</button>
      </div>
    </div>
  );
}

export default function Languages() {
  const { t } = useI18n();
  const [data, setData] = useState<LanguageAdmin | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [pairEdit, setPairEdit] = useState<PairAdmin | null>(null);
  const load = () => { setErr(""); api.adminLanguages().then(setData).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const pairKey = (p: { source: string; target: string }) => `${p.source}>${p.target}`;
  const name = (code: string) => data?.languages.find((l) => l.code === code)?.display_name ?? code;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{t("laTitle")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("laHint")}</p>
      </div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>}
      {!data && !err && <div className="card p-5 text-sm text-slate-500">…</div>}
      {data && (
        <>
          <section className="card divide-y divide-slate-100">
            {data.languages.map((l) => (
              <div key={l.code} className="px-5 py-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="w-8 font-mono text-xs uppercase text-slate-500" dir="ltr">{l.code}</span>
                  <span className="font-medium text-slate-900">{l.display_name}</span>
                  <span className="text-slate-600" dir={l.direction} lang={l.code}>{l.native_name}</span>
                  {l.overridden.length > 0 && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">{t("laChanged")}</span>}
                  <span className="ms-auto flex flex-wrap items-center gap-x-2 text-xs">
                    {l.pdf_font_installed ? <span className="text-green-700">✓ {t("laFontOk")}</span>
                      : l.fallback_installed ? <span className="text-amber-700">⚠ {t("laFontFallback", { f: String(l.values.pdf_font_fallback) })}</span>
                      : <span className="text-red-700">✕ {t("laFontMissing")}</span>}
                    <bdi className="text-slate-500" dir="ltr">{String(l.values.pdf_font)} · {String(l.values.body_size_pt)} pt</bdi>
                  </span>
                  <button className="text-sm text-brand-500 hover:underline" aria-expanded={open === l.code}
                    onClick={() => setOpen(open === l.code ? null : l.code)}>{open === l.code ? t("laClose") : t("laEdit")}</button>
                </div>
                {open === l.code && <LanguageForm l={l} textFields={data.text_fields} onSaved={setData} />}
              </div>
            ))}
          </section>

          <section className="card p-5">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold text-slate-900">{t("laPairs")}</h2>
                <p className="mt-1 text-sm text-slate-500">{t("laPairsHint")}</p>
              </div>
              {!pairEdit && <button className="btn-ghost" onClick={() => setPairEdit({ source: "en", target: "ar", template_id: null, conventions: "",
                no_foreign_script: null, transliteration_standard: null, in_defaults: false, overridden: false })}>+ {t("laAddPair")}</button>}
            </div>
            {pairEdit && !data.pairs.some((x) => pairKey(x) === pairKey(pairEdit)) && (
              <PairForm p={pairEdit} data={data} onCancel={() => setPairEdit(null)} onSaved={(d) => { setData(d); setPairEdit(null); }} />
            )}
            {data.pairs.length === 0 ? <p className="mt-3 text-sm text-slate-500">{t("laNoPairs")}</p> : (
              <ul className="mt-3 divide-y divide-slate-100">
                {data.pairs.map((p) => (
                  <li key={pairKey(p)} className="py-3">
                    <div className="flex flex-wrap items-center gap-3 text-sm">
                      <span className="font-medium text-slate-900">{name(p.source)} <span className="inline-block rtl:rotate-180">→</span> {name(p.target)}</span>
                      {p.in_defaults && !p.overridden && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{t("laInDefaults")}</span>}
                      {p.overridden && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">{t("laChanged")}</span>}
                      <span className="ms-auto flex gap-3">
                        <button className="text-brand-500 hover:underline" onClick={() => setPairEdit(p)}>{t("laEdit")}</button>
                        {p.overridden && <button className="text-red-600 hover:underline" onClick={() => api.adminResetPair(p.source, p.target).then(setData).catch((e) => setErr(e.message))}>
                          {p.in_defaults ? t("laReset") : t("laRemovePair")}</button>}
                      </span>
                    </div>
                    {p.conventions && <p className="mt-1 text-sm text-slate-600" dir="auto">{p.conventions}</p>}
                    {pairEdit && pairKey(pairEdit) === pairKey(p) && (
                      <PairForm p={p} data={data} onCancel={() => setPairEdit(null)} onSaved={(d) => { setData(d); setPairEdit(null); }} />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
