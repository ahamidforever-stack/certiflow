import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import * as Tip from "@radix-ui/react-tooltip";
import { Command } from "cmdk";
import { Toaster } from "sonner";
import {
  BookOpenText, Check, ChevronsUpDown, FileStack, Home, Languages, LogOut, Menu as MenuIcon, Monitor, Moon,
  PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, Sun, UserRound, X,
} from "lucide-react";
import { api, type Job } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";
import { useTheme, type ThemeMode } from "../theme";
import { useJobs } from "../lib/useJobs";
import { bucketOf, dayGroup, jobTime, progressOf } from "../lib/jobs";
import { cn } from "../lib/cn";
import { SealMark, SealRing } from "./Seal";

const COLLAPSE_KEY = "cf_sidebar";
const readCollapsed = () => { try { return window.localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; } };

export default function AppShell({ children }: { children: ReactNode }) {
  const { t, dir } = useI18n();
  const loc = useLocation();
  const inEditor = loc.pathname.includes("/review/");
  const [collapsedPref, setCollapsedPref] = useState(readCollapsed);
  const collapsed = collapsedPref || inEditor; // the editor needs the whole width
  const [drawer, setDrawer] = useState(false);
  const [cmd, setCmd] = useState(false);
  const setCollapsed = (v: boolean) => {
    setCollapsedPref(v);
    try { window.localStorage.setItem(COLLAPSE_KEY, v ? "1" : "0"); } catch { /* private mode */ }
  };
  useEffect(() => setDrawer(false), [loc.pathname]);
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmd((v) => !v); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  return (
    <Tip.Provider delayDuration={300}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:start-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-float">{t("skipToContent")}</a>
      <div className="flex min-h-screen">
        {/* Desktop sidebar */}
        <aside className={cn("sticky top-0 hidden h-screen shrink-0 border-e border-slate-200/70 bg-sidebar transition-[width] duration-200 lg:block",
          collapsed ? "w-[4.25rem]" : "w-[17.5rem]")}>
          {collapsed
            ? <Rail onExpand={inEditor ? undefined : () => setCollapsed(false)} onSearch={() => setCmd(true)} />
            : <SidebarBody onCollapse={() => setCollapsed(true)} onSearch={() => setCmd(true)} />}
        </aside>

        {/* Mobile drawer */}
        <Dialog.Root open={drawer} onOpenChange={setDrawer}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-[2px] animate-fade-in lg:hidden" />
            <Dialog.Content dir={dir} aria-describedby={undefined}
              className="fixed inset-y-0 start-0 z-50 w-[86vw] max-w-[20rem] border-e border-slate-200 bg-sidebar shadow-float focus:outline-none lg:hidden">
              <Dialog.Title className="sr-only">{t("navMenu")}</Dialog.Title>
              <SidebarBody onClose={() => setDrawer(false)} onSearch={() => { setDrawer(false); setCmd(true); }} />
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Mobile top bar */}
          <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-slate-200/70 bg-slate-50/85 px-3 backdrop-blur lg:hidden">
            <button className="icon-btn" aria-label={t("navMenu")} onClick={() => setDrawer(true)}><MenuIcon className="h-5 w-5" /></button>
            <Link to="/" className="flex items-center gap-2"><SealMark size={26} /><span className="font-serif text-lg">{t("appName")}</span></Link>
            <button className="icon-btn ms-auto" aria-label={t("navSearch")} onClick={() => setCmd(true)}><Search className="h-5 w-5" /></button>
            <Link to="/new" className="icon-btn bg-brand-600 text-white hover:bg-brand-700 hover:text-white" aria-label={t("newJob")}><Plus className="h-5 w-5" /></Link>
          </header>
          <main id="main" className={cn("flex-1", inEditor ? "min-w-0" : "mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10")}>
            {children}
          </main>
        </div>
      </div>
      <CommandMenu open={cmd} onOpenChange={setCmd} />
      <Toaster position="bottom-center" dir={dir} toastOptions={{ className: "!bg-surface !text-slate-900 !border-slate-200 !font-sans" }} />
    </Tip.Provider>
  );
}

/* ------------------------------------------------------------------ sidebar */

function SidebarBody({ onCollapse, onClose, onSearch }: { onCollapse?: () => void; onClose?: () => void; onSearch: () => void }) {
  const { t } = useI18n();
  const { user } = useAuth();
  const { jobs } = useJobs();
  const groups = useMemo(() => groupJobs(jobs ?? []), [jobs]);
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-2.5 px-4">
        <Link to="/" className="flex min-w-0 items-center gap-2.5 rounded-lg">
          <SealMark size={30} />
          <div className="min-w-0 leading-tight">
            <div className="font-serif text-[1.15rem] font-medium tracking-tight text-slate-900">{t("appName")}</div>
            <div className="truncate text-[11px] text-slate-500">{t("office")}</div>
          </div>
        </Link>
        {onCollapse && (
          <TipButton label={t("navCollapse")} onClick={onCollapse} className="ms-auto">
            <PanelLeftClose className="h-[18px] w-[18px] rtl:-scale-x-100" />
          </TipButton>
        )}
        {onClose && <button className="icon-btn ms-auto" aria-label={t("navCloseMenu")} onClick={onClose}><X className="h-5 w-5" /></button>}
      </div>

      <div className="space-y-1.5 px-3">
        <Link to="/new" className="btn-primary w-full justify-start px-3"><Plus className="h-4 w-4" />{t("newJob")}</Link>
        <button onClick={onSearch}
          className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-surface/70 px-3 py-2 text-sm text-slate-500 transition hover:border-slate-300 hover:text-slate-700">
          <Search className="h-4 w-4" /><span>{t("navSearch")}</span>
          <span className="ms-auto flex gap-0.5" dir="ltr"><kbd className="kbd">Ctrl</kbd><kbd className="kbd">K</kbd></span>
        </button>
      </div>

      <nav className="mt-3 space-y-0.5 px-3" aria-label={t("navMenu")}>
        <NavItem to="/" end icon={<Home className="h-4 w-4" />} label={t("home")} />
        <NavItem to="/jobs" end icon={<FileStack className="h-4 w-4" />} label={t("navAllJobs")} />
        {user?.role !== "reviewer" && <NavItem to="/glossaries" icon={<BookOpenText className="h-4 w-4" />} label={t("glossaries")} />}
      </nav>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {jobs === null ? (
          <div className="space-y-2 px-2 pt-2">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-5" style={{ width: `${85 - i * 12}%` }} />)}</div>
        ) : jobs.length === 0 ? (
          <p className="px-2 pt-2 text-xs text-slate-500">{t("navNoJobs")}</p>
        ) : (
          <>
            <JobGroup title={t("navNeedsYou")} jobs={groups.needs} highlight />
            <JobGroup title={t("navInProgress")} jobs={groups.progress} />
            {(["navToday", "navYesterday", "navEarlier"] as const).map((k) => <JobGroup key={k} title={t(k)} jobs={groups.done[k]} />)}
          </>
        )}
      </div>

      <div className="space-y-0.5 border-t border-slate-200/70 p-3">
        {user?.role === "admin" && <NavItem to="/admin" icon={<Settings className="h-4 w-4" />} label={t("navSettings")} />}
        <UserMenu />
      </div>
    </div>
  );
}

function groupJobs(jobs: Job[]) {
  const needs: Job[] = [], progress: Job[] = [];
  const done: Record<"navToday" | "navYesterday" | "navEarlier", Job[]> = { navToday: [], navYesterday: [], navEarlier: [] };
  const sorted = [...jobs].sort((a, b) => jobTime(b).getTime() - jobTime(a).getTime());
  for (const j of sorted) {
    const b = bucketOf(j);
    if (b === "needs") needs.push(j);
    else if (b === "progress") progress.push(j);
    else done[dayGroup(jobTime(j))].push(j);
  }
  done.navEarlier = done.navEarlier.slice(0, 12);
  return { needs, progress, done };
}

function JobGroup({ title, jobs, highlight }: { title: string; jobs: Job[]; highlight?: boolean }) {
  if (!jobs.length) return null;
  return (
    <section className="mt-3 first:mt-0">
      <h2 className="flex items-center gap-2 px-2 pb-1 pt-1 text-[11px] font-semibold text-slate-500">
        {title}
        {highlight && <span className="rounded-full bg-seal-100 px-1.5 text-[10px] font-semibold leading-4 text-seal-700">{jobs.length}</span>}
      </h2>
      <ul className="space-y-px">
        {jobs.map((j) => (
          <li key={j.id}>
            <NavLink to={`/jobs/${j.id}`}
              className={({ isActive }) => cn("group flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13px] transition",
                isActive ? "bg-surface text-slate-900 shadow-sm ring-1 ring-slate-200/80" : "text-slate-700 hover:bg-slate-200/50")}>
              <SealRing progress={progressOf(j)} size={16} />
              <span className="min-w-0 flex-1 truncate"><bdi>{j.title}</bdi></span>
              <span className="hidden font-mono text-[10px] uppercase text-slate-400 group-hover:inline" dir="ltr">{j.source_language}→{j.target_language}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NavItem({ to, icon, label, end }: { to: string; icon: ReactNode; label: string; end?: boolean }) {
  return (
    <NavLink to={to} end={end}
      className={({ isActive }) => cn("flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition",
        isActive ? "bg-surface font-medium text-slate-900 shadow-sm ring-1 ring-slate-200/80" : "text-slate-600 hover:bg-slate-200/50 hover:text-slate-900")}>
      <span className="text-slate-500">{icon}</span>{label}
    </NavLink>
  );
}

/* ------------------------------------------------------------------ collapsed rail */

function Rail({ onExpand, onSearch }: { onExpand?: () => void; onSearch: () => void }) {
  const { t } = useI18n();
  const { user } = useAuth();
  const { jobs } = useJobs();
  const needs = (jobs ?? []).filter((j) => bucketOf(j) === "needs").length;
  return (
    <div className="flex h-full flex-col items-center gap-1 py-3">
      <Link to="/" className="mb-2" aria-label={t("home")}><SealMark size={30} /></Link>
      {onExpand && <TipButton label={t("navExpand")} onClick={onExpand}><PanelLeftOpen className="h-[18px] w-[18px] rtl:-scale-x-100" /></TipButton>}
      <TipLink to="/new" label={t("newJob")} className="bg-brand-600 text-white hover:bg-brand-700 hover:text-white"><Plus className="h-[18px] w-[18px]" /></TipLink>
      <TipButton label={t("navSearch")} onClick={onSearch}><Search className="h-[18px] w-[18px]" /></TipButton>
      <TipLink to="/" label={t("home")}>
        <span className="relative"><Home className="h-[18px] w-[18px]" />
          {needs > 0 && <span className="absolute -end-2 -top-1.5 rounded-full bg-seal-500 px-1 text-[9px] font-bold leading-[14px] text-white">{needs}</span>}
        </span>
      </TipLink>
      <TipLink to="/jobs" label={t("navAllJobs")}><FileStack className="h-[18px] w-[18px]" /></TipLink>
      {user?.role !== "reviewer" && <TipLink to="/glossaries" label={t("glossaries")}><BookOpenText className="h-[18px] w-[18px]" /></TipLink>}
      <div className="mt-auto flex flex-col items-center gap-1">
        {user?.role === "admin" && <TipLink to="/admin" label={t("navSettings")}><Settings className="h-[18px] w-[18px]" /></TipLink>}
        <UserMenu compact />
      </div>
    </div>
  );
}

function TipWrap({ label, children }: { label: string; children: ReactNode }) {
  const { dir } = useI18n();
  return (
    <Tip.Root>
      <Tip.Trigger asChild>{children}</Tip.Trigger>
      <Tip.Portal>
        <Tip.Content side={dir === "rtl" ? "left" : "right"} sideOffset={8}
          className="z-50 rounded-md bg-slate-900 px-2 py-1 text-xs font-medium text-slate-50 shadow-float animate-fade-in">{label}</Tip.Content>
      </Tip.Portal>
    </Tip.Root>
  );
}
function TipButton({ label, onClick, className, children }: { label: string; onClick: () => void; className?: string; children: ReactNode }) {
  return <TipWrap label={label}><button aria-label={label} onClick={onClick} className={cn("icon-btn", className)}>{children}</button></TipWrap>;
}
function TipLink({ to, label, className, children }: { to: string; label: string; className?: string; children: ReactNode }) {
  return <TipWrap label={label}><Link to={to} aria-label={label} className={cn("icon-btn", className)}>{children}</Link></TipWrap>;
}

/* ------------------------------------------------------------------ user menu */

function UserMenu({ compact }: { compact?: boolean }) {
  const { t, lang, setLang, dir } = useI18n();
  const { user, setUser } = useAuth();
  const { mode, setMode } = useTheme();
  const nav = useNavigate();
  if (!user) return null;
  const initials = user.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  const switchLang = () => { const next = lang === "en" ? "ar" : "en"; setLang(next); api.setLanguage(next).catch(() => {}); };
  const item = "flex cursor-default select-none items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-slate-700 outline-none data-[highlighted]:bg-slate-100 data-[highlighted]:text-slate-900";
  const themes: [ThemeMode, string, ReactNode][] = [["light", t("themeLight"), <Sun key="l" className="h-4 w-4" />], ["dark", t("themeDark"), <Moon key="d" className="h-4 w-4" />], ["system", t("themeSystem"), <Monitor key="s" className="h-4 w-4" />]];
  return (
    <Menu.Root dir={dir}>
      <Menu.Trigger asChild>
        <button aria-label={t("account")} className={cn("flex items-center gap-2.5 rounded-lg text-start transition hover:bg-slate-200/50", compact ? "p-1.5" : "w-full px-2 py-1.5")}>
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white" dir="auto">{initials}</span>
          {!compact && (
            <>
              <span className="min-w-0 flex-1 leading-tight">
                <span className="block truncate text-sm font-medium text-slate-900" dir="auto">{user.name}</span>
                <span className="block truncate text-[11px] text-slate-500">{t(`role_${user.role}`)}</span>
              </span>
              <ChevronsUpDown className="h-4 w-4 text-slate-400" />
            </>
          )}
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content side={compact ? (dir === "rtl" ? "left" : "right") : "top"} align="start" sideOffset={8}
          className="z-50 w-64 rounded-xl border border-slate-200 bg-raised p-1.5 shadow-float animate-fade-in">
          <div className="px-2.5 pb-2 pt-1.5">
            <div className="truncate text-sm font-medium text-slate-900" dir="auto">{user.name}</div>
            <div className="truncate text-xs text-slate-500">{t(`role_${user.role}`)} · <bdi>{user.username}</bdi></div>
          </div>
          <Menu.Separator className="my-1 h-px bg-slate-200" />
          <Menu.Item className={item} onSelect={() => nav("/account")}><UserRound className="h-4 w-4 text-slate-500" />{t("account")}</Menu.Item>
          <Menu.Item className={item} onSelect={switchLang}><Languages className="h-4 w-4 text-slate-500" />{t("uiLanguage")}<span className="ms-auto text-xs text-slate-500">{t("language")}</span></Menu.Item>
          <Menu.Separator className="my-1 h-px bg-slate-200" />
          <Menu.Label className="px-2.5 pb-1 pt-1.5 text-[11px] font-semibold text-slate-500">{t("themeLabel")}</Menu.Label>
          <Menu.RadioGroup value={mode} onValueChange={(v) => setMode(v as ThemeMode)}>
            {themes.map(([m, label, icon]) => (
              <Menu.RadioItem key={m} value={m} className={item} onSelect={(e) => e.preventDefault()}>
                <span className="text-slate-500">{icon}</span>{label}
                <Menu.ItemIndicator className="ms-auto"><Check className="h-4 w-4 text-brand-500" /></Menu.ItemIndicator>
              </Menu.RadioItem>
            ))}
          </Menu.RadioGroup>
          <Menu.Separator className="my-1 h-px bg-slate-200" />
          <Menu.Item className={item} onSelect={() => api.logout().finally(() => setUser(null))}><LogOut className="h-4 w-4 text-slate-500 rtl:-scale-x-100" />{t("signOut")}</Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

/* ------------------------------------------------------------------ command menu (Ctrl+K) */

function CommandMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t, lang, setLang, dir } = useI18n();
  const { user } = useAuth();
  const { jobs } = useJobs();
  const { dark, setMode } = useTheme();
  const nav = useNavigate();
  const go = (to: string) => { onOpenChange(false); nav(to); };
  const pages: [string, string][] = [["/", t("home")], ["/new", t("newJob")], ["/jobs", t("navAllJobs")], ["/account", t("account")]];
  if (user?.role !== "reviewer") pages.push(["/glossaries", t("glossaries")]);
  if (user?.role === "admin") pages.push(["/admin/users", t("users")], ["/admin/assets", t("assets")], ["/admin/models", t("models")],
    ["/admin/languages", t("languages")], ["/admin/usage", t("costs")], ["/admin/storage", t("storage")]);
  const group = "[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-slate-500";
  const item = "flex cursor-default items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-slate-700 data-[selected=true]:bg-slate-100 data-[selected=true]:text-slate-900";
  return (
    <Command.Dialog open={open} onOpenChange={onOpenChange} label={t("navSearch")} dir={dir}
      overlayClassName="fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-[2px]"
      contentClassName="fixed inset-x-3 top-[12vh] z-50 mx-auto max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-raised shadow-float animate-fade-in">
      <div className="flex items-center gap-2 border-b border-slate-200 px-4">
        <Search className="h-4 w-4 text-slate-400" />
        <Command.Input placeholder={t("cmdPlaceholder")} className="h-12 flex-1 bg-transparent text-[15px] text-slate-900 outline-none placeholder:text-slate-400" />
        <kbd className="kbd">Esc</kbd>
      </div>
      <Command.List className="max-h-[min(60vh,26rem)] overflow-y-auto p-1.5">
        <Command.Empty className="px-3 py-8 text-center text-sm text-slate-500">{t("cmdEmpty")}</Command.Empty>
        {!!jobs?.length && (
          <Command.Group heading={t("cmdJobs")} className={group}>
            {jobs.slice(0, 50).map((j) => (
              <Command.Item key={j.id} value={`${j.title} ${j.client ?? ""} ${j.id}`} onSelect={() => go(`/jobs/${j.id}`)} className={item}>
                <SealRing progress={progressOf(j)} size={18} />
                <span className="min-w-0 flex-1 truncate" dir="auto">{j.title}</span>
                {j.client && <span className="truncate text-xs text-slate-500" dir="auto">{j.client}</span>}
                <span className="font-mono text-[10px] uppercase text-slate-400" dir="ltr">{j.source_language}→{j.target_language}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading={t("cmdPages")} className={group}>
          {pages.map(([to, label]) => (
            <Command.Item key={to} value={`page ${label} ${to}`} onSelect={() => go(to)} className={item}>
              <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />{label}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading={t("cmdActions")} className={group}>
          <Command.Item value="action theme dark light" onSelect={() => { setMode(dark ? "light" : "dark"); onOpenChange(false); }} className={item}>
            {dark ? <Sun className="h-4 w-4 text-slate-500" /> : <Moon className="h-4 w-4 text-slate-500" />}{t("cmdToggleTheme")}
          </Command.Item>
          <Command.Item value="action language arabic english" onSelect={() => { const n = lang === "en" ? "ar" : "en"; setLang(n); api.setLanguage(n).catch(() => {}); onOpenChange(false); }} className={item}>
            <Languages className="h-4 w-4 text-slate-500" />{t("cmdSwitchLang")}
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
