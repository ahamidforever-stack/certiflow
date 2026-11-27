import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";

export default function Login() {
  const { t, lang, setLang } = useI18n();
  const { setUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const u = await api.login(username, password);
      setLang(u.ui_language); setUser(u);
    } catch { setError(t("wrongLogin")); } finally { setBusy(false); }
  };
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-600 to-brand-700 px-4">
      <form onSubmit={submit} className="card w-full max-w-sm p-8">
        <div className="mb-6 flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="h-10 w-10" />
          <div>
            <div className="text-lg font-semibold text-slate-900">{t("appName")}</div>
            <div className="text-sm text-slate-500">{t("office")}</div>
          </div>
          <button type="button" onClick={() => setLang(lang === "en" ? "ar" : "en")} className="ms-auto text-xs text-brand-500 hover:underline">{t("language")}</button>
        </div>
        <label className="label" htmlFor="u">{t("username")}</label>
        <input id="u" className="input mb-4" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <label className="label" htmlFor="p">{t("password")}</label>
        <input id="p" type="password" className="input mb-4" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
        <button className="btn-primary w-full" disabled={busy || !username || !password}>{t("signIn")}</button>
      </form>
    </div>
  );
}
