import { memo, useLayoutEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CircleCheck, OctagonAlert, Sparkles, X } from "lucide-react";
import type { DocBlock } from "../../api";
import { wordDiff } from "../../diff";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { openFlags, pendingChanges, TONE_BAR, toneOf, type Draft } from "./helpers";

/** A textarea that grows with its text, so a block reads like a paragraph, not a form field. */
function AutoText(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [props.value]);
  return <textarea ref={ref} rows={1} {...props} />;
}

export interface BlockRowProps {
  b: DocBlock; sDir: string; tDir: string; sLang: string; tLang: string; editable: boolean; draft?: Draft;
  selected: boolean; hovered: boolean; picked: boolean; busy: boolean;
  onHover: (on: boolean) => void; onSelect: () => void; onPick: (on: boolean) => void;
  onDraft: (p: Draft) => void; onSave: () => void; onCancel: () => void;
  onDecide: (i: number, d: "accept" | "reject") => void; onResolve: (i: number, comment: string) => void;
}

function BlockRowImpl(p: BlockRowProps) {
  const { b, sDir, tDir, sLang, tLang, editable, draft, selected, hovered, picked, busy } = p;
  const { t } = useI18n();
  const flags = openFlags(b);
  const resolved = (b.flags || []).filter((f) => f.resolved);
  const changes = pendingChanges(b);
  const tone = toneOf(b, !!draft);
  const fieldLabel = (f?: string) => (f && f !== "translated_text" ? f.replace(/rows\[(\d+)\]\[(\d+)\]/, (_, r, c) => t("rvCell", { r: +r + 1, c: +c + 1 })) : "");
  const field = "w-full resize-none rounded-md border border-transparent bg-transparent px-2 py-1.5 leading-relaxed text-slate-900 transition hover:border-slate-200 hover:bg-surface focus:border-brand-400 focus:bg-surface focus:outline-none focus:ring-4 focus:ring-brand-500/10";

  return (
    <article id={`tgt-${b.id}`} data-block={b.id} data-page={b.source_page ?? ""}
      onMouseEnter={() => p.onHover(true)} onMouseLeave={() => p.onHover(false)}
      onClick={(e) => { if ((e.target as HTMLElement).closest("button,textarea,input,a")) return; p.onSelect(); }}
      className={cn("group relative scroll-mt-14 rounded-lg border-s-[3px] py-3 pe-3 ps-3 transition-colors",
        TONE_BAR[tone], selected ? "bg-brand-50/70 dark:bg-brand-100/40" : hovered ? "bg-slate-100/60" : "hover:bg-slate-100/40")}>
      {/* meta line */}
      <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 ps-2 text-[11px] text-slate-500">
        {editable && !b.multilingual_duplicate && (
          <input type="checkbox" checked={picked} onChange={(e) => p.onPick(e.target.checked)} aria-label={t("rvPick", { id: b.id })}
            className={cn("h-3.5 w-3.5 rounded border-slate-300 accent-brand-600 transition", picked ? "opacity-100" : "opacity-0 focus:opacity-100 group-hover:opacity-100")} />
        )}
        <button onClick={p.onSelect} className="rounded font-mono text-slate-500 hover:text-brand-500" dir="ltr" title={t("rvShowOnPage")}>{b.id}</button>
        <span>{t(`bt_${b.type}`)}</span>
        {b.multilingual_duplicate && <span className="rounded bg-slate-100 px-1.5">{t("rvDuplicate")}</span>}
        {busy && <span className="flex items-center gap-1 text-brand-500"><Sparkles className="h-3 w-3 animate-pulse" />{t("edAgentWorking")}</span>}
        <span className="ms-auto flex items-center gap-1">
          {draft && <span className="rounded-full bg-seal-100 px-1.5 font-medium text-seal-700">{t("edEditedMark")}</span>}
          {flags.map(({ f, i }) => (
            <span key={i} className={cn("rounded-full px-1.5 font-medium", f.severity === "blocker" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800")}>{t(`sev_${f.severity}`)}</span>
          ))}
        </span>
      </div>

      {/* source text, in the source language direction */}
      {!b.rows?.length && b.source_text && (
        <p className="mb-1 whitespace-pre-wrap px-2 text-[13px] leading-relaxed text-slate-500" dir={sDir} lang={sLang}>
          {b.label ? `${b.label} ` : ""}{b.source_text}
        </p>
      )}

      {b.rows?.length ? (
        <div className="overflow-x-auto px-2">
          <table className="w-full border-collapse overflow-hidden rounded-md text-sm ring-1 ring-slate-200" dir={tDir} lang={tLang}>
            <tbody>
              {b.rows.map((r, ri) => (
                <tr key={ri} className="border-b border-slate-200 last:border-0">
                  {r.cells.map((c, ci) => {
                    const key = `${ri},${ci}`;
                    const val = draft?.cells?.[key] ?? c.translated_text ?? "";
                    return (
                      <td key={ci} colSpan={c.colspan ?? 1} className={cn("border-e border-slate-200 p-1.5 align-top last:border-e-0", (r.header || c.header) && "bg-slate-50 font-medium")}>
                        {c.source_text && <div className="mb-0.5 px-2 text-[11px] text-slate-500" dir={sDir} lang={sLang}>{c.source_text}</div>}
                        {editable && !c.blocks ? (
                          <AutoText aria-label={t("rvCell", { r: ri + 1, c: ci + 1 })} className={cn(field, "px-2 py-1 text-sm")} value={val}
                            onChange={(e) => p.onDraft({ cells: { [key]: e.target.value } })}
                            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); p.onSave(); } }} />
                        ) : <div className="whitespace-pre-wrap px-2 py-1">{c.translated_text}</div>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : b.type === "page_break" ? null : editable ? (
        <AutoText aria-label={t("rvTranslationOf", { id: b.id })} dir={tDir} lang={tLang}
          className={cn(field, "text-[15px]", b.type === "heading" && "text-base font-semibold", b.type === "note" && "italic text-brand-600")}
          value={draft?.text ?? b.translated_text ?? ""} onChange={(e) => p.onDraft({ text: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); p.onSave(); }
            if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur();
          }} />
      ) : (
        <p className={cn("whitespace-pre-wrap px-2 py-1.5 text-[15px] leading-relaxed text-slate-900", b.type === "heading" && "font-semibold", b.type === "note" && "italic text-brand-600")} dir={tDir} lang={tLang}>{b.translated_text}</p>
      )}

      {draft && (
        <div className="mt-2 flex items-center justify-end gap-2 px-2 animate-fade-in">
          <button className="btn-quiet btn-sm" onClick={p.onCancel}>{t("rvCancel")}</button>
          <button className="btn-primary btn-sm" onClick={p.onSave}>{t("rvSave")}<kbd aria-hidden className="kbd border-white/30 bg-white/10 text-white/80" dir="ltr">Ctrl ↵</kbd></button>
        </div>
      )}

      {/* tracked changes from the agents */}
      {changes.map(({ h, i }) => (
        <div key={i} className="mx-2 mt-2 overflow-hidden rounded-lg border border-brand-200/70 bg-surface">
          <div className="flex flex-wrap items-center gap-2 border-b border-brand-100 bg-brand-50/60 px-3 py-1.5 text-xs text-slate-600">
            <Sparkles className="h-3.5 w-3.5 text-brand-500" />
            <span className="font-medium text-slate-700">{t("rvChangeBy", { agent: t(`agent_${h.actor}`) })}</span>
            {fieldLabel(h.field) && <span>· {fieldLabel(h.field)}</span>}
            {h.reason && <span className="text-slate-500" dir="auto">· {h.reason}</span>}
          </div>
          <p className="whitespace-pre-wrap px-3 py-2 text-sm leading-relaxed" dir={tDir} lang={tLang}>
            {wordDiff(h.old ?? "", h.new ?? "").map((d, k) =>
              d.kind === "same" ? <span key={k}>{d.text}</span>
                : d.kind === "del" ? <del key={k} className="rounded-sm bg-red-50 text-red-700 decoration-red-500">{d.text}</del>
                  : <ins key={k} className="rounded-sm bg-emerald-50 text-emerald-800 decoration-emerald-600 decoration-2 underline-offset-2">{d.text}</ins>)}
          </p>
          {editable && (
            <div className="flex gap-1.5 px-3 pb-2.5">
              <button className="btn-ghost btn-sm border-emerald-200 text-emerald-700 hover:border-emerald-300 hover:bg-emerald-50" onClick={() => p.onDecide(i, "accept")}>
                <Check className="h-3.5 w-3.5" />{t("rvAccept")}<kbd aria-hidden className="kbd">A</kbd></button>
              <button className="btn-ghost btn-sm text-red-700 hover:border-red-200 hover:bg-red-50" onClick={() => p.onDecide(i, "reject")}>
                <X className="h-3.5 w-3.5" />{t("rvReject")}<kbd aria-hidden className="kbd">R</kbd></button>
            </div>
          )}
        </div>
      ))}

      {/* QA flags */}
      {flags.map(({ f, i }) => <FlagRow key={i} f={f} editable={editable} onResolve={(c) => p.onResolve(i, c)} />)}
      {resolved.length > 0 && (
        <div className="mt-1.5 space-y-0.5 px-2">
          {resolved.map((f, k) => (
            <p key={k} className="flex items-center gap-1.5 text-xs text-emerald-700">
              <CircleCheck className="h-3.5 w-3.5" />{t("rvResolvedBy", { by: f.resolved_by ?? "" })}{f.resolution ? <>: <span dir="auto">{f.resolution}</span></> : null}
            </p>
          ))}
        </div>
      )}
    </article>
  );
}

export const BlockRow = memo(BlockRowImpl);

function FlagRow({ f, editable, onResolve }: { f: NonNullable<DocBlock["flags"]>[number]; editable: boolean; onResolve: (c: string) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const blocker = f.severity === "blocker";
  return (
    <div className={cn("mx-2 mt-2 rounded-lg px-3 py-2 text-sm", blocker ? "bg-red-50 text-red-800" : "bg-amber-50 text-amber-900")}>
      <div className="flex flex-wrap items-center gap-2">
        {blocker ? <OctagonAlert className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
        {f.message && <span className="flex-1" dir="auto">{f.message}</span>}
        <span className="font-mono text-[10px] opacity-70" dir="ltr">{f.code}</span>
        {editable && !open && (
          <button className={cn("btn-sm btn rounded-md bg-surface/70 ring-1", blocker ? "ring-red-200 hover:bg-surface" : "ring-amber-200 hover:bg-surface")} onClick={() => setOpen(true)}>{t("rvResolve")}</button>
        )}
      </div>
      {open && (
        <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (!blocker || comment.trim()) onResolve(comment); }}>
          <input autoFocus className="input min-w-[12rem] flex-1 py-1.5" dir="auto" placeholder={blocker ? t("rvCommentRequired") : t("rvCommentOptional")}
            aria-label={t("rvComment")} value={comment} onChange={(e) => setComment(e.target.value)} />
          <button className="btn-primary btn-sm" disabled={blocker && !comment.trim()}>{t("rvResolve")}</button>
          <button type="button" className="btn-quiet btn-sm" onClick={() => setOpen(false)}>{t("rvCancel")}</button>
        </form>
      )}
    </div>
  );
}
