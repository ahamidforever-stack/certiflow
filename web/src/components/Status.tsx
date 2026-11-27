import { useI18n } from "../i18n";

const COLORS: Record<string, string> = {
  queued: "bg-slate-100 text-slate-700", running: "bg-blue-50 text-blue-700", releasing: "bg-blue-50 text-blue-700",
  waiting_glossary: "bg-amber-50 text-amber-800", waiting_review: "bg-violet-50 text-violet-800",
  released: "bg-emerald-50 text-emerald-700", failed: "bg-red-50 text-red-700", blocked: "bg-red-50 text-red-700",
};

export function StatusChip({ status }: { status: string }) {
  const { t } = useI18n();
  const busy = status === "running" || status === "releasing" || status === "queued";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${COLORS[status] ?? "bg-slate-100 text-slate-700"}`}>
      {busy && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {t(`st_${status}`)}
    </span>
  );
}

export function LangPair({ s, t: tg }: { s: string; t: string }) {
  return <span className="font-mono text-xs uppercase text-slate-600" dir="ltr">{s} → {tg}</span>;
}
