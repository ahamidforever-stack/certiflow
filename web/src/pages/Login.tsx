import { useState } from "react";
import { Languages } from "lucide-react";
import { api, ApiError } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";
import { SealMark, SealRing } from "../components/Seal";

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
    } catch (e) {
      setError(e instanceof ApiError && e.status === 429 ? t("loginLocked", { min: Math.ceil((e.retryAfter ?? 900) / 60) }) : t("wrongLogin"));
    } finally { setBusy(false); }
  };
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* Brand side: the seal, the steps it stands for. */}
      <aside className="relative hidden overflow-hidden bg-brand-700 p-12 text-white lg:flex lg:flex-col dark:bg-brand-50">
        <div className="flex items-center gap-3">
          <SealMark size={36} />
          <div className="leading-tight">
            <div className="font-serif text-xl">{t("appName")}</div>
            <div className="text-xs text-white/60">{t("office")}</div>
          </div>
        </div>
        <div className="my-auto max-w-md">
          <SealRing progress={{ done: 7, active: null, tone: "done" }} size={88} label={false} />
          <p className="mt-8 font-serif text-[2rem] leading-snug">{t("loginTagline")}</p>
          <ol className="mt-8 space-y-2.5 text-sm text-white/70">
            {(["stepRead", "stepGlossary", "stepTranslate", "stepProofread", "stepCheck", "stepReview", "stepSeal"] as const).map((s, i) => (
              <li key={s} className="flex items-center gap-3">
                <span className="flex h-5 w-5 items-center justify-center rounded-full border border-white/25 text-[10px]">{i + 1}</span>{t(s)}
              </li>
            ))}
          </ol>
        </div>
        <SealMark size={520} className="pointer-events-none absolute -bottom-40 -end-40 opacity-[0.07]" />
      </aside>

      <main className="flex items-center justify-center bg-slate-50 px-6 py-12">
        <form onSubmit={submit} className="w-full max-w-sm animate-fade-in">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <SealMark size={40} />
            <div className="leading-tight">
              <div className="font-serif text-xl text-slate-900">{t("appName")}</div>
              <div className="text-xs text-slate-500">{t("office")}</div>
            </div>
          </div>
          <div className="mb-8 flex items-start gap-3">
            <div>
              <h1 className="page-title">{t("signIn")}</h1>
              <p className="mt-1 text-sm text-slate-500">{t("loginHint")}</p>
            </div>
            <button type="button" onClick={() => setLang(lang === "en" ? "ar" : "en")} className="btn-quiet btn-sm ms-auto">
              <Languages className="h-4 w-4" />{t("language")}
            </button>
          </div>
          <label className="label" htmlFor="u">{t("username")}</label>
          <input id="u" className="input mb-4 h-11" autoComplete="username" autoFocus dir="ltr" value={username} onChange={(e) => setUsername(e.target.value)} />
          <label className="label" htmlFor="p">{t("password")}</label>
          <input id="p" type="password" className="input mb-5 h-11" autoComplete="current-password" dir="ltr" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}
          <button className="btn-primary h-11 w-full" disabled={busy || !username || !password}>{busy ? "…" : t("signIn")}</button>
        </form>
      </main>
    </div>
  );
}
