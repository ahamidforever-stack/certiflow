import { useEffect, useState } from "react";
import { api, type ClientsAdmin } from "../api";
import { useI18n } from "../i18n";

// Admin: per-client access groups. A client with members is restricted to them (and admins).

function MemberPicker({ data, client, initial, onSaved, onCancel }: { data: ClientsAdmin; client: string; initial: string[];
  onSaved: (d: ClientsAdmin) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const [sel, setSel] = useState<string[]>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const toggle = (u: string) => setSel((x) => (x.includes(u) ? x.filter((y) => y !== u) : [...x, u]));
  const save = async () => {
    setBusy(true); setErr("");
    try { onSaved(await api.adminSetMembers(client, sel)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="mt-3 rounded-lg border border-brand-100 bg-brand-50/40 p-4">
      <fieldset>
        <legend className="sr-only">{t("clEditAccess")}</legend>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {data.accounts.map((u) => (
            <label key={u.username} className="flex items-center gap-2 text-sm text-slate-800">
              <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={sel.includes(u.username)} onChange={() => toggle(u.username)} />
              <bdi>{u.name}</bdi> <span className="text-xs text-slate-500">· {t(`role_${u.role}`)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <p className="mt-2 text-xs text-slate-500">{t("clMembersHint")}</p>
      {err && <div role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="mt-3 flex gap-2">
        <button className="btn-primary" disabled={busy} onClick={save}>{t("clSaveAccess")}</button>
        <button className="btn-ghost" onClick={onCancel}>{t("usCancel")}</button>
      </div>
    </div>
  );
}

export default function Clients() {
  const { t } = useI18n();
  const [data, setData] = useState<ClientsAdmin | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const load = () => { setErr(""); api.adminClients().then(setData).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const saved = (d: ClientsAdmin) => { setData(d); setOpen(null); setNewName(""); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-serif text-xl font-medium text-slate-900">{t("clTitle")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("clHint")}</p>
      </div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>}
      {!data && !err && <div className="space-y-2" aria-hidden>{[0, 1, 2].map((i) => <div key={i} className="skeleton h-14 rounded-xl" />)}</div>}
      {data && (
        <>
          {data.clients.length === 0 ? <div className="card p-5 text-sm text-slate-500">{t("clNoClients")}</div> : (
            <ul className="card divide-y divide-slate-100">
              {data.clients.map((c) => (
                <li key={c.client} className="px-5 py-3">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="font-medium text-slate-900"><bdi>{c.client}</bdi></span>
                    <span className="text-xs text-slate-500">{t("clJobs", { n: c.jobs })} · {t("clTerms", { n: c.terms })}</span>
                    {c.members.length ? (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">🔒 {t("clRestricted", { n: c.members.length })}</span>
                    ) : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{t("clOpen")}</span>}
                    <button className="ms-auto text-sm text-brand-500 hover:underline" aria-expanded={open === c.client}
                      onClick={() => setOpen(open === c.client ? null : c.client)}>{t("clEditAccess")}</button>
                  </div>
                  {c.members.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {c.members.map((m) => <span key={m.username} className="rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-700"><bdi>{m.name}</bdi></span>)}
                    </div>
                  )}
                  {open === c.client && (
                    <MemberPicker data={data} client={c.client} initial={c.members.map((m) => m.username)} onSaved={saved} onCancel={() => setOpen(null)} />
                  )}
                </li>
              ))}
            </ul>
          )}
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-slate-900">{t("clNew")}</h2>
            <div className="mt-2 flex flex-wrap gap-2">
              <input className="input max-w-sm" dir="auto" placeholder={t("clNewPh")} aria-label={t("clNewPh")} value={newName}
                onChange={(e) => { setNewName(e.target.value); setOpen(null); }} />
              <button className="btn-ghost" disabled={!newName.trim()} onClick={() => setOpen(`new:${newName.trim()}`)}>{t("clAddBtn")}</button>
            </div>
            {open?.startsWith("new:") && (
              <MemberPicker data={data} client={open.slice(4)} initial={[]} onSaved={saved} onCancel={() => setOpen(null)} />
            )}
          </section>
        </>
      )}
    </div>
  );
}
