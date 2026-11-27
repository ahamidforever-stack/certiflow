import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Language, type StampOption } from "../api";
import { useI18n } from "../i18n";

interface Picked { file: File; source?: string; target?: string; open?: boolean }
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.docx,.doc,.odt,.rtf";

export default function NewJob() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const [langs, setLangs] = useState<Language[]>([]);
  const [stamps, setStamps] = useState<StampOption[]>([]);
  const [recent, setRecent] = useState<{ source: string; target: string }[]>([]);
  const [files, setFiles] = useState<Picked[]>([]);
  const [source, setSource] = useState("en");
  const [target, setTarget] = useState("ar");
  const [stamp, setStamp] = useState<"" | "certified" | "office">("");   // no default, on purpose
  const [docType, setDocType] = useState("");
  const [notes, setNotes] = useState("");
  const [order, setOrder] = useState("translation_then_source");
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.languages().then(setLangs);
    api.stamps().then(setStamps);
    api.recentPairs().then((r) => { setRecent(r); if (r[0]) { setSource(r[0].source); setTarget(r[0].target); } });
  }, []);

  const name = useMemo(() => {
    const m = new Map(langs.map((l) => [l.code, lang === "ar" ? `${l.native}` : `${l.name} · ${l.native}`]));
    return (c: string) => (c === "auto" ? t("autoDetect") : m.get(c) ?? c);
  }, [langs, lang, t]);

  const add = (list: FileList | null) => {
    if (!list) return;
    const picked = Array.from(list).map((file) => ({ file }));   // copy now: the input is cleared right after
    setFiles((f) => [...f, ...picked]);
  };
  const swap = () => { if (source !== "auto") { setSource(target); setTarget(source); } };

  const canStart = files.length > 0 && stamp !== "" && source !== target && !busy;
  const start = async () => {
    setBusy(true); setError("");
    const fd = new FormData();
    files.forEach((p) => fd.append("files", p.file));
    fd.append("source_language", source);
    fd.append("target_language", target);
    fd.append("stamp", stamp);
    fd.append("page_order", order);
    if (docType) fd.append("document_type", docType);
    if (notes) fd.append("notes", notes);
    const ov: Record<string, { source_language: string; target_language: string }> = {};
    files.forEach((p, i) => { if (p.source || p.target) ov[i] = { source_language: p.source ?? source, target_language: p.target ?? target }; });
    if (Object.keys(ov).length) fd.append("overrides", JSON.stringify(ov));
    try {
      const r = await api.createJob(fd);
      nav(`/jobs/${r.id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  const select = (value: string, set: (v: string) => void, withAuto = false, id?: string) => (
    <select id={id} className="input" value={value} onChange={(e) => set(e.target.value)}>
      {withAuto && <option value="auto">{t("autoDetect")}</option>}
      {langs.map((l) => <option key={l.code} value={l.code}>{name(l.code)}</option>)}
    </select>
  );

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <section className="card p-5">
          <h2 className="mb-3 font-semibold text-slate-900">{t("sourceDocs")}</h2>
          <div
            onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${drag ? "border-brand-500 bg-brand-50" : "border-slate-300 hover:border-brand-500"}`}
          >
            <svg className="mb-2 h-8 w-8 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
            <div className="font-medium text-slate-800">{t("dropHere")}</div>
            <div className="mt-1 text-xs text-slate-500">{t("dropHint")}</div>
            <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          </div>
          {files.length > 0 && (
            <ul className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-200">
              {files.map((p, i) => (
                <li key={i} className="px-3 py-2 text-sm">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs text-slate-400">{String(i + 1).padStart(2, "0")}</span>
                    <span className="truncate font-medium text-slate-800" dir="auto">{p.file.name}</span>
                    <span className="text-xs text-slate-400">{(p.file.size / 1024 / 1024).toFixed(1)} MB</span>
                    {(p.source || p.target) && <span className="rounded bg-brand-50 px-1.5 font-mono text-xs uppercase text-brand-600" dir="ltr">{p.source ?? source} → {p.target ?? target}</span>}
                    <button className="ms-auto text-xs text-brand-500 hover:underline" onClick={() => setFiles((f) => f.map((x, j) => j === i ? { ...x, open: !x.open } : x))}>{t("perDocument")}</button>
                    <button className="text-xs text-red-600 hover:underline" onClick={() => setFiles((f) => f.filter((_, j) => j !== i))}>{t("remove")}</button>
                  </div>
                  {p.open && (
                    <div className="mt-2 grid grid-cols-2 gap-2 ps-8">
                      <select className="input" value={p.source ?? ""} onChange={(e) => setFiles((f) => f.map((x, j) => j === i ? { ...x, source: e.target.value || undefined } : x))}>
                        <option value="">{t("sameAsJob")} ({name(source)})</option>
                        <option value="auto">{t("autoDetect")}</option>
                        {langs.map((l) => <option key={l.code} value={l.code}>{name(l.code)}</option>)}
                      </select>
                      <select className="input" value={p.target ?? ""} onChange={(e) => setFiles((f) => f.map((x, j) => j === i ? { ...x, target: e.target.value || undefined } : x))}>
                        <option value="">{t("sameAsJob")} ({name(target)})</option>
                        {langs.map((l) => <option key={l.code} value={l.code}>{name(l.code)}</option>)}
                      </select>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-5">
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto_1fr]">
            <div><label className="label" htmlFor="src">{t("from")}</label>{select(source, setSource, true, "src")}</div>
            <button className="btn-ghost h-10" title={t("swap")} onClick={swap} disabled={source === "auto"} aria-label={t("swap")}>⇄</button>
            <div><label className="label" htmlFor="tgt">{t("to")}</label>{select(target, setTarget, false, "tgt")}</div>
          </div>
          {recent.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <span className="text-slate-500">{t("recent")}:</span>
              {recent.map((r) => (
                <button key={r.source + r.target} onClick={() => { setSource(r.source); setTarget(r.target); }}
                  className="rounded-full border border-slate-300 px-2.5 py-0.5 font-mono uppercase text-slate-600 hover:border-brand-500" dir="ltr">{r.source} → {r.target}</button>
              ))}
            </div>
          )}
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div><label className="label" htmlFor="dt">{t("docType")}</label><input id="dt" className="input" placeholder={t("docTypePh")} value={docType} onChange={(e) => setDocType(e.target.value)} /></div>
            <div><label className="label" htmlFor="po">{t("pageOrder")}</label>
              <select id="po" className="input" value={order} onChange={(e) => setOrder(e.target.value)}>
                <option value="translation_then_source">{t("orderTS")}</option>
                <option value="interleaved">{t("orderIL")}</option>
              </select></div>
          </div>
          <div className="mt-3"><label className="label" htmlFor="nt">{t("notes")}</label><textarea id="nt" rows={2} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        </section>
      </div>

      <aside className="space-y-6">
        <section className="card p-5">
          <h2 className="font-semibold text-slate-900">{t("chooseStamp")} <span className="text-red-600">*</span></h2>
          <p className="mb-3 mt-1 text-xs text-slate-500">{t("chooseStampHint")}</p>
          <div className="space-y-3" role="radiogroup">
            {stamps.map((s) => {
              const on = stamp === s.choice;
              return (
                <button key={s.choice} role="radio" aria-checked={on} disabled={!s.available} onClick={() => setStamp(s.choice)}
                  className={`flex w-full items-center gap-3 rounded-xl border-2 p-3 text-start transition disabled:cursor-not-allowed disabled:opacity-50 ${on ? "border-brand-600 bg-brand-50" : "border-slate-200 hover:border-slate-400"}`}>
                  <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${on ? "border-brand-600" : "border-slate-300"}`}>{on && <span className="h-2.5 w-2.5 rounded-full bg-brand-600" />}</span>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-slate-900">{s.choice === "certified" ? t("certified") : t("officeStamp")}</div>
                    <div className="truncate text-xs text-slate-500" dir="auto">{s.available ? s.name : t("notAvailable")}</div>
                  </div>
                  {s.available && s.image && <img src={s.image} alt="" className="h-14 w-20 object-contain" />}
                </button>
              );
            })}
          </div>
        </section>
        <div>
          <button className="btn-primary w-full py-3 text-base" disabled={!canStart} onClick={start}>{busy ? "…" : t("start")}</button>
          {!busy && !canStart && <p className="mt-2 text-center text-xs text-slate-500">{files.length === 0 ? t("startHintFiles") : stamp === "" ? t("startHintStamp") : ""}</p>}
          {error && <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        </div>
      </aside>
    </div>
  );
}
