import { useEffect, useState } from "react";
import { api, type SessionInfo } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";
import { useTheme } from "../theme";
import { cn } from "../lib/cn";
import { Monitor, Moon, Sun } from "lucide-react";

// My account: the browsers where I am signed in, and "sign out all other devices".

const fmt = (at: string) => new Date(at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short", hour12: false });

function device(ua: string): string {
  const b = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return [b, os].filter(Boolean).join(" · ") || ua.slice(0, 40) || "—";
}

export default function Account() {
  const { t, lang, setLang } = useI18n();
  const { mode, setMode } = useTheme();
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
    <div className="mx-auto max-w-4xl space-y-6 animate-fade-in">
      <header className="flex items-center gap-4">
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-brand-600 text-lg font-semibold text-white">
          <bdi>{(user?.name ?? "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase()}</bdi></span>
        <div className="min-w-0">
          <h1 className="page-title truncate"><bdi>{user?.name}</bdi></h1>
          <div className="mt-0.5 text-sm text-slate-500"><bdi className="font-mono text-xs" dir="ltr">{user?.username}</bdi> · {user ? t(`role_${user.role}`) : ""}</div>
        </div>
      </header>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("acPrefs")}</h2>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <div>
            <span className="label">{t("uiLanguage")}</span>
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1" role="radiogroup" aria-label={t("uiLanguage")}>
              {([["en", "English"], ["ar", "العربية"]] as const).map(([code, label]) => (
                <button key={code} role="radio" aria-checked={lang === code} onClick={() => { setLang(code); api.setLanguage(code).catch(() => {}); }}
                  className={cn("flex-1 rounded-md px-3 py-1.5 text-sm transition", lang === code ? "bg-surface font-medium text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800")}>{label}</button>
              ))}
            </div>
          </div>
          <div>
            <span className="label">{t("themeLabel")}</span>
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1" role="radiogroup" aria-label={t("themeLabel")}>
              {([["light", "themeLight", <Sun key="l" className="h-3.5 w-3.5" />], ["dark", "themeDark", <Moon key="d" className="h-3.5 w-3.5" />], ["system", "acThemeAuto", <Monitor key="s" className="h-3.5 w-3.5" />]] as const).map(([m, label, icon]) => (
                <button key={m} role="radio" aria-checked={mode === m} onClick={() => setMode(m)}
                  className={cn("flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm transition", mode === m ? "bg-surface font-medium text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800")}>{icon}{t(label)}</button>
              ))}
            </div>
          </div>
        </div>
      </section>
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
        {!rows && !err && <div className="mt-4 space-y-2" aria-hidden>{[0, 1].map((i) => <div key={i} className="skeleton h-10" />)}</div>}
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
