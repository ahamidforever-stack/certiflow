import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

// Light / dark / follow the computer. Stored per browser only (a convenience, not a user setting on the server).
export type ThemeMode = "light" | "dark" | "system";
interface Ctx { mode: ThemeMode; dark: boolean; setMode: (m: ThemeMode) => void }
const ThemeCtx = createContext<Ctx>({ mode: "system", dark: false, setMode: () => {} });
const KEY = "cf_theme";

function read(): ThemeMode {
  try { const v = window.localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : "system"; } catch { return "system"; }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(read);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const dark = mode === "dark" || (mode === "system" && systemDark);
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  const setMode = (m: ThemeMode) => {
    setModeState(m);
    try { if (m === "system") window.localStorage.removeItem(KEY); else window.localStorage.setItem(KEY, m); } catch { /* private mode */ }
  };
  return <ThemeCtx.Provider value={{ mode, dark, setMode }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
