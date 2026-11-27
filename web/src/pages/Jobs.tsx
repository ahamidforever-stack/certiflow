import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Job } from "../api";
import { LangPair, StatusChip } from "../components/Status";
import { useI18n } from "../i18n";

export default function Jobs() {
  const { t, lang } = useI18n();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  useEffect(() => {
    const load = () => api.jobs().then(setJobs).catch(() => setJobs([]));
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  return (
    <div>
      <div className="mb-4 flex items-center">
        <h1 className="text-xl font-semibold text-slate-900">{t("jobs")}</h1>
        <Link to="/new" className="btn-primary ms-auto">+ {t("newJob")}</Link>
      </div>
      <div className="card overflow-x-auto">
        {jobs === null ? <div className="p-6 text-slate-400">…</div> : jobs.length === 0 ? (
          <div className="p-10 text-center text-slate-500">{t("noJobs")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-start text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 text-start">{t("title")}</th>
                <th className="px-4 py-2 text-start">{t("pair")}</th>
                <th className="px-4 py-2 text-start">{t("stamp")}</th>
                <th className="px-4 py-2 text-start">{t("status")}</th>
                <th className="px-4 py-2 text-start">{t("created")}</th>
                <th className="px-4 py-2 text-end">{t("cost")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3"><Link to={`/jobs/${j.id}`} className="font-medium text-brand-600 hover:underline">{j.title}</Link>
                    <div className="font-mono text-xs text-slate-400" dir="ltr">{j.id}</div></td>
                  <td className="px-4 py-3"><LangPair s={j.source_language} t={j.target_language} /></td>
                  <td className="px-4 py-3">{j.stamp === "certified" ? t("certified") : t("officeStamp")}</td>
                  <td className="px-4 py-3"><StatusChip status={j.status} /></td>
                  <td className="px-4 py-3 text-slate-500">{new Date(j.created_at).toLocaleString(lang === "ar" ? "ar-AE" : "en-GB", { dateStyle: "medium", timeStyle: "short" })}</td>
                  <td className="px-4 py-3 text-end font-mono text-xs" dir="ltr">${j.cost_usd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
