import { createContext, useContext, useEffect, useState } from "react";
import { Link, Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { api, type User } from "./api";
import { useI18n } from "./i18n";
import Login from "./pages/Login";
import Jobs from "./pages/Jobs";
import NewJob from "./pages/NewJob";
import JobView from "./pages/JobView";
import Review from "./pages/Review";
import Audit from "./pages/Audit";
import Account from "./pages/Account";
import Users from "./pages/Users";
import Usage from "./pages/Usage";
import Assets from "./pages/Assets";
import Glossaries from "./pages/Glossaries";
import Models from "./pages/Models";
import Languages from "./pages/Languages";
import Storage from "./pages/Storage";

const AuthCtx = createContext<{ user: User | null; setUser: (u: User | null) => void }>({ user: null, setUser: () => {} });
export const useAuth = () => useContext(AuthCtx);

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const { setLang } = useI18n();
  useEffect(() => {
    api.me().then((u) => { setUser(u); setLang(u.ui_language); }).catch(() => setUser(null)).finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (loading) return <div className="p-10 text-slate-500">…</div>;
  return (
    <AuthCtx.Provider value={{ user, setUser }}>
      {user ? (
        <Shell>
          <Routes>
            <Route path="/" element={<Jobs />} />
            <Route path="/new" element={<NewJob />} />
            <Route path="/jobs/:id" element={<JobView />} />
            <Route path="/jobs/:id/review/:doc" element={<Review />} />
            <Route path="/jobs/:id/audit" element={<Audit />} />
            <Route path="/account" element={<Account />} />
            {user.role !== "reviewer" && <Route path="/glossaries" element={<Glossaries />} />}
            {user.role === "admin" && (
              <Route path="/admin" element={<AdminLayout />}>
                <Route index element={<Navigate to="users" replace />} />
                <Route path="users" element={<Users />} />
                <Route path="assets" element={<Assets />} />
                <Route path="models" element={<Models />} />
                <Route path="languages" element={<Languages />} />
                <Route path="usage" element={<Usage />} />
                <Route path="storage" element={<Storage />} />
              </Route>
            )}
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </Shell>
      ) : (
        <Login />
      )}
    </AuthCtx.Provider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const { user, setUser } = useAuth();
  const loc = useLocation();
  const nav = (to: string, label: string, prefix?: string) => (
    <Link to={to} className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${(prefix ? loc.pathname.startsWith(prefix) : loc.pathname === to) ? "bg-white/15 text-white" : "text-brand-100 hover:text-white"}`}>{label}</Link>
  );
  const switchLang = () => {
    const next = lang === "en" ? "ar" : "en";
    setLang(next);
    api.setLanguage(next).catch(() => {});
  };
  return (
    <div className="min-h-screen">
      <header className="bg-brand-600 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <div className="leading-tight">
              <div className="font-semibold">{t("appName")}</div>
              <div className="text-xs text-brand-100">{t("office")}</div>
            </div>
          </Link>
          <nav className="order-last flex w-full flex-wrap gap-1 md:order-none md:ms-4 md:w-auto">{nav("/", t("jobs"))}{nav("/new", t("newJob"))}{user?.role !== "reviewer" && nav("/glossaries", t("glossaries"))}{user?.role === "admin" && nav("/admin/users", t("admin"), "/admin")}</nav>
          <div className="ms-auto flex items-center gap-3 text-sm">
            <button onClick={switchLang} className="rounded-md border border-white/30 px-2.5 py-1 hover:bg-white/10">{t("language")}</button>
            <Link to="/account" title={t("account")} className="text-brand-100 hover:text-white hover:underline">{user?.name}</Link>
            <button className="text-brand-100 hover:text-white" onClick={() => api.logout().finally(() => setUser(null))}>{t("signOut")}</button>
          </div>
        </div>
      </header>
      <main className={`mx-auto px-4 py-6 ${loc.pathname.includes("/review/") ? "max-w-[100rem]" : "max-w-6xl"}`}>{children}</main>
    </div>
  );
}

// Admin area: one menu entry, tabs for its pages.
function AdminLayout() {
  const { t } = useI18n();
  const tabs: [string, string][] = [["users", t("users")], ["assets", t("assets")], ["models", t("models")], ["languages", t("languages")], ["usage", t("costs")], ["storage", t("storage")]];
  return (
    <div className="space-y-4">
      <nav aria-label={t("admin")} className="-mt-2 flex flex-wrap gap-1 border-b border-slate-200">
        {tabs.map(([to, label]) => (
          <NavLink key={to} to={`/admin/${to}`}
            className={({ isActive }) => `-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${isActive ? "border-brand-600 text-brand-600" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
