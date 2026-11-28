import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { Building2, Coins, HardDrive, Languages as LanguagesIcon, Sparkles, Stamp, Users as UsersIcon } from "lucide-react";
import { api, type User } from "./api";
import { useI18n } from "./i18n";
import AppShell from "./components/AppShell";
import { SealMark } from "./components/Seal";
import { JobsProvider } from "./lib/useJobs";
import { cn } from "./lib/cn";
import Login from "./pages/Login";
import Home from "./pages/Home";

// Pages load on first visit (code splitting): the first screen stays small.
const Jobs = lazy(() => import("./pages/Jobs"));
const NewJob = lazy(() => import("./pages/NewJob"));
const JobView = lazy(() => import("./pages/JobView"));
const Review = lazy(() => import("./pages/Review"));
const Audit = lazy(() => import("./pages/Audit"));
const Account = lazy(() => import("./pages/Account"));
const Users = lazy(() => import("./pages/Users"));
const Usage = lazy(() => import("./pages/Usage"));
const Assets = lazy(() => import("./pages/Assets"));
const Glossaries = lazy(() => import("./pages/Glossaries"));
const Models = lazy(() => import("./pages/Models"));
const Languages = lazy(() => import("./pages/Languages"));
const Storage = lazy(() => import("./pages/Storage"));
const Clients = lazy(() => import("./pages/Clients"));

function PageLoading() {
  return <div className="space-y-3 pt-2" aria-busy="true"><div className="skeleton h-7 w-56" /><div className="skeleton h-4 w-80" /><div className="skeleton mt-6 h-48 rounded-xl" /></div>;
}

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
  if (loading) return <div className="flex min-h-screen items-center justify-center"><SealMark size={44} className="animate-pulse" /></div>;
  return (
    <AuthCtx.Provider value={{ user, setUser }}>
      {user ? (
        <JobsProvider key={user.id}>
          <AppShell>
            <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/jobs" element={<Jobs />} />
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
                  <Route path="clients" element={<Clients />} />
                  <Route path="assets" element={<Assets />} />
                  <Route path="models" element={<Models />} />
                  <Route path="languages" element={<Languages />} />
                  <Route path="usage" element={<Usage />} />
                  <Route path="storage" element={<Storage />} />
                </Route>
              )}
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
            </Suspense>
          </AppShell>
        </JobsProvider>
      ) : (
        <Login />
      )}
    </AuthCtx.Provider>
  );
}

// Settings (admin): a side list of sections on wide screens, a scrollable row on phones.
function AdminLayout() {
  const { t } = useI18n();
  const tabs: [string, string, React.ReactNode][] = [
    ["users", t("users"), <UsersIcon key="u" className="h-4 w-4" />],
    ["clients", t("clients"), <Building2 key="cl" className="h-4 w-4" />],
    ["assets", t("assets"), <Stamp key="a" className="h-4 w-4" />],
    ["models", t("models"), <Sparkles key="m" className="h-4 w-4" />],
    ["languages", t("languages"), <LanguagesIcon key="l" className="h-4 w-4" />],
    ["usage", t("costs"), <Coins key="c" className="h-4 w-4" />],
    ["storage", t("storage"), <HardDrive key="s" className="h-4 w-4" />],
  ];
  return (
    <div className="animate-fade-in">
      <h1 className="page-title mb-6">{t("navSettings")}</h1>
      <div className="flex flex-col gap-6 lg:flex-row lg:gap-10">
        <nav aria-label={t("navSettings")}
          className="-mx-4 flex shrink-0 gap-1 overflow-x-auto px-4 pb-1 lg:mx-0 lg:w-48 lg:flex-col lg:overflow-visible lg:px-0">
          {tabs.map(([to, label, icon]) => (
            <NavLink key={to} to={`/admin/${to}`}
              className={({ isActive }) => cn("flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition",
                isActive ? "bg-surface font-medium text-slate-900 shadow-sm ring-1 ring-slate-200/80" : "text-slate-600 hover:bg-slate-200/50 hover:text-slate-900")}>
              <span className="text-slate-500">{icon}</span>{label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1"><Suspense fallback={<PageLoading />}><Outlet /></Suspense></div>
      </div>
    </div>
  );
}
