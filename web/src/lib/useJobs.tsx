import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Job } from "../api";

// One shared, polled list of the user's jobs: the sidebar, the desk and the command menu read the same data.
interface Ctx { jobs: Job[] | null; error: boolean; refresh: () => void }
const JobsCtx = createContext<Ctx>({ jobs: null, error: false, refresh: () => {} });

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState(false);
  const busy = useRef(false);
  const refresh = useCallback(() => {
    if (busy.current) return;
    busy.current = true;
    api.jobs().then((j) => { setJobs(j); setError(false); }).catch(() => setError(true)).finally(() => { busy.current = false; });
  }, []);
  useEffect(() => {
    refresh();
    // Poll faster while the tab is visible; pause when hidden.
    const id = setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 5000);
    const vis = () => { if (document.visibilityState === "visible") refresh(); };
    document.addEventListener("visibilitychange", vis);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", vis); };
  }, [refresh]);
  return <JobsCtx.Provider value={{ jobs, error, refresh }}>{children}</JobsCtx.Provider>;
}

export const useJobs = () => useContext(JobsCtx);
