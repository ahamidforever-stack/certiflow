import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ArrowLeft, BookOpenText, Check, ChevronRight, Loader2, RotateCw, Search, Trash2 } from "lucide-react";
import { api, type MemoryClient, type MemoryTerm } from "../api";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";

// Glossary memory per client: what was confirmed in earlier jobs, and is offered again in the next ones.

const KINDS = ["name", "organisation", "place", "acronym", "term"];
const fmt = (at: string) => new Date(at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const initials = (s: string) => s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

function TermRow({ term, onSaved, onDeleted }: { term: MemoryTerm; onSaved: (t: MemoryTerm) => void; onDeleted: () => void }) {
  const { t } = useI18n();
  const [target, setTarget] = useState(term.target);
  const [kind, setKind] = useState(term.kind);
  const [busy, setBusy] = useState(false);
  const dirty = target.trim() !== term.target || kind !== term.kind;
  const save = async () => {
    setBusy(true);
    try { onSaved(await api.memoryUpdate(term.id, target.trim(), kind)); toast.success(t("edToastSaved")); }
    catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  };
  const del = async () => {
    if (!window.confirm(t("gmDeleteConfirm"))) return;
    setBusy(true);
    try { await api.memoryDelete(term.id); onDeleted(); } catch (e) { toast.error((e as Error).message); setBusy(false); }
  };
  return (
    <li className={cn("grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-2 px-4 py-3 transition sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_8rem_7.5rem]", dirty && "bg-seal-50/60")}>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-slate-900"><bdi>{term.source}</bdi></div>
        <div className="truncate text-[11px] text-slate-500">{t("gmTimes", { n: term.uses })} · <bdi dir="ltr">{fmt(term.updated_at)}</bdi> · <bdi>{term.updated_by}</bdi></div>
      </div>
      <input className="input col-span-2 py-1.5 sm:col-span-1" dir="auto" aria-label={t("gmTarget")} value={target} onChange={(e) => setTarget(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && dirty && target.trim()) save(); if (e.key === "Escape") { setTarget(term.target); setKind(term.kind); } }} />
      <select className="input py-1.5 text-[13px]" aria-label={t("gmKind")} value={kind} onChange={(e) => setKind(e.target.value)}>
        {KINDS.map((k) => <option key={k} value={k}>{t(`jk_${k}`)}</option>)}
      </select>
      <div className="flex items-center justify-end gap-1">
        {dirty && <button className="btn-primary btn-sm" disabled={busy || !target.trim()} onClick={save}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}{t("gmSave")}</button>}
        <button className="icon-btn h-8 w-8 hover:bg-red-50 hover:text-red-600" disabled={busy} onClick={del} aria-label={t("gmDelete")} title={t("gmDelete")}><Trash2 className="h-4 w-4" /></button>
      </div>
    </li>
  );
}

function ClientTerms({ c, pair, onBack }: { c: MemoryClient; pair: { source: string; target: string }; onBack: () => void }) {
  const { t } = useI18n();
  const [terms, setTerms] = useState<MemoryTerm[] | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const load = () => { setErr(""); api.memoryTerms(c.client, pair.source, pair.target).then(setTerms).catch((e) => setErr(e.message)); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [c.client, pair.source, pair.target]);
  const shown = useMemo(() => {
    const k = q.trim().toLocaleLowerCase();
    return (terms ?? []).filter((x) => !k || x.source.toLocaleLowerCase().includes(k) || x.target.toLocaleLowerCase().includes(k));
  }, [terms, q]);
  return (
    <div className="animate-fade-in">
      <button className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900" onClick={onBack}>
        <ArrowLeft className="h-4 w-4 rtl:-scale-x-100" />{t("gmBack")}
      </button>
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-sm font-semibold text-white"><bdi>{initials(c.client)}</bdi></span>
        <div className="min-w-0">
          <h1 className="page-title truncate"><bdi>{c.client}</bdi></h1>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
            <bdi className="rounded-full border border-slate-200 bg-surface px-2 py-0.5 font-mono uppercase text-slate-600" dir="ltr">{pair.source} → {pair.target}</bdi>
            {terms && t("gmTerms", { n: terms.length })}
          </div>
        </div>
        <label className="relative ms-auto w-full sm:w-64">
          <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input className="input ps-9" type="search" dir="auto" placeholder={t("gmSearch")} aria-label={t("gmSearch")} value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </header>
      {err && <div role="alert" className="mb-4 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{err}<button className="btn-ghost btn-sm ms-auto" onClick={load}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button></div>}
      {!terms && !err && <div className="space-y-2" aria-hidden>{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-14 rounded-xl" />)}</div>}
      {terms && (
        <div className="card overflow-hidden">
          <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_8rem_7.5rem] gap-3 border-b border-slate-200/80 bg-slate-50/70 px-4 py-2 text-[11px] font-semibold text-slate-500 sm:grid">
            <span>{t("gmSource")}</span><span>{t("gmTarget")}</span><span>{t("gmKind")}</span><span />
          </div>
          <ul className="divide-y divide-slate-100">
            {shown.map((x) => (
              <TermRow key={x.id} term={x}
                onSaved={(n) => setTerms((l) => (l ?? []).map((y) => (y.id === n.id ? n : y)))}
                onDeleted={() => setTerms((l) => (l ?? []).filter((y) => y.id !== x.id))} />
            ))}
          </ul>
          {shown.length === 0 && <p className="px-4 py-8 text-center text-sm text-slate-500">{t("gmNoMatch")}</p>}
        </div>
      )}
    </div>
  );
}

export default function Glossaries() {
  const { t } = useI18n();
  const [clients, setClients] = useState<MemoryClient[] | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<{ c: MemoryClient; pair: { source: string; target: string } } | null>(null);
  const load = () => { setErr(""); api.memory().then(setClients).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const shown = useMemo(() => (clients ?? []).filter((c) => !q.trim() || c.client.toLocaleLowerCase().includes(q.trim().toLocaleLowerCase())), [clients, q]);

  if (open) return <ClientTerms c={open.c} pair={open.pair} onBack={() => { setOpen(null); load(); }} />;
  return (
    <div className="animate-fade-in">
      <header className="mb-6 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="page-title">{t("gmTitle")}</h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-500">{t("gmHint")}</p>
        </div>
        {clients && clients.length > 6 && (
          <label className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input className="input ps-9" type="search" dir="auto" placeholder={t("client")} aria-label={t("client")} value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
        )}
      </header>
      {err && <div role="alert" className="mb-4 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{err}<button className="btn-ghost btn-sm ms-auto" onClick={load}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button></div>}
      {!clients && !err && <div className="grid gap-3 sm:grid-cols-2" aria-hidden>{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-28 rounded-xl" />)}</div>}
      {clients && clients.length === 0 && (
        <div className="card flex flex-col items-center px-6 py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600"><BookOpenText className="h-6 w-6" /></span>
          <p className="mt-4 max-w-md text-sm text-slate-600">{t("gmEmpty")}</p>
        </div>
      )}
      {clients && clients.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((c) => (
            <li key={c.client} className="card flex flex-col p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-sm font-semibold text-brand-600"><bdi>{initials(c.client)}</bdi></span>
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-900"><bdi>{c.client}</bdi></div>
                  <div className="text-xs text-slate-500">{t("gmTerms", { n: c.terms })}{c.updated_at && <> · <bdi dir="ltr">{fmt(c.updated_at)}</bdi></>}</div>
                </div>
              </div>
              <div className="mt-3 space-y-1">
                {c.pairs.map((p) => (
                  <button key={p.source + p.target} onClick={() => setOpen({ c, pair: p })}
                    className="group flex w-full items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-start text-sm transition hover:border-brand-300 hover:bg-brand-50/50">
                    <bdi className="font-mono text-xs uppercase text-slate-700" dir="ltr">{p.source} → {p.target}</bdi>
                    <span className="text-xs text-slate-500">{t("gmTerms", { n: p.terms })}</span>
                    <ChevronRight className="ms-auto h-4 w-4 text-slate-400 transition group-hover:text-brand-500 rtl:-scale-x-100" />
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
