import { useEffect, useState } from "react";
import { api, type SessionInfo } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";

// My account: the browsers where I am signed in, and "sign out all other devices".

const fmt = (at: string) => new Date(at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short", hour12: false });

function device(ua: string): string {
  const b = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return [b, os].filter(Boolean).join(" · ") || ua.slice(0, 40) || "—";
}

export default function Account() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [rows, setRows] = useState<SessionInfo[] | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => { setErr(""); api.sessions().then(setRows).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const others = (rows ?? []).filter((r) => !r.current).length;
  const revoke = async () => {
    setBusy(true); setMsg("");
    try { const r = await api.revokeOtherSessions(); setMsg(t("acRevoked", { n: r.revoked })); load(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">{t("acTitle")}</h1>
      <div className="card p-5 text-sm">
        <div className="font-medium text-slate-900"><bdi>{user?.name}</bdi></div>
        <div className="text-slate-500"><bdi>{user?.username}</bdi> · {user ? t(`role_${user.role}`) : ""}</div>
      </div>
      <section className="card p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold text-slate-900">{t("acSessions")}</h2>
            <p className="mt-1 text-sm text-slate-500">{t("acSessionsHint")}</p>
          </div>
          <div className="sm:text-end">
            <button className="btn-ghost" onClick={revoke} disabled={busy || others === 0}>{t("acRevokeOthers")}</button>
            {rows && others === 0 && <div className="mt-1 text-xs text-slate-500">{t("acNoOthers")}</div>}
          </div>
        </div>
        {msg && <div role="status" className="mt-3 rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg}</div>}
        {err && (
          <div role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button>
          </div>
        )}
        {!rows && !err && <div className="mt-4 text-sm text-slate-500">…</div>}
        {rows && (
          <ul className="mt-4 divide-y divide-slate-100">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-x-6 gap-y-1 py-3 text-sm">
                <div className="min-w-[10rem] flex-1 font-medium text-slate-800">
                  <bdi>{device(r.user_agent)}</bdi>
                  {r.current && <span className="ms-2 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-600">{t("acThis")}</span>}
                </div>
                <div className="text-slate-500">{t("acSince")}: <span dir="ltr">{fmt(r.created_at)}</span></div>
                <div className="text-slate-500">{t("acLastSeen")}: <span dir="ltr">{fmt(r.last_seen_at)}</span></div>
                <div className="text-slate-500">{t("acAddress")}: <span dir="ltr" className="font-mono text-xs">{r.ip || "—"}</span></div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
