import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { toast } from "sonner";
import { ArrowLeft, CheckCheck, FileText, Keyboard, ListChecks, Lock, PanelRightClose, PanelRightOpen, RotateCw, Save, Sparkles, X } from "lucide-react";
import { api, type DocBlock, type DocModel, type Job, type Language, type ReviewResult } from "../api";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import { SealRing } from "../components/Seal";
import { progressOf } from "../lib/jobs";
import { BlockRow } from "../components/review/BlockRow";
import SourcePane from "../components/review/SourcePane";
import Checklist from "../components/review/Checklist";
import { RerunDialog, ShortcutsDialog } from "../components/review/Dialogs";
import { isTyping, needsLook, openFlags, pendingChanges, type Draft, type Filter, type SaveState } from "../components/review/helpers";

// Review workspace: checklist | source pages | translation, full height, each pane scrolling on its own.
// Every save goes to the API, which records history and writes <doc>.reviewed.json. The model never edits directly.

const readBool = (k: string, d: boolean) => { try { const v = window.localStorage.getItem(k); return v == null ? d : v === "1"; } catch { return d; } };
const writeBool = (k: string, v: boolean) => { try { window.localStorage.setItem(k, v ? "1" : "0"); } catch { /* private mode */ } };

function useMedia(q: string) {
  const [m, setM] = useState(() => window.matchMedia?.(q).matches ?? true);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return;
    const on = (e: MediaQueryListEvent) => setM(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return m;
}

export default function Review() {
  const { id = "", doc = "" } = useParams();
  const { t, dir } = useI18n();
  const nav = useNavigate();
  const wide = useMedia("(min-width: 1024px)");
  const [job, setJob] = useState<Job | null>(null);
  const [model, setModel] = useState<DocModel | null>(null);
  const [langs, setLangs] = useState<Language[]>([]);
  const [loadErr, setLoadErr] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [save, setSave] = useState<SaveState>("saved");
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());   // blocks chosen for a re-run
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set()); // blocks an agent is re-running
  const [filter, setFilter] = useState<Filter>("all");
  const [showList, setShowList] = useState(() => readBool("cf_rv_list", true));
  const [follow, setFollow] = useState(() => readBool("cf_rv_follow", true));
  const [view, setView] = useState<"src" | "tgt" | "list">("tgt");   // phones: one pane at a time
  const [help, setHelp] = useState(false);
  const [rerunOpen, setRerunOpen] = useState(false);
  const srcRef = useRef<HTMLDivElement>(null);
  const tgtRef = useRef<HTMLDivElement>(null);
  const quietUntil = useRef(0);   // pause "follow" while we scroll on purpose
  const lastPage = useRef<number | null>(null);

  const load = useCallback(() => {
    setLoadErr("");
    Promise.all([api.job(id), api.documentModel(id, doc), api.languages()])
      .then(([j, m, l]) => { setJob(j); setModel(m.model); setLangs(l); })
      .catch((e) => setLoadErr(e.message));
  }, [id, doc]);
  useEffect(() => { setDrafts({}); setSave("saved"); setSelected(null); load(); }, [load]);

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
    setBusyIds(new Set());
    if (j.error) toast.error(j.error);
    return api.documentModel(id, doc).then((m) => setModel(m.model));
  });
  useEffect(() => {
    if (!reworking) return;
    const h = window.setInterval(() => { refreshAfterRerun().catch(() => {}); }, 2000);
    return () => window.clearInterval(h);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reworking, id, doc]);

  const startRerun = (agent: string, instruction: string) => {
    const ids = [...picked];
    return api.rerun(id, doc, agent, ids, instruction)
      .then(() => { setBusyIds(new Set(ids)); setPicked(new Set()); toast(t("edToastRerun", { n: ids.length })); return refreshAfterRerun(); })
      .catch((e) => toast.error(e.message));
  };
  const dirOf = (code?: string) => langs.find((l) => l.code === code)?.direction ?? "ltr";

  const apply = (p: Promise<ReviewResult>) => {
    setSave("saving");
    return p.then((r) => { setModel(r.model); setSave(Object.keys(drafts).length > 1 ? "dirty" : "saved"); return true; })
      .catch((e) => { toast.error(e.message); setSave("error"); return false; });
  };

  const saveBlock = async (b: DocBlock) => {
    const d = drafts[b.id];
    if (!d) return true;
    const cells = d.cells ? Object.entries(d.cells).map(([k, text]) => { const [row, col] = k.split(",").map(Number); return { row, col, text }; }) : undefined;
    const ok = await apply(api.editBlock(id, doc, b.id, { text: d.text, cells }));
    if (ok) setDrafts((x) => { const y = { ...x }; delete y[b.id]; if (!Object.keys(y).length) setSave("saved"); return y; });
    return ok;
  };
  const saveAll = async () => {
    let n = 0;
    for (const b of model?.blocks ?? []) if (drafts[b.id]) { if (!(await saveBlock(b))) return; n++; }
    if (n) toast.success(t("edToastSaved"));
  };
  const decide = (b: DocBlock, i: number, d: "accept" | "reject") =>
    apply(api.decideChange(id, doc, b.id, i, d)).then((ok) => { if (ok) toast.success(t(d === "accept" ? "edToastAccepted" : "edToastRejected")); });
  const resolve = (b: DocBlock, i: number, c: string) =>
    apply(api.resolveFlag(id, doc, b.id, i, c)).then((ok) => { if (ok) toast.success(t("edToastResolved")); });

  const setDraft = (b: DocBlock, patch: Draft) => {
    setDrafts((x) => ({ ...x, [b.id]: { ...x[b.id], ...patch, cells: { ...x[b.id]?.cells, ...patch.cells } } }));
    setSave("dirty");
  };

  const blocks = useMemo(() => (model?.blocks ?? []).filter((b) => b.type !== "page_break"), [model]);
  const pending = useMemo(() => blocks.flatMap((b) => pendingChanges(b).map((c) => ({ b, ...c }))), [blocks]);
  const acceptAll = async () => {
    for (const c of pending) if (!(await apply(api.decideChange(id, doc, c.b.id, c.i, "accept")))) return;
    toast.success(t("edToastAccepted"));
  };
  const pages = useMemo(() => {
    const n = new Set<number>((model?.pages ?? []).map((p) => p.number));
    for (const b of model?.blocks ?? []) if (b.source_page) n.add(b.source_page);
    return [...n].sort((a, b) => a - b);
  }, [model]);

  const shown = useMemo(() => blocks.filter((b) =>
    filter === "all" || (filter === "issues" && openFlags(b).length > 0) || (filter === "changes" && pendingChanges(b).length > 0) || (filter === "edited" && !!drafts[b.id])),
  [blocks, filter, drafts]);

  /** Select a block and bring it into view on the other side(s). */
  const focus = useCallback((bid: string, from: "src" | "tgt" | "list") => {
    setSelected(bid);
    quietUntil.current = Date.now() + 1000;
    const run = () => {
      if (from !== "tgt") document.getElementById(`tgt-${bid}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      if (from !== "src") document.getElementById(`src-${bid}`)?.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    };
    if (!wide && from !== "tgt") { setView("tgt"); window.setTimeout(run, 60); } else run();
  }, [wide]);

  // Follow: when the translation scrolls to another page, bring that source page into view.
  useEffect(() => {
    const root = tgtRef.current;
    if (!root || !follow) return;
    const io = new IntersectionObserver((entries) => {
      if (Date.now() < quietUntil.current) return;
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      const page = Number((top?.target as HTMLElement | undefined)?.dataset.page);
      if (!page || page === lastPage.current) return;
      lastPage.current = page;
      document.getElementById(`src-page-${page}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, { root, rootMargin: "-15% 0px -70% 0px" });
    root.querySelectorAll("[data-block]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [follow, shown, wide, view]);

  // Keyboard: J/K walk the items to check, A/R decide, Ctrl+S saves, [ toggles the checklist, ? shows help.
  const keyRef = useRef<(e: KeyboardEvent) => void>(() => {});
  keyRef.current = (e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveAll(); return; }
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey || help || rerunOpen) return;
    const k = e.key.toLowerCase();
    if (k === "j" || k === "k") {
      const ids = shown.map((b) => b.id);
      const todo = shown.filter(needsLook).map((b) => b.id);
      if (!todo.length) return;
      const cur = selected ? ids.indexOf(selected) : -1;
      const next = k === "j"
        ? todo.find((x) => ids.indexOf(x) > cur) ?? todo[0]
        : [...todo].reverse().find((x) => ids.indexOf(x) < cur) ?? todo[todo.length - 1];
      e.preventDefault(); focus(next, "list");
    } else if ((k === "a" || k === "r") && editable && selected) {
      const b = blocks.find((x) => x.id === selected);
      const c = b && pendingChanges(b)[0];
      if (b && c) { e.preventDefault(); decide(b, c.i, k === "a" ? "accept" : "reject"); }
    } else if (e.key === "[") { e.preventDefault(); toggleList(); }
    else if (e.key === "?") { e.preventDefault(); setHelp(true); }
  };
  useEffect(() => {
    const h = (e: KeyboardEvent) => keyRef.current(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const toggleList = () => setShowList((v) => { writeBool("cf_rv_list", !v); return !v; });
  const setFollowP = (v: boolean) => { setFollow(v); writeBool("cf_rv_follow", v); };
  const leave = (to: string) => { if (!dirty || window.confirm(t("rvLeaveConfirm"))) nav(to); };

  if (loadErr) return (
    <div className="mx-auto mt-16 flex max-w-lg items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <span className="flex-1">{t("rvLoadError")}</span><button className="btn-ghost btn-sm" onClick={load}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button>
    </div>
  );
  if (!job || !model) return <EditorSkeleton />;

  const sDir = dirOf(model.source_language), tDir = dirOf(model.target_language);
  const blockersN = blocks.filter((b) => openFlags(b).some(({ f }) => f.severity === "blocker")).length;
  const counts = { issues: blocks.filter((b) => openFlags(b).length).length, changes: blocks.filter((b) => pendingChanges(b).length).length, edited: Object.keys(drafts).length };
  const dirtyIds = Object.keys(drafts);

  const checklist = <Checklist jobId={id} blocks={blocks} editable={!!editable} dirtyIds={dirtyIds} selected={selected} onJump={(x) => focus(x, "list")} />;
  const source = (
    <SourcePane ref={srcRef} jobId={id} doc={doc} lang={model.source_language} blocks={blocks} pages={pages}
      selected={selected} hovered={hovered} follow={follow} onFollow={setFollowP} onHover={setHovered} onPick={(x) => focus(x, "src")} />
  );
  const translation = (
    <section className="flex h-full min-h-0 flex-col bg-slate-50" aria-label={t("rvTargetPane")}>
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-slate-200/80 bg-surface px-3">
        <h2 className="text-sm font-medium text-slate-700">
          {t("rvTargetPane")} <span className="font-mono text-[11px] uppercase text-slate-400" dir="ltr">{model.target_language}</span>
        </h2>
        <div className="ms-auto flex items-center gap-0.5 rounded-lg bg-slate-100 p-0.5 text-xs" role="tablist" aria-label={t("edFilterAll")}>
          {(["all", "issues", "changes", "edited"] as Filter[]).map((f) => (
            (f === "all" || counts[f as keyof typeof counts] > 0 || filter === f) && (
              <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}
                className={cn("flex items-center gap-1 rounded-md px-2 py-1 font-medium transition", filter === f ? "bg-surface text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800")}>
                {t(`edFilter${f[0].toUpperCase()}${f.slice(1)}`)}
                {f !== "all" && <span className="tabular-nums text-slate-400">{counts[f as keyof typeof counts]}</span>}
              </button>
            )
          ))}
        </div>
      </header>
      {reworking && (
        <p role="status" className="flex items-center gap-2 border-b border-brand-100 bg-brand-50 px-4 py-2 text-sm text-brand-700">
          <Sparkles className="h-4 w-4 animate-pulse" />{t("rvReworking")}
        </p>
      )}
      {!editable && !reworking && (
        <p className="flex items-center gap-2 border-b border-slate-200 bg-slate-100 px-4 py-2 text-sm text-slate-600"><Lock className="h-3.5 w-3.5" />{t("rvReadOnly")}</p>
      )}
      <div ref={tgtRef} className="relative min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-2 pb-24 pt-2 sm:px-4">
          {shown.length === 0 && <p className="py-16 text-center text-sm text-slate-500">{t("edNoMatch")}</p>}
          {shown.map((b, i) => {
            const newPage = b.source_page && b.source_page !== shown[i - 1]?.source_page;
            return (
              <div key={b.id}>
                {newPage && (
                  <div className="sticky top-0 z-10 -mx-2 flex items-center gap-3 bg-slate-50/90 px-2 py-2 backdrop-blur sm:-mx-4 sm:px-4">
                    <span className="text-[11px] font-semibold text-slate-500">{t("rvPage")} <bdi>{b.source_page}</bdi></span>
                    <span className="h-px flex-1 bg-slate-200" />
                  </div>
                )}
                <BlockRow b={b} sDir={sDir} tDir={tDir} sLang={model.source_language} tLang={model.target_language}
                  editable={!!editable} draft={drafts[b.id]} selected={selected === b.id} hovered={hovered === b.id}
                  picked={picked.has(b.id)} busy={busyIds.has(b.id)}
                  onHover={(on) => setHovered(on ? b.id : null)} onSelect={() => focus(b.id, "tgt")}
                  onPick={(on) => setPicked((x) => { const y = new Set(x); if (on) y.add(b.id); else y.delete(b.id); return y; })}
                  onDraft={(p) => setDraft(b, p)} onSave={() => saveBlock(b)}
                  onCancel={() => setDrafts((x) => { const y = { ...x }; delete y[b.id]; if (!Object.keys(y).length) setSave("saved"); return y; })}
                  onDecide={(ci, d) => decide(b, ci, d)} onResolve={(fi, c) => resolve(b, fi, c)} />
              </div>
            );
          })}
        </div>
        {/* selection bar for re-runs */}
        {editable && picked.size > 0 && (
          <div className="pointer-events-none sticky bottom-4 z-20 flex justify-center px-4">
            <div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-slate-200 bg-raised py-1.5 pe-1.5 ps-4 shadow-float animate-fade-in">
              <span className="text-sm font-medium text-slate-700">{t("edSelected", { n: picked.size })}</span>
              <button className="btn-quiet btn-sm" onClick={() => setPicked(new Set())}><X className="h-3.5 w-3.5" />{t("edClearSelection")}</button>
              <button className="btn-primary btn-sm" onClick={() => setRerunOpen(true)}><Sparkles className="h-3.5 w-3.5" />{t("edRerunOpen")}</button>
            </div>
          </div>
        )}
      </div>
    </section>
  );

  const handle = (
    <PanelResizeHandle className="group relative w-px bg-slate-200 outline-none transition-colors data-[resize-handle-state=drag]:bg-brand-400 data-[resize-handle-state=hover]:bg-brand-300">
      <span className="absolute inset-y-0 -start-1.5 -end-1.5" />
      <span className="absolute top-1/2 start-1/2 h-8 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300 opacity-0 transition group-data-[resize-handle-state=drag]:opacity-100 group-data-[resize-handle-state=hover]:opacity-100 rtl:translate-x-1/2" />
    </PanelResizeHandle>
  );

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col bg-slate-50 lg:h-dvh">
      {/* toolbar */}
      <header className="flex min-h-[3.5rem] shrink-0 items-center gap-x-2 gap-y-2 sm:gap-x-3 border-b border-slate-200/80 bg-surface px-3 py-2 lg:px-4">
        <button onClick={() => leave(`/jobs/${id}`)} className="icon-btn" aria-label={t("rvBackToJob")} title={t("rvBackToJob")}>
          <ArrowLeft className="h-[18px] w-[18px] rtl:-scale-x-100" />
        </button>
        <SealRing progress={progressOf(job)} size={26} className="hidden sm:block" />
        <div className="min-w-0 flex-1 leading-tight lg:flex-none">
          <div className="truncate text-[11px] text-slate-500">{[job.title !== model.title ? job.title : null, job.client].filter(Boolean).map((x, i) => <span key={i}>{i > 0 && " · "}<bdi>{x}</bdi></span>)}</div>
          <h1 className="truncate font-serif text-[17px] text-slate-900"><bdi>{model.title}</bdi></h1>
        </div>
        {(job.documents?.length ?? 0) > 1 && (
          <nav className="flex gap-0.5 rounded-lg bg-slate-100 p-0.5" aria-label={t("documents")}>
            {job.documents!.map((d) => (
              <button key={d.key} onClick={() => d.key !== doc && leave(`/jobs/${id}/review/${d.key}`)} title={d.title} aria-current={d.key === doc ? "page" : undefined}
                className={cn("flex items-center gap-1 rounded-md px-2 py-1 text-xs transition", d.key === doc ? "bg-surface font-medium text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800")}>
                <FileText className="h-3 w-3" /><span className="font-mono" dir="ltr">{d.key}</span>
                {!!d.open_flags?.blocker && <span className="h-1.5 w-1.5 rounded-full bg-red-500" />}
              </button>
            ))}
          </nav>
        )}
        <div className="ms-auto flex items-center gap-1.5">
          <SaveBadge state={save} />
          {blockersN > 0 && <span className="hidden rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 2xl:inline">{t("rvBlockersOpen", { n: blockersN })}</span>}
          {editable && pending.length > 0 && (
            <button className="btn-ghost btn-sm" onClick={acceptAll} disabled={save === "saving"} title={t("rvAcceptAll")} aria-label={t("rvAcceptAll")}><CheckCheck className="h-3.5 w-3.5" /><span className="hidden xl:inline">{t("rvAcceptAll")}</span></button>
          )}
          {editable && (
            <a className={cn("btn-ghost btn-sm", dirty && "pointer-events-none opacity-40")} aria-disabled={dirty}
              href={`/api/jobs/${id}/documents/${doc}/preview.pdf`} target="_blank" rel="noopener"
              title={dirty ? t("rvPreviewSaveFirst") : t("rvPreviewHint")} aria-label={t("rvPreview")}><FileText className="h-3.5 w-3.5" /><span className="hidden xl:inline">{t("rvPreview")}</span></a>
          )}
          {editable && (
            <button className="btn-primary btn-sm" onClick={saveAll} disabled={!dirty || save === "saving"} title="Ctrl+S">
              <Save className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t("rvSaveAll")}</span>
            </button>
          )}
          <span className="mx-0.5 hidden h-5 w-px bg-slate-200 lg:block" />
          <button className="icon-btn hidden h-8 w-8 lg:inline-flex" onClick={() => setHelp(true)} aria-label={t("edShortcuts")} title={`${t("edShortcuts")} (?)`}><Keyboard className="h-4 w-4" /></button>
          <button className="icon-btn hidden h-8 w-8 lg:inline-flex" onClick={toggleList} aria-pressed={showList}
            aria-label={showList ? t("edHideChecklist") : t("edShowChecklist")} title={`${showList ? t("edHideChecklist") : t("edShowChecklist")} ([)`}>
            {showList ? <PanelRightClose className="h-4 w-4 -scale-x-100 rtl:scale-x-100" /> : <PanelRightOpen className="h-4 w-4 -scale-x-100 rtl:scale-x-100" />}
          </button>
        </div>
      </header>

      {wide ? (
        <PanelGroup direction="horizontal" dir={dir} autoSaveId={showList ? "cf-review-3" : "cf-review-2"} className="min-h-0 flex-1">
          {showList && (<>
            <Panel id="list" order={1} defaultSize={20} minSize={14} maxSize={32}>{checklist}</Panel>
            {handle}
          </>)}
          <Panel id="src" order={2} defaultSize={showList ? 38 : 46} minSize={20}>{source}</Panel>
          {handle}
          <Panel id="tgt" order={3} defaultSize={showList ? 42 : 54} minSize={28}>{translation}</Panel>
        </PanelGroup>
      ) : (
        <>
          <div className="flex shrink-0 gap-1 border-b border-slate-200 bg-surface p-1.5" role="tablist">
            {([["src", "edViewSource"], ["tgt", "edViewTranslation"], ["list", "edViewChecklist"]] as const).map(([v, k]) => (
              <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
                className={cn("flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-sm font-medium transition", view === v ? "bg-slate-100 text-slate-900" : "text-slate-500")}>
                {v === "list" && <ListChecks className="h-4 w-4" />}{t(k)}
                {v === "list" && counts.issues + counts.changes > 0 && <span className="rounded-full bg-red-50 px-1.5 text-[11px] text-red-700">{counts.issues + counts.changes}</span>}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">{view === "src" ? source : view === "list" ? checklist : translation}</div>
        </>
      )}

      <ShortcutsDialog open={help} onOpenChange={setHelp} />
      <RerunDialog open={rerunOpen} onOpenChange={setRerunOpen} count={picked.size} dirty={dirty} onRun={startRerun} />
    </div>
  );
}

function SaveBadge({ state }: { state: SaveState }) {
  const { t } = useI18n();
  const map: Record<SaveState, string> = {
    saved: "text-emerald-700", saving: "text-brand-500", dirty: "text-seal-700", error: "text-red-700",
  };
  const dot: Record<SaveState, string> = { saved: "bg-emerald-500", saving: "bg-brand-400 animate-pulse", dirty: "bg-seal-500", error: "bg-red-500" };
  return (
    <span role="status" className={cn("flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", map[state])}>
      <span className={cn("h-1.5 w-1.5 rounded-full", dot[state])} /><span className="hidden sm:inline">{t(`rvSave_${state}`)}</span>
    </span>
  );
}

function EditorSkeleton() {
  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col lg:h-dvh" aria-hidden>
      <div className="flex h-14 items-center gap-3 border-b border-slate-200 bg-surface px-4"><div className="skeleton h-6 w-6 rounded-full" /><div className="skeleton h-4 w-48" /></div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px lg:grid-cols-[1fr_1fr]">
        <div className="hidden bg-slate-100 p-6 lg:block"><div className="skeleton mx-auto aspect-[1/1.41] max-w-md" /></div>
        <div className="space-y-4 p-6">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-16" />)}</div>
      </div>
    </div>
  );
}
