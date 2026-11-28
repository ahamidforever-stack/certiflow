import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StorageSettings, type StorageView } from "../api";
import { StatusChip } from "../components/Status";
import { useI18n } from "../i18n";
import { Sym } from "../components/Sym";

// Admin: automatic deletion of old job files (off until switched on), backups and their encryption status.

const mb = (b: number) => (b / 1e6).toFixed(1);
const size = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${(b / 1e6).toFixed(1)} MB`);
const fmt = (at: string) => new Date(at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short", hour12: false });

function NumField({ id, label, value, min, max, onChange }: { id: string; label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      <input id={id} type="number" min={min} max={max} className="input max-w-[8rem]" dir="ltr" value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </div>
  );
}

export default function Storage() {
  const { t } = useI18n();
  const [v, setV] = useState<StorageView | null>(null);
  const [f, setF] = useState<StorageSettings | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);
  const apply = (d: StorageView) => { setV(d); setF(d.settings); };
  const load = () => { setErr(""); api.adminStorage().then(apply).catch((e) => setErr(e.message)); };
  useEffect(() => { load(); return () => { if (poll.current) window.clearInterval(poll.current); }; }, []);
  useEffect(() => {
    // while a backup runs, refresh every 2 s
    if (v?.backup_state.running && !poll.current) poll.current = window.setInterval(() => api.adminStorage().then(setV).catch(() => {}), 2000);
    if (!v?.backup_state.running && poll.current) { window.clearInterval(poll.current); poll.current = null; }
  }, [v?.backup_state.running]);

  const run = async (fn: () => Promise<StorageView>, ok: (d: StorageView) => string) => {
    setBusy(true); setErr(""); setMsg("");
    try { const d = await fn(); apply(d); setMsg(ok(d)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  if (!v || !f) return (
    <div className="space-y-4">
      <h1 className="font-serif text-xl font-medium text-slate-900">{t("stTitle")}</h1>
      {err ? <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>
        : <div className="card p-5 text-sm text-slate-500">…</div>}
    </div>
  );
  const dirty = (keys: (keyof StorageSettings)[]) => keys.some((k) => f[k] !== v.settings[k]);
  const retKeys: (keyof StorageSettings)[] = ["enabled", "released_days", "unfinished_days"];
  const bkKeys: (keyof StorageSettings)[] = ["backup_daily", "backup_hour", "backup_keep", "backup_jobs"];
  const pick = (keys: (keyof StorageSettings)[]) => Object.fromEntries(keys.map((k) => [k, f[k]]));
  const runNow = () => {
    if (!window.confirm(t("stRunConfirm", { n: v.candidates.length }))) return;
    run(() => api.adminRunRetention(), (d) => {
      const r = (d as StorageView & { result: { purged: string[]; freed: number } }).result;
      return t("stRan", { n: r.purged.length, mb: mb(r.freed) });
    });
  };
  const backup = async () => {
    setErr(""); setMsg("");
    try { await api.adminCreateBackup(); setV({ ...v, backup_state: { running: true, last_error: null } }); }
    catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="space-y-4">
      <h1 className="font-serif text-xl font-medium text-slate-900">{t("stTitle")}</h1>
      {msg && <div role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg}</div>}
      {err && <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="card p-4"><div className="text-sm text-slate-500">{t("stUsage")}</div><div className="mt-1 text-2xl font-semibold text-slate-900"><bdi dir="ltr">{size(v.usage.job_bytes)}</bdi></div></div>
        <div className="card p-4"><div className="text-sm text-slate-500">{t("jobs")}</div><div className="mt-1 text-2xl font-semibold text-slate-900">{v.usage.jobs}</div>
          <div className="text-xs text-slate-500">{t("stPurgedN", { n: v.usage.purged })} · {t("stKeptN", { n: v.usage.kept })}</div></div>
        <div className="card p-4"><div className="text-sm text-slate-500">{t("stFree")}</div><div className="mt-1 text-2xl font-semibold text-slate-900"><bdi dir="ltr">{size(v.usage.free_bytes)}</bdi></div></div>
        <div className="card p-4"><div className="text-sm text-slate-500">{t("stBackups")}</div><div className="mt-1 text-2xl font-semibold text-slate-900">{v.backups.length}</div>
          <div className={`text-xs ${v.backup_encrypted ? "text-green-700" : "text-amber-700"}`}>{v.backup_encrypted ? <><Sym k="ok" />{t("stEncrypted")}</> : <><Sym k="warn" />{t("stPlain")}</>}</div></div>
      </div>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("stRetention")}</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("stRetentionHint")}</p>
        <label className="mt-4 flex items-center gap-2 text-sm font-medium text-slate-800">
          <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} />
          {t("stEnabled")}
        </label>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <NumField id="st-rel" label={t("stReleasedDays")} value={f.released_days} min={7} max={3650} onChange={(x) => setF({ ...f, released_days: x })} />
          <NumField id="st-unf" label={t("stUnfinishedDays")} value={f.unfinished_days} min={7} max={3650} onChange={(x) => setF({ ...f, unfinished_days: x })} />
        </div>
        <button className="btn-primary mt-4" disabled={busy || !dirty(retKeys)} onClick={() => run(() => api.adminStorageSettings(pick(retKeys)), () => t("stSaved"))}>{t("stSave")}</button>

        <h3 className="mt-6 text-sm font-semibold text-slate-900">{t("stPreview")}</h3>
        {!v.settings.enabled && <p className="mt-1 text-xs text-slate-500">{t("stOffNote")}</p>}
        {v.candidates.length === 0 ? <p className="mt-2 text-sm text-slate-500">{t("stPreviewNone")}</p> : (
          <>
            <ul className="mt-2 divide-y divide-slate-100 text-sm">
              {v.candidates.slice(0, 50).map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-3 py-2">
                  <Link to={`/jobs/${c.id}`} className="text-brand-500 hover:underline"><bdi>{c.title}</bdi></Link>
                  <span className="font-mono text-xs text-slate-500"><bdi>{c.id}</bdi></span>
                  <StatusChip status={c.status} />
                  <span className="ms-auto text-xs text-slate-500"><bdi dir="ltr">{fmt(c.last_activity)}</bdi></span>
                </li>
              ))}
            </ul>
            {v.settings.enabled && <button className="btn-ghost mt-3 border-red-300 text-red-700 hover:bg-red-50" disabled={busy} onClick={runNow}>{t("stRunNow")} ({v.candidates.length})</button>}
          </>
        )}
      </section>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("stBackups")}</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">{t("stBackupsHint")}</p>
        <div className={`mt-3 rounded-md px-3 py-2 text-sm ${v.backup_encrypted ? "bg-green-50 text-green-800" : "bg-amber-50 text-amber-800"}`}>
          {v.backup_encrypted ? <><Sym k="ok" />{t("stEncOn")}</> : <><Sym k="warn" />{t("stEncOff")}</>}
        </div>
        <p className="mt-2 text-xs text-slate-500">{t("stDiskNote")}</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-800">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={f.backup_daily} onChange={(e) => setF({ ...f, backup_daily: e.target.checked })} />
            {t("stDaily")}
          </label>
          <NumField id="st-hour" label={t("stHour")} value={f.backup_hour} min={0} max={23} onChange={(x) => setF({ ...f, backup_hour: x })} />
          <NumField id="st-keep" label={t("stKeep")} value={f.backup_keep} min={1} max={365} onChange={(x) => setF({ ...f, backup_keep: x })} />
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-800">
            <input type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={f.backup_jobs} onChange={(e) => setF({ ...f, backup_jobs: e.target.checked })} />
            {t("stWithJobs")}
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-primary" disabled={busy || !dirty(bkKeys)} onClick={() => run(() => api.adminStorageSettings(pick(bkKeys)), () => t("stSaved"))}>{t("stSave")}</button>
          <button className="btn-ghost" disabled={v.backup_state.running} onClick={backup}>{v.backup_state.running ? t("stRunning") : t("stCreate")}</button>
        </div>
        {v.backup_state.last_error && <div role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{t("stBackupError", { e: v.backup_state.last_error })}</div>}
        <p className="mt-4 text-xs text-slate-500">{t("stFolder")}: <bdi dir="ltr" className="break-all font-mono">{v.backup_dir}</bdi></p>
        {v.backups.length === 0 ? <p className="mt-2 text-sm text-slate-500">{t("stNoBackups")}</p> : (
          <ul className="mt-2 divide-y divide-slate-100 text-sm">
            {v.backups.map((b) => (
              <li key={b.name} className="flex flex-wrap items-center gap-3 py-2">
                <span className="break-all font-mono text-xs text-slate-800"><bdi dir="ltr">{b.name}</bdi></span>
                <span className={`text-xs ${b.encrypted ? "text-green-700" : "text-amber-700"}`}>{b.encrypted ? t("stEncrypted") : t("stPlain")}</span>
                <span className="ms-auto text-xs text-slate-500"><bdi dir="ltr">{mb(b.size)} MB · {fmt(b.created)}</bdi></span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
