import { useEffect, useMemo, useState } from "react";
import { api, type MemoryClient, type MemoryTerm } from "../api";
import { useI18n } from "../i18n";

// Glossary memory per client: what was confirmed in earlier jobs, and is offered again in the next ones.

const KINDS = ["name", "organisation", "place", "acronym", "term"];
const fmt = (at: string) => new Date(at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

function TermRow({ term, onSaved, onDeleted }: { term: MemoryTerm; onSaved: (t: MemoryTerm) => void; onDeleted: () => void }) {
  const { t } = useI18n();
  const [target, setTarget] = useState(term.target);
  const [kind, setKind] = useState(term.kind);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const dirty = target.trim() !== term.target || kind !== term.kind;
  const save = async () => {
    setBusy(true); setErr("");
    try { onSaved(await api.memoryUpdate(term.id, target.trim(), kind)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const del = async () => {
    if (!window.confirm(t("gmDeleteConfirm"))) return;
    setBusy(true);
    try { await api.memoryDelete(term.id); onDeleted(); } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  return (
    <tr className="align-top">
      <td className="py-2 pe-3"><div className="pt-2 font-medium text-slate-900" dir="auto">{term.source}</div></td>
      <td className="py-2 pe-3">
        <input className="input" dir="auto" aria-label={t("gmTarget")} value={target} onChange={(e) => setTarget(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && dirty && target.trim()) save(); }} />
        {err && <div role="alert" className="mt-1 text-xs text-red-700">{err}</div>}
      </td>
      <td className="py-2 pe-3">
        <select className="input" aria-label={t("gmKind")} value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </td>
      <td className="whitespace-nowrap py-2 pe-3 pt-4 text-xs text-slate-500">
        {t("gmTimes", { n: term.uses })} · <bdi dir="ltr">{fmt(term.updated_at)}</bdi> · <bdi>{term.updated_by}</bdi>
      </td>
      <td className="whitespace-nowrap py-2 text-end">
        {dirty && <button className="btn-primary me-2 px-3 py-1.5" disabled={busy || !target.trim()} onClick={save}>{t("gmSave")}</button>}
        <button className="pt-2 text-xs text-red-600 hover:underline disabled:opacity-40" disabled={busy} onClick={del}>{t("gmDelete")}</button>
      </td>
    </tr>
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
    <div className="space-y-4">
      <button className="text-sm text-brand-500 hover:underline" onClick={onBack}><span className="inline-block rtl:rotate-180">←</span> {t("gmBack")}</button>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900"><bdi>{c.client}</bdi></h1>
        <span className="rounded-full border border-slate-300 px-2.5 py-0.5 font-mono text-xs uppercase text-slate-600" dir="ltr">{pair.source} → {pair.target}</span>
        <input className="input ms-auto max-w-xs" type="search" placeholder={t("gmSearch")} aria-label={t("gmSearch")} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>}
      {!terms && !err && <div className="card p-5 text-sm text-slate-500">…</div>}
      {terms && (
        <div className="card overflow-x-auto p-5">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="text-xs text-slate-500"><tr>
              <th className="pb-2 text-start font-medium">{t("gmSource")}</th>
              <th className="pb-2 text-start font-medium">{t("gmTarget")}</th>
              <th className="w-36 pb-2 text-start font-medium">{t("gmKind")}</th>
              <th className="pb-2 text-start font-medium">{t("gmLast")}</th>
              <th />
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((x) => (
                <TermRow key={x.id} term={x}
                  onSaved={(n) => setTerms((l) => (l ?? []).map((y) => (y.id === n.id ? n : y)))}
                  onDeleted={() => setTerms((l) => (l ?? []).filter((y) => y.id !== x.id))} />
              ))}
            </tbody>
          </table>
          {shown.length === 0 && <p className="mt-3 text-sm text-slate-500">{t("gmNoMatch")}</p>}
        </div>
      )}
    </div>
  );
}

export default function Glossaries() {
  const { t } = useI18n();
  const [clients, setClients] = useState<MemoryClient[] | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<{ c: MemoryClient; pair: { source: string; target: string } } | null>(null);
  const load = () => { setErr(""); api.memory().then(setClients).catch((e) => setErr(e.message)); };
  useEffect(load, []);

  if (open) return <ClientTerms c={open.c} pair={open.pair} onBack={() => { setOpen(null); load(); }} />;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{t("gmTitle")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("gmHint")}</p>
      </div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>}
      {!clients && !err && <div className="card p-5 text-sm text-slate-500">…</div>}
      {clients && clients.length === 0 && <div className="card p-5 text-sm text-slate-500">{t("gmEmpty")}</div>}
      {clients && clients.length > 0 && (
        <ul className="card divide-y divide-slate-100">
          {clients.map((c) => (
            <li key={c.client} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <div className="font-medium text-slate-900"><bdi>{c.client}</bdi></div>
                <div className="text-xs text-slate-500">{t("gmTerms", { n: c.terms })}{c.updated_at && <> · <bdi dir="ltr">{fmt(c.updated_at)}</bdi></>}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                {c.pairs.map((p) => (
                  <button key={p.source + p.target} onClick={() => setOpen({ c, pair: p })}
                    className="rounded-full border border-slate-300 px-3 py-1 text-sm hover:border-brand-500 hover:text-brand-600">
                    <span className="font-mono text-xs uppercase" dir="ltr">{p.source} → {p.target}</span> <span className="text-slate-500">· {p.terms}</span>
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
