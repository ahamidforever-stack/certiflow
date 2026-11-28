import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeftRight, ArrowRight, ChevronDown, ChevronRight, FileImage, FileText, FileType2, Languages, Loader2, Plus, Settings2, Stamp, Upload, UserRound, X } from "lucide-react";
import { api, type Language, type StampOption } from "../api";
import { useI18n } from "../i18n";
import { useJobs } from "../lib/useJobs";
import { STEPS } from "../lib/jobs";
import { cn } from "../lib/cn";

// New job, "composer" style: drop the documents, set languages, client and stamp, start.
interface Picked { file: File; source?: string; target?: string; open?: boolean }
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.docx,.doc,.odt,.rtf";
const YOU = new Set([1, 5, 6]);   // steps where the translator decides: glossary, review, certify

function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return [<FileText key="p" className="h-4 w-4" />, "bg-red-50 text-red-600"] as const;
  if (["doc", "docx", "odt", "rtf"].includes(ext)) return [<FileType2 key="d" className="h-4 w-4" />, "bg-blue-50 text-blue-600"] as const;
  return [<FileImage key="i" className="h-4 w-4" />, "bg-emerald-50 text-emerald-700"] as const;
}

export default function NewJob() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const loc = useLocation();
  const { refresh } = useJobs();
  const [langs, setLangs] = useState<Language[]>([]);
  const [stamps, setStamps] = useState<StampOption[] | null>(null);
  const [recent, setRecent] = useState<{ source: string; target: string }[]>([]);
  const [files, setFiles] = useState<Picked[]>(() => ((loc.state as { files?: File[] } | null)?.files ?? []).map((file) => ({ file })));
  const [source, setSource] = useState("en");
  const [target, setTarget] = useState("ar");
  const [stamp, setStamp] = useState<"" | "certified" | "office">("");   // no default, on purpose
  const [docType, setDocType] = useState("");
  const [client, setClient] = useState("");
  const [clients, setClients] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [order, setOrder] = useState("translation_then_source");
  const [drag, setDrag] = useState(false);
  const [options, setOptions] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { if (loc.state) nav(loc.pathname, { replace: true, state: null }); }, []);   // files were handed over once // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.clients().then(setClients).catch(() => {}); }, []);
  useEffect(() => {
    api.languages().then(setLangs);
    api.stamps().then(setStamps).catch(() => setStamps([]));
    api.recentPairs().then((r) => { setRecent(r); if (r[0]) { setSource(r[0].source); setTarget(r[0].target); } });
  }, []);

  // Drop anywhere on the page.
  useEffect(() => {
    let depth = 0;
    const has = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
    const enter = (e: DragEvent) => { if (has(e)) { depth++; setDrag(true); } };
    const leave = (e: DragEvent) => { if (has(e) && --depth <= 0) { depth = 0; setDrag(false); } };
    const over = (e: DragEvent) => { if (has(e)) e.preventDefault(); };
    const drop = (e: DragEvent) => { if (!has(e)) return; e.preventDefault(); depth = 0; setDrag(false); add(e.dataTransfer!.files); };
    window.addEventListener("dragenter", enter); window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over); window.addEventListener("drop", drop);
    return () => { window.removeEventListener("dragenter", enter); window.removeEventListener("dragleave", leave); window.removeEventListener("dragover", over); window.removeEventListener("drop", drop); };
  }, []);

  const name = useMemo(() => {
    const m = new Map(langs.map((l) => [l.code, lang === "ar" ? `${l.native}` : `${l.name} · ${l.native}`]));
    return (c: string) => (c === "auto" ? t("autoDetect") : m.get(c) ?? c);
  }, [langs, lang, t]);

  function add(list: FileList | null) {
    if (!list) return;
    const picked = Array.from(list).map((file) => ({ file }));   // copy now: the input is cleared right after
    setFiles((f) => [...f, ...picked]);
  }
  const swap = () => { if (source !== "auto") { setSource(target); setTarget(source); } };

  const canStart = files.length > 0 && stamp !== "" && source !== target && !busy;
  const hint = files.length === 0 ? t("startHintFiles") : stamp === "" ? t("startHintStamp") : source === target ? t("njSameLang") : "";
  const start = async () => {
    setBusy(true); setError("");
    const fd = new FormData();
    files.forEach((p) => fd.append("files", p.file));
    fd.append("source_language", source);
    fd.append("target_language", target);
    fd.append("stamp", stamp);
    fd.append("page_order", order);
    if (docType) fd.append("document_type", docType);
    if (client.trim()) fd.append("client", client.trim());
    if (notes) fd.append("notes", notes);
    const ov: Record<string, { source_language: string; target_language: string }> = {};
    files.forEach((p, i) => { if (p.source || p.target) ov[i] = { source_language: p.source ?? source, target_language: p.target ?? target }; });
    if (Object.keys(ov).length) fd.append("overrides", JSON.stringify(ov));
    try {
      const r = await api.createJob(fd);
      refresh();
      nav(`/jobs/${r.id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  const langSelect = (id: string, value: string, set: (v: string) => void, label: string, withAuto = false) => (
    <label className="relative flex min-w-0 flex-1 items-center">
      <span className="sr-only">{label}</span>
      <select id={id} className="w-full appearance-none truncate rounded-lg border border-slate-200 bg-surface py-2 pe-8 ps-3 text-sm text-slate-900 transition hover:border-slate-300 focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-500/10"
        value={value} onChange={(e) => set(e.target.value)}>
        {withAuto && <option value="auto">{t("autoDetect")}</option>}
        {langs.map((l) => <option key={l.code} value={l.code}>{name(l.code)}</option>)}
      </select>
      <ChevronDown className="pointer-events-none absolute end-2.5 h-4 w-4 text-slate-400" />
    </label>
  );

  return (
    <div className="mx-auto max-w-3xl animate-fade-in">
      {drag && (
        <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-brand-600/10 backdrop-blur-[1px]">
          <div className="rounded-2xl border-2 border-dashed border-brand-500 bg-surface px-10 py-8 text-center shadow-float">
            <Upload className="mx-auto mb-2 h-8 w-8 text-brand-500" /><p className="font-medium text-slate-900">{t("njDropOverlay")}</p>
          </div>
        </div>
      )}

      <header className="mb-8 text-center">
        <h1 className="page-title text-3xl">{t("njTitle")}</h1>
        <p className="mx-auto mt-2 max-w-xl text-[15px] leading-relaxed text-slate-500">{t("njSubtitle")}</p>
      </header>

      <section className="card overflow-hidden">
        {/* documents */}
        {files.length === 0 ? (
          <button type="button" onClick={() => input.current?.click()}
            className="group flex w-full flex-col items-center justify-center px-6 py-14 text-center transition hover:bg-slate-50">
            <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 transition group-hover:scale-105 group-hover:bg-brand-600 group-hover:text-white">
              <Upload className="h-6 w-6" />
            </span>
            <span className="font-medium text-slate-900">{t("dropHere")}</span>
            <span className="mt-1 text-sm text-slate-500">{t("dropHint")}</span>
          </button>
        ) : (
          <div className="p-4">
            <div className="mb-2 flex items-center px-1">
              <span className="eyebrow">{t("sourceDocs")}</span>
              <span className="ms-2 text-xs text-slate-400">{t("njFileCount", { n: files.length })}</span>
            </div>
            <ul className="space-y-1.5">
              {files.map((p, i) => {
                const [icon, tone] = fileIcon(p.file.name);
                return (
                  <li key={i} className="rounded-xl border border-slate-200 bg-surface animate-fade-in">
                    <div className="flex items-center gap-3 px-3 py-2">
                      <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", tone)}>{icon}</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-slate-900"><bdi>{p.file.name}</bdi></div>
                        <div className="flex gap-2 text-xs text-slate-500">
                          <span dir="ltr">{p.file.size < 1024 * 1024 ? `${Math.max(1, Math.round(p.file.size / 1024))} KB` : `${(p.file.size / 1024 / 1024).toFixed(1)} MB`}</span>
                          {(p.source || p.target) && <span className="font-mono uppercase text-brand-600" dir="ltr">{p.source ?? source} → {p.target ?? target}</span>}
                        </div>
                      </div>
                      <button className="btn-quiet btn-sm hidden sm:inline-flex" onClick={() => setFiles((f) => f.map((x, j) => j === i ? { ...x, open: !x.open } : x))}>
                        <Languages className="h-3.5 w-3.5" />{t("perDocument")}</button>
                      <button className="icon-btn h-8 w-8 sm:hidden" aria-label={t("perDocument")} onClick={() => setFiles((f) => f.map((x, j) => j === i ? { ...x, open: !x.open } : x))}><Languages className="h-4 w-4" /></button>
                      <button className="icon-btn h-8 w-8 hover:bg-red-50 hover:text-red-600" aria-label={t("remove")} onClick={() => setFiles((f) => f.filter((_, j) => j !== i))}><X className="h-4 w-4" /></button>
                    </div>
                    {p.open && (
                      <div className="grid gap-2 border-t border-slate-100 px-3 py-2.5 sm:grid-cols-2">
                        <select className="input py-1.5 text-[13px]" value={p.source ?? ""} aria-label={t("from")} onChange={(e) => setFiles((f) => f.map((x, j) => j === i ? { ...x, source: e.target.value || undefined } : x))}>
                          <option value="">{t("sameAsJob")} ({name(source)})</option>
                          <option value="auto">{t("autoDetect")}</option>
                          {langs.map((l) => <option key={l.code} value={l.code}>{name(l.code)}</option>)}
                        </select>
                        <select className="input py-1.5 text-[13px]" value={p.target ?? ""} aria-label={t("to")} onChange={(e) => setFiles((f) => f.map((x, j) => j === i ? { ...x, target: e.target.value || undefined } : x))}>
                          <option value="">{t("sameAsJob")} ({name(target)})</option>
                          {langs.map((l) => <option key={l.code} value={l.code}>{name(l.code)}</option>)}
                        </select>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
            <button className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 py-2.5 text-sm text-slate-500 transition hover:border-brand-400 hover:text-brand-600"
              onClick={() => input.current?.click()}><Plus className="h-4 w-4" />{t("njAddMore")}</button>
          </div>
        )}
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />

        {/* languages, client, stamp */}
        <div className="space-y-4 border-t border-slate-200/80 bg-slate-50/60 p-4 sm:p-5">
          <div>
            <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-slate-600"><Languages className="h-3.5 w-3.5" />{t("njLanguages")}</div>
            <div className="flex items-center gap-2">
              {langSelect("src", source, setSource, t("from"), true)}
              <button className="icon-btn h-9 w-9 shrink-0 border border-slate-200 bg-surface" title={t("swap")} aria-label={t("swap")} onClick={swap} disabled={source === "auto"}>
                <ArrowLeftRight className="h-4 w-4" /></button>
              {langSelect("tgt", target, setTarget, t("to"))}
            </div>
            {recent.length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-slate-500">{t("recent")}:</span>
                {recent.map((r) => {
                  const on = r.source === source && r.target === target;
                  return (
                    <button key={r.source + r.target} onClick={() => { setSource(r.source); setTarget(r.target); }}
                      className={cn("rounded-full border px-2.5 py-0.5 font-mono uppercase transition", on ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-200 bg-surface text-slate-600 hover:border-slate-300")} dir="ltr">
                      {r.source} → {r.target}</button>
                  );
                })}
              </div>
            )}
          </div>

          <div>
            <label htmlFor="cl" className="mb-1.5 flex items-center gap-2 text-xs font-medium text-slate-600"><UserRound className="h-3.5 w-3.5" />{t("client")}</label>
            <input id="cl" className="input" dir="auto" list="cl-list" autoComplete="off" placeholder={t("clientPh")} value={client} onChange={(e) => setClient(e.target.value)} />
            <datalist id="cl-list">{clients.map((c) => <option key={c} value={c} />)}</datalist>
            <p className="mt-1 text-xs text-slate-500">{t("clientHint")}</p>
          </div>

          <div role="radiogroup" aria-labelledby="st-l">
            <div id="st-l" className="mb-1.5 flex items-center gap-2 text-xs font-medium text-slate-600"><Stamp className="h-3.5 w-3.5" />{t("chooseStamp")} <span className="text-red-600">*</span></div>
            <div className="grid gap-2 sm:grid-cols-2">
              {stamps === null ? [0, 1].map((i) => <div key={i} className="skeleton h-16 rounded-xl" />) : stamps.map((s) => {
                const on = stamp === s.choice;
                return (
                  <button key={s.choice} role="radio" aria-checked={on} disabled={!s.available} onClick={() => setStamp(s.choice)} title={s.available ? undefined : t("notAvailable")}
                    className={cn("flex items-center gap-3 rounded-xl border bg-surface p-3 text-start transition disabled:cursor-not-allowed disabled:opacity-50",
                      on ? "border-seal-400 ring-2 ring-seal-400/30" : "border-slate-200 hover:border-slate-300")}>
                    <span className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2", on ? "border-seal-500" : "border-slate-300")}>{on && <span className="h-2 w-2 rounded-full bg-seal-500" />}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-slate-900">{s.choice === "certified" ? t("certified") : t("officeStamp")}</span>
                      <span className="block truncate text-xs text-slate-500" dir="auto">{s.available ? s.name : t("notAvailable")}</span>
                    </span>
                    {s.available && s.image && <img src={s.image} alt="" className="h-10 w-14 object-contain mix-blend-multiply dark:mix-blend-normal dark:opacity-90" />}
                  </button>
                );
              })}
            </div>
            <p className="mt-1 text-xs text-slate-500">{t("chooseStampHint")}</p>
          </div>

          <div>
            <button className="flex items-center gap-2 text-xs font-medium text-slate-600 hover:text-slate-900" aria-expanded={options} onClick={() => setOptions((v) => !v)}>
              <Settings2 className="h-3.5 w-3.5" />{t("njOptions")}<ChevronDown className={cn("h-3.5 w-3.5 transition", options && "rotate-180")} />
              {!options && (docType || notes || order !== "translation_then_source") && <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />}
            </button>
            {options && (
              <div className="mt-3 space-y-3 animate-fade-in">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div><label className="label text-xs" htmlFor="dt">{t("docType")}</label><input id="dt" className="input" dir="auto" placeholder={t("docTypePh")} value={docType} onChange={(e) => setDocType(e.target.value)} /></div>
                  <div>
                    <span className="label text-xs">{t("pageOrder")}</span>
                    <div className="flex gap-1 rounded-lg bg-slate-100 p-1" role="radiogroup" aria-label={t("pageOrder")}>
                      {[["translation_then_source", "orderTS"], ["interleaved", "orderIL"]].map(([v, k]) => (
                        <button key={v} role="radio" aria-checked={order === v} onClick={() => setOrder(v)}
                          className={cn("flex-1 rounded-md px-2 py-1.5 text-xs transition", order === v ? "bg-surface font-medium text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800")}>{t(k)}</button>
                      ))}
                    </div>
                  </div>
                </div>
                <div><label className="label text-xs" htmlFor="nt">{t("notes")}</label><textarea id="nt" rows={2} className="input" dir="auto" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
              </div>
            )}
          </div>
        </div>

        {/* start */}
        <div className="flex flex-wrap items-center gap-3 border-t border-slate-200/80 px-4 py-3 sm:px-5">
          <p className={cn("min-w-0 flex-1 text-xs", error ? "text-red-700" : "text-slate-500")} role={error ? "alert" : undefined} dir={error ? "auto" : undefined}>{error || hint}</p>
          <button className="btn-primary w-full sm:w-auto" disabled={!canStart} onClick={start}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{t("start")}{!busy && <ArrowRight className="h-4 w-4 rtl:-scale-x-100" />}
          </button>
        </div>
      </section>

      {/* what happens next */}
      <section className="mt-8" aria-labelledby="nx">
        <h2 id="nx" className="eyebrow mb-3 text-center">{t("njNext")}</h2>
        <ol className="flex flex-wrap items-center justify-center gap-x-1 gap-y-2">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-1">
              <span className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs",
                YOU.has(i) ? "bg-seal-50 font-medium text-seal-800 ring-1 ring-seal-200" : "text-slate-500")}>
                {YOU.has(i) && <UserRound className="h-3 w-3" />}{t(s)}
              </span>
              {i < STEPS.length - 1 && <ChevronRight className="h-3 w-3 text-slate-300 rtl:-scale-x-100" aria-hidden />}
            </li>
          ))}
        </ol>
        <p className="mt-2 text-center text-xs text-slate-500">{t("njYouHint")}</p>
      </section>
    </div>
  );
}
