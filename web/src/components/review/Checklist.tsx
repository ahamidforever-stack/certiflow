import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Check, OctagonAlert, PencilLine, Sparkles } from "lucide-react";
import type { DocBlock } from "../../api";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { openFlags, pendingChanges } from "./helpers";

interface Props {
  jobId: string; blocks: DocBlock[]; editable: boolean; dirtyIds: string[]; selected: string | null;
  onJump: (id: string) => void;
}

// The translator's checklist: what stands between this document and approval, each item one click away.
export default function Checklist({ jobId, blocks, editable, dirtyIds, selected, onJump }: Props) {
  const { t } = useI18n();
  const blockers = blocks.flatMap((b) => openFlags(b).filter(({ f }) => f.severity === "blocker").map(({ f }) => ({ b, f })));
  const warnings = blocks.flatMap((b) => openFlags(b).filter(({ f }) => f.severity !== "blocker").map(({ f }) => ({ b, f })));
  const changes = blocks.flatMap((b) => pendingChanges(b).map(({ h }) => ({ b, h })));
  const resolved = blocks.reduce((n, b) => n + (b.flags || []).filter((f) => f.resolved).length, 0);
  const steps = [
    { key: "edStepBlockers", done: blockers.length === 0, n: blockers.length },
    { key: "edStepChanges", done: changes.length === 0, n: changes.length },
    { key: "edStepSaved", done: dirtyIds.length === 0, n: dirtyIds.length },
  ];
  const doneN = steps.filter((s) => s.done).length;
  const ready = doneN === steps.length;

  return (
    <aside className="flex h-full min-h-0 flex-col bg-sidebar" aria-label={t("edChecklist")}>
      <header className="flex h-11 shrink-0 items-center border-b border-slate-200/80 px-4">
        <h2 className="text-sm font-medium text-slate-700">{t("edChecklist")}</h2>
      </header>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-3">
        {/* readiness */}
        {editable && (
          <section className={cn("rounded-xl border p-3.5", ready ? "border-seal-300 bg-seal-50" : "border-slate-200 bg-surface")}>
            <div className="mb-2.5 flex items-center justify-between">
              <h3 className="eyebrow">{t("edReadiness")}</h3>
              <span className="text-[11px] tabular-nums text-slate-500">{t("edReadyN", { n: doneN, total: steps.length })}</span>
            </div>
            <div className="mb-3 flex gap-1" aria-hidden>
              {steps.map((s) => <span key={s.key} className={cn("h-1 flex-1 rounded-full", s.done ? (ready ? "bg-seal-500" : "bg-brand-500") : "bg-slate-200")} />)}
            </div>
            <ul className="space-y-1.5">
              {steps.map((s) => (
                <li key={s.key} className={cn("flex items-center gap-2 text-[13px]", s.done ? "text-slate-500" : "text-slate-800")}>
                  <span className={cn("flex h-4 w-4 shrink-0 items-center justify-center rounded-full", s.done ? "bg-emerald-500 text-white" : "ring-1 ring-slate-300")}>
                    {s.done && <Check className="h-3 w-3" strokeWidth={3} />}
                  </span>
                  <span className={cn(s.done && "line-through decoration-slate-300")}>{t(s.key)}</span>
                  {!s.done && <span className="ms-auto rounded-full bg-slate-100 px-1.5 text-[11px] tabular-nums text-slate-600">{s.n}</span>}
                </li>
              ))}
            </ul>
            {ready && (
              <div className="mt-3 border-t border-seal-200 pt-3">
                <p className="mb-2.5 text-xs leading-relaxed text-seal-800">{t("edAllClear")}</p>
                <Link to={`/jobs/${jobId}`} className="btn-seal btn-sm w-full">{t("edGoApprove")}<ArrowRight className="h-3.5 w-3.5 rtl:-scale-x-100" /></Link>
              </div>
            )}
          </section>
        )}

        <Group title={t("edBlockers")} icon={<OctagonAlert className="h-3.5 w-3.5 text-red-500" />} count={blockers.length}>
          {blockers.map(({ b, f }, k) => (
            <Item key={k} id={b.id} active={selected === b.id} onJump={onJump} tone="red">{f.message || f.code}</Item>
          ))}
        </Group>
        <Group title={t("edWarnings")} icon={<AlertTriangle className="h-3.5 w-3.5 text-amber-500" />} count={warnings.length}>
          {warnings.map(({ b, f }, k) => (
            <Item key={k} id={b.id} active={selected === b.id} onJump={onJump} tone="amber">{f.message || f.code}</Item>
          ))}
        </Group>
        <Group title={t("edChanges")} icon={<Sparkles className="h-3.5 w-3.5 text-brand-500" />} count={changes.length}>
          {changes.map(({ b, h }, k) => (
            <Item key={k} id={b.id} active={selected === b.id} onJump={onJump} tone="brand">{t("rvChangeBy", { agent: t(`agent_${h.actor}`) })}{h.reason ? ` · ${h.reason}` : ""}</Item>
          ))}
        </Group>
        {dirtyIds.length > 0 && (
          <Group title={t("edUnsavedList")} icon={<PencilLine className="h-3.5 w-3.5 text-seal-600" />} count={dirtyIds.length}>
            {dirtyIds.map((id) => <Item key={id} id={id} active={selected === id} onJump={onJump} tone="seal">{t("edEditedMark")}</Item>)}
          </Group>
        )}
        {resolved > 0 && <p className="flex items-center gap-1.5 px-1 text-xs text-emerald-700"><Check className="h-3.5 w-3.5" />{t("edResolvedN", { n: resolved })}</p>}
      </div>
    </aside>
  );
}

function Group({ title, icon, count, children }: { title: string; icon: React.ReactNode; count: number; children: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <section>
      <h3 className="mb-1 flex items-center gap-1.5 px-1 text-[11px] font-semibold text-slate-500">{icon}{title}
        <span className="ms-auto tabular-nums">{count}</span></h3>
      {count ? <ul className="space-y-px">{children}</ul> : <p className="px-1 text-xs text-slate-400">{t("edNothingHere")}</p>}
    </section>
  );
}

const ITEM_TONE = { red: "bg-red-500", amber: "bg-amber-400", brand: "bg-brand-400", seal: "bg-seal-400" };
function Item({ id, active, tone, onJump, children }: { id: string; active: boolean; tone: keyof typeof ITEM_TONE; onJump: (id: string) => void; children: React.ReactNode }) {
  return (
    <li>
      <button onClick={() => onJump(id)}
        className={cn("flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-start text-[13px] transition",
          active ? "bg-surface text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-700 hover:bg-slate-200/50")}>
        <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", ITEM_TONE[tone])} />
        <span className="min-w-0 flex-1 leading-snug"><span className="line-clamp-2" dir="auto">{children}</span></span>
        <span className="mt-px font-mono text-[10px] text-slate-400" dir="ltr">{id}</span>
      </button>
    </li>
  );
}
