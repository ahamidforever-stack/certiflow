import { useEffect, useRef, useState } from "react";
import { api, ApiError, type AdminEvent, type AdminUser, type Role } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";

// Admin: user accounts (add, role, deactivate, password, unlock, sign out) and the log of these changes.

const ROLES: Role[] = ["certified_translator", "reviewer", "admin"];
const fmt = (at: string) => new Date(at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short", hour12: false });

function newPassword(): string {
  const abc = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const r = crypto.getRandomValues(new Uint32Array(14));
  return Array.from(r, (n) => abc[n % abc.length]).join("");
}

function useErrText() {
  const { t } = useI18n();
  return (e: unknown) => {
    const m = e instanceof Error ? e.message : String(e);
    if (e instanceof ApiError && e.status === 409 && m.includes("exists")) return t("usErrExists");
    if (m.includes("last active administrator")) return t("usErrLastAdmin");
    if (m.includes("your own role")) return t("usErrSelf");
    if (m.includes("10 characters")) return t("usErrPassword");
    if (m.startsWith("username")) return t("usErrUsername");
    return m;
  };
}

function StatusPill({ u }: { u: AdminUser }) {
  const { t } = useI18n();
  const [cls, label] = !u.active ? ["bg-slate-100 text-slate-600", t("usInactive")]
    : u.locked ? ["bg-red-50 text-red-700", t("usLocked")] : ["bg-green-50 text-green-700", t("usActive")];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}

function PasswordField({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  const { t } = useI18n();
  return (
    <div className="flex gap-2">
      <input id={id} className="input font-mono" dir="ltr" autoComplete="new-password" value={value} onChange={(e) => onChange(e.target.value)} />
      <button type="button" className="btn-ghost shrink-0" onClick={() => onChange(newPassword())}>{t("usGenerate")}</button>
    </div>
  );
}

export default function Users() {
  const { t } = useI18n();
  const { user: me } = useAuth();
  const errText = useErrText();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [events, setEvents] = useState<AdminEvent[]>([]);
  const [err, setErr] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const load = () => {
    setErr("");
    api.adminUsers().then(setUsers).catch((e) => setErr(errText(e)));
    api.adminEvents().then(setEvents).catch(() => {});
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, []);
  const updated = (u: AdminUser) => {
    setUsers((l) => (l ?? []).some((x) => x.id === u.id) ? (l ?? []).map((x) => (x.id === u.id ? u : x)) : [...(l ?? []), u]);
    if (editing?.id === u.id) setEditing(u);
    api.adminEvents().then(setEvents).catch(() => {});
  };
  const name = (username: string) => users?.find((u) => u.username === username)?.name ?? username;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900">{t("usTitle")}</h1>
        {!adding && <button className="btn-primary ms-auto" onClick={() => setAdding(true)}>+ {t("usAdd")}</button>}
      </div>

      {adding && <AddUser onDone={(u) => { setAdding(false); if (u) updated(u); }} />}

      {err && (
        <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button>
        </div>
      )}
      {!users && !err && <div className="card p-5 text-sm text-slate-500">…</div>}
      {users && users.length === 0 && <div className="card p-5 text-sm text-slate-500">{t("usEmpty")}</div>}
      {users && users.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="hidden bg-slate-50 text-start text-xs uppercase tracking-wide text-slate-500 md:table-header-group">
              <tr>
                <th className="px-4 py-2 text-start font-medium">{t("usName")}</th>
                <th className="px-4 py-2 text-start font-medium">{t("usRole")}</th>
                <th className="px-4 py-2 text-start font-medium">{t("usStatus")}</th>
                <th className="px-4 py-2 text-start font-medium">{t("usStamp")}</th>
                <th className="px-4 py-2 text-start font-medium">{t("usLastLogin")}</th>
                <th className="px-4 py-2 text-start font-medium">{t("usDevices")}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => (
                <tr key={u.id} className={`flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 md:table-row md:p-0 ${u.active ? "" : "opacity-60"}`}>
                  <td className="w-full md:w-auto md:px-4 md:py-3">
                    <div className="font-medium text-slate-900"><bdi>{u.name}</bdi>{u.id === me?.id && <span className="ms-2 text-xs font-normal text-slate-500">({t("usYou")})</span>}</div>
                    <div className="font-mono text-xs text-slate-500"><bdi>{u.username}</bdi></div>
                  </td>
                  <td className="md:px-4 md:py-3">{t(`role_${u.role}`)}</td>
                  <td className="md:px-4 md:py-3"><StatusPill u={u} /></td>
                  <td className="md:px-4 md:py-3">
                    {u.role === "certified_translator"
                      ? (u.certified_stamp ? <span className="text-green-700">✓ {t("usStampYes")}</span>
                        : <span className="text-amber-700" title={t("usStampNeeded")}>⚠ {t("usStampNo")}</span>)
                      : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="text-slate-600 md:px-4 md:py-3">
                    <span className="me-1 text-slate-500 md:hidden">{t("usLastLogin")}:</span>
                    {u.last_login_at ? <span dir="ltr">{fmt(u.last_login_at)}</span> : t("usNever")}
                  </td>
                  <td className="text-slate-600 md:px-4 md:py-3"><span className="me-1 text-slate-500 md:hidden">{t("usDevices")}:</span>{u.devices}</td>
                  <td className="ms-auto md:px-4 md:py-3 md:text-end">
                    <button className="btn-ghost px-3 py-1" onClick={() => setEditing(u)}>{t("usEdit")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("usActivity")}</h2>
        {events.length === 0 ? <p className="mt-2 text-sm text-slate-500">{t("usNoActivity")}</p> : (
          <ul className="mt-3 space-y-1.5 text-sm">
            {events.slice(0, 30).map((e, i) => (
              <li key={i} className="flex flex-wrap gap-x-2">
                <span className="text-slate-500" dir="ltr">{fmt(e.at)}</span>
                <span><bdi className="font-medium">{name(e.actor)}</bdi> {t(`ev_${e.action}`)}: <bdi className="font-medium">{name(e.target)}</bdi></span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {editing && <EditUser u={editing} isMe={editing.id === me?.id} onUpdated={updated} onClose={() => setEditing(null)} />}
    </div>
  );
}

function AddUser({ onDone }: { onDone: (u?: AdminUser) => void }) {
  const { t } = useI18n();
  const errText = useErrText();
  const [f, setF] = useState({ username: "", name: "", role: "certified_translator" as Role, password: newPassword() });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    try { onDone(await api.adminCreateUser({ ...f, username: f.username.trim().toLowerCase() })); }
    catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  };
  const ok = /^[a-z0-9._-]{2,80}$/.test(f.username.trim().toLowerCase()) && f.name.trim() && f.password.length >= 10;
  return (
    <form onSubmit={submit} className="card space-y-4 p-5">
      <h2 className="font-semibold text-slate-900">{t("usAdd")}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="label" htmlFor="nu-name">{t("usName")}</label>
          <input id="nu-name" className="input" dir="auto" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </div>
        <div>
          <label className="label" htmlFor="nu-user">{t("username")}</label>
          <input id="nu-user" className="input font-mono" dir="ltr" autoComplete="off" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
          <p className="mt-1 text-xs text-slate-500">{t("usUsernameHint")}</p>
        </div>
        <div>
          <label className="label" htmlFor="nu-role">{t("usRole")}</label>
          <select id="nu-role" className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
            {ROLES.map((r) => <option key={r} value={r}>{t(`role_${r}`)}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="nu-pw">{t("password")}</label>
          <PasswordField id="nu-pw" value={f.password} onChange={(password) => setF({ ...f, password })} />
          <p className="mt-1 text-xs text-slate-500">{t("usPasswordHint")}</p>
        </div>
      </div>
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={busy || !ok}>{t("usCreate")}</button>
        <button type="button" className="btn-ghost" onClick={() => onDone()}>{t("usCancel")}</button>
      </div>
    </form>
  );
}

function EditUser({ u, isMe, onUpdated, onClose }: { u: AdminUser; isMe: boolean; onUpdated: (u: AdminUser) => void; onClose: () => void }) {
  const { t } = useI18n();
  const errText = useErrText();
  const [name, setName] = useState(u.name);
  const [role, setRole] = useState<Role>(u.role);
  const [active, setActive] = useState(u.active);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    first.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);
  const run = async (fn: () => Promise<AdminUser>, done: string) => {
    setBusy(true); setErr(""); setMsg("");
    try { onUpdated(await fn()); setMsg(done); } catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  };
  const dirty = name.trim() !== u.name || role !== u.role || active !== u.active;

  return (
    <div className="fixed inset-0 z-40 !mt-0 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:items-center" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="eu-title" className="card w-full max-w-lg space-y-5 p-6">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id="eu-title" className="font-semibold text-slate-900"><bdi>{u.name}</bdi></h2>
            <div className="font-mono text-xs text-slate-500"><bdi>{u.username}</bdi></div>
          </div>
          <StatusPill u={u} />
          <button className="text-slate-400 hover:text-slate-700" onClick={onClose} aria-label={t("usClose")}>✕</button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="label" htmlFor="eu-name">{t("usName")}</label>
            <input ref={first} id="eu-name" className="input" dir="auto" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="eu-role">{t("usRole")}</label>
            <select id="eu-role" className="input" value={role} disabled={isMe} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => <option key={r} value={r}>{t(`role_${r}`)}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={active} disabled={isMe} onChange={(e) => setActive(e.target.checked)} />
            {t("usAccountActive")}
          </label>
          {isMe && <p className="text-xs text-slate-500">{t("usErrSelf")}</p>}
          {role === "certified_translator" && !u.certified_stamp && <p className="text-xs text-amber-700">⚠ {t("usStampNeeded")}</p>}
          <button className="btn-primary" disabled={busy || !dirty || !name.trim()}
            onClick={() => run(() => api.adminUpdateUser(u.id, { name: name.trim(), role, active }), t("usSaved"))}>{t("usSave")}</button>
        </div>

        <div className="space-y-3 border-t border-slate-100 pt-4">
          <h3 className="text-sm font-semibold text-slate-900">{t("usSecurity")}</h3>
          <div>
            <label className="label" htmlFor="eu-pw">{t("usNewPassword")}</label>
            <PasswordField id="eu-pw" value={pw} onChange={setPw} />
            <p className="mt-1 text-xs text-slate-500">{t("usSetPasswordHint")} {t("usPasswordHint")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" disabled={busy || pw.length < 10}
              onClick={() => run(() => api.adminSetPassword(u.id, pw), t("usPasswordSet")).then(() => setPw(""))}>{t("usSetPassword")}</button>
            {u.locked && <button className="btn-ghost" disabled={busy} onClick={() => run(() => api.adminUnlock(u.id), t("usUnlocked"))}>{t("usUnlock")}</button>}
            <button className="btn-ghost" disabled={busy || u.devices === 0} onClick={() => run(() => api.adminSignOut(u.id), t("usSignedOut"))}>{t("usSignOutAll")}</button>
          </div>
        </div>

        {msg && <div role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg}</div>}
        {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      </div>
    </div>
  );
}
