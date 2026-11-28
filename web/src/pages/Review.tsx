import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type DocBlock, type DocModel, type Job, type Language, type ReviewResult } from "../api";
import { wordDiff } from "../diff";
import { useI18n } from "../i18n";

// Side-by-side review editor: source page (with block boxes) | translated blocks (editable).
// Every save goes to the API, which records history and writes <doc>.reviewed.json.

const AGENTS = new Set(["translator", "proofreader", "qa", "formatter"]);
type Draft = { text?: string; cells?: Record<string, string> };
type SaveState = "saved" | "saving" | "dirty" | "error";

const pendingChanges = (b: DocBlock) =>
  (b.history || []).map((h, i) => ({ h, i }))
    .filter(({ h }) => AGENTS.has(h.actor) && h.old != null && h.new != null && h.old !== h.new && !h.review);
const openFlags = (b: DocBlock) => (b.flags || []).map((f, i) => ({ f, i })).filter(({ f }) => !f.resolved);
const hasBlocker = (b: DocBlock) => openFlags(b).some(({ f }) => f.severity === "blocker");

export default function Review() {
  const { id = "", doc = "" } = useParams();
  const { t } = useI18n();
  const nav = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [model, setModel] = useState<DocModel | null>(null);
  const [langs, setLangs] = useState<Language[]>([]);
  const [loadErr, setLoadErr] = useState("");
  const [err, setErr] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [save, setSave] = useState<SaveState>("saved");
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());   // blocks chosen for a re-run

  const load = useCallback(() => {
    setLoadErr("");
    Promise.all([api.job(id), api.documentModel(id, doc), api.languages()])
      .then(([j, m, l]) => { setJob(j); setModel(m.model); setLangs(l); })
      .catch((e) => setLoadErr(e.message));
  }, [id, doc]);
  useEffect(() => { setDrafts({}); setSave("saved"); load(); }, [load]);

  const dirty = Object.keys(drafts).length > 0;
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const editable = job?.status === "waiting_review";
  const reworking = job?.status === "reworking";

  // after a re-run: reload the document once the job is back in review (a fast agent may already be done)
  const refreshAfterRerun = () => api.job(id).then((j) => {
    setJob(j);
    if (j.status === "reworking") return;
    if (j.error) setErr(j.error);
    return api.documentModel(id, doc).then((m) => setModel(m.model));
  });

  // while an agent re-runs, follow the job
  useEffect(() => {
    if (!reworking) return;
    const h = window.setInterval(() => { refreshAfterRerun().catch(() => {}); }, 2000);
    return () => window.clearInterval(h);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reworking, id, doc]);

  const startRerun = (agent: string, instruction: string) => {
    setErr("");
    return api.rerun(id, doc, agent, [...picked], instruction)
      .then(() => { setPicked(new Set()); return refreshAfterRerun(); })
      .catch((e) => setErr(e.message));
  };
  const dirOf = (code?: string) => langs.find((l) => l.code === code)?.direction ?? "ltr";

  const apply = (p: Promise<ReviewResult>) => {
    setSave("saving"); setErr("");
    return p.then((r) => { setModel(r.model); setSave("saved"); return true; })
      .catch((e) => { setErr(e.message); setSave("error"); return false; });
  };

  const saveBlock = async (b: DocBlock) => {
    const d = drafts[b.id];
    if (!d) return;
    const cells = d.cells ? Object.entries(d.cells).map(([k, text]) => { const [row, col] = k.split(",").map(Number); return { row, col, text }; }) : undefined;
    const ok = await apply(api.editBlock(id, doc, b.id, { text: d.text, cells }));
    if (ok) setDrafts((x) => { const y = { ...x }; delete y[b.id]; return y; });
  };
  const saveAll = async () => { for (const b of model?.blocks ?? []) if (drafts[b.id]) await saveBlock(b); };
  const saveAllRef = useRef(saveAll);
  saveAllRef.current = saveAll;
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveAllRef.current(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const setDraft = (b: DocBlock, patch: Draft) => {
    setDrafts((x) => ({ ...x, [b.id]: { ...x[b.id], ...patch, cells: { ...x[b.id]?.cells, ...patch.cells } } }));
    setSave("dirty");
  };

  const pending = useMemo(() => (model?.blocks ?? []).flatMap((b) => pendingChanges(b).map((c) => ({ b, ...c }))), [model]);
  const blockers = useMemo(() => (model?.blocks ?? []).filter(hasBlocker), [model]);
  const acceptAll = async () => {
    for (const c of pending) if (!(await apply(api.decideChange(id, doc, c.b.id, c.i, "accept")))) break;
  };

  const pages = useMemo(() => {
    const n = new Set<number>((model?.pages ?? []).map((p) => p.number));
    for (const b of model?.blocks ?? []) if (b.source_page) n.add(b.source_page);
    return [...n].sort((a, b) => a - b);
  }, [model]);

  const focus = (bid: string, side: "src" | "tgt") => {
    setSelected(bid);
    document.getElementById(`${side}-${bid}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const leave = (to: string) => { if (!dirty || window.confirm(t("rvLeaveConfirm"))) nav(to); };

  if (loadErr) return (
    <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <span className="flex-1">{t("rvLoadError")}</span><button className="btn-ghost" onClick={load}>{t("retry")}</button>
    </div>
  );
  if (!job || !model) return <div className="text-slate-500">…</div>;
  const sDir = dirOf(model.source_language), tDir = dirOf(model.target_language);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => leave(`/jobs/${id}`)} className="text-sm text-brand-500 hover:underline">
          <span className="inline-block rtl:rotate-180">←</span> {t("rvBackToJob")}
        </button>
        <h1 className="text-lg font-semibold text-slate-900" dir="auto">{model.title}</h1>
        {(job.documents?.length ?? 0) > 1 && (
          <nav className="flex gap-1" aria-label={t("documents")}>
            {job.documents!.map((d) => (
              <button key={d.key} onClick={() => leave(`/jobs/${id}/review/${d.key}`)}
                className={`rounded-md px-2.5 py-1 font-mono text-xs ${d.key === doc ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>{d.key}</button>
            ))}
          </nav>
        )}
        <SaveBadge state={save} />
      </div>

      <div className="card flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-sm">
        <span className={blockers.length ? "font-medium text-red-700" : "text-emerald-700"}>
          {blockers.length ? t("rvBlockersOpen", { n: blockers.length }) : t("rvNoBlockers")}
        </span>
        {blockers.length > 0 && (
          <span className="flex flex-wrap gap-1">
            {blockers.map((b) => <button key={b.id} onClick={() => focus(b.id, "tgt")} className="rounded bg-red-50 px-1.5 font-mono text-xs text-red-700 hover:bg-red-100" dir="ltr">{b.id}</button>)}
          </span>
        )}
        <span className="text-slate-600">{t("rvPendingChanges", { n: pending.length })}</span>
        <div className="ms-auto flex gap-2">
          {editable && pending.length > 0 && <button className="btn-ghost" onClick={acceptAll} disabled={save === "saving"}>{t("rvAcceptAll")}</button>}
          {editable && (
            <a className={`btn-ghost ${dirty ? "pointer-events-none opacity-40" : ""}`} aria-disabled={dirty}
              href={`/api/jobs/${id}/documents/${doc}/preview.pdf`} target="_blank" rel="noopener"
              title={dirty ? t("rvPreviewSaveFirst") : t("rvPreviewHint")}>{t("rvPreview")}</a>
          )}
          {editable && <button className="btn-primary" onClick={saveAll} disabled={!dirty || save === "saving"} title="Ctrl+S">{t("rvSaveAll")}</button>}
        </div>
      </div>
      {reworking && (
        <p role="status" className="flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-2 text-sm text-blue-800">
          <span className="h-2 w-2 animate-pulse rounded-full bg-current" />{t("rvReworking")}
        </p>
      )}
      {!editable && !reworking && <p className="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-700">{t("rvReadOnly")}</p>}
      {editable && picked.size > 0 && (
        <RerunPanel count={picked.size} onRun={startRerun} onClear={() => setPicked(new Set())} dirty={dirty} />
      )}
      {err && <p className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700" dir="auto">{err}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* source pane */}
        <section className="card overflow-hidden lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto" aria-label={t("rvSourcePane")}>
          <h2 className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-700">
            {t("rvSourcePane")} · <span className="font-mono text-xs uppercase" dir="ltr">{model.source_language}</span>
          </h2>
          {pages.length === 0 && <p className="p-4 text-sm text-slate-500">{t("rvNoPages")}</p>}
          {pages.map((n) => (
            <div key={n} className="border-b border-slate-200 p-3">
              <div className="mb-1 text-xs text-slate-500">{t("rvPage")} <bdi>{n}</bdi></div>
              <div className="relative">
                <img src={api.pageImage(id, doc, n)} alt={`${t("rvPage")} ${n}`} className="w-full select-none rounded border border-slate-200" loading="lazy" />
                {model.blocks.filter((b) => b.source_page === n && b.bbox?.length === 4).map((b) => {
                  const [x0, y0, x1, y1] = b.bbox!;
                  const on = selected === b.id || hovered === b.id;
                  const tone = hasBlocker(b) ? "border-red-500 bg-red-500/10" : openFlags(b).length ? "border-amber-500 bg-amber-400/10" : "border-transparent hover:border-brand-500";
                  // the image is not mirrored in RTL, so position from the physical left edge
                  return (
                    <button key={b.id} id={`src-${b.id}`} aria-label={b.id} dir="ltr"
                      onClick={() => focus(b.id, "tgt")} onMouseEnter={() => setHovered(b.id)} onMouseLeave={() => setHovered(null)}
                      className={`absolute rounded-sm border-2 ${on ? "border-brand-600 bg-brand-500/15" : tone}`}
                      style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` }} />
                  );
                })}
              </div>
            </div>
          ))}
        </section>

        {/* translation pane */}
        <section className="space-y-3" aria-label={t("rvTargetPane")}>
          {model.blocks.filter((b) => b.type !== "page_break").map((b) => (
            <BlockCard key={b.id} b={b} sDir={sDir} tDir={tDir} sLang={model.source_language} tLang={model.target_language}
              editable={!!editable} draft={drafts[b.id]} active={selected === b.id || hovered === b.id}
              onHover={(on) => setHovered(on ? b.id : null)} onSelect={() => focus(b.id, "src")}
              onDraft={(p) => setDraft(b, p)} onSave={() => saveBlock(b)}
              onCancel={() => setDrafts((x) => { const y = { ...x }; delete y[b.id]; if (!Object.keys(y).length) setSave("saved"); return y; })}
              onDecide={(i, d) => apply(api.decideChange(id, doc, b.id, i, d))}
              onResolve={(i, c) => apply(api.resolveFlag(id, doc, b.id, i, c))}
              picked={picked.has(b.id)} onPick={(on) => setPicked((x) => { const y = new Set(x); if (on) y.add(b.id); else y.delete(b.id); return y; })} />
          ))}
        </section>
      </div>
      <p className="text-xs text-slate-500">{t("rvApproveOnJob")} <Link className="text-brand-500 hover:underline" to={`/jobs/${id}`} onClick={(e) => { if (dirty && !window.confirm(t("rvLeaveConfirm"))) e.preventDefault(); }}>{t("rvBackToJob")}</Link></p>
    </div>
  );
}

function SaveBadge({ state }: { state: SaveState }) {
  const { t } = useI18n();
  const map: Record<SaveState, string> = {
    saved: "bg-emerald-50 text-emerald-700", saving: "bg-blue-50 text-blue-700", dirty: "bg-amber-50 text-amber-800", error: "bg-red-50 text-red-700",
  };
  return <span role="status" className={`ms-auto rounded-full px-2.5 py-0.5 text-xs font-medium ${map[state]}`}>{t(`rvSave_${state}`)}</span>;
}

interface CardProps {
  picked: boolean; onPick: (on: boolean) => void;
  b: DocBlock; sDir: string; tDir: string; sLang: string; tLang: string; editable: boolean; draft?: Draft; active: boolean;
  onHover: (on: boolean) => void; onSelect: () => void; onDraft: (p: Draft) => void; onSave: () => void; onCancel: () => void;
  onDecide: (i: number, d: "accept" | "reject") => void; onResolve: (i: number, comment: string) => void;
}

function BlockCard({ b, sDir, tDir, sLang, tLang, editable, draft, active, onHover, onSelect, onDraft, onSave, onCancel, onDecide, onResolve, picked, onPick }: CardProps) {
  const { t } = useI18n();
  const flags = openFlags(b);
  const resolved = (b.flags || []).filter((f) => f.resolved);
  const changes = pendingChanges(b);
  const border = hasBlocker(b) ? "border-red-300" : flags.length ? "border-amber-300" : active ? "border-brand-500" : "border-slate-200";
  const fieldLabel = (f?: string) => (f && f !== "translated_text" ? f.replace(/rows\[(\d+)\]\[(\d+)\]/, (_, r, c) => t("rvCell", { r: +r + 1, c: +c + 1 })) : "");

  return (
    <article id={`tgt-${b.id}`} onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}
      className={`rounded-xl border bg-surface shadow-sm transition ${border} ${active ? "ring-2 ring-brand-100" : ""}`}>
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-1.5 text-xs text-slate-500">
        {editable && !b.multilingual_duplicate && (
          <input type="checkbox" checked={picked} onChange={(e) => onPick(e.target.checked)} aria-label={t("rvPick", { id: b.id })}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-2 focus:ring-brand-100" />
        )}
        <button onClick={onSelect} className="font-mono text-slate-600 hover:text-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100" dir="ltr" title={t("rvShowOnPage")}>{b.id}</button>
        <span>{t(`bt_${b.type}`)}</span>
        {b.source_page && <span>· {t("rvPage")} <bdi>{b.source_page}</bdi></span>}
        {b.multilingual_duplicate && <span className="rounded bg-slate-100 px-1.5">{t("rvDuplicate")}</span>}
        <span className="ms-auto flex gap-1">
          {flags.map(({ f, i }) => (
            <span key={i} className={`rounded px-1.5 font-medium ${f.severity === "blocker" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"}`}>{t(`sev_${f.severity}`)}</span>
          ))}
        </span>
      </header>

      <div className="grid gap-2 px-3 py-2">
        {/* source text, in the source language direction */}
        {!b.rows?.length && b.source_text && (
          <p className="whitespace-pre-wrap text-sm text-slate-500" dir={sDir} lang={sLang}>{b.label ? `${b.label} ` : ""}{b.source_text}</p>
        )}
        {b.rows?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm" dir={tDir} lang={tLang}>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri}>
                    {r.cells.map((c, ci) => {
                      const key = `${ri},${ci}`;
                      const val = draft?.cells?.[key] ?? c.translated_text ?? "";
                      return (
                        <td key={ci} colSpan={c.colspan ?? 1} className={`border border-slate-200 p-1 align-top ${r.header || c.header ? "bg-slate-50 font-medium" : ""}`}>
                          {c.source_text && <div className="mb-1 text-xs text-slate-500" dir={sDir} lang={sLang}>{c.source_text}</div>}
                          {editable && !c.blocks ? (
                            <textarea aria-label={t("rvCell", { r: ri + 1, c: ci + 1 })} rows={Math.max(1, Math.ceil(val.length / 30))}
                              className="w-full resize-y rounded border border-transparent bg-transparent p-1 hover:border-slate-300 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100"
                              value={val} onChange={(e) => onDraft({ cells: { [key]: e.target.value } })} />
                          ) : <div className="whitespace-pre-wrap p-1">{c.translated_text}</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : b.type === "page_break" ? null : editable ? (
          <textarea aria-label={t("rvTranslationOf", { id: b.id })} dir={tDir} lang={tLang}
            rows={Math.max(2, Math.ceil(((draft?.text ?? b.translated_text) || "").length / 70))}
            className={`input resize-y leading-relaxed ${b.type === "heading" ? "font-semibold" : ""} ${b.type === "note" ? "italic text-brand-600" : ""}`}
            value={draft?.text ?? b.translated_text ?? ""} onChange={(e) => onDraft({ text: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); onSave(); } }} />
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed" dir={tDir} lang={tLang}>{b.translated_text}</p>
        )}
        {draft && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-amber-700">{t("rvSave_dirty")}</span>
            <button className="btn-ghost ms-auto px-3 py-1" onClick={onCancel}>{t("rvCancel")}</button>
            <button className="btn-primary px-3 py-1" onClick={onSave} title="Ctrl+Enter">{t("rvSave")}</button>
          </div>
        )}

        {/* tracked changes from the agents */}
        {changes.map(({ h, i }) => (
          <div key={i} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <span className="font-medium">{t("rvChangeBy", { agent: t(`agent_${h.actor}`) })}</span>
              {fieldLabel(h.field) && <span>· {fieldLabel(h.field)}</span>}
              {h.reason && <span dir="auto">· {h.reason}</span>}
            </div>
            <p className="whitespace-pre-wrap leading-relaxed" dir={tDir} lang={tLang}>
              {wordDiff(h.old ?? "", h.new ?? "").map((p, k) =>
                p.kind === "same" ? <span key={k}>{p.text}</span>
                  : p.kind === "del" ? <del key={k} className="bg-red-50 text-red-700 decoration-red-500">{p.text}</del>
                    : <ins key={k} className="bg-emerald-50 text-emerald-800 decoration-emerald-600 decoration-2">{p.text}</ins>)}
            </p>
            {editable && (
              <div className="mt-2 flex gap-2">
                <button className="btn-ghost px-3 py-1" onClick={() => onDecide(i, "accept")}>✓ {t("rvAccept")}</button>
                <button className="btn-ghost px-3 py-1 text-red-700" onClick={() => onDecide(i, "reject")}>✕ {t("rvReject")}</button>
              </div>
            )}
          </div>
        ))}

        {/* QA flags */}
        {flags.map(({ f, i }) => <FlagRow key={i} f={f} editable={editable} onResolve={(c) => onResolve(i, c)} />)}
        {resolved.map((f, k) => (
          <p key={k} className="text-xs text-emerald-700">
            ✓ {t("rvResolvedBy", { by: f.resolved_by ?? "" })}{f.resolution ? <>: <span dir="auto">{f.resolution}</span></> : null}
          </p>
        ))}
      </div>
    </article>
  );
}

function FlagRow({ f, editable, onResolve }: { f: NonNullable<DocBlock["flags"]>[number]; editable: boolean; onResolve: (c: string) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const blocker = f.severity === "blocker";
  return (
    <div className={`rounded-lg px-3 py-2 text-sm ${blocker ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs" dir="ltr">{f.code}</span>
        {f.message && <span className="flex-1" dir="auto">{f.message}</span>}
        {editable && !open && <button className="ms-auto text-xs font-medium underline" onClick={() => setOpen(true)}>{t("rvResolve")}</button>}
      </div>
      {open && (
        <div className="mt-2 flex flex-wrap gap-2">
          <input className="input min-w-[12rem] flex-1 bg-surface" dir="auto" placeholder={blocker ? t("rvCommentRequired") : t("rvCommentOptional")}
            aria-label={t("rvComment")} value={comment} onChange={(e) => setComment(e.target.value)} />
          <button className="btn-primary px-3 py-1" disabled={blocker && !comment.trim()} onClick={() => onResolve(comment)}>{t("rvResolve")}</button>
          <button className="btn-ghost px-3 py-1" onClick={() => setOpen(false)}>{t("rvCancel")}</button>
        </div>
      )}
    </div>
  );
}

function RerunPanel({ count, dirty, onRun, onClear }: { count: number; dirty: boolean; onRun: (agent: string, instruction: string) => Promise<unknown>; onClear: () => void }) {
  const { t } = useI18n();
  const [agent, setAgent] = useState("translator");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <section className="card border-brand-100 p-4" aria-label={t("rvRerunTitle")}>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="label" htmlFor="rr-agent">{t("rvRerunAgent")}</label>
          <select id="rr-agent" className="input" value={agent} onChange={(e) => setAgent(e.target.value)}>
            {["translator", "proofreader", "qa"].map((a) => <option key={a} value={a}>{t(`agent_${a}`)}</option>)}
          </select>
        </div>
        <div className="min-w-[16rem] flex-1">
          <label className="label" htmlFor="rr-ins">{t("rvRerunInstruction")}</label>
          <input id="rr-ins" className="input" dir="auto" maxLength={2000} value={instruction} placeholder={t("rvRerunInstructionPh")}
            onChange={(e) => setInstruction(e.target.value)} />
        </div>
        <button className="btn-ghost" onClick={onClear}>{t("rvCancel")}</button>
        <button className="btn-primary" disabled={busy || dirty}
          onClick={() => { setBusy(true); onRun(agent, instruction).finally(() => setBusy(false)); }}>
          {t("rvRerunRun", { n: count })}
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">{dirty ? t("rvRerunSaveFirst") : t("rvRerunHint")}</p>
    </section>
  );
}
