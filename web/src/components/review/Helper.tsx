import { forwardRef, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, Copy, CornerDownLeft, MousePointerClick, Sparkles, UserRound } from "lucide-react";
import { api, type AssistReply, type DocBlock } from "../../api";
import { useI18n } from "../../i18n";

// AI helper: questions about one block, answered by the "assistant" agent. It only suggests: "Use this" puts a
// wording into the editor as an unsaved draft; the reviewer saves it as their own edit (normal history).

export type Turn = { q: string; a?: AssistReply; error?: boolean };

interface Props {
  jobId: string; doc: string; block: DocBlock | null; tDir: string; tLang: string; editable: boolean;
  turns: Turn[]; setTurns: (id: string, fn: (t: Turn[]) => Turn[]) => void; onUse: (text: string) => void;
}

const Helper = forwardRef<HTMLTextAreaElement, Props>(function Helper({ jobId, doc, block, tDir, tLang, editable, turns, setTurns, onUse }, inputRef) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [used, setUsed] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const local = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => { setQ(""); setUsed(null); }, [block?.id]);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }); }, [turns.length, busy]);
  useLayoutEffect(() => {
    const el = local.current;
    if (el) { el.style.height = "0px"; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; }
  }, [q]);

  if (!block) return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-brand-50 text-brand-500"><MousePointerClick className="h-5 w-5" /></span>
      <p className="mt-3 text-sm text-slate-600">{t("hpPick")}</p>
      <p className="mt-2 text-xs text-slate-400">{t("hpCost")}</p>
    </div>
  );
  const bid = block.id;
  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setQ(""); setBusy(true);
    setTurns(bid, (x) => [...x, { q: text }]);
    try {
      const a = await api.assist(jobId, doc, bid, text);
      setTurns(bid, (x) => x.map((tn, i) => (i === x.length - 1 ? { ...tn, a } : tn)));
    } catch {
      setTurns(bid, (x) => x.map((tn, i) => (i === x.length - 1 ? { ...tn, error: true } : tn)));
    } finally { setBusy(false); }
  };
  const copy = (text: string, key: string) => { navigator.clipboard?.writeText(text).catch(() => {}); setCopied(key); window.setTimeout(() => setCopied(null), 1500); };
  const isTable = !!block.rows?.length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-slate-200/70 px-3 py-2.5">
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <Sparkles className="h-3.5 w-3.5 text-brand-500" />{t("hpAbout", { id: "" })}<span className="font-mono text-slate-700" dir="ltr">{bid}</span>· {t(`bt_${block.type}`)}
        </div>
        {block.translated_text && <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-slate-700" dir={tDir} lang={tLang}>{block.translated_text}</p>}
      </div>

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3" aria-live="polite">
        {!editable && <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-600">{t("hpReadOnly")}</p>}
        {turns.length === 0 && editable && (
          <div className="space-y-1.5">
            {(["hpQ1", "hpQ2", "hpQ3", "hpQ4"] as const).map((k) => (
              <button key={k} onClick={() => ask(t(k))} disabled={busy}
                className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-surface px-3 py-2 text-start text-[13px] text-slate-700 transition hover:border-brand-300 hover:bg-brand-50/50">
                <Sparkles className="h-3.5 w-3.5 shrink-0 text-brand-400" />{t(k)}
              </button>
            ))}
          </div>
        )}
        {turns.map((tn, i) => (
          <div key={i} className="space-y-2 animate-fade-in">
            <div className="flex justify-end gap-2">
              <p className="max-w-[85%] rounded-2xl rounded-se-sm bg-brand-600 px-3 py-2 text-[13px] leading-snug text-white" dir="auto">{tn.q}</p>
              <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600"><UserRound className="h-3.5 w-3.5" /></span>
            </div>
            {tn.error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{t("hpError")}</p> : !tn.a ? (
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-50 text-brand-500"><Sparkles className="h-3.5 w-3.5 animate-pulse" /></span>
                {t("hpThinking")}
                <span className="flex gap-0.5"><span className="h-1 w-1 animate-bounce rounded-full bg-slate-400" /><span className="h-1 w-1 animate-bounce rounded-full bg-slate-400 [animation-delay:120ms]" /><span className="h-1 w-1 animate-bounce rounded-full bg-slate-400 [animation-delay:240ms]" /></span>
              </div>
            ) : (
              <div className="flex gap-2">
                <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-500"><Sparkles className="h-3.5 w-3.5" /></span>
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-800" dir="auto">{tn.a.answer}</p>
                  {tn.a.suggestions.map((sg, k) => {
                    const key = `${i}-${k}`;
                    return (
                      <div key={k} className="overflow-hidden rounded-xl border border-brand-200/70 bg-surface">
                        <p className="whitespace-pre-wrap px-3 py-2 text-sm leading-relaxed text-slate-900" dir={tDir} lang={tLang}>{sg.text}</p>
                        {sg.note && <p className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-500" dir="auto">{sg.note}</p>}
                        <div className="flex gap-1 border-t border-slate-100 bg-slate-50/60 px-2 py-1.5">
                          {editable && !isTable && (
                            <button className="btn-sm btn rounded-md bg-brand-600 px-2 py-1 text-xs text-white hover:bg-brand-700"
                              onClick={() => { onUse(sg.text); setUsed(key); }}>
                              {used === key ? <Check className="h-3.5 w-3.5" /> : <CornerDownLeft className="h-3.5 w-3.5 rtl:-scale-x-100" />}{t("hpUse")}
                            </button>
                          )}
                          <button className="btn-quiet btn-sm px-2 py-1 text-xs" onClick={() => copy(sg.text, key)}>
                            {copied === key ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}{copied === key ? t("hpCopied") : t("hpCopy")}
                          </button>
                        </div>
                        {used === key && <p className="px-3 pb-2 text-[11px] text-seal-700">{t("hpUsed")}</p>}
                      </div>
                    );
                  })}
                  {isTable && tn.a.suggestions.length > 0 && <p className="text-[11px] text-slate-500">{t("hpTableNote")}</p>}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {editable && (
        <form className="border-t border-slate-200/70 p-2.5" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <div className="flex items-end gap-2 rounded-xl border border-slate-200 bg-surface p-1.5 transition focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-500/10">
            <textarea ref={(el) => { local.current = el; if (typeof inputRef === "function") inputRef(el); else if (inputRef) inputRef.current = el; }}
              rows={1} dir="auto" maxLength={1000} value={q} placeholder={t("hpAsk")} aria-label={t("hpAsk")}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q); } if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur(); }}
              className="max-h-36 min-h-[2rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-[13px] text-slate-900 outline-none placeholder:text-slate-400" />
            <button className="btn-primary btn-sm shrink-0 px-2.5" disabled={busy || !q.trim()} aria-label={t("hpSend")}>
              <Sparkles className="h-3.5 w-3.5" />{t("hpSend")}
            </button>
          </div>
          <p className="mt-1.5 px-1 text-[10px] leading-snug text-slate-400">{t("hpCost")}</p>
        </form>
      )}
    </div>
  );
});

export default Helper;
